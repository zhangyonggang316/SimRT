"""Qt deployment and target inventory, sharing one serialized SSH worker."""

from datetime import datetime
import math
from pathlib import Path, PurePosixPath
import queue
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QProgressBar,
    QPushButton, QSpinBox, QSplitter, QStyle, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget, QScrollArea,
)

from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.payload_archive import PayloadArchive
from pyxcp_host.services.target_monitor import TargetMonitor

from .common import AsyncWorker, menu_command
from .credential_store import CredentialStore


def _capacity(value):
    return '--' if value is None else '{:.2f} GiB'.format(value / 1024 ** 3)


class TargetWorkspace(QWidget):
    logMessage = Signal(str)
    logReadAvailable = Signal(bool)
    error = Signal(str)
    payloadSelected = Signal(object)

    def __init__(self, parent=None, stop_guard=None, service=None, monitor=None, credential_store=None):
        super().__init__(parent)
        self.setObjectName('targetWorkspace')
        self._logs = queue.Queue(maxsize=256)
        self.service = service if service is not None else SSHDeployment(self._enqueue_log)
        self.monitor = monitor if monitor is not None else TargetMonitor(self.service)
        self.credential_store = credential_store if credential_store is not None else CredentialStore()
        self._credentials_restored = False
        self.stop_guard = stop_guard or (lambda action, on_failure=None: action())
        self.worker = AsyncWorker(self)
        self.worker.busyChanged.connect(self._policy)
        self.payload_archive = PayloadArchive()
        self._background_refresh = False
        self._queued_operation = None
        self._context_menu_open = False
        self._deferred_render = None
        self._inventory_dirty = True
        self._inventory_root = None
        self.deployment = self.target = self
        self._closing = self._closed = self._close_submitted = False
        self.control_pending = False
        self.running = False
        self.models = []
        self.autostart = {}
        self._home = ''
        self._next_refresh = 0.0
        self._was_connected = False
        self._rendering = False
        self._fields = []
        self.buttons = {}
        self._build_ui()
        self._restore_credentials()
        self._policy()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    @property
    def busy(self):
        return bool(self.worker.busy and not self._background_refresh or self._queued_operation
                    or self.control_pending or self._closing and not self._closed)

    def _entry(self, value='', password=False):
        widget = QLineEdit(value)
        widget.setMinimumWidth(0)
        if password:
            widget.setEchoMode(QLineEdit.EchoMode.Password)
        self._fields.append(widget)
        return widget

    def _button(self, name, text, callback, icon=None, compact=False):
        button = QToolButton() if compact else QPushButton(text)
        if compact:
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.setFixedSize(30, 30)
        if icon is not None:
            button.setIcon(self.style().standardIcon(icon))
        button.clicked.connect(callback)
        button.setMinimumWidth(0)
        self.buttons[name] = button
        return button

    @staticmethod
    def _label(text, section=False):
        label = QLabel(text)
        if section:
            label.setObjectName('sectionHeading')
        return label

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter)
        left, right = QWidget(), QWidget()
        left.setMinimumWidth(355)
        right.setMinimumWidth(435)
        self.deployment_scroll = QScrollArea()
        self.deployment_scroll.setWidgetResizable(True)
        self.deployment_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.deployment_scroll.setMinimumWidth(355)
        self.deployment_scroll.setWidget(left)
        self.splitter.addWidget(self.deployment_scroll)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        self.splitter.setSizes([400, 600])
        deploy = QVBoxLayout(left)
        deploy.setContentsMargins(12, 10, 12, 10)
        deploy.setSpacing(7)
        deploy.addWidget(self._label('SSH 与模型部署', True))
        connection = QGridLayout()
        connection.setHorizontalSpacing(7)
        self.host_edit = self._entry()
        self.user_edit = self._entry()
        self.password_edit = self._entry(password=True)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(22)
        self._fields.append(self.port_spin)
        for row, label, field in ((0, 'Ubuntu 主机', self.host_edit), (1, '用户', self.user_edit)):
            connection.addWidget(self._label(label), row, 0)
            connection.addWidget(field, row, 1)
        connection.addWidget(self._label('端口'), 0, 2)
        connection.addWidget(self.port_spin, 0, 3)
        connection.addWidget(self._label('密码'), 1, 2)
        connection.addWidget(self.password_edit, 1, 3)
        connection.setColumnStretch(1, 3)
        connection.setColumnStretch(3, 2)
        deploy.addLayout(connection)
        self.remember_credentials = QCheckBox('记住 SSH 凭据')
        self.remember_credentials.setToolTip('使用当前 Windows 用户加密保存；取消勾选将清除记录')
        self.remember_credentials.toggled.connect(self._remember_changed)
        self._fields.append(self.remember_credentials)
        deploy.addWidget(self.remember_credentials)
        connect_row = QHBoxLayout()
        self.ssh_status = self._label('SSH 未连接')
        self.ssh_status.setWordWrap(True)
        connect_row.addWidget(self.ssh_status, 1)
        connect_row.addWidget(self._button('connect', '连接 SSH', self.connect_ssh,
                                           QStyle.StandardPixmap.SP_DialogOkButton))
        connect_row.addWidget(self._button('disconnect', '断开', self.disconnect_ssh,
                                           QStyle.StandardPixmap.SP_DialogCloseButton))
        deploy.addLayout(connect_row)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        deploy.addWidget(separator)

        project = QGridLayout()
        project.setHorizontalSpacing(7)
        project.setVerticalSpacing(4)
        self.local_edit = self._entry()
        self.remote_edit = self._entry('pyxcp-project')
        self.elf_edit = self._entry('demo.elf')
        project.addWidget(self._label('本地模型包 (ZIP)'), 0, 0, 1, 4)
        project.addWidget(self.local_edit, 1, 0, 1, 3)
        project.addWidget(self._button('browse', '选择模型 ZIP', self._choose_payload,
                                      QStyle.StandardPixmap.SP_DirOpenIcon, True), 1, 3)
        project.addWidget(self._label('远程项目目录'), 2, 0, 1, 4)
        project.addWidget(self.remote_edit, 3, 0, 1, 4)
        project.addWidget(self._label('ELF 相对路径'), 4, 0, 1, 4)
        project.addWidget(self.elf_edit, 5, 0, 1, 4)
        project.setColumnStretch(0, 1)
        project.setColumnStretch(2, 1)
        deploy.addLayout(project)
        self.payload_status = self._label('产物尚未校验')
        self.payload_status.setWordWrap(True)
        self.local_edit.textEdited.connect(lambda _: self.payload_status.setText('产物尚未校验'))
        deploy.addWidget(self.payload_status)
        actions = QGridLayout()
        actions.setSpacing(5)
        for index, (name, label, call, icon) in enumerate((
                ('upload', '上传产物', self.upload, QStyle.StandardPixmap.SP_ArrowUp),
                ('start', '启动 ELF', self.start_elf, QStyle.StandardPixmap.SP_MediaPlay),
                ('stop', '停止 ELF', self.stop_elf, QStyle.StandardPixmap.SP_MediaStop))):
            actions.addWidget(self._button(name, label, call, icon), index // 3, index % 3)
            actions.setColumnStretch(index % 3, 1)
        deploy.addLayout(actions)
        self.process_status = self._label('ELF 状态未知')
        self.process_status.setWordWrap(True)
        deploy.addWidget(self.process_status)
        deploy.addStretch(1)

        target = QVBoxLayout(right)
        target.setContentsMargins(12, 10, 12, 10)
        target.setSpacing(8)
        self.machine_label = self._label('目标机资源', True)
        self.machine_label.setWordWrap(True)
        self.target_status = self._label('SSH 未连接')
        self.target_status.setWordWrap(True)
        target.addWidget(self.machine_label)
        target.addWidget(self.target_status)
        metrics = QGridLayout()
        self.metric_labels, self.metric_bars = {}, {}
        for column, (key, title) in enumerate((('cpu', 'CPU'), ('memory', '内存'), ('disk', '磁盘'))):
            metrics.addWidget(self._label(title, True), 0, column)
            value = self._label('--')
            value.setWordWrap(True)
            value.setMinimumHeight(38)
            metrics.addWidget(value, 1, column)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(6)
            metrics.addWidget(bar, 2, column)
            metrics.setColumnStretch(column, 1)
            self.metric_labels[key], self.metric_bars[key] = value, bar
        target.addLayout(metrics)
        self.details_label = self._label('--')
        self.details_label.setWordWrap(True)
        self.details_label.setMinimumHeight(38)
        target.addWidget(self.details_label)
        folder = QHBoxLayout()
        folder.addWidget(self._label('模型目录'))
        self.root_edit = QLineEdit('MATLAB_ws')
        self.root_edit.setMinimumWidth(0)
        self.root_edit.editingFinished.connect(self._request_inventory)
        folder.addWidget(self.root_edit, 1)
        folder.addWidget(self._button('refresh_models', '刷新模型', self.refresh,
                                      QStyle.StandardPixmap.SP_BrowserReload, True))
        target.addLayout(folder)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        for name, label, call, icon in (
                ('start_model', '启动模型', self.start_model, QStyle.StandardPixmap.SP_MediaPlay),
                ('stop_model', '停止模型', self.stop_model, QStyle.StandardPixmap.SP_MediaStop),
                ('select_model', '选择模型', self.select_model, QStyle.StandardPixmap.SP_FileIcon)):
            toolbar.addWidget(self._button(name, label, call, icon))
        target.addLayout(toolbar)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['开机自启', '模型', '状态', 'PID', '大小', '修改时间', '远程路径'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((78, 150, 95, 60, 75, 120, 240)):
            self.table.setColumnWidth(column, width)
        self.table.setMinimumWidth(0)
        self.table.itemSelectionChanged.connect(self._policy)
        self.table.itemChanged.connect(self._autostart_changed)
        self.table.cellDoubleClicked.connect(lambda row, column: self.select_model() if column else None)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._model_context_menu)
        target.addWidget(self.table, 1)

    def apply_demo(self, settings):
        if self.busy or self.service.connected:
            raise RuntimeError('Disconnect SSH before changing the demo preset')
        source = getattr(settings, 'payload_archive', None) or settings.payload_dir
        for field, value in ((self.local_edit, str(source)), (self.remote_edit, settings.remote_dir),
                             (self.elf_edit, settings.elf_name), (self.root_edit, settings.remote_dir)):
            field.setText(value)
        if not self._credentials_restored:
            self.host_edit.setText(settings.host)
            self.user_edit.setText(settings.username)
            self.password_edit.clear()

    def _restore_credentials(self):
        try:
            saved = self.credential_store.load()
            if saved:
                self.host_edit.setText(saved['host'])
                self.user_edit.setText(saved['username'])
                self.password_edit.setText(saved['password'])
                self.port_spin.setValue(saved['port'])
                self.remember_credentials.setChecked(True)
                self._credentials_restored = True
        except Exception:
            self._enqueue_log('保存的 SSH 凭据无法恢复，请重新输入。')

    def _remember_changed(self, checked):
        if checked:
            return
        try:
            self.credential_store.clear()
        except Exception:
            self.remember_credentials.blockSignals(True)
            self.remember_credentials.setChecked(True)
            self.remember_credentials.blockSignals(False)
            self._error('保存的 SSH 凭据未能清除。')
            return
        self._credentials_restored = False
        self.password_edit.clear()

    def _enqueue_log(self, message):
        if self._closed:
            return
        text = str(message)[-8192:]
        try:
            self._logs.put_nowait(text)
        except queue.Full:
            try:
                self._logs.get_nowait()
            except queue.Empty:
                pass
            try:
                self._logs.put_nowait(text)
            except queue.Full:
                pass

    def _append(self, message):
        text = str(message).rstrip()[-32768:]
        self.logMessage.emit(text)

    def _error(self, error):
        self._append('错误：' + str(error))
        self.error.emit(str(error))

    def _submit(self, label, call, success=None, reserved=False, background=False):
        if self._closing or self._queued_operation or self.control_pending and not reserved:
            return False
        if self.worker.busy:
            if self._background_refresh and not background:
                self._queued_operation = (label, call, success, reserved)
                self._policy()
                return True
            return False
        self._background_refresh = background

        def complete():
            self._background_refresh = False
            pending, self._queued_operation = self._queued_operation, None
            if pending and not self._closing:
                self._submit(*pending)
            self._policy()

        def finished(result):
            if reserved:
                self.control_pending = False
            self._next_refresh = time.monotonic() + 2.0
            if not self._closing:
                if not background:
                    self._append(label + '完成')
                if success is not None:
                    success(result)
            complete()

        def failed(error):
            if reserved:
                self.control_pending = False
            self._next_refresh = time.monotonic() + 2.0
            if not self._closing:
                self._error(error)
            complete()

        accepted = self.worker.submit(label, call, finished, failed)
        if accepted:
            if not background:
                self._append(label + '...')
            self._policy()
        return bool(accepted)

    def connect_ssh(self):
        if not self._ready(disconnected=True) or self.service.connected:
            return False
        settings = self.host_edit.text(), self.user_edit.text(), self.password_edit.text(), self.port_spin.value()
        remember = self.remember_credentials.isChecked()
        self.password_edit.clear()

        def connect():
            try:
                result = self.service.connect(*settings)
                result['process'] = self.service.status()
                return result
            except Exception as error:
                message = str(error)
                if settings[2]:
                    message = message.replace(settings[2], '[redacted]')
                raise RuntimeError(message) from None

        def connected(result):
            self._home = result['home']
            self.ssh_status.setText('已连接 ' + result['host'])
            self._process_state(result['process'])
            self._next_refresh = 0
            self._was_connected = False
            if remember:
                try:
                    self.credential_store.save(settings[0], settings[1], settings[2], settings[3])
                    self._credentials_restored = True
                except Exception:
                    self._error('SSH 已连接，但凭据未能加密保存。')

        return self._submit('连接 SSH', connect, connected)

    def disconnect_ssh(self):
        if self._ready():
            return self._submit('断开 SSH', self.service.close, lambda _: self._reset_target())
        return False

    def _elf_path(self):
        relative = PurePosixPath(self.elf_edit.text().strip())
        if not relative.name or relative.is_absolute() or '..' in relative.parts or '\\' in str(relative):
            raise ValueError('ELF 必须使用项目目录内的相对路径。')
        remote = self.remote_edit.text().strip()
        if not remote:
            raise ValueError('请填写远程项目目录。')
        return str(PurePosixPath(remote, relative))

    def _choose_payload(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择模型 ZIP', self.local_edit.text(), '模型包 (*.zip)')
        if path:
            self.select_payload(path)

    def select_payload(self, source):
        if not self._ready(disconnected=True) or self.running:
            return False
        if Path(source).suffix.lower() == '.zip':
            return self._submit('加载模型包', lambda: self.payload_archive.load(source), self._accept_payload)
        try:
            payload = self.payload_archive.load(source)
        except Exception as error:
            self._error(error)
            return False
        self._accept_payload(payload)
        return True

    def _accept_payload(self, payload):
        self.local_edit.setText(payload.get('source', payload['directory']))
        self.elf_edit.setText(payload['elf_name'])
        self.payload_status.setText('清单校验通过：{} 个文件'.format(len(payload['files'])))
        self.payloadSelected.emit(payload)

    def upload(self):
        if not self._ready() or self.running:
            return False
        local, remote = self.local_edit.text().strip(), self.remote_edit.text().strip()
        if not local:
            self._error('请选择本地模型 ZIP。')
            return False
        try:
            payload = self.payload_archive.load(local) if Path(local).is_dir() else None
            if not remote:
                raise ValueError('请填写远程项目目录。')
        except Exception as error:
            self._error(error)
            return False
        if payload is not None:
            self._accept_payload(payload)

        def deploy():
            loaded = payload if payload is not None else self.payload_archive.load(local)
            return loaded, self.service.deploy_payload(Path(loaded['directory']), remote)

        def uploaded(value):
            loaded, result = value
            if payload is None:
                self._accept_payload(loaded)
            if not result.get('verified'):
                self._error('目标机产物哈希校验未通过。')
                return
            path = PurePosixPath(result['elf_path'])
            self.remote_edit.setText(str(path.parent))
            self.elf_edit.setText(path.name)
            self._append('目标机校验通过：{} 个文件'.format(result['file_count']))
            self._next_refresh = 0
            self._inventory_dirty = True

        return self._submit('上传产物', deploy, uploaded)

    def start_elf(self):
        if not self._ready() or self.running:
            return False
        try:
            remote = self._elf_path()
        except ValueError as exc:
            self._error(exc)
            return False
        def start():
            self.service.start(remote)
            return self.service.status()

        return self._submit('启动 ELF', start, self._process_changed)

    def _guarded_stop(self, remote=None):
        if not self._ready():
            return False
        self.control_pending = True
        self._policy()

        def release():
            self.control_pending = False
            self._policy()

        def stop():
            if remote is not None:
                self.service.status(remote)
            self.service.stop()
            return self.service.status()

        def proceed():
            accepted = self._submit('停止模型', stop, self._process_changed, reserved=True)
            if not accepted:
                release()
            return accepted

        try:
            self.stop_guard(proceed, release)
        except Exception as exc:
            release()
            self._error(exc)
            return False
        return True

    def stop_elf(self):
        return self._guarded_stop() if self.running else False

    def _process_state(self, state, log=True):
        self.running = bool(state.get('running'))
        self.process_status.setText('PID {}'.format(state.get('pid')) if self.running else 'ELF 已停止')
        if log and state.get('elf_path'):
            self._append('ELF: {} [{}]'.format(state['elf_path'], state.get('state', '--')))
        self._policy()

    def _process_changed(self, state):
        self._process_state(state)
        self._update_model_process(state)
        self._next_refresh = 0

    def _update_model_process(self, state):
        path = state.get('elf_path')
        changed = False
        for model in self.models:
            if model['path'] == path and (model['owned'] or state.get('running')):
                values = dict(running=bool(state.get('running')), owned=bool(state.get('running')),
                              pids=[state['pid']] if state.get('pid') else [])
                changed |= any(model.get(key) != value for key, value in values.items())
                model.update(values)
        if changed:
            self._render_models(self.models)

    def read_log(self):
        if not self._ready():
            return False
        selected = self.selected()
        try:
            remote = selected['path'] if selected else self._elf_path()
        except ValueError as exc:
            self._error(exc)
            return False

        def read():
            self.service.status(remote)
            return self.service.read_log()

        return self._submit('读取运行日志', read,
                            lambda value: self._append('运行日志 [{}]\n{}'.format(remote, value or '(暂无运行日志)')))

    def cancel(self):
        if self.worker.busy:
            self.service.cancel()
            self._append('已请求取消当前任务')

    def selected(self):
        row = self.table.currentRow()
        return self.models[row] if 0 <= row < len(self.models) else None

    def select_model(self):
        selected = self.selected()
        if not self._ready() or not selected:
            return False
        path = PurePosixPath(selected['path'])
        self.remote_edit.setText(str(path.parent))
        self.elf_edit.setText(path.name)
        self.remote_edit.setFocus()
        return True

    def start_model(self):
        selected = self.selected()
        if not self._ready() or not selected or selected['running'] or self.running:
            return False
        path = selected['path']
        def start():
            self.service.start(path)
            return self.service.status()

        return self._submit('启动模型', start, self._process_changed)

    def stop_model(self):
        selected = self.selected()
        if not selected or not selected['running'] or not selected['owned']:
            return False
        return self._guarded_stop(selected['path'])

    def _confirm_model_delete(self, model):
        dialog = QMessageBox(self)
        dialog.setWindowTitle('删除模型')
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText('删除模型“{}”及其整个远程文件夹？'.format(model['name']))
        dialog.setInformativeText('{}\n\n文件夹内的所有文件将永久删除；该模型的开机自启配置也会清除。'.format(
            PurePosixPath(model['path']).parent))
        delete = dialog.addButton('删除', QMessageBox.ButtonRole.DestructiveRole)
        cancel = dialog.addButton('取消', QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        return dialog.clickedButton() == delete

    def delete_model(self, remote_elf=None):
        selected = (next((model for model in self.models if model['path'] == remote_elf), None)
                    if remote_elf is not None else self.selected())
        if not self._ready() or not selected or selected['running']:
            return False
        selected = dict(selected)
        root = self.root_edit.text().strip()
        self.control_pending = True
        self._policy()
        try:
            if not self._confirm_model_delete(selected) or self._closing:
                self.control_pending = False
                self._policy()
                return False
        except Exception as exc:
            self.control_pending = False
            self._policy()
            self._error(exc)
            return False

        def deleted(result):
            if result.get('deleted') is not True:
                self._error('目标机未确认删除结果，请刷新模型列表。')
                return
            directory = PurePosixPath(result['directory'])
            self._rendering = True
            try:
                for row in range(len(self.models) - 1, -1, -1):
                    if directory in PurePosixPath(self.models[row]['path']).parents:
                        self.models.pop(row)
                        self.table.removeRow(row)
                self.table.clearSelection()
                self.table.setCurrentItem(None)
            finally:
                self._rendering = False
            if result.get('autostart_cleared'):
                self.autostart = {}
            self._paint_autostart()
            self._append('已删除远程文件夹：' + str(directory))
            self._next_refresh = 0
            self._inventory_dirty = True

        accepted = self._submit('删除模型',
                                lambda: self.service.delete_model(selected['path'], root=root),
                                deleted, reserved=True)
        if not accepted:
            self.control_pending = False
            self._policy()
        return accepted

    def _autostart_changed(self, item):
        if self._rendering or item.column() != 0:
            return
        row = item.row()
        if not 0 <= row < len(self.models):
            return
        self.table.selectRow(row)
        self.toggle_autostart()
        self._paint_autostart()

    def _paint_autostart(self):
        self._rendering = True
        try:
            for row, model in enumerate(self.models):
                checked = self.autostart.get('enabled') and self.autostart.get('elf_path') == model['path']
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self._rendering = False

    def toggle_autostart(self):
        selected = self.selected()
        if not self._ready() or not selected:
            return False
        path = selected['path']
        enabled = self.autostart.get('enabled') and self.autostart.get('elf_path') == path

        def configured(result):
            self.autostart = result
            self._paint_autostart()
            self._append('开机自启：' + (result.get('elf_path', '') if result.get('enabled') else '未设置'))
            self._next_refresh = 0

        return self._submit('设置开机自启', lambda: self.service.set_autostart(None if enabled else path, ''), configured)

    def _request_inventory(self):
        if self.root_edit.text().strip() != self._inventory_root:
            self._inventory_dirty = True

    def refresh(self, *, background=False):
        if not self._ready():
            return False
        root = self.root_edit.text().strip()

        def query():
            snapshot = self.monitor.snapshot()
            models = self.monitor.list_models(root)
            try:
                autostart = self.service.autostart_status()
                if not isinstance(autostart, dict):
                    autostart = {}
                failure = ''
            except Exception as exc:
                autostart, failure = {}, str(exc)
            return snapshot, models, autostart, failure, self.service.status()

        accepted = self._submit('刷新目标机', query, self._render, background=background)
        if accepted:
            self._inventory_dirty = False
            self._inventory_root = root
            self._was_connected = True
        return accepted

    def _poll_resources(self):
        def render(result):
            if self._context_menu_open:
                return
            snapshot, process = result
            self._render_resources(snapshot, process)
            self._update_model_process(process)

        return self._submit('目标机状态', lambda: (self.monitor.snapshot(), self.service.status()),
                            render, background=True)

    def _render(self, result):
        if self._context_menu_open:
            self._deferred_render = result
            return
        snapshot, models, self.autostart, autostart_error, process = result
        self._render_resources(snapshot, process)
        self._render_models(models)
        suffix = ''
        scan = getattr(self.monitor, 'last_scan', {})
        if isinstance(scan, dict) and scan.get('truncated'):
            suffix = ' | 扫描未完整：' + str(scan.get('reason', '达到扫描限制'))
        if autostart_error:
            suffix += ' | 自启状态未知'
            self._append('开机自启查询失败：' + autostart_error)
        elif self.autostart.get('enabled') and not self.autostart.get('linger'):
            suffix += ' | 自启未就绪：用户未启用 linger'
        self.target_status.setText('{} 个模型{}'.format(len(models), suffix))
        self._policy()

    def _render_resources(self, snapshot, process):
        self._process_state(process, log=False)
        self.machine_label.setText('{} | {} | {}'.format(snapshot['host'], snapshot['architecture'], snapshot['kernel']))
        for key in ('cpu', 'memory', 'disk'):
            percent = snapshot.get(key + '_percent')
            valid = isinstance(percent, (int, float)) and math.isfinite(percent)
            self.metric_bars[key].setValue(int(max(0, min(100, percent)) * 10) if valid else 0)
            label = '{:.1f}%'.format(percent) if valid else '--'
            if key != 'cpu':
                label += '\n{} / {}'.format(_capacity(snapshot.get(key + '_used')), _capacity(snapshot.get(key + '_total')))
            self.metric_labels[key].setText(label)
        uptime = snapshot.get('uptime')
        elapsed = '--' if uptime is None else '{} 天 {:02d}:{:02d}'.format(int(uptime // 86400), int(uptime // 3600 % 24), int(uptime // 60 % 60))
        cores = '  '.join('{}:{:.0f}%'.format(index, value) for index, value in enumerate(snapshot.get('core_percents', [])) if value is not None)
        load = ' / '.join('--' if value is None else '{:.2f}'.format(value) for value in snapshot.get('load_average', []))
        self.details_label.setText('运行时间 {}    负载 {}\nCPU 核心 {}'.format(elapsed, load, cores or '--'))

    def _render_models(self, models):
        selected = self.selected()
        selected_path = selected['path'] if selected else None
        old_paths = [model['path'] for model in self.models]
        new_paths = [model['path'] for model in models]
        vertical = self.table.verticalScrollBar().value()
        horizontal = self.table.horizontalScrollBar().value()
        self._rendering = True
        self.models = list(models)
        self.table.setUpdatesEnabled(False)
        try:
            if old_paths != new_paths:
                self.table.clearContents()
                self.table.setRowCount(len(models))
                self.table.clearSelection()
                self.table.setCurrentItem(None)
            for row, model in enumerate(models):
                state = ('运行中' if model['owned'] else '外部运行中') if model['running'] else '已停止'
                values = ('', model['name'], state, ','.join(str(pid) for pid in model.get('pids', [])) or '--',
                          '{:.0f} KiB'.format(model['size'] / 1024), datetime.fromtimestamp(model['mtime']).strftime('%m-%d %H:%M:%S'), model['path'])
                for column, value in enumerate(values):
                    item = self.table.item(row, column)
                    if item is None:
                        item = QTableWidgetItem(value)
                        self.table.setItem(row, column, item)
                    elif item.text() != value:
                        item.setText(value)
                    if column and item.toolTip() != value:
                        item.setToolTip(value)
                    if column == 0:
                        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setToolTip('仅配置下次开机自启；全局最多选择一个模型')
                if old_paths != new_paths and model['path'] == selected_path:
                    self.table.selectRow(row)
        finally:
            self._rendering = False
            self.table.setUpdatesEnabled(True)
        self._paint_autostart()
        self.table.verticalScrollBar().setValue(vertical)
        self.table.horizontalScrollBar().setValue(horizontal)
        self._policy()

    def _reset_target(self):
        self._was_connected = False
        self._inventory_dirty = True
        self.running = False
        self._home = ''
        self.models.clear()
        self.autostart.clear()
        self.table.setRowCount(0)
        self.ssh_status.setText('SSH 未连接')
        self.process_status.setText('ELF 状态未知')
        self.target_status.setText('SSH 未连接')
        self.machine_label.setText('目标机资源')
        self.details_label.setText('--')
        for key, label in self.metric_labels.items():
            label.setText('--')
            self.metric_bars[key].setValue(0)

    def _tick(self):
        for _ in range(30):
            try:
                self._append(self._logs.get_nowait())
            except queue.Empty:
                break
        if self._closing:
            self._finish_close()
            return
        if not self.service.connected:
            if self._was_connected:
                self._reset_target()
        elif not self.worker.busy and not self.control_pending and not self._context_menu_open:
            if not self._was_connected or self._inventory_dirty:
                self.refresh(background=True)
            elif time.monotonic() >= self._next_refresh:
                self._poll_resources()
        self._policy()

    def _ready(self, disconnected=False):
        return not self.busy and not self._closed and (disconnected or self.service.connected)

    def _policy(self, *_):
        ready = self._ready()
        editable = self._ready(disconnected=True)
        for field in self._fields:
            field.setEnabled(editable)
        self.remember_credentials.setEnabled(bool(editable and self.credential_store.available))
        for name, button in self.buttons.items():
            enabled = ready
            if name == 'connect':
                enabled = editable and not self.service.connected
            elif name == 'browse':
                enabled = editable and not self.running
            elif name in ('upload', 'start'):
                enabled = ready and not self.running
            elif name == 'stop':
                enabled = ready and self.running
            button.setEnabled(bool(enabled))
        selected = self.selected()
        self.buttons['start_model'].setEnabled(bool(ready and selected and not selected['running'] and not self.running))
        self.buttons['stop_model'].setEnabled(bool(ready and selected and selected['running'] and selected['owned']))
        self.buttons['select_model'].setEnabled(bool(ready and selected))
        self.root_edit.setEnabled(ready)
        self.table.setEnabled(not self._closing)
        self.logReadAvailable.emit(bool(ready))

    def _copy_model_path(self):
        selected = self.selected()
        if selected:
            QApplication.clipboard().setText(selected['path'])

    def _model_context_menu(self, position):
        item = self.table.itemAt(position)
        if item is not None:
            self.table.selectRow(item.row())
        selected, ready = self.selected() if item is not None else None, self._ready()
        menu = QMenu(self)
        path = selected['path'] if selected else None

        def invoke(call):
            for row, model in enumerate(self.models):
                if model['path'] == path:
                    self.table.selectRow(row)
                    return call()
            return False

        icons = QStyle.StandardPixmap
        for label, call, enabled, icon in (
                ('选择模型', self.select_model, ready and selected, icons.SP_FileIcon),
                ('启动模型', self.start_model, ready and selected and not selected['running'] and not self.running, icons.SP_MediaPlay),
                ('停止模型', self.stop_model, ready and selected and selected['running'] and selected['owned'], icons.SP_MediaStop),
                ('取消开机自启' if selected and self.autostart.get('enabled') and self.autostart.get('elf_path') == path else '设为开机自启', self.toggle_autostart, ready and selected, icons.SP_ComputerIcon),
                ('删除模型', lambda: self.delete_model(path), ready and selected and not selected['running'], icons.SP_TrashIcon),
                ('复制远程路径', self._copy_model_path, selected, icons.SP_FileLinkIcon),
                ('刷新', None, ready, icons.SP_BrowserReload)):
            callback = (lambda call=call: invoke(call)) if call else self.refresh
            action = menu_command(menu, label, callback, icon, enabled=bool(enabled))
            if label == '删除模型':
                action.setToolTip('请先停止模型' if selected and selected['running'] else '删除模型及其整个远程文件夹')
        self._context_menu_open = True
        try:
            menu.exec(self.table.viewport().mapToGlobal(position))
        finally:
            self._context_menu_open = False
            result, self._deferred_render = self._deferred_render, None
            if result is not None:
                if self.busy:
                    self._inventory_dirty = True
                else:
                    self._render(result)

    def close_workspace(self):
        if self._closed:
            return True
        if not self._closing:
            self._closing = True
            self.control_pending = False
            self._queued_operation = None
            self.password_edit.clear()
            self.service.cancel()
            self._policy()
        self._finish_close()
        return self._closed

    def _finish_close(self):
        if self.worker.busy or self.control_pending or self._close_submitted or self._closed:
            return
        self._close_submitted = True

        def finished(_):
            self.payload_archive.close()
            self.worker.shutdown()
            self._closed = True
            self.timer.stop()

        def failed(error):
            self._close_submitted = False
            self._append('关闭 SSH 失败：' + str(error))

        if not self.worker.submit('关闭 SSH', self.service.close, finished, failed):
            self._close_submitted = False
