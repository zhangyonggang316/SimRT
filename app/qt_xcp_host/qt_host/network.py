"""Network configuration dialog using the target workspace's serialized worker."""

from ipaddress import IPv4Interface

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QStyle, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout,
)

from pyxcp_host.services.network_configuration import validate_ipv4


class NetworkDialog(QDialog):
    addressApplied = Signal(str)
    def __init__(self, service, submit, parent=None):
        super().__init__(parent)
        self.service = service
        self.submit = submit
        self.pending = False
        self.interfaces = []
        self.setWindowTitle('实时机网络接口')
        self.resize(740, 560)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.status = QLabel('尚未读取')
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.refresh_button = QToolButton()
        self.refresh_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.refresh_button.setToolTip('刷新网络接口')
        self.refresh_button.setAccessibleName('刷新网络接口')
        self.refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['网口', '状态', 'IP 地址', '默认网关'])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 75)
        self.table.setColumnWidth(3, 135)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)
        form = QFormLayout()
        self.interface_label = QLabel('--')
        self.address = QLineEdit()
        self.mask = QLineEdit('255.255.255.0')
        self.gateway = QLineEdit()
        for title, field in (('网口', self.interface_label), ('IPv4', self.address),
                             ('子网掩码 / 前缀', self.mask), ('默认网关（可空）', self.gateway)):
            form.addRow(title, field)
        layout.addLayout(form)
        self.apply_button = QPushButton('应用并保存 IPv4')
        self.apply_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.apply_button.clicked.connect(self.apply)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.addButton(self.apply_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        self.close_button.setText('关闭')
        layout.addWidget(buttons)
        self._policy()

    def selected(self):
        row = self.table.currentRow()
        return self.interfaces[row] if 0 <= row < len(self.interfaces) else None

    def _selected(self, preferred_address=None):
        selected = self.selected()
        self.interface_label.setText(selected['name'] if selected else '--')
        addresses = [item for item in selected.get('addresses', []) if item['family'] == 'inet'] if selected else []
        ipv4 = next((item for item in addresses if item['address'] == preferred_address),
                    addresses[0] if addresses else None)
        self.address.setText(ipv4['address'] if ipv4 else '')
        self.mask.setText(str(ipv4['prefix']) if ipv4 else '255.255.255.0')
        self.gateway.setText(selected.get('gateway', '') if selected else '')
        self._policy()

    def _policy(self):
        editable = bool(not self.pending and self.selected() and self.selected()['name'] != 'lo')
        for widget in (self.address, self.mask, self.gateway, self.apply_button):
            widget.setEnabled(editable)
        self.table.setEnabled(not self.pending)
        self.refresh_button.setEnabled(not self.pending)
        self.close_button.setEnabled(not self.pending)

    def _run(self, label, operation, success):
        if self.pending:
            return False
        self.pending = True
        self.status.setText(label + '...')
        self._policy()

        def finished(result):
            self.pending = False
            success(result)
            self._policy()

        def failed(error):
            self.pending = False
            self.status.setText('操作失败：' + str(error).splitlines()[0][:180])
            QMessageBox.warning(self, '网络配置失败', str(error))
            self._policy()

        accepted = self.submit(label, operation, finished, on_error=failed)
        if not accepted:
            self.pending = False
            self.status.setText('SSH 正忙，请稍后重试')
            self._policy()
        return accepted

    def refresh(self):
        return self._run('读取网络接口', self.service.interfaces, self._render)

    def _render(self, result, preferred_address=None):
        previous = self.selected()
        self.interfaces = result['interfaces']
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.interfaces))
        self.table.clearSelection()
        self.table.setCurrentItem(None)
        selected_row = -1
        for row, interface in enumerate(self.interfaces):
            addresses = '\n'.join('{}/{}'.format(item['address'], item['prefix']) for item in interface['addresses']) or '--'
            values = (interface['name'], interface['state'], addresses, interface.get('gateway') or '--')
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value + ('\n当前 SSH 接口' if interface.get('management') else ''))
                self.table.setItem(row, column, item)
            if previous and previous['name'] == interface['name']:
                selected_row = row
        self.table.resizeRowsToContents()
        self.table.blockSignals(False)
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        self._selected(preferred_address)
        self.status.setText('{} 个网络接口'.format(len(self.interfaces)))

    def _confirm_apply(self, values):
        dialog = QDialog(self)
        dialog.setWindowTitle('确认网口 IPv4 配置')
        dialog.setMinimumWidth(430)
        layout = QVBoxLayout(dialog)
        label = QLabel('网口：{}\nIPv4：{}/{}\n默认网关：{}\n\n'
                       '配置在线生效，确认成功后自动保存，重启后继续使用。\n'
                       '当前 SSH 地址会保留，其他原有 IPv4 地址将被替换。\n'
                       '默认路由变更可能中断 SSH 和模型通信。\n'
                       'SSH 未确认成功时，45 秒后自动回滚。'.format(values['interface'],
                           values['address'], values['prefix'], values['gateway'] or '无'))
        label.setWordWrap(True)
        layout.addWidget(label)
        form = QFormLayout()
        password = QLineEdit()
        password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('管理员密码', password)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText('应用')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        secret = password.text() if accepted else ''
        password.clear()
        dialog.deleteLater()
        return accepted, secret

    def apply(self):
        selected = self.selected()
        if self.pending or selected is None:
            return False
        try:
            values = validate_ipv4(selected['name'], self.address.text(), self.mask.text(), self.gateway.text())
        except ValueError as error:
            QMessageBox.warning(self, 'IPv4 配置无效', str(error))
            return False
        accepted, password = self._confirm_apply(values)
        if not accepted:
            return False

        def configure_and_refresh():
            result = self.service.configure(values['interface'], values['address'],
                str(values['prefix']), values['gateway'], password=password)
            try:
                return result, self.service.interfaces(), ''
            except Exception as error:
                message = str(error).replace(password, '[redacted]') if password else str(error)
                return result, None, (message or type(error).__name__).splitlines()[0][:180]

        def configured(outcome):
            result, inventory, refresh_error = outcome
            retained = result.get('retained_management_addresses', [])
            applied = IPv4Interface(result['address'])
            if inventory is None:
                # Preserve the confirmed address even if the subsequent SSH read fails.
                interfaces = [dict(interface) for interface in self.interfaces]
                for interface in interfaces:
                    if interface['name'] == result['interface']:
                        interface['addresses'] = [dict(family='inet', address=str(applied.ip), prefix=applied.network.prefixlen)] + [
                            item for item in interface['addresses']
                            if item['family'] != 'inet' or '{}/{}'.format(item['address'], item['prefix']) in retained]
                        interface['gateway'] = result.get('gateway', values['gateway'])
                inventory = dict(interfaces=interfaces)
            self._render(inventory, preferred_address=str(applied.ip))
            self.status.setText('{} 已应用并保存 {}{}'.format(result['interface'], result['address'],
                '；保留 SSH 地址 ' + ', '.join(retained) if retained else '') +
                ('；列表刷新失败：' + refresh_error if refresh_error else ''))
            if retained:
                self.addressApplied.emit(str(applied.ip))

        return self._run('应用网口 IPv4', configure_and_refresh, configured)

    def reject(self):
        if not self.pending:
            super().reject()

    def closeEvent(self, event):
        if self.pending:
            event.ignore()
        else:
            super().closeEvent(event)
