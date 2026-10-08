#!/usr/bin/env python3
"""Exercise an isolated local tmux console; never connect to a remote host."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid


def tmux(socket, *arguments):
    return subprocess.run(["tmux", "-L", socket, *arguments], check=True,
                          capture_output=True, text=True, timeout=5).stdout


def pane_rows(raw):
    rows = [line.split("|") for line in raw.splitlines()]
    if len(rows) != 1 or any(len(row) != 6 for row in rows):
        raise AssertionError("Expected exactly one pane with six status fields")
    return {int(index): {"active": active == "1", "dead": dead == "1",
                         "width": int(width), "height": int(height), "pid": int(pid)}
            for index, active, dead, width, height, pid in rows}


def validate_capture(panes, dashboard):
    if set(panes) != {0} or panes[0]["dead"] or not panes[0]["active"]:
        raise AssertionError("One active dashboard must remain alive")
    if panes[0]["height"] < 24:
        raise AssertionError("Dashboard must fill the terminal")
    if "SimRT:" not in dashboard or "-- LOG" not in dashboard:
        raise AssertionError("The dashboard is blank, incomplete, or failed to redraw")
    if "OS: " in dashboard or "Kernel: " in dashboard:
        raise AssertionError("OS and Linux version must not be displayed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=120, help="Total test seconds")
    parser.add_argument("--sample-interval", type=float, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.duration < 2 or not 2 <= args.sample_interval <= 60:
        parser.error("duration must be >= 2 and sample-interval must be 2..60 seconds")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    dashboard_path = Path(__file__).with_name("simrt_console.py").resolve()
    socket = "simrt-validation-{}-{}".format(os.getpid(), uuid.uuid4().hex[:8])
    report = {"kind": "isolated_local_tmux_fullscreen", "socket": socket,
              "physical_tty1_test": False, "reboot_test": False,
              "source_sha256": hashlib.sha256(dashboard_path.read_bytes()).hexdigest(),
              "requested_seconds": args.duration, "samples": [], "passed": False}
    started = time.monotonic()
    report_path = output / "tmux_validation.json"

    def persist():
        temporary = report_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(report_path)

    try:
        command = "exec " + shlex.join(["python3", str(dashboard_path), "--interval", "0.5"])
        tmux(socket, "-f", "/dev/null", "new-session", "-d", "-s", "validation", "-x", "80", "-y", "25", command)
        tmux(socket, "set-option", "-t", "validation", "status", "off")
        tmux(socket, "set-window-option", "-t", "validation", "remain-on-exit", "on")
        tmux(socket, "select-pane", "-t", "validation:0.0")
        time.sleep(1)
        first_dashboard_pid = None
        sizes = [(80, 25), (120, 40), (160, 50), (80, 25)]
        while True:
            index = len(report["samples"])
            width, height = sizes[index % len(sizes)]
            tmux(socket, "resize-window", "-t", "validation:0", "-x", str(width), "-y", str(height))
            tmux(socket, "send-keys", "-t", "validation:0.0", "Escape", "q", "Enter")
            time.sleep(1)
            panes = pane_rows(tmux(socket, "list-panes", "-t", "validation:0", "-F",
                                   "#{pane_index}|#{pane_active}|#{pane_dead}|#{pane_width}|#{pane_height}|#{pane_pid}"))
            top = tmux(socket, "capture-pane", "-p", "-t", "validation:0.0")
            validate_capture(panes, top)
            if first_dashboard_pid is None:
                first_dashboard_pid = panes[0]["pid"]
            if panes[0]["pid"] != first_dashboard_pid:
                raise AssertionError("Dashboard process restarted during input/resize checks")
            (output / "{:04d}_dashboard.txt".format(index)).write_text(top, encoding="utf-8")
            report["samples"].append({"elapsed_seconds": time.monotonic() - started,
                                      "size": [width, height], "panes": panes,
                                      "passed": True})
            persist()
            remaining = args.duration - (time.monotonic() - started)
            if remaining <= 0:
                break
            time.sleep(min(args.sample_interval, remaining))
        report["passed"] = True
    except Exception as exc:
        report["error"] = "{}: {}".format(type(exc).__name__, exc)
    finally:
        # The socket is unique to this invocation, never the interactive server.
        try:
            tmux(socket, "kill-server")
        except (OSError, subprocess.SubprocessError):
            pass
        report["actual_seconds"] = time.monotonic() - started
        persist()
    print(json.dumps({"passed": report["passed"], "samples": len(report["samples"]),
                      "actual_seconds": report["actual_seconds"], "report": str(report_path)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
