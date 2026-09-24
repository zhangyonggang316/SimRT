"""Verify ZIP-only demo startup using the real A2L parser and Qt event loop."""
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'qt_xcp_host'), str(ROOT / 'qt_xcp_host/tests'), str(ROOT / 'x280_linux_target/python')]
from PySide6.QtWidgets import QApplication
from qt_host.common import apply_theme
from qt_host.window import MainWindow
from pyxcp_host.demo import load_demo
from test_target import FakeCredentialStore, FakeDeployment, FakeMonitor
from test_window import Dialogs


def main():
    output = Path(__file__).resolve().parent
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    service, dialogs = FakeDeployment(), Dialogs()
    window = MainWindow(dialogs=dialogs, target_service=service, target_monitor=FakeMonitor(), credential_store=FakeCredentialStore())
    window.target_tab.timer.stop()
    settings = load_demo(ROOT / 'Demo_XCP_Qt')
    assert settings.payload_archive.is_file()
    assert settings.a2l_path is None and settings.payload_dir is None
    assert not settings.payload_archive.with_suffix('').exists()
    window.apply_demo(settings)
    window.resize(1320, 820)
    window.show()

    def settle(predicate):
        deadline = time.monotonic() + 15
        while not predicate():
            app.processEvents()
            assert time.monotonic() < deadline, 'Qt completion timed out'
            time.sleep(.005)
        app.processEvents()

    settle(lambda: not window.target_tab.worker.busy and window._has_a2l)
    assert not dialogs.errors, dialogs.errors
    assert not service.calls
    extracted = window._loaded_a2l_path.parent
    assert len(list(extracted.iterdir())) == 3
    assert window.vm.measurements and window.vm.calibrations
    bar = window.connection_bar
    assert not bar.endpoint_error
    assert bar.protocol_var.get() == 'UDP' and bar.port_var.get() == '17725'
    assert bar.connect_button.isEnabled() and not bar.disconnect_button.isEnabled()
    window.notebook.setCurrentWidget(window.observation_tab)
    app.processEvents()
    window.grab().save(str(output / 'zip_loaded.png'))
    report = dict(passed=True, archive=str(settings.payload_archive), real_a2l_parser=True,
                  measurements=len(window.vm.measurements), calibrations=len(window.vm.calibrations),
                  protocol=bar.protocol_var.get(), port=bar.port_var.get(), host=bar.host_var.get(),
                  automatic_demo_loading=True, remote_hardware=False)
    window.close()
    settle(lambda: window._closed)
    assert not extracted.exists()
    report['extracted_cache_removed_on_close'] = True
    (output / 'zip_ui_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
