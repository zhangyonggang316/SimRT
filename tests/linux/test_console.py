"""Collector boundary checks use synthetic proc files, never a target machine."""

import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'linux' / 'console'))
from simrt_console import Collector, MAX_JSON_BYTES, clean, hours_seconds, number, read_json, render_lines, tail_log
from validate_tmux import pane_rows, validate_capture


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.sys = self.root / "sys"
        (self.sys / "kernel").mkdir(parents=True)
        self.write(self.proc / "uptime", "123.0 0.0\n")
        self.write(self.proc / "stat", "cpu  10 0 10 80 0 0 0 0 5 0\n")
        self.write(self.proc / "meminfo", "MemTotal: 1000 kB\nMemAvailable: 750 kB\n")
        self.write(self.proc / "cpuinfo", "processor : 0\nmodel name : Intel(R) Core(TM) i5-8350U CPU @ 1.70GHz\n")
        self.os_release = self.root / "os-release"
        self.write(self.os_release, 'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04 LTS"\n')
        self.write(self.sys / "kernel/realtime", "1\n")
        self.network_calls = 0
        self.collector = Collector(proc=self.proc, sys_root=self.sys,
                                   uid=self.root.stat().st_uid, clock_ticks=100,
                                   disk_path=str(self.root), network_runner=self.network,
                                   os_release=self.os_release, display_interval=1.0)

    def write(self, path, text):
        path.write_text(text, encoding="utf-8")

    def network(self):
        self.network_calls += 1
        return [{"ifname": "wlan0", "addr_info": [
            {"family": "inet", "local": "192.168.219.195", "prefixlen": 24}]}]

    def test_deep_json_and_oversized_integer_do_not_terminate_display(self):
        nested = self.root / "nested.json"
        self.write(nested, '{"metric":' + '[' * 1100 + '0' + ']' * 1100 + '}')
        self.assertIsNone(read_json(nested))
        self.assertIsNone(number(10 ** 1000))
        executable = self.process()
        self.telemetry(executable, {"pid": 42, "model_step_execution_current_ns": 10 ** 1000})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertIn("Task execution current/max: unavailable / unavailable",
                      "\n".join(render_lines(snapshot, 120, 30)))

    def process(self, pid=42, start_ticks=2300, state="S", name="model (worker)"):
        directory = self.proc / str(pid)
        directory.mkdir(exist_ok=True)
        fields = [state] + ["0"] * 18 + [str(start_ticks)] + ["0"] * 5
        self.write(directory / "stat", "{} ({}) {}".format(pid, name, " ".join(fields)))
        executable = self.root / ("model_{}.elf".format(pid))
        self.write(executable, "placeholder")
        self.write(executable.with_suffix(".xcp-manifest.json"), json.dumps({
            "ELFFile": executable.name, "ModelName": "display_model", "MATLABRelease": "2024b"}))
        return executable

    def telemetry(self, executable, value, mtime=1000):
        path = Path(str(executable) + ".simrt-status.json")
        payload = {"schema_version": 1, "event": "simrt_status", "state": "RUNNING", "sample_monotonic_ns": 0,
                   "model_step_calls": 2, "model_step_completed_calls": 2}
        payload.update(value)
        self.write(path, json.dumps(payload))
        os.utime(path, (mtime, mtime))
        return path

    def test_real_sources_cpu_delta_memory_network_and_rt(self):
        first = self.collector.collect(now=1000, monotonic=0)
        self.assertIsNone(first["cpu_percent"])
        self.assertEqual(first["memory"]["percent"], 25)
        self.assertEqual(first["realtime"], "YES")
        self.assertIn("192.168.219.195 / 255.255.255.0", first["network"])
        self.write(self.proc / "stat", "cpu  20 0 20 160 0 0 0 0 10 0\n")
        second = self.collector.collect(now=1001, monotonic=1)
        self.assertAlmostEqual(second["cpu_percent"], 20)
        self.assertEqual(self.network_calls, 1)
        self.collector.collect(now=1006, monotonic=6)
        self.assertEqual(self.network_calls, 2)

    def test_clock_refresh_reloads_the_system_timezone(self):
        with patch('simrt_console.time.tzset', create=True) as reload_timezone:
            self.collector.collect(now=1000, monotonic=0)
            self.collector.collect(now=1001, monotonic=1)
        self.assertEqual(reload_timezone.call_count, 2)

    def test_process_manifest_elapsed_and_live_runtime_data(self):
        executable = self.process()
        self.telemetry(executable, {"pid": 42, "period_ns": 1000000,
                                    "deadline_misses": 2, "model_step_execution_current_ns": 9000,
                                    "elapsed_ns": 99000000000, "stop_time_seconds": None})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1001, monotonic=1)
        model = snapshot["models"][0]
        self.assertEqual(model["name"], "display_model")
        self.assertEqual(model["elapsed"], 100)
        self.assertEqual(model["telemetry"]["deadline_misses"], 2)
        self.assertEqual(model["telemetry_state"], "live (1.0s old)")
        self.assertEqual(model["state"], "RUNNING")
        rendered = "\n".join(render_lines(snapshot, 80, 18))
        self.assertIn("1.000000 ms", rendered)
        self.assertIn("0.009000 ms", rendered)
        self.assertIn("Model elapsed: 0 h 99.000 s / inf", rendered)

    def test_hours_seconds_rounding_and_unbounded_hours(self):
        for seconds, expected in [
            (0, "0 h 0.000 s"),
            (-0.0, "0 h 0.000 s"),
            (59030.831, "16 h 1430.831 s"),
            (3599.9994, "0 h 3599.999 s"),
            (3599.9996, "1 h 0.000 s"),
            (3600, "1 h 0.000 s"),
            (49 * 3600 + 0.125, "49 h 0.125 s"),
            (10 ** 12 * 3600 + 1430, "1000000000000 h 1430.000 s"),
        ]:
            with self.subTest(seconds=seconds):
                self.assertEqual(hours_seconds(seconds), expected)
        self.assertTrue(hours_seconds(1e308).endswith(" s"))

    def test_hours_seconds_invalid_values_remain_unavailable(self):
        for value in [None, -1, -0.001, float('nan'), float('inf'), -float('inf'), "12", True, 10 ** 1000]:
            with self.subTest(value=value):
                self.assertEqual(hours_seconds(value), "unavailable")

    def test_long_model_elapsed_and_stop_use_hours_without_changing_timing_units(self):
        executable = self.process()
        self.telemetry(executable, {"pid": 42, "elapsed_ns": 59030831000000,
                                   "stop_time_seconds": 25 * 3600 + 2.5, "period_ns": 1000000,
                                   "model_step_execution_current_ns": 9000,
                                   "model_step_execution_max_ns": 12000,
                                   "model_step_interval_min_ns": 999000,
                                   "model_step_interval_mean_ns": 1000000,
                                   "model_step_interval_max_ns": 1001000})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        lines = render_lines(snapshot, 119, 33)
        self.assertIn("Model elapsed: 16 h 1430.831 s / 25 h 2.500 s  Period: 1.000000 ms", lines)
        self.assertIn("Task execution current/max: 0.009000 ms / 0.012000 ms", lines)
        self.assertIn("Interval min/avg/max: 0.999000 ms / 1.000000 ms / 1.001000 ms", lines)
        self.assertTrue(all(len(line) <= 119 for line in lines))

    def test_fresh_file_does_not_hide_a_stalled_model_sample(self):
        executable = self.process()
        self.telemetry(executable, {"pid": 42, "sample_monotonic_ns": 0})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=10)
        self.assertEqual(snapshot["models"][0]["telemetry"], {})
        self.assertIn("sample stale", snapshot["models"][0]["telemetry_state"])
        self.assertEqual(snapshot["models"][0]["state"], "STALE")
        self.assertNotIn("State: RUNNING", "\n".join(render_lines(snapshot, 80, 18)))

    def test_jitter_counts_require_matching_tolerance(self):
        executable = self.process()
        for tolerance, expected in [(50000, "early 2 / late 3"), (100000, "early unavailable / late unavailable")]:
            with self.subTest(tolerance=tolerance):
                self.telemetry(executable, {"pid": 42, "interval_tolerance_ns": tolerance,
                    "model_step_interval_early_count": 2, "model_step_interval_late_count": 3})
                with patch("simrt_console.os.readlink", return_value=str(executable)):
                    snapshot = self.collector.collect(now=1000, monotonic=0)
                self.assertIn("Jitter > +/-50 us: " + expected, render_lines(snapshot, 119, 33))

    def test_unsupported_schema_and_stopped_telemetry_are_unavailable(self):
        executable = self.process()
        for value in [{"schema_version": 2}, {"state": "STOPPED"}]:
            self.telemetry(executable, dict(value, pid=42))
            with patch("simrt_console.os.readlink", return_value=str(executable)):
                snapshot = self.collector.collect(now=1000, monotonic=0)
            self.assertEqual(snapshot["models"][0]["telemetry"], {})

    def test_stale_or_mismatched_runtime_data_never_shows_fake_counters(self):
        executable = self.process()
        for value, modified, reason in [
            ({"pid": 7, "deadline_misses": 0}, 1000, "PID"),
            ({"pid": 42, "deadline_misses": 0}, 990, "stale"),
            ({"pid": 42, "deadline_misses": 0}, 1020, "stale"),
        ]:
            with self.subTest(reason=reason, modified=modified):
                self.telemetry(executable, value, modified)
                with patch("simrt_console.os.readlink", return_value=str(executable)):
                    snapshot = self.collector.collect(now=1000, monotonic=0)
                self.assertEqual(snapshot["models"][0]["telemetry"], {})
                self.assertIn(reason, snapshot["models"][0]["telemetry_state"])
                self.assertIn("Deadline misses: unavailable", "\n".join(render_lines(snapshot, 80, 18)))

    def test_missing_rt_flag_is_not_inferred_from_kernel_name(self):
        (self.sys / "kernel/realtime").unlink()
        with patch("simrt_console.platform.release", return_value="6.8-PREEMPT_RT"):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertEqual(snapshot["realtime"], "UNKNOWN")
        self.assertIn("missing", snapshot["realtime_detail"])

    def test_zero_rt_flag_means_no_and_invalid_flag_remains_unknown(self):
        self.write(self.sys / "kernel/realtime", "0\n")
        self.assertEqual(self.collector.collect(now=1000, monotonic=0)["realtime"], "NO")
        self.write(self.sys / "kernel/realtime", "garbage\n")
        self.assertEqual(self.collector.collect(now=1000, monotonic=0)["realtime"], "UNKNOWN")

    def test_identity_disk_capacity_release_and_refresh_have_distinct_labels(self):
        executable = self.process()
        self.telemetry(executable, {"pid": 42, "period_ns": 1000000})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        snapshot["disk"] = {"total": 256000000000, "percent": 8.5}
        text = "\n".join(render_lines(snapshot, 79, 18))
        self.assertNotIn("Ubuntu", text)
        self.assertNotIn("Kernel:", text)
        self.assertIn("CPU model: Intel(R) Core(TM) i5-8350U", text)
        self.assertIn("Disk: 8.5% of 256.0 GB", text)
        self.assertIn("MATLAB: R2024b", text)
        self.assertIn("UI refresh: 1000.000 ms", text)
        self.assertIn("Period: 1.000000 ms", text)

    def test_non_loopback_interfaces_show_ipv4_ipv6_mac_and_unassigned_down(self):
        self.collector.network_runner = lambda: [
            {"ifname": "lo", "operstate": "UNKNOWN", "addr_info": [
                {"family": "inet", "local": "127.0.0.1", "prefixlen": 8},
                {"family": "inet6", "local": "::1", "prefixlen": 128}]},
            {"ifname": "eth0", "operstate": "DOWN", "address": "02:00:00:00:00:01", "addr_info": []},
            {"ifname": "eth1", "operstate": "UP", "address": "02:00:00:00:00:02", "addr_info": [
                {"family": "inet", "local": "10.1.2.3", "prefixlen": 24},
                {"family": "inet6", "local": "2001:db8::1234", "prefixlen": 64}]}]
        snapshot = self.collector.collect(now=1000, monotonic=0)
        expected = [
            "eth0 [DOWN]: no IP address (02:00:00:00:00:01)",
            "eth1 [UP]: 10.1.2.3 / 255.255.255.0 (02:00:00:00:00:02)",
            "eth1 [UP]: 2001:db8::1234/64 (02:00:00:00:00:02)",
        ]
        self.assertEqual(snapshot["network_rows"], expected)
        text = "\n".join(render_lines(snapshot, 80, 25))
        for row in expected:
            self.assertIn(row, text)
        self.assertNotIn("lo [", text)
        self.assertNotIn("127.0.0.1", text)
        self.assertNotIn("::1/128", text)

    def test_loopback_type_flags_and_addresses_are_hidden(self):
        self.collector.network_runner = lambda: [
            {"ifname": "loop-type", "link_type": "loopback", "addr_info": []},
            {"ifname": "loop-flags", "flags": ["UP", "LOOPBACK"], "addr_info": []},
            {"ifname": "eth0", "operstate": "UP", "address": "02:00:00:00:00:01", "addr_info": [
                {"family": "inet", "local": "127.2.3.4", "prefixlen": 8},
                {"family": "inet6", "local": "::1", "prefixlen": 128},
                {"family": "inet", "local": "10.1.2.3", "prefixlen": 24}]}]
        snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertEqual(snapshot["network_rows"], [
            "eth0 [UP]: 10.1.2.3 / 255.255.255.0 (02:00:00:00:00:01)"])

    def test_missing_or_empty_mac_is_explicitly_unavailable(self):
        self.collector.network_runner = lambda: [
            {"ifname": "eth0", "operstate": "DOWN", "addr_info": []},
            {"ifname": "eth1", "operstate": "UP", "address": "", "addr_info": [
                {"family": "inet", "local": "10.1.2.3", "prefixlen": 24}]}]
        snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertEqual(snapshot["network_rows"], [
            "eth0 [DOWN]: no IP address (unavailable)",
            "eth1 [UP]: 10.1.2.3 / 255.255.255.0 (unavailable)",
        ])

    def test_wifi_link_local_ipv6_is_hidden_without_hiding_other_addresses(self):
        (self.sys / 'class/net/wlan0/wireless').mkdir(parents=True)
        addresses = [
            {"family": "inet", "local": "192.0.2.3", "prefixlen": 24},
            {"family": "inet6", "local": "fe80::1234", "prefixlen": 64},
            {"family": "inet6", "local": "2001:db8::1234", "prefixlen": 64},
        ]
        self.collector.network_runner = lambda: [
            {"ifname": "wlan0", "address": "02:00:00:00:00:01", "addr_info": addresses},
            {"ifname": "eth0", "address": "02:00:00:00:00:02", "addr_info": addresses},
        ]
        rows = self.collector.collect(now=1000, monotonic=0)['network_rows']
        self.assertEqual(sum(row.startswith('wlan0 ') for row in rows), 2)
        self.assertEqual(sum(row.startswith('eth0 ') for row in rows), 3)
        self.assertNotIn('wlan0 [UNKNOWN]: fe80::1234/64 (02:00:00:00:00:01)', rows)
        self.assertIn('wlan0 [UNKNOWN]: 192.0.2.3 / 255.255.255.0 (02:00:00:00:00:01)', rows)
        self.assertIn('wlan0 [UNKNOWN]: 2001:db8::1234/64 (02:00:00:00:00:01)', rows)

    def test_narrow_network_rows_wrap_without_losing_mac(self):
        self.collector.network_runner = lambda: [
            {"ifname": "eth1", "operstate": "UP", "address": "02:00:00:00:00:02", "addr_info": [
                {"family": "inet", "local": "10.1.2.3", "prefixlen": 24},
                {"family": "inet6", "local": "2001:db8::1234", "prefixlen": 64}]}]
        snapshot = self.collector.collect(now=1000, monotonic=0)
        lines = render_lines(snapshot, 39, 18)
        start = lines.index("Network:") + 1
        end = next(index for index in range(start, len(lines)) if lines[index].startswith("CPU: "))
        network_lines = lines[start:end]
        self.assertGreater(len(network_lines), len(snapshot["network_rows"]))
        self.assertTrue(all(len(line) <= 39 for line in lines))
        self.assertEqual(" ".join(line.strip() for line in network_lines),
                         " ".join(snapshot["network_rows"]))

    def test_network_overflow_rotates_without_losing_addresses(self):
        snapshot = self.collector.collect(now=1000, monotonic=0)
        snapshot["network_rows"] = ["eth{}: 192.168.1.{}/24".format(i, i) for i in range(40)]
        displayed = []
        for page in range(40):
            snapshot["network_page"] = page
            displayed.extend(render_lines(snapshot, 39, 18))
        text = "\n".join(displayed)
        for row in snapshot["network_rows"]:
            self.assertIn(row, text)

    def test_finite_stop_time_and_process_fallback_use_hours_seconds(self):
        executable = self.process()
        self.telemetry(executable, {"pid": 42, "stop_time_seconds": 2.5})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertIn("Process elapsed: 0 h 100.000 s / 0 h 2.500 s", "\n".join(render_lines(snapshot, 100, 25)))

    def test_process_without_runtime_confirmation_is_not_a_running_model(self):
        executable = self.process()
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertEqual(snapshot["models"][0]["state"], "UNVERIFIED")
        self.assertIn("PROCESS FOUND", snapshot["events"][0])
        self.assertNotIn("RUNNING", "\n".join(render_lines(snapshot, 80, 18)))

    def test_initial_zero_completed_steps_is_starting_without_fake_timings(self):
        executable = self.process()
        self.telemetry(executable, {"pid": 42, "model_step_calls": 0, "model_step_completed_calls": 0,
                                   "model_step_execution_current_ns": 0, "model_step_interval_min_ns": 0})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertEqual(snapshot["models"][0]["state"], "STARTING")
        text = "\n".join(render_lines(snapshot, 80, 18))
        self.assertIn("Task execution current/max: unavailable / unavailable", text)
        self.assertIn("Interval min/avg/max: unavailable", text)

    def test_paused_process_is_not_shown_as_running_even_with_fresh_status(self):
        executable = self.process(state="T")
        self.telemetry(executable, {"pid": 42})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        self.assertEqual(snapshot["models"][0]["state"], "PAUSED")
        self.assertEqual(snapshot["models"][0]["telemetry"], {})

    def test_other_uid_zombie_and_non_elf_processes_are_excluded(self):
        executable = self.process(state="Z")
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            self.assertEqual(self.collector.collect(now=1000, monotonic=0)["models"], [])
        self.process(state="S")
        with patch("simrt_console.os.readlink", return_value="/usr/bin/bash"):
            self.assertEqual(self.collector.collect(now=1000, monotonic=0)["models"], [])
        self.collector.uid += 1
        with patch("simrt_console.os.readlink") as readlink:
            self.assertEqual(self.collector.collect(now=1000, monotonic=0)["models"], [])
            readlink.assert_not_called()

    def test_manifest_is_only_read_for_discovered_executable(self):
        executable = self.process()
        unrelated = self.root / "unrelated"
        unrelated.mkdir()
        self.write(unrelated / "bad.xcp-manifest.json", "not json")
        with patch("simrt_console.os.readlink", return_value=str(executable)), \
                patch("simrt_console.read_json", wraps=read_json) as parser:
            self.collector.collect(now=1000, monotonic=0)
            self.collector.collect(now=1001, monotonic=1)
        paths = [str(call.args[0]) for call in parser.call_args_list]
        self.assertEqual(paths.count(str(executable.with_suffix(".xcp-manifest.json"))), 1)
        self.assertFalse(any("unrelated" in path for path in paths))

    def test_logs_are_bounded_and_terminal_control_characters_are_removed(self):
        log = self.root / "model.log"
        self.write(log, "old line\n" * 2000 + "\x1b[2Jdanger\ttext\nlast\n")
        lines = tail_log(log, lines=2)
        self.assertEqual(lines, ["?[2Jdanger?text", "last"])
        self.assertNotIn("\x1b", clean("abc\x1b[2J"))
        self.write(log, "{" + "x" * MAX_JSON_BYTES)
        self.assertIsNone(read_json(log))

    def test_rendering_80x25_console_top_and_larger_layout(self):
        executable = self.process()
        self.telemetry(executable, {"pid": 42})
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            snapshot = self.collector.collect(now=1000, monotonic=0)
        snapshot["models"][0]["logs"] = ["runtime log " + str(i) for i in range(30)]
        for width, height in [(79, 18), (119, 33), (39, 8), (0, 0)]:
            with self.subTest(width=width, height=height):
                lines = render_lines(snapshot, width, height)
                self.assertLessEqual(len(lines), height)
                self.assertTrue(all(len(line) <= width for line in lines))
                if height >= 18:
                    self.assertIn("runtime log 29", lines[-1])
                    self.assertTrue(any("Task execution" in line for line in lines))

    def test_stopped_process_retains_event_without_showing_it_as_running(self):
        executable = self.process()
        with patch("simrt_console.os.readlink", return_value=str(executable)):
            self.collector.collect(now=1000, monotonic=0)
        (self.proc / "42/stat").unlink()
        (self.proc / "42").rmdir()
        snapshot = self.collector.collect(now=1001, monotonic=1)
        rendered = "\n".join(render_lines(snapshot, 80, 18))
        self.assertIn("State: IDLE", rendered)
        self.assertIn("STOPPED display_model", rendered)
        self.assertEqual(self.collector.manifests, {})

    def test_tmux_verifier_requires_single_fullscreen_dashboard(self):
        panes = pane_rows("0|1|0|80|25|101\n")
        top = "SimRT: fixture\n-- LOG\n"
        validate_capture(panes, top)
        with self.assertRaises(AssertionError):
            pane_rows("0|0|0|80|18|101\n1|1|0|80|6|102\n")
        panes[0]["active"] = False
        with self.assertRaises(AssertionError):
            validate_capture(panes, top)


if __name__ == "__main__":
    unittest.main(verbosity=2)
