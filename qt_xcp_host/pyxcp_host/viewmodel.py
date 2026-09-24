"""Application state and synchronous commands consumed by the Tk UI."""

from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path
from typing import Callable, Dict, Iterable, Mapping, Optional, Union

from .models import CatalogInfo, ConnectionInfo, Endpoint, HostState
from .services import A2LCatalogService, XcpSession


class HostViewModel:
    def __init__(
        self,
        log_callback: Optional[Callable[[str], None]] = None,
        catalog_service: Optional[A2LCatalogService] = None,
        session: Optional[XcpSession] = None,
    ) -> None:
        self.catalog_service = catalog_service or A2LCatalogService()
        self.session = session or XcpSession(self.catalog_service)
        self.state = HostState.EMPTY
        self.catalog = None  # type: Optional[CatalogInfo]
        self.last_error = ""
        self._log_callback = log_callback
        self._log_lines = []
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self.session.connected

    @property
    def measurements(self) -> tuple:
        return self.catalog.measurements if self.catalog else tuple()

    @property
    def calibrations(self) -> tuple:
        return self.catalog.calibrations if self.catalog else tuple()

    @property
    def diagnostics(self) -> Dict[str, object]:
        result = self.session.diagnostics()
        result.update(
            {
                "state": self.state.value,
                "a2l_file": str(self.catalog.path) if self.catalog else "",
                "supported_measurements": len(self.measurements),
                "supported_calibrations": len(self.calibrations),
                "last_error": self.last_error,
            }
        )
        return result

    @property
    def log_lines(self) -> tuple:
        with self._lock:
            return tuple(self._log_lines)

    def set_log_sink(self, callback: Optional[Callable[[str], None]]) -> None:
        """Route future ViewModel log entries to the active UI."""

        with self._lock:
            self._log_callback = callback

    def load_a2l(self, file_path: Path) -> CatalogInfo:
        with self._lock:
            if self.connected:
                self.disconnect()
            try:
                catalog = self.catalog_service.load(file_path)
            except BaseException as exc:
                self._fail("A2L 加载失败", exc)
                raise
            self.catalog = catalog
            self.state = HostState.LOADED
            self.last_error = ""
            self._log(
                "已加载 A2L：{}（测量量 {}，标定量 {}）".format(
                    catalog.path.name,
                    len(catalog.measurements),
                    len(catalog.calibrations),
                )
            )
            return catalog

    def connect(
        self, protocol: str, host: str, port: int, timeout: float = 2.0
    ) -> ConnectionInfo:
        with self._lock:
            if self.catalog is None:
                raise RuntimeError("请先加载 A2L 文件。")
            endpoint = Endpoint(protocol, host, int(port), float(timeout))
            self.state = HostState.CONNECTING
            self._log("正在连接 {}".format(endpoint.summary))
            try:
                info = self.session.connect(endpoint)
            except BaseException as exc:
                self._fail("XCP 连接失败", exc)
                raise
            self.state = HostState.CONNECTED
            self.last_error = ""
            self._log("已连接 {}".format(endpoint.summary))
            return info

    def disconnect(self) -> None:
        with self._lock:
            try:
                self.session.disconnect(restore=True)
            except BaseException as exc:
                self._fail("断开前恢复标定值失败", exc, preserve_connection=True)
                raise
            self.state = HostState.LOADED if self.catalog else HostState.EMPTY
            self.last_error = ""
            self._log("XCP 已断开")

    def poll_measurements(self, names: Iterable[str]) -> Dict[str, Union[int, float]]:
        with self._lock:
            try:
                return self.session.read_measurements(names)
            except BaseException as exc:
                self._fail("测量轮询失败", exc, preserve_connection=True)
                raise

    @property
    def daq_active(self) -> bool:
        return self.session.daq_active

    @property
    def daq_diagnostics(self) -> dict:
        return self.session.daq_diagnostics

    def start_daq(self, names: Iterable[str], event_channel: int = 0) -> dict:
        with self._lock:
            try:
                metadata = self.session.start_daq(names, event_channel)
            except BaseException as exc:
                self._fail("DAQ 启动失败", exc, preserve_connection=True)
                raise
            self._log("DAQ 已启动：事件 {}，模型周期 {:.6g} ms，{} 个测量量".format(
                metadata["event_channel"], metadata["period_seconds"] * 1000,
                len(metadata["signals"]),
            ))
            return metadata

    def drain_daq(self, max_samples: int = 5000) -> list:
        return self.session.drain_daq(max_samples)

    def stop_daq(self) -> None:
        with self._lock:
            try:
                self.session.stop_daq()
            except BaseException as exc:
                self._fail("DAQ 停止失败", exc, preserve_connection=True)
                raise
            self._log("DAQ 已停止")

    def read_calibrations(
        self, names: Optional[Iterable[str]] = None
    ) -> Dict[str, Union[int, float]]:
        with self._lock:
            try:
                values = self.session.read_calibrations(names)
            except BaseException as exc:
                self._fail("标定量读取失败", exc, preserve_connection=True)
                raise
            self._log("已读取 {} 个标定量".format(len(values)))
            return values

    def write_calibrations(
        self, values: Mapping[str, Union[str, int, float]]
    ) -> Dict[str, Union[int, float]]:
        with self._lock:
            try:
                result = self.session.write_calibrations(values)
            except BaseException as exc:
                self._fail("标定写入失败", exc, preserve_connection=True)
                raise
            self._log("已写入并回读验证 {} 个标定量".format(len(result)))
            return result

    def restore_calibrations(
        self, names: Optional[Iterable[str]] = None
    ) -> Dict[str, Union[int, float]]:
        with self._lock:
            try:
                result = self.session.restore_calibrations(names)
            except BaseException as exc:
                self._fail("标定恢复失败", exc, preserve_connection=True)
                raise
            self._log("已恢复并验证 {} 个标定量".format(len(result)))
            return result

    def close(self) -> None:
        with self._lock:
            if self.state is HostState.CLOSED:
                return
            try:
                self.session.disconnect(restore=True)
            except BaseException as exc:
                self._fail("关闭前恢复标定值失败", exc, preserve_connection=True)
                raise
            self.state = HostState.CLOSED
            self._log("上位机已关闭")

    @staticmethod
    def default_port(protocol: str) -> int:
        return 5555 if protocol.strip().upper() == "TCP" else 17725

    def _log(self, message: str) -> None:
        line = "{}  {}".format(
            dt.datetime.now().strftime("%H:%M:%S"), str(message).strip()
        )
        self._log_lines.append(line)
        del self._log_lines[:-500]
        if self._log_callback is not None:
            self._log_callback(line)

    def _fail(
        self,
        context: str,
        error: BaseException,
        preserve_connection: bool = False,
    ) -> None:
        self.last_error = "{}：{}".format(context, error)
        self.state = (
            HostState.CONNECTED
            if preserve_connection and self.connected
            else HostState.ERROR
        )
        self._log(self.last_error)
