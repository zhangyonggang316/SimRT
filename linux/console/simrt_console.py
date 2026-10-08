#!/usr/bin/env python3
"""Read-only Linux console status. No GUI, XCP, SSH, or third-party modules."""

import argparse
import collections
import ipaddress
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import stat
import subprocess
import textwrap
import time


UNAVAILABLE = "unavailable"
MAX_JSON_BYTES = 65536
MAX_LOG_BYTES = 8192


def clean(value):
    """Prevent log/control sequences from changing the physical terminal."""
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in str(value))


def read_text(path, limit=MAX_JSON_BYTES):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            return None
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return None


def read_json(path):
    raw = read_text(path)
    try:
        value = json.loads(raw) if raw is not None else None
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, RecursionError):
        return None


def number(value):
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        try:
            return value if math.isfinite(value) and value >= 0 else None
        except OverflowError:
            return None
    return None


def duration(seconds):
    if number(seconds) is None:
        return UNAVAILABLE
    return metric(seconds * 1000.0, " ms")


def hours_seconds(seconds):
    if number(seconds) is None:
        return UNAVAILABLE
    whole_seconds = int(seconds)
    hours, remainder = divmod(whole_seconds, 3600)
    # Round the fractional second separately to avoid overflow on long durations.
    milliseconds = remainder * 1000 + round((seconds - whole_seconds) * 1000)
    carry, milliseconds = divmod(milliseconds, 3600000)
    return "{} h {}.{:03d} s".format(hours + carry, milliseconds // 1000, milliseconds % 1000)


def nanoseconds_ms(value):
    value = number(value)
    return metric(value / 1e6 if value is not None else None, " ms", 6)


def metric(value, suffix="", precision=3):
    value = number(value)
    if value is None:
        return UNAVAILABLE
    if isinstance(value, int):
        return str(value) + suffix
    return ("{:." + str(precision) + "f}").format(value) + suffix


def tail_log(path, lines=8):
    try:
        if not stat.S_ISREG(Path(path).stat().st_mode):
            return []
        with Path(path).open("rb") as stream:
            length = stream.seek(0, 2)
            stream.seek(max(0, length - MAX_LOG_BYTES))
            raw = stream.read(MAX_LOG_BYTES)
        rows = raw.decode("utf-8", errors="replace").splitlines()
        if length > MAX_LOG_BYTES and rows:
            rows = rows[1:]
        return [clean(row) for row in rows[-lines:]]
    except OSError:
        return []


class Collector:
    def __init__(self, proc="/proc", sys_root="/sys", uid=None,
                 clock_ticks=None, disk_path="/", network_runner=None,
                 os_release="/etc/os-release", display_interval=1.0):
        self.proc = Path(proc)
        self.sys_root = Path(sys_root)
        self.uid = os.getuid() if uid is None else uid
        self.clock_ticks = os.sysconf("SC_CLK_TCK") if clock_ticks is None else clock_ticks
        self.disk_path = disk_path
        self.network_runner = network_runner or self._network_command
        self.previous_cpu = None
        self.network_at = float("-inf")
        self.network = UNAVAILABLE
        self.network_rows = [UNAVAILABLE]
        self.manifests = {}
        self.previous_processes = set()
        self.events = collections.deque(maxlen=8)
        self.display_interval = display_interval
        self.os_name = self._os_name(os_release)
        self.cpu_model = self._cpu_model()

    @staticmethod
    def _os_name(path):
        for row in (read_text(path) or "").splitlines():
            key, separator, value = row.partition("=")
            if separator and key == "PRETTY_NAME":
                try:
                    tokens = shlex.split(value)
                    return " ".join(tokens) if tokens else UNAVAILABLE
                except ValueError:
                    return UNAVAILABLE
        return UNAVAILABLE

    def _cpu_model(self):
        try:
            with (self.proc / "cpuinfo").open("r", encoding="utf-8", errors="replace") as stream:
                rows = stream.read(4096).splitlines()
        except OSError:
            rows = []
        for row in rows:
            key, separator, value = row.partition(":")
            if separator and key.strip() in ("model name", "Hardware", "Processor"):
                return value.strip() or UNAVAILABLE
        return UNAVAILABLE

    @staticmethod
    def _network_command():
        result = subprocess.run(["ip", "-j", "address", "show"],
                                capture_output=True, text=True, timeout=1.5, check=True)
        return json.loads(result.stdout)

    def _network(self, monotonic):
        if monotonic - self.network_at < 5:
            return self.network
        self.network_at = monotonic
        try:
            interfaces = self.network_runner()
            if not isinstance(interfaces, list):
                raise ValueError("Expected interface list")
            rows = []
            for interface in interfaces:
                if (interface["ifname"] == "lo" or interface.get("link_type") == "loopback"
                        or "LOOPBACK" in interface.get("flags", [])):
                    continue
                label = "{} [{}]".format(clean(interface["ifname"]), clean(interface.get("operstate", "UNKNOWN")))
                mac = clean(interface.get("address") or UNAVAILABLE)
                wireless = (self.sys_root / 'class/net' / interface['ifname'] / 'wireless').is_dir()
                addresses = []
                for address in interface.get("addr_info", []):
                    if address.get("family") not in ("inet", "inet6"):
                        continue
                    ip = ipaddress.ip_interface("{}/{}".format(address["local"], address["prefixlen"]))
                    if ip.ip.is_loopback or wireless and ip.version == 6 and ip.ip.is_link_local:
                        continue
                    addresses.append("{} / {}".format(ip.ip, ip.netmask) if ip.version == 4 else str(ip))
                rows.extend("{}: {} ({})".format(label, address, mac)
                            for address in (addresses or ["no IP address"]))
            self.network_rows = rows or ["no network interfaces"]
            self.network = "; ".join(self.network_rows)
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, AttributeError):
            self.network = UNAVAILABLE
            self.network_rows = [UNAVAILABLE]
        return self.network

    def _cpu(self):
        raw = read_text(self.proc / "stat")
        try:
            fields = next(row.split()[1:] for row in (raw or "").splitlines() if row.startswith("cpu "))
            values = list(map(int, fields))
            # guest and guest_nice are already included in user and nice.
            current = (sum(values[:8]), values[3] + (values[4] if len(values) > 4 else 0))
            previous, self.previous_cpu = self.previous_cpu, current
            if previous is None or current[0] <= previous[0]:
                return None
            return max(0.0, min(100.0, 100 * (1 - (current[1] - previous[1]) / (current[0] - previous[0]))))
        except (ValueError, IndexError, StopIteration):
            return None

    def _memory(self):
        raw = read_text(self.proc / "meminfo") or ""
        fields = {}
        for line in raw.splitlines():
            match = re.fullmatch(r"(\w+):\s+(\d+) kB", line)
            if match:
                fields[match[1]] = int(match[2]) * 1024
        total = fields.get("MemTotal", 0)
        available = fields.get("MemAvailable")
        if not total or available is None:
            return None
        return {"used": total - available, "total": total, "percent": 100 * (total - available) / total}

    def _manifest(self, executable):
        path = executable.with_suffix(".xcp-manifest.json")
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return {}
        cached = self.manifests.get(str(path))
        if cached is None or cached[0] != stamp:
            value = read_json(path) or {}
            if value.get("ELFFile") != executable.name:
                value = {}
            self.manifests[str(path)] = (stamp, value)
        return self.manifests[str(path)][1]

    def _telemetry(self, executable, pid, now, monotonic):
        path = Path(str(executable) + ".simrt-status.json")
        value = read_json(path)
        if value is None:
            return {}, "unavailable (runtime status missing or invalid)", "UNVERIFIED"
        if value.get("schema_version") != 1 or value.get("event") != "simrt_status":
            return {}, "unavailable (unsupported runtime status schema)", "UNVERIFIED"
        if value.get("pid") != pid:
            return {}, "unavailable (runtime PID does not match)", "UNVERIFIED"
        try:
            age = now - path.stat().st_mtime
        except OSError:
            return {}, "unavailable (runtime status disappeared)", "UNVERIFIED"
        if age < -2 or age > 5:
            return {}, "unavailable (runtime status stale)", "STALE"
        sample_ns = number(value.get("sample_monotonic_ns"))
        sample_age = monotonic - sample_ns / 1e9 if sample_ns is not None else None
        if sample_age is None or sample_age < -2 or sample_age > 5:
            return {}, "unavailable (runtime sample stale or missing)", "STALE"
        runtime_state = value.get("state")
        if runtime_state == "STARTING":
            return {}, "runtime reports STARTING; no completed step confirmed", "STARTING"
        if runtime_state == "STOPPED":
            return {}, "runtime reports STOPPED; process still exists", "STOPPING"
        if runtime_state != "RUNNING":
            return {}, "unavailable (runtime has not reported RUNNING)", "UNVERIFIED"
        completed = number(value.get("model_step_completed_calls"))
        if completed is None:
            return {}, "unavailable (completed-step count missing)", "UNVERIFIED"
        if completed < 2:
            value = {key: item for key, item in value.items()
                     if not key.startswith("model_step_interval_")
                     and (completed > 0 or not key.startswith("model_step_execution_"))}
        state = "RUNNING" if completed > 0 else "STARTING"
        return value, "live ({:.1f}s old)".format(max(0, sample_age)), state

    def _processes(self, uptime, now, monotonic):
        models = []
        try:
            candidates = list(self.proc.iterdir())
        except OSError:
            return models
        for process in candidates:
            if not process.name.isdigit():
                continue
            try:
                if process.stat().st_uid != self.uid:
                    continue
                executable = Path(os.readlink(str(process / "exe")))
                if executable.suffix != ".elf":
                    continue
                process_stat = read_text(process / "stat") or ""
                fields = process_stat[process_stat.rfind(")") + 2:].split()
                if fields[0] in ("Z", "X"):
                    continue
                started = int(fields[19]) / self.clock_ticks
                pid = int(process.name)
                manifest = self._manifest(executable)
                telemetry, telemetry_state, model_state = self._telemetry(executable, pid, now, monotonic)
                if fields[0] in ("T", "t"):
                    telemetry, telemetry_state, model_state = {}, "process is paused by the OS", "PAUSED"
                models.append({"pid": pid, "executable": str(executable),
                               "name": manifest.get("ModelName") or executable.stem,
                               "release": manifest.get("MATLABRelease"),
                               "state": model_state,
                               "started": started,
                               "elapsed": max(0, uptime - started) if uptime is not None else None,
                               "telemetry": telemetry, "telemetry_state": telemetry_state,
                               "logs": tail_log(str(executable) + ".pyxcp-host.log")})
            except (OSError, ValueError, IndexError):
                continue
        models.sort(key=lambda model: (model["started"], model["pid"]), reverse=True)
        # Only cache manifests for executable directories discovered in /proc.
        keep = {str(Path(model["executable"]).with_suffix(".xcp-manifest.json")) for model in models}
        self.manifests = {path: value for path, value in self.manifests.items() if path in keep}
        return models

    def collect(self, now=None, monotonic=None):
        if hasattr(time, 'tzset'):
            time.tzset()
        now = time.time() if now is None else now
        monotonic = time.monotonic() if monotonic is None else monotonic
        try:
            uptime = float((read_text(self.proc / "uptime") or "").split()[0])
        except (ValueError, IndexError):
            uptime = None
        models = self._processes(uptime, now, monotonic)
        current = {(model["pid"], model["started"], str(model["name"])) for model in models}
        timestamp = time.strftime("%H:%M:%S", time.localtime(now))
        for pid, _, name in sorted(current - self.previous_processes):
            self.events.append("{} PROCESS FOUND {} (PID {})".format(timestamp, clean(name), pid))
        for pid, _, name in sorted(self.previous_processes - current):
            self.events.append("{} STOPPED {} (PID {})".format(timestamp, clean(name), pid))
        self.previous_processes = current
        realtime_flag = read_text(self.sys_root / "kernel/realtime")
        realtime = (realtime_flag or "").strip()
        try:
            disk = shutil.disk_usage(self.disk_path)
            disk = {"used": disk.used, "total": disk.total, "percent": disk.used * 100 / disk.total}
        except OSError:
            disk = None
        network = self._network(monotonic)
        return {"hostname": platform.node(), "kernel": platform.release(),
                "realtime": {"1": "YES", "0": "NO"}.get(realtime, "UNKNOWN"),
                "realtime_detail": "flag missing/unreadable" if realtime_flag is None else "invalid flag" if realtime not in ("0", "1") else "kernel flag=" + realtime,
                "os_name": self.os_name, "cpu_model": self.cpu_model,
                "display_interval": self.display_interval,
                "network": network, "network_rows": list(self.network_rows),
                "network_page": int(monotonic // 5), "cpu_percent": self._cpu(),
                "memory": self._memory(), "disk": disk, "uptime": uptime,
                "models": models, "events": list(self.events), "time": timestamp}


def render_lines(snapshot, width, height):
    """Pure fixed-size layout, also usable for capture and fixture tests."""
    width, height = max(0, width), max(0, height)
    memory, disk = snapshot.get("memory"), snapshot.get("disk")
    memory_text = metric(memory["percent"], "%", 1) if memory else UNAVAILABLE
    disk_total = number(disk.get("total")) if disk else None
    disk_text = "{} of {} GB".format(metric(disk["percent"], "%", 1), metric(disk_total / 1e9 if disk_total is not None else None, precision=1)) if disk else UNAVAILABLE
    realtime_text = snapshot.get("realtime", "UNKNOWN")
    if realtime_text == "UNKNOWN":
        realtime_text += " (flag unavailable)"
    rows = [
        "SimRT: {} | UI refresh: {} | {}".format(snapshot.get("hostname", UNAVAILABLE), duration(snapshot.get("display_interval")), snapshot.get("time", "")),
        "CPU model: " + snapshot.get("cpu_model", UNAVAILABLE),
        "PREEMPT_RT: {}".format(realtime_text),
        "CPU: {}  Memory: {}  Disk: {}".format(metric(snapshot.get("cpu_percent"), "%", 1), memory_text, disk_text),
    ]
    models = snapshot.get("models", [])
    logs = list(snapshot.get("events", []))
    if models:
        model = models[0]
        stats = model.get("telemetry", {})
        others = " +{} other".format(len(models) - 1) if len(models) > 1 else ""
        elapsed_ns = number(stats.get("elapsed_ns"))
        elapsed = hours_seconds(elapsed_ns / 1e9) if elapsed_ns is not None else hours_seconds(model.get("elapsed"))
        elapsed_label = "Model elapsed" if elapsed_ns is not None else "Process elapsed"
        stop = ("inf" if stats["stop_time_seconds"] is None else hours_seconds(stats["stop_time_seconds"])) if "stop_time_seconds" in stats else UNAVAILABLE
        rows += [
            "State: {} -> {} (PID {}){}".format(model.get("state", "UNVERIFIED"), model["name"], model["pid"], others),
            "{}: {} / {}  Period: {}".format(elapsed_label, elapsed, stop, nanoseconds_ms(stats.get("period_ns"))),
            "MATLAB: {} | Steps: {} calls / {} completed".format("R" + str(model["release"]).lstrip("Rr") if model.get("release") else UNAVAILABLE, metric(stats.get("model_step_calls")), metric(stats.get("model_step_completed_calls"))),
            "Deadline misses: {}  Skipped periods: {}".format(metric(stats.get("deadline_misses")), metric(stats.get("skipped_releases"))),
            "Task execution current/max: {} / {}".format(nanoseconds_ms(stats.get("model_step_execution_current_ns")), nanoseconds_ms(stats.get("model_step_execution_max_ns"))),
            "Interval min/avg/max: {} / {} / {}".format(nanoseconds_ms(stats.get("model_step_interval_min_ns")), nanoseconds_ms(stats.get("model_step_interval_mean_ns")), nanoseconds_ms(stats.get("model_step_interval_max_ns"))),
            "Jitter > +/-50 us: early {} / late {}".format(
                metric(stats.get("model_step_interval_early_count") if stats.get("interval_tolerance_ns") == 50000 else None),
                metric(stats.get("model_step_interval_late_count") if stats.get("interval_tolerance_ns") == 50000 else None)),
            "Telemetry: " + model.get("telemetry_state", UNAVAILABLE),
        ]
        logs.extend(model.get("logs", []))
    else:
        rows += ["State: IDLE (no running .elf owned by this user)",
                 "System uptime: " + duration(snapshot.get("uptime")),
                 "Model period / deadlines / task execution: " + UNAVAILABLE]
    network_rows = []
    for entry in snapshot.get("network_rows", [snapshot.get("network", UNAVAILABLE)]):
        network_rows.extend(textwrap.wrap(clean(entry), width=max(1, width), subsequent_indent="  ", break_on_hyphens=False))
    # Rotate overflowing address rows so even small displays expose every interface.
    network_space = max(1, height - len(rows) - 3)
    pages = max(1, math.ceil(len(network_rows) / network_space))
    page = snapshot.get("network_page", 0) % pages
    network_header = "Network:" + (" [{}/{}]".format(page + 1, pages) if pages > 1 else "")
    rows[3:3] = [network_header] + network_rows[page * network_space:(page + 1) * network_space]
    rows.append("-- LOG " + "-" * max(0, width - 7))
    available = max(0, height - len(rows))
    rows.extend(logs[-available:] if available else [])
    return [clean(row)[:width] for row in rows[:height]]


def run_screen(screen, collector, interval):
    import curses
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_CYAN, curses.COLOR_BLACK)
        screen.bkgd(" ", curses.color_pair(1))
    screen.nodelay(True)
    while True:
        height, width = screen.getmaxyx()
        rows = render_lines(collector.collect(), max(0, width - 1), height)
        screen.erase()
        for y, row in enumerate(rows):
            label, separator, value = row.partition(": ")
            try:
                if separator:
                    screen.addstr(y, 0, label + separator, curses.color_pair(1) | curses.A_BOLD)
                    screen.addstr(value, curses.color_pair(2))
                else:
                    screen.addstr(y, 0, row, curses.color_pair(1))
            except curses.error:
                pass
        screen.refresh()
        # Local keys never expose a shell; administration remains available over SSH.
        screen.getch()
        time.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Print one real snapshot without curses")
    parser.add_argument("--json", action="store_true", help="Print one real JSON snapshot")
    parser.add_argument("--width", type=int, default=80)
    parser.add_argument("--height", type=int, default=24)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args(argv)
    if not 0.2 <= args.interval <= 10:
        parser.error("--interval must be between 0.2 and 10 seconds")
    collector = Collector(display_interval=args.interval)
    if args.once or args.json:
        snapshot = collector.collect()
        print(json.dumps(snapshot, indent=2) if args.json else "\n".join(render_lines(snapshot, args.width, args.height)))
        return 0
    import curses
    try:
        curses.wrapper(run_screen, collector, args.interval)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
