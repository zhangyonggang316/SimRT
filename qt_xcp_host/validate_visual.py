"""Render deterministic Qt test fixtures, not remote hardware observations."""
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
project = Path(__file__).resolve().parent
sys.path[:0] = [str(project), str(project / 'tests')]
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from PIL import Image, ImageStat
from qt_host.common import apply_theme
from qt_host.window import MainWindow
from qt_host.state import HostState
from test_window import ViewModel, Dialogs
from test_target import FakeCredentialStore, FakeDeployment, FakeMonitor, model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    vm, service, monitor = ViewModel(), FakeDeployment(), FakeMonitor()
    vm.connected = service.connected = True
    monitor.models = [model('x280_rt_single', True, True)]
    window = MainWindow(vm, dialogs=Dialogs(), target_service=service, target_monitor=monitor,
                        credential_store=FakeCredentialStore())
    window.target_tab.timer.stop()
    window.target_tab.host_edit.setText('192.168.219.86')
    window.target_tab.user_edit.setText('zh')
    window.target_tab.refresh()
    deadline = time.monotonic() + 3
    while window.target_tab.worker.busy:
        app.processEvents()
        QTest.qWait(5)
        assert time.monotonic() < deadline
    observation = window.observation_tab
    for item in vm.measurements:
        item.model_path = ('x280_rt_single', 'Controller', 'Signals')
    for item in vm.calibrations:
        item.model_path = ('x280_rt_single', 'Controller', 'Gains')
    observation.set_measurements(vm.measurements)
    window._has_a2l = True
    window._set_state(HostState.CONNECTED)
    observation._set_selected([item.name for item in vm.measurements], True)
    observation.set_daq_metadata({'period_seconds': .001})
    observation.append_samples([SimpleNamespace(timestamp_seconds=i * .001, values={
        'MeasuredOutput': math.sin(i * .004) * 1.5,
        'MeasuredSine': math.cos(i * .004)}) for i in range(10000)])
    observation.chart.set_cursors_enabled(True)
    observation.chart.set_cursors(2.5, 7.5)
    observation.tree.select_item(observation.tree.leaves['MeasuredOutput'])
    window.calibration_tab.set_calibrations(vm.calibrations)
    window.calibration_tab.update_current_values({'CalGain': 1.5})
    window._has_a2l = True
    window._set_state(HostState.CONNECTED)
    window.diagnostics_tab.append_log('Deterministic UI fixture; no remote connection was made.')
    window.show()
    results = []
    for width, height in ((1320, 820), (1000, 660)):
        window.resize(width, height)
        for index, name, section in ((0, 'machine', 0), (0, 'diagnostics', 1),
                                     (1, 'observation', 0), (2, 'calibration', 0)):
            window.notebook.setCurrentIndex(index)
            window.machine_notebook.setCurrentIndex(section)
            QTest.qWait(120)
            app.processEvents()
            actual = [window.width(), window.height()]
            path = output / f'{name}_{width}x{height}.png'
            window.grab().save(str(path))
            outside = []
            clipped_text = []
            for button in window.findChildren(QPushButton):
                if not button.isVisible() or not button.text():
                    continue
                # Scroll-area descendants may be intentionally outside the viewport.
                parent = button.parentWidget()
                point = button.mapTo(parent, QPoint(0, 0))
                if point.x() < 0 or point.y() < 0 or point.x() + button.width() > parent.width() + 2:
                    outside.append(button.text())
                icon = button.iconSize().width() + 4 if not button.icon().isNull() else 0
                required = button.fontMetrics().horizontalAdvance(button.text()) + icon + 8
                if button.width() < required:
                    clipped_text.append(button.text())
            results.append(dict(page=name, requested=[width, height], actual=actual,
                out_of_parent=outside, clipped_button_text=clipped_text, screenshot=path.name))
    chart = output / 'chart_native_10000.png'
    observation.chart.save_png(chart)
    with Image.open(chart).convert('RGB') as pixels:
        variance = sum(ImageStat.Stat(pixels).var)
        assert variance > 100, variance
    report = dict(kind='deterministic_qt_fixture', remote_hardware=False, platform=app.platformName(),
                  device_pixel_ratio=window.devicePixelRatioF(), screenshots=results,
                  raw_points_per_signal=10000, chart_rgb_variance=variance,
                  passed=all(row['actual'] == row['requested'] and not row['out_of_parent'] and not row['clipped_button_text'] for row in results))
    (output / 'visual_report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    window.close()
    deadline = time.monotonic() + 3
    while not window._closed:
        app.processEvents()
        QTest.qWait(5)
        assert time.monotonic() < deadline
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
