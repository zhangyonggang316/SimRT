"""Native Qt application shell; one serialized XCP command worker."""
import queue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel,
    QVBoxLayout, QHBoxLayout, QTabWidget, QPlainTextEdit, QTableWidgetItem,
    QFileDialog, QInputDialog, QMessageBox, QStyle, QMenu)
from pyxcp_host.viewmodel import HostViewModel
from .common import command, table, menu_command
from .fields import Field, Scheduler
from .state import HostState
from .controller import HostController
from .connection import ConnectionBar
from .observation import ObservationTab
from .native import DEFAULT_HISTORY_POINTS, SamplePoint
from .calibration import CalibrationTab
from .target import TargetWorkspace


class QtDialogs:
    def __init__(self, parent):
        self.parent = parent

    def open_a2l(self):
        return QFileDialog.getOpenFileName(self.parent, '加载模型', '', '模型文件 (*.zip *.a2l);;模型包 (*.zip);;ASAM MCD-2 MC (*.a2l)')[0]

    def save_csv(self):
        return QFileDialog.getSaveFileName(self.parent, '导出观测数据', 'observation.csv', 'CSV (*.csv)')[0]

    def save_log(self):
        return QFileDialog.getSaveFileName(self.parent, '保存诊断日志', 'diagnostics.log', '日志 (*.log);;文本 (*.txt)')[0]

    def edit_value(self, name, initial):
        text, ok = QInputDialog.getText(self.parent, '标定原始值', '{} 的新原始值'.format(name), text=initial)
        return text if ok else None

    def confirm(self, title, text):
        return QMessageBox.question(self.parent, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def warning(self, title, text):
        QMessageBox.warning(self.parent, title, text)

    def error(self, title, text):
        QMessageBox.critical(self.parent, title, text)


class StatusLamp(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(9, 9)

    def set_color(self, color):
        self.setStyleSheet('background: {}; border-radius: 4px;'.format(color))


class DiagnosticsTab(QWidget):
    def __init__(self, parent, on_save, on_read_log):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = table(('项目', '值'))
        self.summary.setColumnWidth(0, 220)
        self.summary.setMaximumHeight(260)
        layout.addWidget(self.summary)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('诊断日志'))
        toolbar.addStretch()
        self.read_log_button = command('读取运行日志', on_read_log, icon=QStyle.StandardPixmap.SP_FileDialogContentsView)
        self.read_log_button.setEnabled(False)
        self.copy_button = command('复制全部', self.copy_all, icon=QStyle.StandardPixmap.SP_FileIcon)
        self.clear_button = command('清空显示', self.clear_log, icon=QStyle.StandardPixmap.SP_DialogResetButton)
        self.save_button = command('保存日志', on_save, icon=QStyle.StandardPixmap.SP_DialogSaveButton)
        for button in (self.read_log_button, self.copy_button, self.clear_button, self.save_button):
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(10000)
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.log_text.customContextMenuRequested.connect(self._log_context_menu)
        layout.addWidget(self.log_text, 1)
        self.log_text.textChanged.connect(self._log_policy)
        self._log_policy()

    def copy_all(self):
        QApplication.clipboard().setText(self.log_text_value())

    def clear_log(self):
        self.log_text.clear()

    def _log_policy(self):
        available = not self.log_text.document().isEmpty()
        for button in (self.copy_button, self.clear_button, self.save_button):
            button.setEnabled(available)

    def _log_context_menu(self, position):
        menu = QMenu(self.log_text)
        menu_command(menu, '复制所选文本', self.log_text.copy, QStyle.StandardPixmap.SP_FileIcon,
                     self.log_text.textCursor().hasSelection())
        menu_command(menu, '选择全部', self.log_text.selectAll, QStyle.StandardPixmap.SP_DialogApplyButton,
                     not self.log_text.document().isEmpty())
        menu.addSeparator()
        for button in (self.read_log_button, self.copy_button, self.clear_button, self.save_button):
            action = menu_command(menu, button.text(), button.click, QStyle.StandardPixmap.SP_FileIcon, button.isEnabled())
            action.setIcon(button.icon())
        menu.exec(self.log_text.viewport().mapToGlobal(position))

    def set_summary(self, details):
        self.summary.setRowCount(len(details))
        for row, (key, value) in enumerate(details.items()):
            self.summary.setItem(row, 0, QTableWidgetItem(str(key)))
            self.summary.setItem(row, 1, QTableWidgetItem(str(value)))

    def append_log(self, text):
        self.log_text.appendPlainText(text)

    def log_text_value(self):
        return self.log_text.toPlainText()


class MainWindow(QMainWindow, HostController):
    def __init__(self, view_model=None, executor=None, dialogs=None, target_service=None,
                 target_monitor=None, max_chart_points=DEFAULT_HISTORY_POINTS, credential_store=None):
        super().__init__()
        self.root = Scheduler(self)
        self.vm = view_model if view_model is not None else HostViewModel()
        self.dialogs = dialogs or QtDialogs(self)
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix='qt-xcp')
        self._owns_executor = executor is None
        self._state = HostState.EMPTY
        self._has_a2l = False
        self._loaded_a2l_path = None
        self._payload_endpoint = self._catalog_endpoint = None
        self._closed = self._closing = self._close_authorized = False
        self._remote_stop_pending = False
        self._acquiring = self._poll_pending = False
        self._poll_after_id = None
        self._poll_started_at = self._poll_offset = 0.0
        self._daq_mode = self._daq_start_pending = False
        self._daq_generation = 0
        self._calibration_pending = False
        self._pending_futures = set()
        self._ui_queue = queue.Queue()
        self._last_connection = None
        self.setWindowTitle('pyXCP 观测与标定上位机 · Qt')
        self.setMinimumSize(1000, 660)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1320, available.width() - 24), min(820, available.height() - 48))
        content = QWidget(self)
        self.setCentralWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName('appHeader')
        header.setFixedHeight(40)
        heading = QHBoxLayout(header)
        heading.setContentsMargins(16, 0, 18, 0)
        title = QLabel('pyXCP 观测与标定上位机')
        title.setObjectName('appTitle')
        heading.addWidget(title)
        heading.addStretch()
        endpoint = QLabel('-- --:--')
        self.endpoint_var = Field(endpoint)
        heading.addWidget(endpoint)
        heading.addSpacing(18)
        self.status_lamp = StatusLamp()
        heading.addWidget(self.status_lamp)
        status = QLabel()
        self.status_var = Field(status)
        heading.addWidget(status)
        layout.addWidget(header)
        self.notebook = QTabWidget()
        self.notebook.setObjectName('mainTabs')
        layout.addWidget(self.notebook, 1)
        self.machine_page = QWidget()
        machine = QVBoxLayout(self.machine_page)
        machine.setContentsMargins(10, 10, 10, 10)
        self.connection_bar = ConnectionBar(self.machine_page, self._browse_a2l, self._load_a2l,
            self._connect, self._disconnect, self._endpoint_changed, self._a2l_changed)
        self.machine_notebook = QTabWidget()
        machine.addWidget(self.machine_notebook, 1)
        self.model_deployment_tab = TargetWorkspace(self.machine_notebook, self._with_xcp_disconnected,
                                                     target_service, target_monitor, credential_store)
        self.target_tab = self.deployment_tab = self.model_deployment_tab
        self.diagnostics_tab = DiagnosticsTab(self.machine_notebook, self._save_log, self.target_tab.read_log)
        self.target_tab.logReadAvailable.connect(lambda ready: self.diagnostics_tab.read_log_button.setEnabled(
            ready and not self._closing and not self._remote_stop_pending))
        self.machine_notebook.addTab(self.model_deployment_tab, '模型部署')
        self.machine_notebook.addTab(self.diagnostics_tab, '诊断日志')
        self.observation_tab = ObservationTab(self.notebook, self._start_observation, self._stop_observation,
            self._export_csv, self._open_native_sdi, max_chart_points)
        self.observation_tab.layout().insertWidget(0, self.connection_bar)
        self.calibration_tab = CalibrationTab(self.notebook, self._refresh_calibrations, self._write_calibrations,
            self._restore_calibrations, self.dialogs.edit_value, lambda text: self.dialogs.error('标定', text))
        self.notebook.addTab(self.machine_page, '实时机')
        self.notebook.addTab(self.observation_tab, '观测')
        self.notebook.addTab(self.calibration_tab, '标定')
        self.target_tab.logMessage.connect(self.log)
        self.target_tab.error.connect(lambda text: self.dialogs.error('模型部署', text))
        self.target_tab.payloadSelected.connect(self._payload_selected)
        self.target_tab.host_edit.textChanged.connect(self._resolve_file_endpoint)
        self._install_log_sink()
        self._set_state(HostState.EMPTY)
        self.root.after(40, self._drain_ui_queue)

    def apply_demo(self, settings):
        self.target_tab.apply_demo(settings)
        archive = getattr(settings, 'payload_archive', None)
        self.target_tab.select_payload(archive or settings.payload_dir)
        self.show_machine_section(self.target_tab)

    def show_machine_section(self, section):
        self.notebook.setCurrentWidget(self.machine_page)
        self.machine_notebook.setCurrentWidget(section)

    def _payload_selected(self, payload):
        if self._closing or self._closed:
            return
        if self.vm.connected or self._acquiring or self._state == HostState.CONNECTING or self._remote_stop_pending:
            self.log('本地产物已选择；请在 XCP 断开后重新选择，以加载配套 A2L。', level='WARNING')
            return
        self._payload_endpoint = dict(payload)
        self.connection_bar.a2l_var.set(payload['a2l'])
        self._load_a2l()

    def _open_native_sdi(self):
        from pyxcp_host.services.sdi_export import export_sdi_session, find_matlab_executable, launch_sdi
        if self._acquiring or self._poll_pending:
            self.dialogs.warning('MATLAB SDI', '请先停止采样，再发送本次数据。')
            return
        buffer = self.observation_tab.buffer
        if not len(buffer):
            self.dialogs.warning('MATLAB SDI', '当前没有可导出的样本。')
            return
        executable = find_matlab_executable()
        if executable is None:
            selected = QFileDialog.getOpenFileName(self, '选择 MATLAB R2024b 程序', '', 'MATLAB (matlab.exe)')[0]
            if not selected:
                return
            executable = Path(selected)
        destination = QFileDialog.getExistingDirectory(self, '选择 SDI 会话保存目录')
        if not destination:
            return
        def action():
            arrays = buffer.snapshot_arrays()
            snapshot = {name: (SamplePoint(float(stamp), float(value)) for stamp, value in points)
                        for name, points in arrays.items()}
            script = export_sdi_session(snapshot, Path(destination))
            launch_sdi(script, executable)
            return script

        self._submit(action,
                     lambda script: self.log('已请求 MATLAB 打开 SDI，会话文件：{}；导入结果请在 MATLAB 窗口确认。'.format(script.parent)),
                     '打开 MATLAB SDI')

    def _with_xcp_disconnected(self, action, on_failure=None):
        if self._closed or self._closing or self._remote_stop_pending:
            if on_failure:
                on_failure()
            return
        self._remote_stop_pending = True
        self._stop_observation(settle=False)
        self._set_state(HostState.CONNECTING, '恢复标定后停止模型')

        def finish(failed=False):
            self._remote_stop_pending = False
            if failed and on_failure:
                on_failure()
            if not self._closed and not self._closing:
                if bool(getattr(self.vm, 'connected', False)):
                    self._set_state(HostState.CONNECTED)
                else:
                    self._after_disconnected()

        def wait_for_stop():
            if self._closed or self._closing:
                return
            if self.target_tab.busy or self.target_tab.control_pending:
                self.root.after(40, wait_for_stop)
            else:
                finish()

        def disconnected(_result):
            if self._closing:
                finish(True)
                return
            self._set_state(HostState.CONNECTING, '正在停止模型')
            try:
                accepted = action()
            except Exception as exc:
                finish(True)
                self.log('停止模型失败：{}'.format(exc), level='ERROR')
                self.dialogs.error('停止模型失败', str(exc))
                return
            if accepted:
                wait_for_stop()
            else:
                finish(True)

        self._submit(self.vm.disconnect, disconnected, '停止前恢复标定并断开 XCP', on_error=lambda: finish(True))

    def _finish_close(self):
        if not self.target_tab.close_workspace():
            self.root.after(40, self._finish_close)
            return
        self.target_tab.worker.shutdown()
        self.observation_tab.dispose()
        self._closed = True
        if self._owns_executor:
            self.executor.shutdown(wait=False)
        self.root.destroy()

    def closeEvent(self, event):
        if self._close_authorized:
            event.accept()
        else:
            event.ignore()
            self.request_close()
