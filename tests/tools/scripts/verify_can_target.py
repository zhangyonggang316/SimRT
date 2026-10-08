"""Deploy a CAN loopback payload to an explicit SSH target and verify XCP samples."""

from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import asdict
from datetime import datetime, timezone
import getpass
import gzip
import json
import math
from pathlib import Path
import re
import shlex
import struct
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "shared/python"))
from can_validation_support import catalog_with_payload_bytes, evaluate_samples
from pyxcp_host.models import Endpoint
from pyxcp_host.services.payload_archive import PayloadArchive
from pyxcp_host.services.a2l_catalog import A2LCatalogService
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.xcp_session import XcpSession

sys.excepthook = sys.__excepthook__


def load_payload(archive, source, length):
    payload = archive.load(source)
    manifest = json.loads(Path(payload["manifest"]).read_text(encoding="utf-8-sig"))
    model = manifest["ModelName"]
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", model):
        raise ValueError("Payload ModelName must be a C identifier")
    catalog = A2LCatalogService()
    catalog.load(Path(payload["a2l"]))
    scalars = {item.name: item for item in catalog.database.scalars}
    waveform = all(model + "_B." + name in scalars
                   for name in ("CAN1set", "CAN2set", "CAN1_Data", "CAN2_Data"))
    if waveform:
        if length != 8:
            raise ValueError("The waveform model transmits 8-byte double values")
        payload["validation_profile"] = "waveform_double"
    else:
        catalog = catalog_with_payload_bytes(Path(payload["a2l"]), model, length)
        payload["validation_profile"] = "fixed_byte_pattern"
    names = [model + "_B.CAN{}_{}".format(channel, suffix)
             for channel in (1, 2) for suffix in ("TxStatus", "RxStatus", "Valid", "ID")]
    if waveform:
        names += [model + "_B." + name for name in ("CAN1set", "CAN2set", "CAN1_Data", "CAN2_Data")]
    else:
        names += [model + "_B.CAN{}_Data[{}]".format(channel, index)
                  for channel in (1, 2) for index in range(length)]
    available = {item.name for item in catalog.database.scalars}
    missing = set(names) - available
    if missing:
        raise ValueError("Missing CAN measurements: " + ", ".join(sorted(missing)))
    return payload, manifest, catalog, names


def evaluate_waveform(samples, model):
    """Match every received double bit-for-bit against a recent peer transmission."""
    result = {}
    prefix = model + "_B."
    for channel in (1, 2):
        name, peer = "CAN{}".format(channel), "CAN{}".format(3 - channel)
        history, counts = deque(), Counter()
        valid, matched, mismatch = 0, 0, []
        observed_values = set()
        first = samples[0].timestamp_seconds if samples else 0
        for sample in samples:
            stamp = sample.timestamp_seconds
            value = sample.values[prefix + peer + "set"]
            packed = struct.pack("<d", value)
            history.append((stamp, packed))
            counts[packed] += 1
            while history and history[0][0] < stamp - 0.5:
                _, old = history.popleft()
                counts[old] -= 1
                if not counts[old]:
                    del counts[old]
            if not sample.values[prefix + name + "_Valid"]:
                continue
            valid += 1
            if stamp - first < 0.5:
                continue
            received = sample.values[prefix + name + "_Data"]
            actual = struct.pack("<d", received)
            expected_id = 514 if channel == 1 else 257
            if (sample.values[prefix + name + "_ID"] == expected_id and
                    math.isfinite(received) and actual in counts):
                matched += 1
                observed_values.add(actual)
            else:
                mismatch.append({"time": stamp, "id": sample.values[prefix + name + "_ID"],
                                 "value": received})
        statuses = {kind: dict(Counter(str(int(s.values[prefix + name + "_" + kind])) for s in samples))
                    for kind in ("TxStatus", "RxStatus")}
        errors = sum(count for values in statuses.values() for status, count in values.items()
                     if int(status) not in (0, -6))
        result[name] = dict(valid_frames=valid, matched_frames=matched, mismatches=len(mismatch),
                            mismatch_examples=mismatch[:5], statuses=statuses,
                            errors_excluding_trylock_busy=errors, distinct_matched_values=len(observed_values),
                            reference_window_seconds=0.5, warmup_seconds=0.5,
                            passed=matched >= 1000 and len(observed_values) > 10 and not mismatch and errors == 0)
    return result


