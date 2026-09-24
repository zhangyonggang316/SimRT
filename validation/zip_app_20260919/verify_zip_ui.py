"""Load a published ZIP through the real A2L parser and render its Qt menus."""
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'qt_xcp_host'), str(ROOT / 'qt_xcp_host/tests'),
                str(ROOT / 'x280_linux_target/python')]

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMenu
from qt_host.common import apply_theme
from qt_host.window import MainWindow
from pyxcp_host.demo import load_demo
from test_target import FakeCredentialStore, FakeDeployment, FakeMonitor, model
from test_window import Dialogs


def main():
    output = Path(__file__).resolve().parent
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    service, monitor, dialogs = FakeDeployment(), FakeMonitor(), Dialogs()
    window = MainWindow(dialogs=dialogs, target_service=service, target_monitor=monitor,
                        credential_store=FakeCredentialStore())
    target = window.target_tab
    target.timer.stop()
    settings = load_demo(ROOT / 'Demo_XCP_Qt')
    archive = settings.payload_dir.with_suffix('.zip')
    selected = []
    target.payloadSelected.connect(selected.append)
    window.show()
    window.resize(1320, 820)

    def settle(predicate):
        deadline = time.monotonic() + 10
        while not predicate():
            app.processEvents()
            assert time.monotonic() < deadline, 'Qt completion timed out'
            time.sleep(.005)
        app.processEvents()

    assert target.select_payload(archive)
    settle(lambda: not target.worker.busy and window._has_a2l)
    assert not dialogs.errors, dialogs.errors
    assert window.vm.measurements and window.vm.calibrations
    assert not service.calls
    extracted = Path(selected[-1]['directory'])
    assert extracted != settings.payload_dir
    assert len(list(extracted.iterdir())) == 3
    assert Path(window._loaded_a2l_path).parent == extracted
    window.grab().save(str(output / 'zip_loaded.png'))

    service.connected = True
    item = model('x280_rt_single')
    item['path'] = '/home/zh/MATLAB_ws/zip_ui_fixture/x280_rt_single.elf'
    monitor.models = [item]
    target._render((monitor.snapshot(), monitor.models, {}, '', service.status()))
    target.table.selectRow(0)
    report = dict(archive=str(archive), real_a2l_parser=True, remote_hardware=False,
                  measurements=len(window.vm.measurements), calibrations=len(window.vm.calibrations))

    def capture():
        menu = QApplication.activePopupWidget()
        if isinstance(menu, QMenu):
            report['menu_icons'] = {action.text(): not action.icon().isNull() for action in menu.actions()}
            menu.grab().save(str(output / 'model_context_menu.png'))
            menu.close()

    QTimer.singleShot(60, capture)
    target._model_context_menu(target.table.visualItemRect(target.table.item(0, 1)).center())
    assert report.get('menu_icons') and all(report['menu_icons'].values())
    window.close()
    settle(lambda: window._closed)
    assert not extracted.exists()
    report.update(passed=True, extracted_cache_removed_on_close=True)
    (output / 'zip_ui_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True))


if __name__ == '__main__':
    main()
