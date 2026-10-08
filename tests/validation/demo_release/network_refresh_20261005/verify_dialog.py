"""Exercise the Qt network dialog with its real worker and synthetic network data."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'qt_xcp_host'))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qt_host.branding import apply_branding
from qt_host.common import AsyncWorker, apply_theme
from qt_host.network import NetworkDialog


class NetworkFixture:
    fail_read = False

    def __init__(self):
        self.rows = [
            dict(name='lo', state='UNKNOWN', addresses=[dict(family='inet', address='127.0.0.1', prefix=8)]),
            dict(name='enp3s0', state='DOWN', addresses=[], gateway=''),
            dict(name='wlx7c3d09705041', state='UP', addresses=[dict(family='inet', address='192.168.193.195', prefix=24)], gateway='192.168.193.1'),
        ]

    def interfaces(self):
        if self.fail_read:
            raise RuntimeError('SSH read timed out')
        return dict(interfaces=deepcopy(self.rows))

    def configure(self, interface, address, prefix, gateway, password):
        row = next(row for row in self.rows if row['name'] == interface)
        row['addresses'] = [dict(family='inet', address=address, prefix=int(prefix))]
        row['gateway'] = gateway
        return dict(interface=interface, address=address + '/' + prefix, gateway=gateway,
                    confirmed=True, persistent=True)


app = QApplication([])
apply_branding(app)
apply_theme(app)
worker = AsyncWorker()
service = NetworkFixture()
dialog = NetworkDialog(service, lambda label, call, success, on_error: worker.submit(label, call, success, on_error))
dialog.resize(850, 590)
output = Path(__file__).resolve().parent


def settle():
    deadline = time.monotonic() + 5
    while dialog.pending or worker.busy:
        app.processEvents()
        QTest.qWait(10)
        assert time.monotonic() < deadline, 'Dialog worker did not complete'
    app.processEvents()


try:
    dialog.show()
    dialog.refresh()
    settle()
    dialog.table.selectRow(1)
    for address, fail_read, filename in (
        ('192.168.8.1', False, 'after_save.png'),
        ('192.168.9.1', True, 'after_read_failure.png'),
    ):
        service.fail_read = fail_read
        dialog.address.setText(address)
        with patch.object(dialog, '_confirm_apply', return_value=(True, 'fixture')):
            assert dialog.apply()
        assert dialog.pending and dialog.table.rowCount() == 3
        assert not dialog.close_button.isEnabled()
        settle()
        assert dialog.table.rowCount() == 3
        assert dialog.selected()['name'] == 'enp3s0'
        assert dialog.address.text() == address
        assert dialog.table.item(1, 2).text() == address + '/24'
        assert dialog.apply_button.isEnabled() and dialog.close_button.isEnabled()
        assert ('列表刷新失败' in dialog.status.text()) == fail_read
        QTest.qWait(100)
        assert dialog.grab().save(str(output / filename))
    (output / 'dialog_result.json').write_text(json.dumps(dict(
        passed=True, actual_async_worker=True, platform=app.platformName(),
        automatic_refresh=True, selection_preserved=True, confirmed_address_retained_on_read_error=True,
        physical_network_changes=False, fixture_only=True), indent=2), encoding='utf-8')
finally:
    dialog.close()
    assert worker.shutdown()
