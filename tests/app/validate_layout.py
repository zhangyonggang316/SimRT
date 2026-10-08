"""Verify relocated APP imports and Demo loading without contacting hardware."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'app/qt_xcp_host'), str(ROOT / 'shared/python'),
               str(ROOT / 'tests/app/ui')]
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pyxcp_host.demo import load_demo
from pyxcp_host.services.payload_archive import PayloadArchive
from qt_host.common import apply_theme
from qt_host.window import MainWindow
from test_target import FakeCredentialStore


def main():
    output = ROOT / 'tests/app/layout_results'
    output.mkdir(exist_ok=True)
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    records = []
    for directory in (ROOT / 'demos/Demo_XCP_Qt', output / 'portable_package'):
        settings = load_demo(directory)
        loader = PayloadArchive()
        try:
            payload = loader.load(settings.payload_archive)
            record = {'demo': str(directory.relative_to(ROOT)), 'model': payload['model'],
                      'archive_sha256': hashlib.sha256(settings.payload_archive.read_bytes()).hexdigest()}
        finally:
            loader.close()
        window = MainWindow(credential_store=FakeCredentialStore())
        try:
            window.apply_demo(settings)
            window.show()
            deadline = time.monotonic() + 20
            while not window._has_a2l:
                app.processEvents()
                QTest.qWait(20)
                if time.monotonic() > deadline:
                    raise AssertionError(window.diagnostics_tab.log_text_value())
            record.update(measurements=len(window.vm.measurements),
                          calibrations=len(window.vm.calibrations),
                          xcp_connected=window.vm.connected,
                          ssh_connected=window.target_tab.service.connected)
            assert record['measurements'] == 6 and record['calibrations'] == 12, record
            assert not record['xcp_connected'] and not record['ssh_connected'], record
            records.append(record)
            window.grab().save(str(output / ('source_demo.png' if len(records) == 1 else 'portable_demo.png')))
        finally:
            window.close()
            app.processEvents()
    report = {'passed': True, 'hardware_test': False, 'demos': records}
    (output / 'layout_import.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
