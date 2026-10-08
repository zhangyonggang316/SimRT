"""Independently audit the downloaded long-run console evidence."""

import collections
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simrt_linux_target/console"))
from validate_tmux import validate_capture


def main():
    output = Path(__file__).resolve().parent / "tmux_soak"
    report = json.loads((output / "tmux_validation.json").read_text())
    if "actual_seconds" not in report:
        raise SystemExit("The soak is still running; no final audit has been written.")
    launch = json.loads((output / "launch.json").read_text())
    failures, clocks, pids, states, capture_hashes = [], [], set(), collections.Counter(), {}
    previous_elapsed = -1
    for index, sample in enumerate(report["samples"]):
        top_path = output / "{:04d}_dashboard.txt".format(index)
        shell_path = output / "{:04d}_shell.txt".format(index)
        try:
            top, shell = top_path.read_text(encoding="utf-8"), shell_path.read_text(encoding="utf-8")
            panes = {int(key): value for key, value in sample["panes"].items()}
            validate_capture(panes, top, shell, sample["input_marker"])
            if not sample["passed"] or sample["elapsed_seconds"] <= previous_elapsed:
                raise AssertionError("Sample status or elapsed sequence is invalid")
            previous_elapsed = sample["elapsed_seconds"]
            width, height = sample["size"]
            if panes[0]["width"] != width or panes[0]["height"] + 7 != height:
                raise AssertionError("Captured pane size differs from the requested terminal size")
            pids.add(panes[0]["pid"])
            clock = re.search(r"(\d{2}:\d{2}:\d{2})\s*$", top.splitlines()[0])
            if not clock:
                raise AssertionError("Dashboard clock is missing")
            clocks.append(clock.group(1))
            state = re.search(r"^State: ([A-Z]+)", top, re.MULTILINE)
            if state:
                states[state.group(1)] += 1
            for path in (top_path, shell_path):
                capture_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception as exc:
            failures.append({"index": index, "error": "{}: {}".format(type(exc).__name__, exc)})
    clock_progress = bool(clocks) and all(left != right for left, right in zip(clocks, clocks[1:]))
    source = ROOT / "simrt_linux_target/console/simrt_console.py"
    current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    sizes = sorted({tuple(sample["size"]) for sample in report["samples"]})
    checks = {
        "validator_passed": report.get("passed") is True,
        "duration_at_least_requested": report["actual_seconds"] >= launch["requested_seconds"] >= 7200,
        "all_captures_and_commands_verified": not failures and bool(report["samples"]),
        "single_dashboard_pid": len(pids) == 1,
        "clock_changed_between_all_captures": clock_progress,
        "all_three_terminal_sizes": sizes == [(80, 25), (120, 40), (160, 50)],
        "current_source_matches_tested_source": current_hash == report["source_sha256"],
    }
    resources = []
    for path in sorted(output.glob("resources_*.json")):
        value = json.loads(path.read_text())
        value["file"] = path.name
        resources.append(value)
    resources.sort(key=lambda value: value["utc"])
    resource_summary = None
    if len(resources) >= 2:
        first, last = resources[0], resources[-1]
        seconds = (datetime.datetime.fromisoformat(last["utc"]) - datetime.datetime.fromisoformat(first["utc"])).total_seconds()
        ticks = last["utime_ticks"] + last["stime_ticks"] - first["utime_ticks"] - first["stime_ticks"]
        resource_summary = {"first": first["file"], "last": last["file"], "seconds": seconds,
                            "rss_first_kb": int(first["status"]["VmRSS"].split()[0]),
                            "rss_last_kb": int(last["status"]["VmRSS"].split()[0]),
                            "average_percent_of_one_logical_cpu": ticks / last["clock_ticks"] / seconds * 100}
    audit = {"kind": "independent_downloaded_capture_audit", "passed": all(checks.values()),
             "checks": checks, "actual_seconds": report["actual_seconds"],
             "sample_count": len(report["samples"]), "capture_count": len(capture_hashes),
             "observed_states": dict(states), "dashboard_pids": sorted(pids),
             "failures": failures, "ssh_error_count": len(launch.get("ssh_errors", [])),
             "resource_summary": resource_summary, "capture_sha256": capture_hashes,
             "physical_tty1_test": False, "reboot_test": False, "model_scheduling_acceptance": False}
    (output / "independent_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in audit.items() if key != "capture_sha256"}, indent=2))
    return 0 if audit["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
