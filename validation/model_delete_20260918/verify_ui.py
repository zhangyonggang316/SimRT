"""Render the deletion menu and cancel the real confirmation using local fixtures."""

import json
import os
from pathlib import Path
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'qt_xcp_host'), str(ROOT / 'qt_xcp_host' / 'tests'),
                str(ROOT / 'x280_linux_target' / 'python')]

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
from qt_host.common import apply_theme
from qt_host.target import TargetWorkspace
from test_target import FakeCredentialStore, FakeDeployment, FakeMonitor, model


def main():
    output = Path(__file__).resolve().parent
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    service, monitor = FakeDeployment(), FakeMonitor()
    service.connected = True
    selected = model('x280_rt_single')
    selected['path'] = '/home/zh/MATLAB_ws/manual_demo_20260918_001500/x280_rt_single.elf'
    monitor.models = [selected]
    widget = TargetWorkspace(service=service, monitor=monitor, credential_store=FakeCredentialStore())
    widget.timer.stop()
    widget.host_edit.setText('192.168.219.86')
    widget.user_edit.setText('zh')
    widget._render((monitor.snapshot(), monitor.models, {}, '', service.status()))
    widget.resize(1320, 740)
    widget.show()
    widget.table.selectRow(0)
    app.processEvents()
    report = dict(remote_hardware=False, screenshots=[], menu_enabled=False, cancel_default=False)

    def menu_opened():
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu):
            report['menu_enabled'] = next(action for action in popup.actions()
                                          if action.text() == '删除模型').isEnabled()
            popup.grab().save(str(output / 'delete_menu.png'))
            report['screenshots'].append('delete_menu.png')
            popup.close()

    QTimer.singleShot(40, menu_opened)
    widget._model_context_menu(widget.table.visualItemRect(widget.table.item(0, 1)).center())

    def dialog_opened():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, QMessageBox):
            report['cancel_default'] = dialog.defaultButton().text() == '取消'
            report['directory_shown'] = selected['path'].rsplit('/', 1)[0] in dialog.informativeText()
            dialog.grab().save(str(output / 'delete_confirmation.png'))
            report['screenshots'].append('delete_confirmation.png')
            dialog.defaultButton().click()

    QTimer.singleShot(40, dialog_opened)
    assert widget.delete_model() is False
    assert not any(call[0] == 'delete_model' for call in service.calls)
    assert not widget.control_pending
    assert report['menu_enabled'] and report['cancel_default'] and report['directory_shown']
    report['passed'] = True
    (output / 'ui_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    widget.close_workspace()
    while not widget._closed:
        app.processEvents()
    widget.worker.shutdown()
    widget.close()
    print(json.dumps(report))


if __name__ == '__main__':
    main()
