"""Serialized pyXCP session with exact-byte calibration recovery."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Union

from ..models import ConnectionInfo, Endpoint
from .a2l_catalog import A2LCatalogService
from .backend import (
    CalibrationRestoreError,
    TransportSettings,
    XcpClient,
    XcpClientError,
)
from .daq_acquisition import DaqAcquisition


Number = Union[int, float]


class XcpSession:
    def __init__(
        self,
        catalog: A2LCatalogService,
        client_factory: Callable[[TransportSettings], XcpClient] = XcpClient,
    ) -> None:
        self.catalog = catalog
        self._client_factory = client_factory
        self._client = None  # type: Optional[XcpClient]
        self._endpoint = None  # type: Optional[Endpoint]
        self._original_bytes = {}  # type: Dict[str, bytes]
        self._original_spans = {}  # type: Dict[str, tuple]
        self._lock = threading.RLock()
        self._daq = None  # type: Optional[DaqAcquisition]
        self._diagnostic_connection = {}

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.connected

    @property
    def endpoint(self) -> Optional[Endpoint]:
        return self._endpoint

    @property
    def pending_calibrations(self) -> tuple:
        with self._lock:
            return tuple(self._original_bytes)

    def connect(self, endpoint: Endpoint) -> ConnectionInfo:
        with self._lock:
            if self.catalog.database is None:
                raise RuntimeError("请先加载 A2L 文件。")
            if self.connected:
                self.disconnect(restore=True)
            client = self._client_factory(
                TransportSettings(
                    host=endpoint.host,
                    port=endpoint.port,
                    timeout=endpoint.timeout,
                    protocol=endpoint.protocol,
                )
            )
            try:
                client.connect()
            except BaseException:
                self._client = None
                self._endpoint = None
                raise
            self._client = client
            self._endpoint = endpoint
            self._original_bytes.clear()
            self._original_spans.clear()
            self._daq = None
            try:
                info = self.connection_info()
                self._diagnostic_connection = info.as_dict()
                return info
            except BaseException:
                try:
                    client.disconnect()
                finally:
                    self._client = None
                    self._endpoint = None
                raise

    def connection_info(self) -> ConnectionInfo:
        with self._lock:
            client = self._require_client()
            properties = client.master.slaveProperties
            byte_order = getattr(getattr(properties, "byteOrder", None), "name", None)
            if byte_order is None:
                byte_order = self.catalog.database.byte_order
            normalized_byte_order = self._normalize_byte_order(byte_order)
            if (
                normalized_byte_order is not None
                and normalized_byte_order != self.catalog.database.byte_order
            ):
                raise XcpClientError(
                    "Slave 字节序 {} 与 A2L 字节序 {} 不一致，已拒绝连接。".format(
                        normalized_byte_order, self.catalog.database.byte_order
                    )
                )
            return ConnectionInfo(
                endpoint=self._endpoint,
                byte_order=normalized_byte_order or str(byte_order),
                address_granularity_bytes=getattr(properties, "bytesPerElement", None),
                max_cto=getattr(properties, "maxCto", None),
                max_dto=getattr(properties, "maxDto", None),
                supports_calibration=bool(
                    getattr(properties, "supportsCalpag", False)
                ),
                supports_daq=bool(getattr(properties, "supportsDaq", False)),
            )

    def read_measurements(self, names: Iterable[str]) -> Dict[str, Number]:
        with self._lock:
            client = self._require_client()
            return {
                name: client.read_measurement(self.catalog.scalar(name, "MEASUREMENT"))
                for name in self._unique_names(names)
            }

    @property
    def daq_active(self) -> bool:
        daq = self._daq
        return daq is not None and daq.active

    @property
    def daq_diagnostics(self) -> dict:
        daq = self._daq
        return daq.diagnostics() if daq is not None else {"active": False}

    def start_daq(self, names: Iterable[str], event_channel: int = 0) -> dict:
        with self._lock:
            client = self._require_client()
            if self.daq_active:
                raise XcpClientError("DAQ is already active.")
            scalars = [self.catalog.scalar(name, "MEASUREMENT") for name in self._unique_names(names)]
            daq = DaqAcquisition(client)
            self._daq = daq
            metadata = daq.start(scalars, event_channel, self.catalog.database.daq_events)
            return metadata

    def drain_daq(self, max_samples: int = 5000) -> list:
        # DTO delivery does not wait on a calibration's command lock.
        daq = self._daq
        return daq.drain(max_samples) if daq is not None else []

    def stop_daq(self) -> None:
        with self._lock:
            if self._daq is not None:
                self._daq.stop()

    def read_calibrations(
        self, names: Optional[Iterable[str]] = None
    ) -> Dict[str, Number]:
        with self._lock:
            client = self._require_client()
            selected = (
                [item.name for item in self.catalog.info.calibrations]
                if names is None
                else self._unique_names(names)
            )
            if not selected:
                return {}
            return {
                name: client.read_characteristic(
                    self.catalog.scalar(name, "CHARACTERISTIC")
                )
                for name in selected
            }

    def write_calibrations(
        self, values: Mapping[str, Union[str, int, float]]
    ) -> Dict[str, Number]:
        if not values:
            raise ValueError("请选择至少一个需要写入的标定量。")
        with self._lock:
            client = self._require_client()
            entries = []
            for name, value in values.items():
                scalar = self.catalog.scalar(name, "CHARACTERISTIC")
                entries.append((str(name), scalar, value))
            self._validate_non_overlapping(entries)
            written = []
            try:
                result = {}  # type: Dict[str, Number]
                for name, scalar, value in entries:
                    if name not in self._original_bytes:
                        original = client.read_memory(
                            scalar.address, scalar.size, scalar.address_extension
                        )
                        self._original_bytes[name] = original
                        self._original_spans[name] = self._span(scalar)
                    result[name] = client.write_characteristic(scalar, value, verify=True)
                    written.append(name)
                return result
            except BaseException as operation_error:
                recovery_names = list(dict.fromkeys(written + [str(name)]))
                try:
                    self.restore_calibrations(recovery_names)
                except BaseException as restore_error:
                    raise CalibrationRestoreError(
                        "标定写入失败，且无法完整恢复本次写入的原始值。"
                    ) from restore_error
                raise operation_error

    def restore_calibrations(
        self, names: Optional[Iterable[str]] = None
    ) -> Dict[str, Number]:
        with self._lock:
            client = self._require_client()
            selected = (
                list(self._original_bytes)
                if names is None
                else self._unique_names(names)
            )
            restored = {}  # type: Dict[str, Number]
            failures = []
            for name in selected:
                original = self._original_bytes.get(name)
                if original is None:
                    continue
                scalar = self.catalog.scalar(name, "CHARACTERISTIC")
                try:
                    client.write_memory(
                        scalar.address, original, scalar.address_extension
                    )
                    actual = client.read_memory(
                        scalar.address, scalar.size, scalar.address_extension
                    )
                    if actual != original:
                        raise CalibrationRestoreError(
                            "{} 的恢复值回读不一致。".format(name)
                        )
                    restored[name] = scalar.decode(actual)
                    del self._original_bytes[name]
                    self._original_spans.pop(name, None)
                except BaseException as exc:
                    failures.append("{}: {}".format(name, exc))
            if failures:
                raise CalibrationRestoreError("; ".join(failures))
            return restored

    def disconnect(self, restore: bool = True) -> None:
        with self._lock:
            client = self._client
            if client is None:
                if restore and self._original_bytes:
                    raise CalibrationRestoreError(
                        "没有活动 XCP 连接，无法恢复仍待处理的标定原始值。"
                    )
                if not restore:
                    self._original_bytes.clear()
                    self._original_spans.clear()
                self._endpoint = None
                return
            if restore and self._original_bytes:
                if not client.connected:
                    raise CalibrationRestoreError(
                        "XCP 连接已失效，无法恢复仍待处理的标定原始值。"
                    )
                self.restore_calibrations()
            self.stop_daq()
            try:
                client.disconnect()
            finally:
                self._client = None
                self._endpoint = None
                self._original_bytes.clear()
                self._original_spans.clear()

    def diagnostics(self) -> Dict[str, Any]:
        # Negotiated connection fields are immutable until reconnect. The UI must
        # not wait on a pending calibration CTO just to repaint its status.
        connected = self.connected
        result = dict(self._diagnostic_connection) if connected else {}
        result["connected"] = connected
        result["pending_calibrations"] = len(self._original_bytes)
        result["daq"] = self.daq_diagnostics
        return result

    def _require_client(self) -> XcpClient:
        if not self.connected:
            raise RuntimeError("请先连接 XCP Slave。")
        return self._client

    @staticmethod
    def _span(scalar: Any) -> tuple:
        return (
            int(scalar.address_extension),
            int(scalar.address),
            int(scalar.address) + int(scalar.size),
        )

    @staticmethod
    def _normalize_byte_order(value: Any) -> Optional[str]:
        text = str(getattr(value, "name", value)).strip().upper()
        if text in {"INTEL", "LITTLE", "LITTLE_ENDIAN", "LSB_FIRST"}:
            return "little"
        if text in {"MOTOROLA", "BIG", "BIG_ENDIAN", "MSB_FIRST"}:
            return "big"
        return None

    def _validate_non_overlapping(self, entries: Iterable[tuple]) -> None:
        spans = dict(self._original_spans)
        for name, scalar, _value in entries:
            extension, start, end = self._span(scalar)
            for other_name, (other_extension, other_start, other_end) in spans.items():
                if other_name == name or extension != other_extension:
                    continue
                if start < other_end and other_start < end:
                    raise ValueError(
                        "标定量 {} 与 {} 的地址范围重叠，已拒绝同一会话写入。".format(
                            name, other_name
                        )
                    )
            spans[name] = (extension, start, end)

    @staticmethod
    def _unique_names(names: Iterable[str]) -> list:
        result = list(dict.fromkeys(str(name) for name in names if str(name)))
        if not result:
            raise ValueError("请至少选择一个 A2L 对象。")
        return result
