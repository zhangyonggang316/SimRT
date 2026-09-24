"""Deploy the locally compiled CAN model and verify both channels through XCP DAQ."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shlex
import sys
import time

from target_probe import ROOT, credentials_from_environment
from pyxcp_host.models import Endpoint
from pyxcp_host.services.a2l_catalog import A2LCatalogService
from pyxcp_host.services.model_payload import validate_payload
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.xcp_session import XcpSession
from x280_xcp.a2l import A2LDatabase, A2LScalar, _BLOCK_RE, _COMMENT_RE, _keyword_value, _tokens

sys.excepthook = sys.__excepthook__


def catalog_with_payload_bytes(a2l: Path, model: str, length: int) -> A2LCatalogService:
    catalog = A2LCatalogService()
    catalog.load(a2l)
    database = catalog.database
    elements = []
    text = _COMMENT_RE.sub(" ", a2l.read_text(encoding="utf-8-sig"))
    wanted = {model + "_B.CAN1_Data", model + "_B.CAN2_Data"}
    for kind, body in _BLOCK_RE.findall(text):
        tokens = _tokens(body)
        if kind.upper() != "MEASUREMENT" or not tokens or tokens[0] not in wanted:
            continue
        if tokens[2] != "UBYTE" or int(_keyword_value(tokens, "MATRIX_DIM")) != length:
            raise ValueError("Unexpected received payload type or length")
        address = int(_keyword_value(tokens, "ECU_ADDRESS"), 0)
        extension = int(_keyword_value(tokens, "ECU_ADDRESS_EXTENSION") or "0", 0)
        for index in range(length):
            elements.append(A2LScalar(tokens[0] + "[{}]".format(index), "MEASUREMENT",
                                      address + index, "UBYTE", database.byte_order, extension))
    if len(elements) != 2 * length:
        raise ValueError("Both complete received payloads must be described by the A2L")
    catalog.database = A2LDatabase(database.scalars + tuple(elements),
                                  database.byte_order, database.daq_events)
    return catalog


def evaluate_samples(samples: list, model: str, length: int) -> dict:
    result = {}
    prefix = model + "_B."
    for channel in (1, 2):
        name = "CAN{}".format(channel)
        valid = [sample for sample in samples if sample.values[prefix + name + "_Valid"]]
        expected = list(range(length, 0, -1)) if channel == 1 else list(range(1, length + 1))
        expected_id = 514 if channel == 1 else 257
        mismatches = []
        for sample in valid:
            values = sample.values
            actual = [values[prefix + name + "_Data[{}]".format(index)] for index in range(length)]
            if values[prefix + name + "_ID"] != expected_id or actual != expected:
                mismatches.append({"time": sample.timestamp_seconds, "id": values[prefix + name + "_ID"],
                                   "data": actual})
        statuses = {kind: dict(Counter(str(int(sample.values[prefix + name + "_" + kind]))
                                      for sample in samples)) for kind in ("TxStatus", "RxStatus")}
        errors = sum(count for counts in statuses.values() for status, count in counts.items()
                     if int(status) not in (0, -6))
        result[name] = {"valid_frames": len(valid), "expected_id": expected_id,
                        "expected_payload": expected, "mismatches": len(mismatches),
                        "mismatch_examples": mismatches[:5], "statuses": statuses,
                        "errors_excluding_trylock_busy": errors,
                        "passed": len(valid) >= 1000 and not mismatches and errors == 0}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--length", type=int, choices=(8, 64), default=8)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("hardware_can.json"))
    args = parser.parse_args()
    if not 3 <= args.seconds <= 12:
        parser.error("Capture duration must be between 3 and 12 seconds")
    validate_payload(args.payload)
    manifest_path = next(args.payload.glob("*.xcp-manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    model = manifest["ModelName"]
    remote_dir = "/home/zh/MATLAB_ws/{}_{}".format(model, datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    remote_elf = remote_dir + "/" + manifest["ELFFile"]
    catalog = catalog_with_payload_bytes(args.payload / manifest["A2LFile"], model, args.length)
    names = [model + "_B.CAN{}_{}".format(channel, suffix)
             for channel in (1, 2) for suffix in ("TxStatus", "RxStatus", "Valid", "ID")]
    names += [model + "_B.CAN{}_Data[{}]".format(channel, index)
              for channel in (1, 2) for index in range(args.length)]
    service = SSHDeployment()
    session = XcpSession(catalog)
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "payload": str(args.payload.resolve()),
              "manifest": manifest, "remote_elf": remote_elf, "passed": False}
    samples = []
    try:
        host, username, password = credentials_from_environment()
        service.connect(host, username, password=password)
        password = None
        result["uploaded_files"] = service.upload(args.payload, remote_dir)
        result["pid"] = service.start(remote_elf, "-tf {}".format(args.seconds + 7))
        time.sleep(1)
        result["initial_status"] = service.status()
        probe = """
import json, os
from pathlib import Path
pid = %d
tasks = []
for entry in Path('/proc/{}/task'.format(pid)).iterdir():
    tid = int(entry.name)
    tasks.append({'tid': tid, 'name': (entry / 'comm').read_text().strip(),
                  'policy': os.sched_getscheduler(tid),
                  'priority': os.sched_getparam(tid).sched_priority,
                  'cpus': sorted(os.sched_getaffinity(tid))})
print(json.dumps({'cwd': os.readlink('/proc/{}/cwd'.format(pid)), 'threads': tasks}))
""" % result["pid"]
        result["runtime_process"] = json.loads(service._execute("python3 -c " + shlex.quote(probe)))
        result["connection"] = session.connect(Endpoint("UDP", host, manifest["XCPPort"])).as_dict()
        result["daq_metadata"] = session.start_daq(names)
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
        result["channels"] = evaluate_samples(samples, model, args.length)
        result["samples"] = len(samples)
        result["captured_seconds"] = samples[-1].timestamp_seconds - samples[0].timestamp_seconds if samples else 0
        result["passed"] = (all(item["passed"] for item in result["channels"].values())
                            and result["status_after_xcp_disconnect"]["running"])
        deadline = time.monotonic() + 9
        while time.monotonic() < deadline and service.status()["running"]:
            time.sleep(0.25)
        result["exited_at_stop_time"] = not service.status()["running"]
    except BaseException as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if session.connected:
            try:
                session.disconnect()
            except BaseException as exc:
                result["xcp_cleanup_error"] = str(exc)
        if service.connected:
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
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = args.output.with_suffix(".samples.jsonl.gz")
    with gzip.open(raw, "wt", encoding="utf-8") as stream:
        for sample in samples:
            stream.write(json.dumps(asdict(sample)) + "\n")
    result["raw_samples"] = str(raw.resolve())
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
