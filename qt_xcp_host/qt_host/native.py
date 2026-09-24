"""ctypes ownership layer for the required C++17 signal-history core.

There is deliberately no Python data-core fallback: deployment mistakes fail
early, with an actionable path. The adapter lock serializes compound operations;
the DLL also protects every exported operation and its opaque-handle registry.
"""
from __future__ import annotations

import ctypes as ct
import csv
from dataclasses import dataclass
import heapq
import os
from pathlib import Path
import tempfile
import threading
from typing import Iterable, Mapping, Optional
import numpy as np

DEFAULT_HISTORY_POINTS = 1_000_000


@dataclass(frozen=True)
class SamplePoint:
    elapsed_seconds: float
    value: float


class NativeCoreError(RuntimeError):
    pass


class _Point(ct.Structure):
    _fields_ = [("elapsed_seconds", ct.c_double), ("value", ct.c_double)]


class _Stats(ct.Structure):
    _fields_ = [("latest", ct.c_double), ("minimum", ct.c_double),
                ("maximum", ct.c_double), ("count", ct.c_uint64)]


def _load_core(dll_path: Optional[Path] = None):
    path = Path(dll_path) if dll_path is not None else Path(__file__).parent / "native_bin" / "xcp_core.dll"
    if not path.is_file():
        raise NativeCoreError(f"Required C++ core is missing: {path}. Run qt_xcp_host/build_native.ps1.")
    try:
        dll = ct.CDLL(str(path.resolve()))
    except OSError as error:
        raise NativeCoreError(f"Cannot load the required C++ core {path}: {error}") from error
    u64 = ct.c_uint64
    ptr = ct.POINTER
    signatures = {
        "xcp_core_create": [u64, ptr(u64)],
        "xcp_core_destroy": [u64],
        "xcp_core_ensure_signal": [u64, ct.c_char_p, ptr(u64)],
        "xcp_core_append": [u64, ptr(u64), ptr(ct.c_double), ptr(ct.c_double), u64],
        "xcp_core_clear": [u64],
        "xcp_core_total": [u64, ptr(u64)],
        "xcp_core_stats": [u64, u64, ptr(_Stats)],
        "xcp_core_snapshot": [u64, u64, ptr(_Point), u64, ptr(u64)],
        "xcp_core_plot": [u64, u64, u64, ptr(_Point), u64, ptr(u64)],
        "xcp_core_plot_range": [u64, u64, ct.c_double, ct.c_double, u64, ptr(_Point), u64, ptr(u64)],
        "xcp_core_value_at": [u64, u64, ct.c_double, ptr(ct.c_double), ptr(ct.c_int), ptr(ct.c_int)],
    }
    try:
        dll.xcp_core_abi_version.argtypes = []
        dll.xcp_core_abi_version.restype = ct.c_uint32
        dll.xcp_core_last_error.argtypes = []
        dll.xcp_core_last_error.restype = ct.c_char_p
        if dll.xcp_core_abi_version() != 1:
            raise NativeCoreError("Unsupported C++ core ABI; rebuild the Qt application.")
        for name, args in signatures.items():
            function = getattr(dll, name)
            function.argtypes = args
            function.restype = ct.c_int
    except AttributeError as error:
        raise NativeCoreError(f"C++ core has missing ABI exports: {path}") from error
    return dll