def runtime_process(service, pid):
    source = """
import hashlib, json, os
from pathlib import Path
pid = %d
tasks = []
for entry in Path('/proc/{}/task'.format(pid)).iterdir():
    tid = int(entry.name)
    tasks.append({'tid': tid, 'name': (entry / 'comm').read_text().strip(),
                  'policy': os.sched_getscheduler(tid),
                  'priority': os.sched_getparam(tid).sched_priority,
                  'cpus': sorted(os.sched_getaffinity(tid))})
libraries = {}
for line in Path('/proc/{}/maps'.format(pid)).read_text().splitlines():
    fields = line.split(None, 5)
    if len(fields) != 6:
        continue
    path = Path(fields[5])
    if path.name in ('libTSCANApiOnLinux.so', 'libTSH.so') and str(path) not in libraries:
        libraries[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps({'cwd': os.readlink('/proc/{}/cwd'.format(pid)), 'kernel': os.uname().release,
                  'threads': tasks,
                  'vendor_libraries': libraries}))
""" % pid
    return json.loads(service._execute("python3 -c " + shlex.quote(source)))


def final_runtime_status(service, remote_elf):
    source = "import json; from pathlib import Path; p=Path({!r}); print(p.read_text() if p.is_file() else 'null')".format(
        remote_elf + '.simrt-status.json')
    return json.loads(service._execute("python3 -c " + shlex.quote(source)))


def clean_termination(status, pid):
    return (isinstance(status, dict) and status.get('state') == 'STOPPED'
            and status.get('pid') == pid and status.get('model_step_calls', 0) > 0
            and status.get('model_step_calls') == status.get('model_step_completed_calls'))


