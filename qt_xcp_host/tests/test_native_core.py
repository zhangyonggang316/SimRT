import ctypes as ct
import csv
from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import random
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qt_host.native import DEFAULT_HISTORY_POINTS, NativeBuffer, NativeCoreError, SamplePoint, _Point, _load_core


class NativeCoreTests(unittest.TestCase):
    def make_buffer(self, capacity=DEFAULT_HISTORY_POINTS):
        buffer = NativeBuffer(capacity)
        self.addCleanup(buffer.close)
        return buffer

    def test_default_capacity_and_empty_state(self):
        buffer = self.make_buffer()
        self.assertEqual(buffer.max_points, 1000000)
        self.assertEqual(len(buffer), 0)
        self.assertEqual(buffer.snapshot(), {})
        self.assertEqual(buffer.stats(), {})
        self.assertIsNone(buffer.latest_timestamp())
        self.assertEqual(buffer.plot_points("absent"), [])
        self.assertEqual(buffer.value_at("absent", 0), (None, False))

    def test_wraparound_retains_raw_order_and_updates_extrema(self):
        buffer = self.make_buffer(3)
        buffer.append_batch([(0, {"a": -100}), (1, {"a": 300}),
                             (2, {"a": 2}), (3, {"a": 3}), (4, {"a": 4})])
        self.assertEqual(buffer.snapshot()["a"], [SamplePoint(2, 2), SamplePoint(3, 3), SamplePoint(4, 4)])
        self.assertEqual(buffer.stats(), {"a": (4, 2, 4, 3)})
        self.assertEqual(len(buffer), 3)

    def test_multiple_signals_have_independent_bounded_histories(self):
        buffer = self.make_buffer(2)
        buffer.append_batch([(0, {"a": 0, "b": 10}), (1, {"a": 1}), (2, {"a": 2})])
        self.assertEqual(len(buffer), 3)
        self.assertEqual(buffer.stats(), {"a": (2, 1, 2, 2), "b": (10, 10, 10, 1)})
        self.assertEqual(buffer.latest_timestamp(), 2)

    def test_single_sample_capacity(self):
        buffer = self.make_buffer(1)
        for index in range(20):
            buffer.append(index, {"a": index})
        self.assertEqual(buffer.snapshot(), {"a": [SamplePoint(19, 19)]})
        self.assertEqual(buffer.stats(), {"a": (19, 19, 19, 1)})

    def test_statistics_against_raw_values_after_repeated_wraps(self):
        buffer = self.make_buffer(41)
        generator = random.Random(314159)
        expected = []
        for index in range(1000):
            value = generator.uniform(-50, 90)
            expected.append(value)
            expected = expected[-41:]
            buffer.append(index, {"a": value})
            if index % 13 == 0:
                self.assertEqual(buffer.stats()["a"], (expected[-1], min(expected), max(expected), len(expected)))

    def test_cursor_exact_interpolated_and_outside_range(self):
        buffer = self.make_buffer()
        buffer.append_batch([(1, {"a": 10}), (2, {"a": 20}), (4, {"a": 0})])
        self.assertEqual(buffer.value_at("a", 1), (10, False))
        self.assertEqual(buffer.value_at("a", 4), (0, False))
        self.assertEqual(buffer.value_at("a", 1.5), (15, True))
        self.assertEqual(buffer.value_at("a", 3), (10, True))
        self.assertEqual(buffer.value_at("a", 0.999), (None, False))
        self.assertEqual(buffer.value_at("a", 4.001), (None, False))

    def test_cursor_equal_timestamps_choose_last_value(self):
        buffer = self.make_buffer()
        buffer.append_batch([(0, {"a": 1}), (0, {"a": 2}), (1, {"a": 4})])
        self.assertEqual(buffer.value_at("a", 0), (2, False))
        self.assertEqual(buffer.value_at("a", 0.5), (3, True))

    def test_cursor_uses_retained_ring_only(self):
        buffer = self.make_buffer(2)
        buffer.append_batch([(0, {"a": 0}), (1, {"a": 10}), (2, {"a": 20})])
        self.assertEqual(buffer.value_at("a", 0), (None, False))
        self.assertEqual(buffer.value_at("a", 1.5), (15, True))

    def test_cursor_extreme_finite_values_do_not_overflow_difference(self):
        buffer = self.make_buffer()
        buffer.append_batch([(0, {"a": -1.7e308}), (1, {"a": 1.7e308})])
        self.assertEqual(buffer.value_at("a", 0.5), (0, True))

    def test_minmax_envelope_preserves_positive_and_negative_spikes(self):
        buffer = self.make_buffer()
        buffer.append_batch((index / 1000, {"a": 100 if index == 235 else -90 if index == 764 else 0})
                            for index in range(1000))
        points = buffer.plot_points("a", 80)
        self.assertLessEqual(len(points), 80)
        self.assertEqual(points[0], SamplePoint(0, 0))
        self.assertEqual(points[-1], SamplePoint(.999, 0))
        self.assertIn(SamplePoint(.235, 100), points)
        self.assertIn(SamplePoint(.764, -90), points)
        self.assertEqual(points, sorted(points, key=lambda item: item.elapsed_seconds))
        self.assertEqual(len(buffer.snapshot()["a"]), 1000)

    def test_plot_budgets_and_wraparound(self):
        buffer = self.make_buffer(100)
        buffer.append_batch((index, {"a": math.sin(index)}) for index in range(300))
        for budget in range(1, 120):
            points = buffer.plot_points("a", budget)
            self.assertLessEqual(len(points), budget)
            self.assertEqual(points[-1].elapsed_seconds, 299)
            if budget >= 2:
                self.assertEqual(points[0].elapsed_seconds, 200)
            self.assertEqual(points, sorted(points, key=lambda item: item.elapsed_seconds))
        self.assertEqual(buffer.plot_points("a", 100), buffer.snapshot()["a"])

    def test_minimum_budget_preserves_global_extrema(self):
        buffer = self.make_buffer()
        buffer.append_batch((index, {"a": 100 if index == 10 else -50 if index == 90 else 0})
                            for index in range(100))
        points = buffer.plot_points("a", 4)
        self.assertEqual(points, [SamplePoint(0, 0), SamplePoint(10, 100),
                                  SamplePoint(90, -50), SamplePoint(99, 0)])

    def test_plot_range_refines_raw_samples_and_keeps_viewport_neighbors(self):
        buffer = self.make_buffer(100)
        buffer.append_batch((index, {"a": index}) for index in range(200))
        self.assertEqual(buffer.plot_points("a", 100, time_range=(145, 150)),
                         [SamplePoint(index, index) for index in range(144, 152)])
        self.assertEqual(buffer.plot_points("a", 100, time_range=(100.25, 100.75)),
                         [SamplePoint(100, 100), SamplePoint(101, 101)])
        self.assertEqual(buffer.plot_points("a", 100, time_range=(0, 90)), [])
        self.assertEqual(buffer.plot_points("a", 100, time_range=(201, 300)), [])
        self.assertLessEqual(len(buffer.plot_points("a", 4, time_range=(110, 180))), 4)
        with self.assertRaises(NativeCoreError):
            buffer.plot_points("a", 100, time_range=(0, float("nan")))

    def test_compact_snapshot_is_owned_readonly_and_keeps_duplicate_times(self):
        buffer = self.make_buffer(3)
        buffer.ensure_signals(("empty",))
        buffer.append_batch([(0, {"a": 1}), (0, {"a": 2}), (1, {"a": 3})])
        snapshot = buffer.snapshot_arrays()
        self.assertEqual(snapshot["empty"].shape, (0, 2))
        self.assertEqual(snapshot["a"].nbytes, 3 * 16)
        self.assertEqual(snapshot["a"].tolist(), [[0, 1], [0, 2], [1, 3]])
        with self.assertRaises(ValueError):
            snapshot["a"][0, 1] = 42
        buffer.append(2, {"a": 4})
        buffer.clear()
        buffer.close()
        self.assertEqual(snapshot["a"].tolist(), [[0, 1], [0, 2], [1, 3]])

    def test_csv_streams_asynchronous_duplicates_and_double_precision(self):
        buffer = self.make_buffer()
        precise_time = 123.12345678901234
        precise_value = 1.2345678901234567
        buffer.append_batch([(0, {"a": 1}), (0, {"a": 2, "b": 3}),
                             (0, {"b": 4}), (0, {"b": 5}),
                             (precise_time, {"a": precise_value})])
        buffer.ensure_signals(("empty",))
        with tempfile.TemporaryDirectory() as directory:
            destination = buffer.export_csv(Path(directory) / "samples.csv")
            with destination.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 4)
        self.assertEqual([float(row["a"]) for row in rows if row["a"]], [1, 2, precise_value])
        self.assertEqual([float(row["b"]) for row in rows if row["b"]], [3, 4, 5])
        self.assertEqual(float(rows[-1]["time_s"]), precise_time)
        self.assertTrue(all(row["empty"] == "" for row in rows))

    def test_clear_retains_signal_registration_and_resets_time(self):
        buffer = self.make_buffer()
        buffer.ensure_signals(["a", "b"])
        buffer.append(10, {"a": 5})
        buffer.clear()
        self.assertEqual(buffer.snapshot(), {"a": [], "b": []})
        self.assertEqual(buffer.stats(), {})
        buffer.append(0, {"a": 3})
        self.assertEqual(buffer.snapshot()["a"], [SamplePoint(0, 3)])

    def test_invalid_batch_does_not_mutate_existing_samples(self):
        buffer = self.make_buffer()
        buffer.append(0, {"a": 1})
        with self.assertRaises(NativeCoreError):
            buffer.append_batch([(1, {"a": 2}), (2, {"a": float("nan")})])
        self.assertEqual(buffer.snapshot()["a"], [SamplePoint(0, 1)])

    def test_nonfinite_values_and_timestamps_are_rejected(self):
        buffer = self.make_buffer()
        for invalid in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(invalid=invalid):
                with self.assertRaises(NativeCoreError):
                    buffer.append(0, {"a": invalid})
                with self.assertRaises(NativeCoreError):
                    buffer.append(invalid, {"a": 0})
                with self.assertRaises(NativeCoreError):
                    buffer.value_at("a", invalid)
        with self.assertRaises(NativeCoreError):
            buffer.append(-1, {"a": 0})
        self.assertEqual(len(buffer), 0)

    def test_nonmonotonic_batch_and_later_append_rejected(self):
        buffer = self.make_buffer()
        with self.assertRaises(NativeCoreError):
            buffer.append_batch([(2, {"a": 20}), (1, {"a": 10})])
        self.assertEqual(len(buffer), 0)
        buffer.append(2, {"a": 20})
        with self.assertRaises(NativeCoreError):
            buffer.append(1, {"a": 10})
        self.assertEqual(len(buffer), 1)

    def test_bad_capacity_and_names(self):
        for capacity in (0, -1, 10000001, True, 1.5):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                NativeBuffer(capacity)
        buffer = self.make_buffer()
        for name in ("", "a\0b", "a" * 1025):
            with self.subTest(name=name), self.assertRaises(ValueError):
                buffer.ensure_signals([name])
        with self.assertRaises(TypeError):
            buffer.ensure_signals([42])
        buffer.ensure_signals(["voltage_\u7535\u538b"])
        self.assertEqual(buffer.snapshot(), {"voltage_\u7535\u538b": []})

    def test_missing_library_never_falls_back(self):
        with self.assertRaisesRegex(NativeCoreError, "Required C\\+\\+ core is missing"):
            NativeBuffer(dll_path=Path(__file__).parent / "not_present.dll")

    def test_close_is_idempotent_and_other_operations_fail(self):
        buffer = self.make_buffer()
        buffer.close()
        buffer.close()
        for action in (lambda: len(buffer), buffer.clear, buffer.snapshot, buffer.stats,
                       lambda: buffer.append(0, {"a": 0}), lambda: buffer.plot_points("a"),
                       lambda: buffer.value_at("a", 0)):
            with self.assertRaisesRegex(NativeCoreError, "closed"):
                action()

    def test_threaded_producers_and_reader_keep_consistent_snapshots(self):
        buffer = self.make_buffer(500)
        buffer.ensure_signals(["a", "b", "c"])

        def producer(name):
            for offset in range(0, 2000, 20):
                buffer.append_batch((index, {name: index}) for index in range(offset, offset + 20))

        def reader():
            for _ in range(100):
                for points in buffer.snapshot().values():
                    self.assertLessEqual(len(points), 500)
                    self.assertEqual(points, sorted(points, key=lambda item: item.elapsed_seconds))
                buffer.stats()
                buffer.plot_points("a", 64)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(producer, name) for name in ("a", "b", "c")]
            futures.append(pool.submit(reader))
            for future in futures:
                future.result()
        self.assertEqual(len(buffer), 1500)
        self.assertTrue(all(stats == (1999, 1500, 1999, 500) for stats in buffer.stats().values()))

    def test_million_point_capacity_and_plot_performance(self):
        buffer = self.make_buffer(1000000)
        started = time.perf_counter()
        for first in range(0, 1000000, 10000):
            buffer.append_batch((index / 1000, {"a": float(index)})
                                for index in range(first, first + 10000))
        elapsed = time.perf_counter() - started
        self.assertEqual(len(buffer), 1000000)
        self.assertEqual(buffer.stats()["a"], (999999, 0, 999999, 1000000))
        started = time.perf_counter()
        points = buffer.plot_points("a", 2000)
        plot_elapsed = time.perf_counter() - started
        self.assertLessEqual(len(points), 2000)
        self.assertEqual(points[-1].value, 999999)
        self.assertLess(elapsed, 60, "Million-point input unexpectedly slow")
        self.assertLess(plot_elapsed, 5, "Native million-point envelope unexpectedly slow")
        raw = buffer.snapshot_arrays()["a"]
        self.assertEqual(len(raw), 1000000)
        self.assertEqual(raw.nbytes, 16000000)
        self.assertEqual(raw[0].tolist(), [0, 0])
        self.assertEqual(raw[-1].tolist(), [999.999, 999999])
        buffer.append(1000, {"a": 1000000})
        self.assertEqual(buffer.stats()["a"], (1000000, 1, 1000000, 1000000))
        self.assertEqual(buffer.value_at("a", 0), (None, False))
        self.assertEqual(buffer.value_at("a", .001), (1, False))
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as directory:
            destination = buffer.export_csv(Path(directory) / "million.csv")
            with destination.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                first = next(reader)
                self.assertEqual(float(first["a"]), 1)
                count = 1
                for last in reader:
                    count += 1
                self.assertEqual(count, 1000000)
                self.assertEqual(float(last["a"]), 1000000)
                self.assertEqual(float(last["time_s"]), 1000)
        export_elapsed = time.perf_counter() - started
        self.assertLess(export_elapsed, 60, "Million-point raw export unexpectedly slow")
        print(f"\nNative capacity benchmark: 1,000,000 points appended in {elapsed:.3f}s; "
              f"{len(points)}-point envelope in {plot_elapsed:.4f}s; CSV verified in {export_elapsed:.3f}s")

    def test_c_abi_rejects_invalid_handles_and_insufficient_output(self):
        dll = _load_core()
        count = ct.c_uint64()
        self.assertEqual(dll.xcp_core_total(0, ct.byref(count)), -1)
        self.assertIn(b"handle", dll.xcp_core_last_error())
        self.assertEqual(dll.xcp_core_create(10, None), -1)
        buffer = self.make_buffer()
        buffer.append(0, {"a": 1})
        self.assertEqual(dll.xcp_core_snapshot(buffer._handle.value, buffer._signals["a"],
                                              None, 0, ct.byref(count)), -1)
        self.assertEqual(count.value, 1)
        self.assertIn(b"capacity", dll.xcp_core_last_error())

    def test_c_abi_thread_safety_without_adapter_lock(self):
        buffer = self.make_buffer(1000)
        buffer.ensure_signals(["a", "b"])
        dll = buffer._dll

        def append_signal(name):
            ids = (ct.c_uint64 * 1000)(*([buffer._signals[name]] * 1000))
            times = (ct.c_double * 1000)(*range(1000))
            values = (ct.c_double * 1000)(*range(1000))
            self.assertEqual(dll.xcp_core_append(buffer._handle.value, ids, times, values, 1000), 0)

        with ThreadPoolExecutor(max_workers=2) as pool:
            for future in [pool.submit(append_signal, name) for name in ("a", "b")]:
                future.result()
        self.assertEqual(len(buffer), 2000)


if __name__ == "__main__":
    unittest.main()
