"""Observation-page commands with a file-derived XCP endpoint."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QStyle
from .common import command
from .state import ConnectionDraft


class ValueField:
    def __init__(self, value='', changed=None):
        self.value = str(value)
        self.changed = changed

    def get(self):
        return self.value

    def set(self, value):
        value = str(value)
        if value != self.value:
            self.value = value
            if self.changed:
                self.changed()


class ConnectionBar(QWidget):
    def __init__(self, parent, on_browse, on_load, on_connect, on_disconnect, on_endpoint_changed, on_a2l_changed):
        super().__init__(parent)
        self._policy = None
        self._connected = False
        self._metadata_error = '请先加载模型 ZIP 或 A2L。'
        self.a2l_var = ValueField(changed=on_a2l_changed)
        self.protocol_var = ValueField(changed=on_endpoint_changed)
        self.host_var = ValueField(changed=on_endpoint_changed)
        self.port_var = ValueField('0', on_endpoint_changed)
        self.timeout_var = ValueField('2.0')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.load_button = command('加载模型', on_browse, icon=QStyle.StandardPixmap.SP_DirOpenIcon)
        self.load_button.setToolTip('加载模型 ZIP 或 A2L')
        self.browse_button = self.load_button
        self.connect_button = command('上线', on_connect, role='primary', icon=QStyle.StandardPixmap.SP_DialogApplyButton)
        self.disconnect_button = command('下线', on_disconnect, role='danger', icon=QStyle.StandardPixmap.SP_DialogCancelButton)
        for button in (self.load_button, self.connect_button, self.disconnect_button):
            layout.addWidget(button)
        layout.addStretch(1)

    @property
    def endpoint_error(self):
        return self._metadata_error

    def set_endpoint(self, protocol='', host='', port=0, error=''):
        self.protocol_var.set(protocol)
        self.host_var.set(host)
        self.port_var.set(port)
        self._metadata_error = error
        self.connect_button.setToolTip(error or '{} {}:{}'.format(protocol, host, port))
        if self._policy is not None:
            self.set_policy(self._policy, self._connected)

    def draft(self):
        return ConnectionDraft(self.protocol_var.get(), self.host_var.get(), self.port_var.get(), self.timeout_var.get(), self.a2l_var.get())

    def set_policy(self, policy, connected=False):
        self._policy, self._connected = policy, connected
        self.load_button.setEnabled(policy.a2l_enabled and not connected)
        self.connect_button.setEnabled(policy.connect_enabled and not connected and not self._metadata_error)
        self.disconnect_button.setEnabled(policy.disconnect_enabled or connected and policy.endpoint_enabled)