def verify(args, password):
    archive = PayloadArchive()
    service = SSHDeployment()
    session = None
    samples = []
    started = False
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": str(args.payload.resolve()),
        "endpoint": {"host": args.host, "username": args.user, "port": 22},
        "baseline": args.baseline,
        "passed": False,
        "scope": "CAN functionality; not a zero-loss, endurance or worst-case timing certification",
    }
    try:
        payload, manifest, catalog, names = load_payload(archive, args.payload, args.length)
        port = getattr(args, 'port', None) or payload['port']
        model = manifest["ModelName"]
        result["manifest"] = manifest
        result["payload_files"] = payload["files"]
        result["validation_profile"] = payload["validation_profile"]
        result["xcp_endpoint"] = {"host": args.host, "protocol": payload["protocol"], "port": port}
        if args.check:
            result.update(passed=True, local_check_only=True, hardware_tested=False)
            return result
        session = XcpSession(catalog)
        service.connect(args.host, args.user, password=password)
        password = None
        # Test port availability before transmitting so another model remains untouched.
        source = "import socket; s=socket.socket(socket.AF_INET, %s); s.bind(('0.0.0.0', %d)); s.close()" % (
            "socket.SOCK_DGRAM" if payload["protocol"] == "UDP" else "socket.SOCK_STREAM", port)
        service._execute("python3 -c " + shlex.quote(source))
        root = args.remote_root or "/home/{}/MATLAB_ws".format(args.user)
        remote_dir = root.rstrip("/") + "/{}_{}_{}".format(
            model, datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"), uuid.uuid4().hex[:8])
        remote_elf = remote_dir + "/" + manifest["ELFFile"]
        result["remote_elf"] = remote_elf
        result["uploaded_files"] = service.upload(Path(payload["directory"]), remote_dir)
        started = True
        environment = {"SIMRT_RT_REQUIRE_KERNEL": "0"} if args.baseline else None
        result["pid"] = service.start(remote_elf, "-tf {} -port {}".format(args.seconds + 7, port),
                                      runtime_environment=environment)
        time.sleep(1)
        result["initial_status"] = service.status()
        result["runtime_process"] = runtime_process(service, result["pid"])
        result["connection"] = session.connect(
            Endpoint(payload["protocol"], args.host, port)).as_dict()
        result["daq_metadata"] = session.start_daq(names)
        result["runtime_process_during_daq"] = runtime_process(service, result["pid"])
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            time.sleep(0.05)
            samples.extend(session.drain_daq())
        session.stop_daq()
        samples.extend(session.drain_daq())
        result["daq_diagnostics"] = session.daq_diagnostics
        session.disconnect()
        time.sleep(1)
        result["status_after_xcp_disconnect"] = service.status()
        result["channels"] = (evaluate_waveform(samples, model) if payload["validation_profile"] == "waveform_double"
                              else evaluate_samples(samples, model, args.length))
        result["samples"] = len(samples)
        result["captured_seconds"] = samples[-1].timestamp_seconds - samples[0].timestamp_seconds if samples else 0
        result["passed"] = (all(item["passed"] for item in result["channels"].values())
                            and result["status_after_xcp_disconnect"]["running"])
        deadline = time.monotonic() + 9
        while time.monotonic() < deadline and service.status()["running"]:
            time.sleep(0.25)
        result["exited_at_stop_time"] = not service.status()["running"]
        result["final_runtime_status"] = final_runtime_status(service, remote_elf)
        result["clean_termination"] = clean_termination(result["final_runtime_status"], result["pid"])
        result["passed"] = result["passed"] and result["exited_at_stop_time"] and result["clean_termination"]
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["passed"] = False
    finally:
        if session is not None and session.connected:
            try:
                session.disconnect()
            except Exception as exc:
                result["xcp_cleanup_error"] = str(exc)
                result["passed"] = False
        if service.connected and started:
            try:
                service.stop()
                result["final_status"] = service.status()
                result["runtime_log"] = service.read_log()
                if result["final_status"]["running"]:
                    result["passed"] = False
            except Exception as exc:
                result["cleanup_error"] = str(exc)
                result["passed"] = False
        service.close()
        archive.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not args.check:
            raw = args.output.with_suffix(".samples.jsonl.gz")
            with gzip.open(raw, "wt", encoding="utf-8") as stream:
                for sample in samples:
                    stream.write(json.dumps(asdict(sample)) + "\n")
            result["raw_samples"] = str(raw.resolve())
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="Matching CAN model ZIP or three-file directory")
    parser.add_argument("--host", required=True, help="Explicit SSH and XCP host; overrides historical payload address")
    parser.add_argument("--user", required=True)
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--length", type=int, choices=(8, 64), default=8)
    parser.add_argument("--port", type=int, help="Override runtime and XCP UDP port for isolated validation")
    parser.add_argument("--remote-root", help="Remote model root; defaults to /home/USER/MATLAB_ws")
    parser.add_argument("--baseline", action="store_true", help="Allow non-PREEMPT_RT kernel for functional checks only")
    parser.add_argument("--check", action="store_true", help="Validate ZIP, SHA256 and CAN measurements locally; no SSH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 3 <= args.seconds <= 12:
        parser.error("Capture duration must be between 3 and 12 seconds")
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", args.user):
        parser.error("User must be a valid Linux account name")
    if not args.host.strip() or any(ord(char) < 33 for char in args.host):
        parser.error("Host must be nonempty and contain no whitespace or control characters")
    password = None if args.check else getpass.getpass("SSH password for {}@{}: ".format(args.user, args.host))
    result = verify(args, password)
    password = None
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
