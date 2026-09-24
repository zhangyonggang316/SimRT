"""Qt event-loop controller ported from the stage-tested host lifecycle.

Only field/scheduler boundaries are adapted; XCP commands still use one worker.
"""
from __future__ import annotations
import math
import queue
import time
from collections import OrderedDict
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence
from .state import HostState, ControlPolicy, control_policy, optional_attr

COLORS = dict(neutral='#8a98a5', primary='#1264b2', warning='#d88916',
              success='#1f8a70', danger='#c9343a')


class HostController:
    STATE_LABELS = {
        HostState.EMPTY: "未加载 A2L",
        HostState.LOADED: "A2L 已加载",
        HostState.CONNECTING: "正在处理",
        HostState.CONNECTED: "已连接",
        HostState.ACQUIRING: "观测采集中",
        HostState.ERROR: "发生错误",
        HostState.CLOSING: "正在关闭",
    }

    STATE_COLORS = {
        HostState.EMPTY: COLORS["neutral"],
        HostState.LOADED: COLORS["primary"],
        HostState.CONNECTING: COLORS["warning"],
        HostState.CONNECTED: COLORS["success"],
        HostState.ACQUIRING: COLORS["success"],
        HostState.ERROR: COLORS["danger"],
        HostState.CLOSING: COLORS["warning"],
    }

    DIAGNOSTIC_LABELS = {
        "transport": "传输",
        "host": "Slave 主机",
        "port": "Slave 端口",
        "byte_order": "字节序",
        "address_granularity_bytes": "地址粒度（字节）",
        "max_cto": "MAX_CTO",
        "max_dto": "MAX_DTO",
        "supports_calibration": "支持 CAL/PAG",
        "supports_daq": "支持 DAQ",
        "connected": "已连接",
        "pending_calibrations": "待恢复标定量",
        "state": "内部状态",
        "a2l_file": "已加载 A2L",
        "supported_measurements": "可用测量量",
        "supported_calibrations": "可用标定量",
        "last_error": "最近错误",
    }

    def _install_log_sink(self) -> None:
        setter = getattr(self.vm, "set_log_sink", None)
        if callable(setter):
            setter(self.log)

    def _browse_a2l(self) -> None:
        if self.vm.connected or self._closing or self._remote_stop_pending:
            return
        path = self.dialogs.open_a2l()
        if path:
            if Path(path).suffix.lower() == '.zip':
                self.target_tab.select_payload(path)
                return
            self._payload_endpoint = None
            self.connection_bar.a2l_var.set(path)
            self._load_a2l()

    def _load_a2l(self) -> None:
        if self.vm.connected or self._closing or self._remote_stop_pending:
            return
        path_text = self.connection_bar.a2l_var.get().strip()
        if not path_text:
            self.dialogs.warning("A2L", "请选择 A2L 文件。")
            return
        path = Path(path_text).expanduser()
        if not path.is_file():
            self.dialogs.error("A2L", "A2L 文件不存在：{}".format(path))
            return
        self._stop_observation(settle=False)
        self._has_a2l = False
        self._loaded_a2l_path = None
        self.observation_tab.set_measurements(())
        self.calibration_tab.set_calibrations(())
        self._set_state(HostState.CONNECTING, "正在加载 A2L")
        self._submit(
            lambda: self.vm.load_a2l(path),
            self._after_a2l_loaded,
            "加载 A2L",
            error_state=HostState.ERROR,
        )

    def _after_a2l_loaded(self, result: Any) -> None:
        result_path = Path(optional_attr(result, "path", self.connection_bar.a2l_var.get())).resolve()
        current_path = Path(self.connection_bar.a2l_var.get()).expanduser().resolve()
        if result_path != current_path:
            self._has_a2l = False
            self._loaded_a2l_path = None
            self._set_state(HostState.EMPTY, "A2L 路径已修改")
            self.log("A2L 加载期间路径发生变化，请重新加载。", level="WARNING")
            return
        measurements = self._catalog_values(result, "measurements")
        calibrations = self._catalog_values(result, "calibrations")
        self.observation_tab.set_measurements(measurements)
        self.calibration_tab.set_calibrations(calibrations)
        self._has_a2l = True
        self._loaded_a2l_path = result_path
        self._catalog_endpoint = result
        self._resolve_file_endpoint()
        self._set_state(HostState.LOADED)
        self._update_diagnostics(result)
        self.log("A2L 已加载：{} 个测量量，{} 个标定量。".format(len(measurements), len(calibrations)))

    def _connect(self) -> None:
        if self._remote_stop_pending or self._closing or self._closed:
            return
        self._resolve_file_endpoint()
        if self.connection_bar.endpoint_error:
            self.dialogs.error('通信配置', self.connection_bar.endpoint_error)
            return
        try:
            settings = self.connection_bar.draft().validated()
        except ValueError as exc:
            self.dialogs.error("连接参数", str(exc))
            return
        if self._loaded_a2l_path is None or settings.a2l_path.resolve() != self._loaded_a2l_path:
            self.dialogs.error("A2L", "A2L 路径已修改，请先重新加载后再连接。")
            return
        self._stop_observation(settle=False)
        self._set_state(HostState.CONNECTING, "正在连接")

        def action():
            return self.vm.connect(
                protocol=settings.protocol,
                host=settings.host,
                port=settings.port,
                timeout=settings.timeout,
            )

        self._last_connection = settings
        self._submit(action, self._after_connected, "连接 XCP", error_state=HostState.ERROR)

    def _after_connected(self, result: Any) -> None:
        self._set_state(HostState.CONNECTED)
        self._update_diagnostics(result)
        endpoint = self._last_connection.endpoint if self._last_connection else "XCP"
        self.log("已连接：{}。".format(endpoint))

    def _disconnect(self) -> None:
        if self._closing:
            return
        self._stop_observation(settle=False)
        self._set_state(HostState.CONNECTING, "正在断开")
        self._submit(self.vm.disconnect, self._after_disconnected, "断开 XCP", error_state=HostState.ERROR)

    def _after_disconnected(self, _result: Any = None) -> None:
        self._set_state(HostState.LOADED if self._has_a2l else HostState.EMPTY)
        self._update_diagnostics()
        self.log("XCP 已断开。")

    def _endpoint_changed(self) -> None:
        draft = self.connection_bar.draft()
        self.endpoint_var.set("{} {}:{}".format(draft.protocol or '--', draft.host.strip() or "--", draft.port if draft.port != '0' else '--'))
        if hasattr(self, "diagnostics_tab"):
            self._update_diagnostics()

    def _a2l_changed(self) -> None:
        if self._loaded_a2l_path is None:
            return
        text = self.connection_bar.a2l_var.get().strip()
        try:
            unchanged = bool(text) and Path(text).expanduser().resolve() == self._loaded_a2l_path
        except (OSError, RuntimeError):
            unchanged = False
        if unchanged:
            return
        self._has_a2l = False
        self._loaded_a2l_path = None
        self._catalog_endpoint = None
        self.connection_bar.set_endpoint(error='请先加载模型 ZIP 或 A2L。')
        self.observation_tab.set_measurements(())
        self.calibration_tab.set_calibrations(())
        self._set_state(HostState.EMPTY, "A2L 路径已修改")

    def _resolve_file_endpoint(self, *_):
        if self.vm.connected or not self._has_a2l:
            return
        catalog = getattr(self, '_catalog_endpoint', None)
        ports = optional_attr(catalog, 'declared_ports', {}) or {}
        hosts = optional_attr(catalog, 'declared_hosts', {}) or {}
        payload = getattr(self, '_payload_endpoint', None)
        if payload and Path(payload['a2l']).resolve() != self._loaded_a2l_path:
            payload = None
        error = ''
        if payload:
            protocol, port = payload['protocol'], payload['port']
            if ports and (protocol not in ports or int(ports[protocol]) != int(port)):
                error = 'A2L 与模型包的通信协议或端口不一致。'
        elif len(ports) == 1:
            protocol, port = next(iter(ports.items()))
        else:
            protocol, port = '', 0
            error = ('A2L 声明了多个通信协议，请加载配套模型 ZIP。' if ports
                     else '文件未声明 XCP 通信协议和端口，请加载完整 A2L 或模型 ZIP。')
        host = (payload.get('host') if payload else '') or hosts.get(protocol, '') or self.target_tab.host_edit.text().strip()
        if not error and not host:
            error = '文件未声明目标地址，请在实时机页面填写 SSH 主机。'
        self.connection_bar.set_endpoint(protocol, host, port, error)

    def _start_observation(self, silent: bool = False) -> None:
        if self._remote_stop_pending:
            return
        if self._state != HostState.CONNECTED:
            if not silent:
                self.dialogs.warning("观测", "请先连接 XCP。")
            return
        names = self.observation_tab.selected_names()
        if not names:
            if not silent:
                self.dialogs.warning("观测", "请至少选择一个测量量。")
            return
        if self.observation_tab.acquisition_var.get() == "DAQ":
            self._start_daq(names)
            return
        try:
            interval = self.observation_tab.sample_interval()
        except ValueError as exc:
            self.dialogs.error("观测", str(exc))
            return
        latest = self.observation_tab.buffer.latest_timestamp()
        self._poll_offset = latest + interval if latest is not None else 0.0
        self._poll_started_at = time.monotonic()
        self._acquiring = True
        self._set_state(HostState.ACQUIRING)
        if not silent:
            self.log("开始轮询 {} 个测量量，周期 {:.3f} s。".format(len(names), interval))
        self._schedule_poll(0)

    def _start_daq(self, names) -> None:
        self._daq_generation += 1
        generation = self._daq_generation
        self._daq_start_pending = True
        self._daq_mode = True
        self._set_state(HostState.CONNECTING, "正在配置模型 DAQ")

        def started(metadata):
            if generation != self._daq_generation or self._closing:
                return
            self._daq_start_pending = False
            self.observation_tab.set_daq_metadata(metadata)
            latest = self.observation_tab.buffer.latest_timestamp()
            self._poll_offset = latest + metadata['period_seconds'] if latest is not None else 0.0
            self._acquiring = True
            self._set_state(HostState.ACQUIRING)
            self.log("DAQ 已启动：模型周期 {:.6g} s，事件 {}，{} 个信号。".format(
                metadata['period_seconds'], metadata['event_channel'], len(names)))
            self._schedule_poll(0)

        def failed():
            if generation == self._daq_generation:
                self._daq_start_pending = False
                self._daq_mode = bool(self.vm.daq_active)
                if self._daq_mode:
                    self._acquiring = True
                    self._set_state(HostState.ACQUIRING, "DAQ 启动未确认，请停止或断开")

        self._submit(lambda: self.vm.start_daq(names), started, "启动 DAQ", on_error=failed)

    def _schedule_poll(self, delay_ms: int) -> None:
        if self._closed or self._closing or not self._acquiring:
            return
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except RuntimeError:
                pass
        self._poll_after_id = self.root.after(max(0, int(delay_ms)), self._poll_once)

    def _poll_once(self) -> None:
        self._poll_after_id = None
        if self._closed or self._closing or not self._acquiring or self._poll_pending:
            return
        if self._daq_mode:
            try:
                samples = self.vm.drain_daq(max_samples=5000)
                if samples:
                    self.observation_tab.append_samples(samples, offset=self._poll_offset)
                    self._apply_policy()
            except Exception as exc:
                self._poll_failed(exc)
                return
            self._schedule_poll(40)
            return
        names = tuple(self.observation_tab.selected_names())
        if not names:
            self._stop_observation()
            return
        self._poll_pending = True
        future = self.executor.submit(self.vm.poll_measurements, names)
        self._track_future(future)

        def completed(done_future: Future) -> None:
            try:
                values = done_future.result()
            except Exception as exc:
                self._ui_queue.put((self._poll_failed, (exc,)))
            else:
                self._ui_queue.put((self._poll_succeeded, (values,)))

        future.add_done_callback(completed)

    def _poll_succeeded(self, result: Any) -> None:
        self._poll_pending = False
        if not self._acquiring or self._closed or self._closing:
            return
        values = self._coerce_values(result)
        elapsed = self._poll_offset + (time.monotonic() - self._poll_started_at)
        self.observation_tab.append_values(elapsed, values)
        self._apply_policy()
        self._schedule_poll(round(self.observation_tab.sample_interval() * 1000))

    def _poll_failed(self, exception: Exception) -> None:
        self._poll_pending = False
        self._stop_observation()
        if bool(getattr(self.vm, "connected", False)):
            self._set_state(HostState.CONNECTED, "观测失败，连接仍有效")
        else:
            self._set_state(HostState.ERROR)
        self.log("观测失败：{}".format(exception), level="ERROR")
        self.dialogs.error("观测失败", str(exception))

    def _stop_observation(self, settle: bool = True) -> None:
        was_running = self._acquiring
        was_daq = self._daq_mode or self._daq_start_pending
        self._daq_generation += 1
        self._daq_start_pending = False
        self._acquiring = False
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except RuntimeError:
                pass
            self._poll_after_id = None
        if was_daq:
            self._daq_mode = False
            if not self._closing:
                self._set_state(HostState.CONNECTING, "正在停止 DAQ")

                def stopped(_result):
                    samples = self.vm.drain_daq(max_samples=20000)
                    if samples:
                        self.observation_tab.append_samples(samples, offset=self._poll_offset)
                    if settle and not self._remote_stop_pending and not self._closing and self._state == HostState.CONNECTING:
                        self._set_state(HostState.CONNECTED if self.vm.connected else HostState.LOADED)

                def failed():
                    if self.vm.daq_active and not self._remote_stop_pending:
                        self._daq_mode = True
                        self._acquiring = True
                        self._set_state(HostState.ACQUIRING, "停止 DAQ 未确认，可重试")
                        self._schedule_poll(40)

                self._submit(self.vm.stop_daq, stopped, "停止 DAQ", on_error=failed)
        elif self._state == HostState.ACQUIRING:
            self._set_state(HostState.CONNECTED)
        if was_running:
            self.log("观测采样已停止。")

    def _export_csv(self) -> None:
        buffer = self.observation_tab.buffer
        if not len(buffer):
            self.dialogs.warning("导出", "当前没有观测数据。")
            return
        path = self.dialogs.save_csv()
        if not path:
            return
        self._submit(lambda: buffer.export_csv(Path(path)),
                     lambda output: self.log("观测数据已导出：{}".format(output)), "导出 CSV")

    def _refresh_calibrations(self) -> None:
        names = tuple(self.calibration_tab._items)
        self._run_with_poll_paused(
            lambda: self.vm.read_calibrations(names or None),
            lambda values: self.calibration_tab.update_current_values(self._coerce_values(values)),
            "读取标定量",
        )

    def _write_calibrations(self) -> None:
        try:
            changes = self.calibration_tab.pending_changes()
        except ValueError as exc:
            self.dialogs.error("标定", str(exc))
            return
        if not changes:
            self.dialogs.warning("标定", "请为至少一个选中项填写新原始值。")
            return
        preview_lines = ["{}: {}".format(name, value) for name, value in list(changes.items())[:20]]
        if len(changes) > 20:
            preview_lines.append("... 另有 {} 项".format(len(changes) - 20))
        if not self.dialogs.confirm("确认写入", "将写入并回读验证：\n\n" + "\n".join(preview_lines)):
            return

        def action():
            self.vm.write_calibrations(changes)
            verified = self._coerce_values(self.vm.read_calibrations(tuple(changes)))
            for name, expected in changes.items():
                if name not in verified or not self._values_equal(expected, verified[name]):
                    raise RuntimeError("{} 写入后的回读值不匹配。".format(name))
            return verified

        def succeeded(values):
            self.calibration_tab.update_current_values(values, status="已写入并验证")
            self.calibration_tab.clear_pending(values)
            self.log("已写入并回读验证 {} 个标定量。".format(len(values)))

        self._run_with_poll_paused(action, succeeded, "写入标定量")

    def _restore_calibrations(self) -> None:
        if not self.dialogs.confirm("恢复标定", "恢复本次连接会话中已写入的原始值？"):
            return

        def action():
            restored = self.vm.restore_calibrations()
            if restored is None:
                restored = self.vm.read_calibrations(None)
            return restored

        def succeeded(values):
            clean = self._coerce_values(values)
            self.calibration_tab.update_current_values(clean, status="已恢复并验证")
            self.calibration_tab.clear_pending(clean)
            self.log("已恢复并验证 {} 个标定量。".format(len(clean)))

        self._run_with_poll_paused(action, succeeded, "恢复标定量")

    def _run_with_poll_paused(self, action: Callable[[], Any], on_success: Callable[[Any], None], label: str) -> None:
        if self._calibration_pending or self._remote_stop_pending or self._closing:
            return
        if self._state not in (HostState.CONNECTED, HostState.ACQUIRING):
            return
        self._calibration_pending = True
        self._apply_policy()

        def finished():
            self._calibration_pending = False
            self._apply_policy()

        def succeeded(result):
            try:
                on_success(result)
            finally:
                finished()

        self._submit(action, succeeded, label, error_state=HostState.ERROR, on_error=finished)

    def _save_log(self) -> None:
        text = self.diagnostics_tab.log_text_value()
        if not text:
            self.dialogs.warning("日志", "当前没有日志。")
            return
        path = self.dialogs.save_log()
        if not path:
            return

        def action() -> Path:
            output = Path(path)
            output.write_text(text, encoding="utf-8")
            return output

        self._submit(action, lambda output: self.log("日志已保存：{}".format(output)), "保存日志")

    def _submit(
        self,
        action: Callable[[], Any],
        on_success: Optional[Callable[[Any], None]],
        label: str,
        error_state: Optional[HostState] = None,
        on_error: Optional[Callable[[], None]] = None,
    ) -> None:
        if self._closed or self._closing:
            return
        self.log("{}...".format(label))
        future = self.executor.submit(action)
        self._track_future(future)

        def completed(done_future: Future) -> None:
            try:
                result = done_future.result()
            except Exception as exc:
                self._ui_queue.put((self._operation_failed, (label, exc, error_state, on_error)))
            else:
                self._ui_queue.put((self._operation_succeeded, (result, on_success)))

        future.add_done_callback(completed)

    def _track_future(self, future: Future) -> None:
        self._pending_futures.add(future)
        future.add_done_callback(lambda completed: self._pending_futures.discard(completed))

    def _operation_succeeded(self, result: Any, callback: Optional[Callable[[Any], None]]) -> None:
        if callback is not None:
            callback(result)
        self._apply_policy()

    def _operation_failed(self, label: str, exception: Exception, error_state: Optional[HostState], on_error=None) -> None:
        if bool(getattr(self.vm, "connected", False)):
            self._set_state(HostState.ACQUIRING if self._acquiring else HostState.CONNECTED, "操作失败，连接仍有效")
        else:
            self._set_state(error_state or (HostState.LOADED if self._has_a2l else HostState.EMPTY))
        self.log("{}失败：{}".format(label, exception), level="ERROR")
        self.dialogs.error("{}失败".format(label), str(exception))
        if on_error:
            on_error()

    def _drain_ui_queue(self) -> None:
        if self._closed:
            return
        while True:
            try:
                callback, arguments = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*arguments)
            except Exception as exc:
                if not self._closing:
                    self.log("界面更新失败：{}".format(exc), level="ERROR")
        if not self._closed:
            self.root.after(40, self._drain_ui_queue)

    def _set_state(self, state: HostState, label: Optional[str] = None) -> None:
        self._state = state
        self.status_var.set(label or self.STATE_LABELS[state])
        self.status_lamp.set_color(self.STATE_COLORS[state])
        self._apply_policy()
        self._update_diagnostics()

    def _apply_policy(self) -> ControlPolicy:
        state = HostState.CONNECTING if self._remote_stop_pending else self._state
        policy = control_policy(state, has_a2l=self._has_a2l)
        if self._calibration_pending:
            from dataclasses import replace
            policy = replace(policy, calibration_enabled=False)
        self.connection_bar.set_policy(policy, self.vm.connected)
        self.observation_tab.set_policy(policy)
        self.calibration_tab.set_policy(policy)
        self.diagnostics_tab.read_log_button.setEnabled(
            self.target_tab._ready() and not self._closing and not self._remote_stop_pending)
        return policy

    def _update_diagnostics(self, source: Any = None) -> None:
        draft = self.connection_bar.draft()
        details = OrderedDict(
            (
                ("状态", self.STATE_LABELS[self._state]),
                ("协议", draft.protocol),
                ("目标", "{}:{}".format(draft.host.strip() or "--", draft.port or "--")),
                ("超时", "{} s".format(draft.timeout or "--")),
                ("A2L", draft.a2l_path or "--"),
            )
        )
        for candidate in (source, getattr(self.vm, "diagnostics", None)):
            if callable(candidate):
                candidate = candidate()
            as_dict = getattr(candidate, "as_dict", None)
            if callable(as_dict):
                candidate = as_dict()
            diagnostics = optional_attr(candidate, "diagnostics", candidate)
            if isinstance(diagnostics, Mapping):
                for key, value in diagnostics.items():
                    label = self.DIAGNOSTIC_LABELS.get(str(key), str(key))
                    if isinstance(value, bool):
                        value = "是" if value else "否"
                    details[label] = value
        self.diagnostics_tab.set_summary(details)

    def log(self, message: str, level: str = "INFO") -> None:
        line = "[{}] [{}] {}".format(datetime.now().strftime("%H:%M:%S"), level, message)
        if self._closed:
            return
        if self._is_ui_thread():
            self.diagnostics_tab.append_log(line)
        else:
            self._ui_queue.put((self.diagnostics_tab.append_log, (line,)))

    def request_close(self) -> None:
        if self._closed or self._closing:
            return
        self._closing = True
        self._stop_observation()
        self._set_state(HostState.CLOSING)
        for future in tuple(self._pending_futures):
            future.cancel()

        def cleanup() -> None:
            close_method = getattr(self.vm, "close", None)
            if callable(close_method):
                close_method()
            else:
                self.vm.disconnect()

        future = self.executor.submit(cleanup)

        def completed(done_future: Future) -> None:
            try:
                done_future.result()
            except Exception as exc:
                self._ui_queue.put((self._close_failed, (exc,)))
            else:
                self._ui_queue.put((self._finish_close, ()))

        future.add_done_callback(completed)

    def _close_failed(self, exception: Exception) -> None:
        self._closing = False
        if bool(getattr(self.vm, "connected", False)):
            self._set_state(HostState.CONNECTED, "关闭已取消，标定恢复失败")
        else:
            self._set_state(HostState.ERROR, "关闭失败")
        self.log("关闭失败：{}".format(exception), level="ERROR")
        self.dialogs.error(
            "关闭失败",
            "未能安全恢复本次会话的标定值，窗口保持打开：\n{}".format(exception),
        )

    def _catalog_values(self, result: Any, name: str) -> Sequence[Any]:
        values = optional_attr(result, name, None)
        if values is None:
            catalog = optional_attr(result, "catalog", None)
            values = optional_attr(catalog, name, None)
        if values is None:
            values = getattr(self.vm, name, ())
        return tuple(values or ())

    @staticmethod
    def _coerce_values(result: Any) -> Dict[str, Any]:
        if result is None:
            return {}
        if isinstance(result, Mapping):
            return {str(name): value for name, value in result.items()}
        values = {}
        for item in result:
            name = optional_attr(item, "name", None)
            value = optional_attr(item, "value", optional_attr(item, "current_value", None))
            if name is not None and value is not None:
                values[str(name)] = value
        return values

    @staticmethod
    def _values_equal(expected: Any, actual: Any) -> bool:
        try:
            return math.isclose(float(expected), float(actual), rel_tol=1e-7, abs_tol=1e-9)
        except (TypeError, ValueError):
            return expected == actual

    @staticmethod
    def _is_ui_thread() -> bool:
        import threading

        return threading.current_thread() is threading.main_thread()