class NativeBuffer:
    """Per-signal bounded, chronological raw history, owned by the native DLL.

    ``len(buffer)`` is the total retained sample count across signals. Values and
    nonnegative timestamps must be finite, and time cannot go backwards within a
    signal until ``clear()``. ``stats()`` omits empty signals. A plot budget >= 4
    preserves both endpoints and each bucket's extrema. Budgets 1/2/3 retain the
    last / endpoints / endpoints and largest absolute interior value respectively.
    """

    def __init__(self, max_points: int = DEFAULT_HISTORY_POINTS, *, dll_path: Optional[Path] = None):
        if isinstance(max_points, bool) or not isinstance(max_points, int) or not 1 <= max_points <= 10000000:
            raise ValueError("max_points must be an integer in 1..10000000")
        self.max_points = max_points
        self._lock = threading.RLock()
        self._dll = _load_core(dll_path)
        self._handle = ct.c_uint64()
        self._signals: dict[str, int] = {}
        self._check(self._dll.xcp_core_create(max_points, ct.byref(self._handle)))

    def _check(self, code: int) -> None:
        if code != 0:
            message = self._dll.xcp_core_last_error()
            raise NativeCoreError(message.decode("utf-8", "replace") if message else "Native core error")

    def _open(self) -> int:
        if not self._handle.value:
            raise NativeCoreError("Native buffer is closed")
        return self._handle.value

    @staticmethod
    def _validate_name(name: str) -> bytes:
        if not isinstance(name, str):
            raise TypeError("Signal names must be strings")
        encoded = name.encode("utf-8")
        if not encoded or len(encoded) > 1024 or b"\0" in encoded:
            raise ValueError("Signal name must contain 1..1024 UTF-8 bytes without NUL")
        return encoded

    def ensure_signals(self, names: Iterable[str]) -> None:
        with self._lock:
            handle = self._open()
            prepared = [(name, self._validate_name(name)) for name in names]
            for name, encoded in prepared:
                if name not in self._signals:
                    signal = ct.c_uint64()
                    self._check(self._dll.xcp_core_ensure_signal(handle, encoded, ct.byref(signal)))
                    self._signals[name] = signal.value

    def append(self, timestamp: float, values: Mapping[str, float]) -> None:
        self.append_batch(((timestamp, values),))

    def append_batch(self, rows: Iterable[tuple[float, Mapping[str, float]]]) -> None:
        with self._lock:
            handle = self._open()
            prepared = [(float(time), [(name, float(value)) for name, value in values.items()])
                        for time, values in rows]
            self.ensure_signals(name for _, values in prepared for name, _ in values)
            count = sum(len(values) for _, values in prepared)
            ids = (ct.c_uint64 * count)()
            times = (ct.c_double * count)()
            samples = (ct.c_double * count)()
            index = 0
            for time, values in prepared:
                for name, value in values:
                    ids[index], times[index], samples[index] = self._signals[name], time, value
                    index += 1
            self._check(self._dll.xcp_core_append(handle, ids, times, samples, count))

    def _stats(self, name: str) -> _Stats:
        result = _Stats()
        self._check(self._dll.xcp_core_stats(self._open(), self._signals[name], ct.byref(result)))
        return result

    def snapshot(self) -> dict[str, list[SamplePoint]]:
        return {name: [SamplePoint(float(time), float(value)) for time, value in points]
                for name, points in self.snapshot_arrays().items()}

    def snapshot_arrays(self) -> dict[str, np.ndarray]:
        """Copy consistent raw histories into owned (time, value) float64 arrays.

        Each million-sample signal uses 16 MB, without a Python object per point.
        The copies remain valid after acquisition, clear(), or close().
        """
        with self._lock:
            handle = self._open()
            result = {}
            for name, signal in self._signals.items():
                count = self._stats(name).count
                points = np.empty((count, 2), dtype=np.float64)
                written = ct.c_uint64()
                self._check(self._dll.xcp_core_snapshot(
                    handle, signal, points.ctypes.data_as(ct.POINTER(_Point)), count, ct.byref(written)))
                points.flags.writeable = False
                result[name] = points[:written.value]
            return result

    def stats(self) -> dict[str, tuple[float, float, float, int]]:
        with self._lock:
            self._open()
            result = {}
            for name in self._signals:
                item = self._stats(name)
                if item.count:
                    result[name] = (item.latest, item.minimum, item.maximum, item.count)
            return result

    def rows(self):
        return tuple(self._merged_rows(self.snapshot_arrays()))

    def latest_timestamp(self) -> Optional[float]:
        with self._lock:
            self._open()
            return max((point.elapsed_seconds for name in self._signals
                        for point in self.plot_points(name, 1)), default=None)

    @staticmethod
    def _merged_rows(snapshot):
        series = tuple(snapshot.items())
        pending = [(float(points[0, 0]), 0, signal, 0)
                   for signal, (_, points) in enumerate(series) if len(points)]
        heapq.heapify(pending)
        while pending:
            key = pending[0][:2]
            values = {}
            while pending and pending[0][:2] == key:
                stamp, occurrence, signal, index = heapq.heappop(pending)
                name, points = series[signal]
                values[name] = float(points[index, 1])
                index += 1
                if index < len(points):
                    next_stamp = float(points[index, 0])
                    heapq.heappush(pending, (next_stamp, occurrence + 1 if next_stamp == stamp else 0,
                                            signal, index))
            yield key[0], values

    def export_csv(self, destination: Path) -> Path:
        """Stream one raw snapshot; duplicate times retain their occurrence order."""
        snapshot = self.snapshot_arrays()
        output = Path(destination)
        names = tuple(snapshot)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig", newline="",
                                             dir=output.parent, prefix=".xcp-csv-", delete=False) as stream:
                temporary = Path(stream.name)
                writer = csv.writer(stream)
                writer.writerow(("time_s",) + names)
                for elapsed, values in self._merged_rows(snapshot):
                    writer.writerow((elapsed,) + tuple(values.get(name, "") for name in names))
            os.replace(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return output

    def plot_points(self, name: str, max_points: int = 2000, *, time_range=None) -> list[SamplePoint]:
        if isinstance(max_points, bool) or not isinstance(max_points, int) or max_points < 1:
            raise ValueError("Plot budget must be a positive integer")
        with self._lock:
            handle = self._open()
            if name not in self._signals:
                return []
            count = min(max_points, self._stats(name).count)
            points = (_Point * count)()
            written = ct.c_uint64()
            if time_range is None:
                code = self._dll.xcp_core_plot(handle, self._signals[name], max_points,
                                               points, count, ct.byref(written))
            else:
                first, last = sorted(map(float, time_range))
                code = self._dll.xcp_core_plot_range(handle, self._signals[name], first, last,
                                                     max_points, points, count, ct.byref(written))
            self._check(code)
            return [SamplePoint(point.elapsed_seconds, point.value) for point in points[:written.value]]

    def value_at(self, name: str, time: float) -> tuple[Optional[float], bool]:
        with self._lock:
            handle = self._open()
            if name not in self._signals:
                return None, False
            value, found, interpolated = ct.c_double(), ct.c_int(), ct.c_int()
            self._check(self._dll.xcp_core_value_at(handle, self._signals[name], float(time),
                                                   ct.byref(value), ct.byref(found), ct.byref(interpolated)))
            return (value.value if found.value else None), bool(interpolated.value)

    def clear(self) -> None:
        with self._lock:
            self._check(self._dll.xcp_core_clear(self._open()))

    def __len__(self) -> int:
        with self._lock:
            count = ct.c_uint64()
            self._check(self._dll.xcp_core_total(self._open(), ct.byref(count)))
            return count.value

    def close(self) -> None:
        with self._lock:
            if self._handle.value:
                self._check(self._dll.xcp_core_destroy(self._handle.value))
                self._handle.value = 0

    def __enter__(self):
        self._open()
        return self

    def __exit__(self, *_exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
