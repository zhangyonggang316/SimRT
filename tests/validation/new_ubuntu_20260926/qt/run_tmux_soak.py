"""Launch and monitor an isolated, pinned-host console verification run."""

import argparse
import datetime
import json
from pathlib import Path
import shlex
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from target_session import connect, execute, HOST, FINGERPRINT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=int, default=7200)
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip("\r\n")
    output = Path(__file__).resolve().parent / "tmux_soak"
    output.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    remote_output = "/home/zh/simrt-console-validation-" + stamp
    program = "\n".join([
        "import json, pathlib, subprocess",
        "out = pathlib.Path(" + repr(remote_output) + ")",
        "out.mkdir(exist_ok=False)",
        "log = (out / 'runner.log').open('w')",
        "child = subprocess.Popen(['python3', '/home/zh/.local/lib/simrt-console/validate_tmux.py', '--duration', " + repr(str(args.duration)) + ", '--sample-interval', '30', '--output', str(out)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)",
        "print(json.dumps({'pid': child.pid, 'output': str(out)}))",
    ])
    client = connect(password)
    try:
        launch = execute(client, "python3 -c " + shlex.quote(program), timeout=20)
        if launch["exit_code"]:
            raise RuntimeError("Remote validator launch failed")
        child = json.loads(launch["stdout"])
    finally:
        client.close()
    record = {"host": HOST, "host_key_sha256": FINGERPRINT,
              "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "remote_output": remote_output, "remote_pid": child["pid"],
              "requested_seconds": args.duration, "ssh_errors": [],
              "production_tmux_touched": False, "reboot_performed": False,
              "sudo_used": False, "models_started": False}
    (output / "launch.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    deadline = time.monotonic() + args.duration + 300
    last_count = -1
    while time.monotonic() < deadline:
        client = None
        try:
            client = connect(password)
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_output + "/tmux_validation.json") as stream:
                    report = json.load(stream)
            except FileNotFoundError:
                report = None
            if report:
                (output / "tmux_validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                count = len(report.get("samples", []))
                if count != last_count:
                    latest = report["samples"][-1] if count else {}
                    print(json.dumps({"samples": count, "elapsed_seconds": latest.get("elapsed_seconds"),
                                      "latest_size": latest.get("size"), "error": report.get("error")}), flush=True)
                    last_count = count
                    if count:
                        for suffix in ("dashboard", "shell"):
                            name = "{:04d}_{}.txt".format(count - 1, suffix)
                            sftp.get(remote_output + "/" + name, str(output / ("latest_" + suffix + ".txt")))
                if "actual_seconds" in report:
                    for name in sftp.listdir(remote_output):
                        if Path(name).name == name and name.endswith((".json", ".txt", ".log")):
                            sftp.get(remote_output + "/" + name, str(output / name))
                    record["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    record["passed"] = report["passed"]
                    record["actual_seconds"] = report["actual_seconds"]
                    (output / "launch.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
                    print(json.dumps({"finished": True, "passed": report["passed"],
                                      "actual_seconds": report["actual_seconds"], "samples": count}), flush=True)
                    return 0 if report["passed"] else 1
        except Exception as exc:
            record["ssh_errors"].append({"utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                         "error": "{}: {}".format(type(exc).__name__, exc)})
            (output / "launch.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            print(json.dumps(record["ssh_errors"][-1]), flush=True)
        finally:
            if client:
                client.close()
        time.sleep(30)
    raise TimeoutError("Validator did not finish within the monitoring deadline")


if __name__ == "__main__":
    raise SystemExit(main())
