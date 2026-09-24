"""Qt UI and command lifecycle regressions, without network access."""
import csv
import json
import math
import os
import runpy
import sys
import tempfile
import time
import unittest
from collections import deque
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qt_host.common import apply_theme
from qt_host.window import MainWindow
from qt_host.state import HostState
from qt_host.native import NativeBuffer
from pyxcp_host.demo import load_demo
from test_target import FakeCredentialStore, FakeDeployment, FakeMonitor, make_payload


class EntryPointTests(unittest.TestCase):
    def _launch(self, arguments):
        workspace = Path(__file__).resolve().parents[2]
        entry = workspace / 'qt_xcp_host/main.py'
        app = Mock()
        app.exec.return_value = 0
        with patch.object(sys, 'path', list(sys.path)), \
                patch('PySide6.QtWidgets.QApplication') as application, \
                patch('qt_host.common.apply_theme'), \
                patch('qt_host.window.MainWindow') as window, \
                patch('pyxcp_host.demo.load_demo') as preset:
            application.instance.return_value = app
            namespace = runpy.run_path(str(entry), run_name='qt_entry_test')
            self.assertEqual(namespace['main'](arguments), 0)
            window.return_value.show.assert_called_once_with()
            app.exec.assert_called_once_with()
            return window, preset

    def test_qt_entry_starts_the_current_app(self):
        window, preset = self._launch([])
        preset.assert_not_called()
        window.return_value.apply_demo.assert_not_called()

    def test_qt_entry_accepts_demo_directory_aliases(self):
        for argument in ('--demo', '--demo-dir'):
            with self.subTest(argument=argument):
                window, preset = self._launch([argument, 'current delivery'])
                preset.assert_called_once_with('current delivery')
                window.return_value.apply_demo.assert_called_once_with(preset.return_value)


class DeferredExecutor:
    def __init__(self):
        self.pending = deque()

    def submit(self, function, *args, **kwargs):
        future = Future()
        self.pending.append((future, function, args, kwargs))
        return future

    def complete(self):
        future, function, args, kwargs = self.pending.popleft()
        if future.set_running_or_notify_cancel():
            try:
                future.set_result(function(*args, **kwargs))
            except Exception as error:
                future.set_exception(error)


class Dialogs:
    def __init__(self):
        self.errors = []
        self.confirmed = True
        self.path = ''
        self.value = '2.5'

    def warning(self, title, text):
        self.errors.append((title, text))

    error = warning

    def confirm(self, *args):
        return self.confirmed

    def open_a2l(self):
        return getattr(self, 'a2l_path', '')

    def save_csv(self):
        return self.path

    save_log = save_csv

    def edit_value(self, name, initial):
        return self.value


class ViewModel:
    def __init__(self):
        self.connected = self.daq_active = False
        self.calls = []
        self.diagnostics = {}
        self.close_error = self.stop_error = self.start_error = self.disconnect_error = False
        self.measurements = [SimpleNamespace(name=name, address=4096 + i * 8, data_type='FLOAT64_IEEE') for i, name in enumerate(('MeasuredOutput', 'MeasuredSine'))]
        self.calibrations = [SimpleNamespace(name='CalGain', address=8192, data_type='FLOAT64_IEEE')]
        self.samples = []
        self.gain = 1.0

    def set_log_sink(self, sink):
        self.log = sink

    def load_a2l(self, path):
        self.calls.append('load')
        return SimpleNamespace(path=path, measurements=self.measurements, calibrations=self.calibrations,
                               declared_ports={'UDP': 17725}, declared_hosts={'UDP': '127.0.0.1'})

    def connect(self, **kwargs):
        self.calls.append('connect')
        self.connected = True

    def disconnect(self):
        self.calls.append('disconnect')
        if self.disconnect_error:
            raise RuntimeError('restore failed')
        self.connected = self.daq_active = False

    def close(self):
        self.calls.append('close')
        if self.close_error:
            raise RuntimeError('restore failed')
        self.disconnect()

    def start_daq(self, names):
        self.calls.append('start')
        self.daq_active = True
        if self.start_error:
            raise RuntimeError('start uncertain')
        return {'period_seconds': .001, 'event_channel': 0, 'signals': names}

    def stop_daq(self):
        self.calls.append('stop')
        if self.stop_error:
            raise RuntimeError('stop uncertain')
        self.daq_active = False

    def drain_daq(self, max_samples=5000):
        result, self.samples = self.samples[:max_samples], self.samples[max_samples:]
        return result

    def poll_measurements(self, names):
        self.calls.append('poll')
        return {name: 1.0 for name in names}

    def write_calibrations(self, changes):
        self.calls.append('write')
        self.gain = changes['CalGain']
        return dict(changes)

    def read_calibrations(self, names):
        self.calls.append('read')
        return {name: self.gain for name in names}

    def restore_calibrations(self):
        self.calls.append('restore')
        self.gain = 1.0
        return {'CalGain': self.gain}


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'sample.a2l'
        self.path.write_text('fixture', encoding='ascii')
        self.vm, self.executor, self.dialogs = ViewModel(), DeferredExecutor(), Dialogs()
        self.dialogs.a2l_path = str(self.path)
        self.service, self.monitor = FakeDeployment(), FakeMonitor()
        self.window = MainWindow(self.vm, self.executor, self.dialogs, self.service, self.monitor,
                                 credential_store=FakeCredentialStore())
        self.window.target_tab.timer.stop()
        self.window.connection_bar.a2l_var.set(str(self.path))

    def spin(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.app.processEvents()
            if time.monotonic() > deadline:
                self.fail('Qt completion timeout')
            QTest.qWait(2)

    def complete(self):
        self.executor.complete()
        self.window._drain_ui_queue()

    def connect(self):
        self.window.connection_bar.load_button.click()
        self.complete()
        self.window.connection_bar.connect_button.click()
        self.complete()
        self.window.observation_tab._set_selected(('MeasuredOutput', 'MeasuredSine'), True)
        self.vm.calls.clear()

    def start(self):
        self.window.observation_tab.start_button.click()
        self.complete()
        self.assertEqual(self.window._state, HostState.ACQUIRING)

    def tearDown(self):
        self.vm.close_error = self.vm.disconnect_error = self.vm.stop_error = False
        self.window.close()
        while self.executor.pending:
            self.complete()
        self.spin(lambda: self.window._closed)
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_real_qt_widgets_and_native_core_without_tk(self):
        self.assertNotIn('tkinter', sys.modules)
        self.assertIsInstance(self.window.observation_tab.buffer, NativeBuffer)
        self.assertEqual([self.window.notebook.tabText(i) for i in range(3)], ['实时机', '观测', '标定'])
        self.assertEqual(self.window.status_var.get(), '未加载 A2L')

    def test_load_demo_never_connects(self):
        demo = Path(self.temp.name) / 'demo'
        demo.mkdir()
        make_payload(demo / 'payload')
        (demo / 'demo.json').write_text(json.dumps(dict(version=1, host='192.0.2.5', username='tester',
            manifest='payload/model.xcp-manifest.json')), encoding='utf-8')
        settings = load_demo(demo)
        self.window.apply_demo(settings)
        self.complete()
        self.assertEqual(self.vm.calls, ['load'])
        self.assertFalse(self.service.connected)
        self.assertEqual(self.window.connection_bar.protocol_var.get(), 'UDP')
        self.assertEqual(self.window.connection_bar.port_var.get(), '17725')
        self.assertEqual(self.window._state, HostState.LOADED)

    def test_local_payload_loads_matching_a2l_without_network_connection(self):
        directory = make_payload(Path(self.temp.name) / 'payload')
        self.assertTrue(self.window.target_tab.select_payload(directory))
        self.complete()
        self.assertEqual(self.window.connection_bar.a2l_var.get(), str(directory / 'model.a2l'))
        self.assertEqual(self.window.connection_bar.host_var.get(), '192.0.2.5')
        self.assertEqual(self.window.connection_bar.protocol_var.get(), 'UDP')
        self.assertEqual(self.window.connection_bar.port_var.get(), '17725')
        self.assertEqual(self.vm.calls, ['load'])
        self.assertFalse(self.vm.connected)
        self.assertFalse(self.service.connected)

    def test_local_payload_selection_does_not_replace_connected_xcp_catalog(self):
        self.connect()
        previous = self.window.connection_bar.a2l_var.get()
        directory = make_payload(Path(self.temp.name) / 'payload')
        self.assertTrue(self.window.target_tab.select_payload(directory))
        self.assertEqual(self.window.connection_bar.a2l_var.get(), previous)
        self.assertTrue(self.vm.connected)
        self.assertEqual(self.vm.calls, [])
        self.assertFalse(self.service.connected)
        self.assertEqual(self.window._state, HostState.CONNECTED)

    def test_connection_commands_use_loaded_protocol_and_port(self):
        bar = self.window.connection_bar
        self.window._load_a2l()
        self.complete()
        self.assertEqual(bar.protocol_var.get(), 'UDP')
        self.assertEqual(bar.port_var.get(), '17725')
        self.assertFalse(hasattr(bar, 'port_spin'))
        self.assertFalse(hasattr(bar, 'buttons'))
        self.assertIs(bar.parentWidget(), self.window.observation_tab)

    def test_edit_a2l_invalidates_loaded_catalog(self):
        self.window._load_a2l()
        self.complete()
        self.window.connection_bar.a2l_var.set(str(self.path) + '.other')
        self.assertEqual(self.window._state, HostState.EMPTY)
        self.assertFalse(self.window.connection_bar.connect_button.isEnabled())
        self.assertFalse(self.window.observation_tab._items)

    def test_click_stop_returns_to_connected_state(self):
        self.connect()
        self.start()
        self.window.observation_tab.stop_button.click()
        self.complete()
        self.assertEqual(self.window._state, HostState.CONNECTED)
        self.assertEqual(self.vm.calls, ['start', 'stop'])

    def test_pending_start_then_stop_cannot_restart_observation(self):
        self.connect()
        self.window._start_observation()
        self.window._stop_observation()
        self.complete()
        self.assertFalse(self.window._acquiring)
        self.complete()
        self.assertEqual(self.window._state, HostState.CONNECTED)

    def test_uncertain_stop_retains_owner_and_retry(self):
        self.connect()
        self.start()
        self.vm.stop_error = True
        self.window.observation_tab.stop_button.click()
        self.complete()
        self.assertEqual(self.window._state, HostState.ACQUIRING)
        self.assertTrue(self.window.observation_tab.stop_button.isEnabled())

    def test_uncertain_start_retains_stop_entry(self):
        self.connect()
        self.vm.start_error = True
        self.window._start_observation()
        self.complete()
        self.assertTrue(self.window._daq_mode)
        self.assertTrue(self.window.observation_tab.stop_button.isEnabled())

    def test_daq_1ms_is_read_only_and_calibration_does_not_stop_daq(self):
        self.connect()
        self.start()
        observation, calibration = self.window.observation_tab, self.window.calibration_tab
        self.assertEqual(observation.daq_period.text(), '0.001')
        self.assertTrue(observation.daq_period.isReadOnly())
        calibration._edit_name('CalGain')
        calibration.write_button.click()
        self.assertFalse(calibration.write_button.isEnabled())
        self.complete()
        self.assertEqual(self.vm.calls, ['start', 'write', 'read'])
        self.assertEqual(self.vm.gain, 2.5)
        self.assertTrue(self.window._acquiring)
        self.assertEqual(calibration.pending_changes(), {})

    def test_calibration_cancel_never_writes(self):
        self.connect()
        self.window.calibration_tab._edit_name('CalGain')
        self.dialogs.confirmed = False
        self.window.calibration_tab.write_button.click()
        self.assertNotIn('write', self.vm.calls)
        self.assertFalse(self.executor.pending)

    def test_invalid_calibration_value_is_not_committed(self):
        self.connect()
        self.dialogs.value = 'nan'
        self.window.calibration_tab._edit_name('CalGain')
        self.assertEqual(self.window.calibration_tab.pending_changes(), {})
        self.assertTrue(self.dialogs.errors)

    def test_close_failure_keeps_window_and_connection(self):
        self.connect()
        self.vm.close_error = True
        self.window.close()
        self.complete()
        self.assertFalse(self.window._closed)
        self.assertFalse(self.window._closing)
        self.assertTrue(self.vm.connected)
        self.assertFalse(self.service.calls)

    def test_model_stop_waits_for_disconnect_and_freezes_xcp(self):
        self.connect()
        events = []
        def stop():
            events.append(self.vm.connected)
            return True
        self.window._with_xcp_disconnected(stop)
        self.assertFalse(events)
        self.assertFalse(self.window.connection_bar.connect_button.isEnabled())
        self.complete()
        self.assertEqual(events, [False])
        self.assertFalse(self.window._remote_stop_pending)

    def test_restore_failure_blocks_model_stop(self):
        self.connect()
        self.vm.disconnect_error = True
        action, failure = [], []
        self.window._with_xcp_disconnected(lambda: action.append(1), lambda: failure.append(1))
        self.complete()
        self.assertEqual(action, [])
        self.assertEqual(failure, [1])
        self.assertFalse(self.window._remote_stop_pending)
        self.assertTrue(self.vm.connected)

    def test_batch_raw_capacity_plot_envelope_and_cursor(self):
        self.connect()
        observation = self.window.observation_tab
        samples = [SimpleNamespace(timestamp_seconds=i * .001, values={'MeasuredOutput': math.sin(i * .01)}) for i in range(10000)]
        with patch.object(observation, '_refresh_samples', wraps=observation._refresh_samples) as refresh:
            observation.append_samples(samples)
            self.assertEqual(refresh.call_count, 1)
        self.assertEqual(len(observation.buffer.snapshot()['MeasuredOutput']), 10000)
        self.assertLess(len(observation.chart.lines['MeasuredOutput'].get_xdata()), 10000)
        observation.chart.set_display_mode('points')
        self.assertLessEqual(len(observation.chart.lines['MeasuredOutput'].get_xdata()), 4000)
        observation.chart.follow_var.set(False)
        observation.chart.axes[0].set_xlim(.010, .020)
        observation.chart._flush_draw()
        self.assertEqual(list(observation.chart.lines['MeasuredOutput'].get_xdata()),
                         [i * .001 for i in range(9, 22)])
        observation.chart.follow_var.set(True)
        observation.chart._follow_changed()
        self.assertEqual(observation.chart.lines['MeasuredOutput'].get_xdata()[0], 0)
        self.assertEqual(observation.chart.lines['MeasuredOutput'].get_xdata()[-1], 9.999)
        observation.chart.set_cursors_enabled(True)
        observation.chart.set_cursors(.0005, .0015)
        self.assertIn('*', observation.cursor_tree.item(0, 1).text())
        observation.details.setCurrentIndex(0)
        observation._render_cursors()
        self.assertEqual(observation.details.currentIndex(), 0)
        observation.chart.set_layout('2 x 2')
        observation.chart.set_signal_display('MeasuredOutput', subplot=3)
        self.assertEqual(observation.chart.lines['MeasuredOutput'].axes, observation.chart.axes[3])

    def test_csv_preserves_raw_samples_not_decimated_points(self):
        self.connect()
        self.dialogs.path = str(Path(self.temp.name) / 'samples.csv')
        buffer = self.window.observation_tab.buffer
        buffer.append_batch((i * .001, {'MeasuredOutput': i}) for i in range(10000))
        with patch.object(buffer, 'snapshot_arrays', wraps=buffer.snapshot_arrays) as snapshot:
            self.window._export_csv()
            snapshot.assert_not_called()
            self.complete()
            snapshot.assert_called_once()
        with open(self.dialogs.path, encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 10000)
        self.assertEqual(float(rows[-1]['MeasuredOutput']), 9999)
        self.assertEqual(float(rows[-1]['time_s']), 9.999)

    def test_app_default_retains_million_raw_points_and_bounds_both_plot_modes(self):
        observation = self.window.observation_tab
        self.assertEqual(observation.buffer.max_points, 1000000)
        observation.set_measurements(self.vm.measurements)
        self.assertEqual(observation.buffer.max_points, 1000000)
        observation._selection_enabled = True
        observation._set_selected(['MeasuredOutput'], True)
        for first in range(0, 1000000, 10000):
            observation.buffer.append_batch((i * .001, {'MeasuredOutput': i})
                                            for i in range(first, first + 10000))
        started = time.perf_counter()
        for mode in ('line', 'points'):
            observation.chart.set_display_mode(mode)
            line = observation.chart.lines['MeasuredOutput']
            self.assertLessEqual(len(line.get_xdata()), 4000)
            self.assertEqual(line.get_ydata()[0], 0)
            self.assertEqual(line.get_ydata()[-1], 999999)
        self.assertLess(time.perf_counter() - started, 5)
        observation.append_values(1000, {'MeasuredOutput': 1000000})
        self.assertEqual(observation.buffer.stats()['MeasuredOutput'], (1000000, 1, 1000000, 1000000))
        observation.chart.follow_var.set(False)
        observation.chart.axes[0].set_xlim(500, 500.010)
        observation.chart._flush_draw()
        self.assertEqual(list(observation.chart.lines['MeasuredOutput'].get_ydata()),
                         list(range(499999, 500012)))

    def test_auto_endpoint_missing_ambiguous_and_ssh_fallback(self):
        self.window.connection_bar.load_button.click()
        self.complete()
        catalog = self.window._catalog_endpoint
        bar = self.window.connection_bar
        catalog.declared_ports = {}
        self.window._resolve_file_endpoint()
        self.assertTrue(bar.endpoint_error)
        self.assertFalse(bar.connect_button.isEnabled())
        catalog.declared_ports = {'TCP': 1234, 'UDP': 5678}
        self.window._resolve_file_endpoint()
        self.assertTrue(bar.endpoint_error)
        catalog.declared_ports = {'TCP': 1234}
        catalog.declared_hosts = {}
        self.window.target_tab.host_edit.setText('192.0.2.10')
        self.window._resolve_file_endpoint()
        self.assertEqual((bar.protocol_var.get(), bar.port_var.get(), bar.host_var.get()), ('TCP', '1234', '192.0.2.10'))
        self.assertFalse(bar.endpoint_error)
        self.assertTrue(bar.connect_button.isEnabled())
        self.window.target_tab.host_edit.setText('192.0.2.11')
        self.assertEqual(bar.host_var.get(), '192.0.2.11')

    def test_payload_endpoint_conflict_blocks_online(self):
        self.window.connection_bar.load_button.click()
        self.complete()
        self.window._payload_endpoint = dict(a2l=self.window._loaded_a2l_path, protocol='TCP', port=17725, host='192.0.2.10')
        self.window._resolve_file_endpoint()
        self.assertTrue(self.window.connection_bar.endpoint_error)
        self.assertFalse(self.window.connection_bar.connect_button.isEnabled())
        self.window._connect()
        self.assertNotIn('connect', self.vm.calls)

    def test_sdi_export_uses_worker_snapshot_and_preserves_signal_series(self):
        buffer = self.window.observation_tab.buffer
        buffer.append_batch([(0, {'a': 1}), (.001, {'a': 2, 'b': 5}), (.002, {'b': 6})])
        with patch('pyxcp_host.services.sdi_export.find_matlab_executable', return_value=Path('matlab.exe')), \
                patch('qt_host.window.QFileDialog.getExistingDirectory', return_value=self.temp.name), \
                patch('pyxcp_host.services.sdi_export.launch_sdi') as launch, \
                patch.object(buffer, 'snapshot_arrays', wraps=buffer.snapshot_arrays) as snapshot:
            self.window._open_native_sdi()
            snapshot.assert_not_called()
            launch.assert_not_called()
            self.complete()
            snapshot.assert_called_once()
            launch.assert_called_once()
            script = launch.call_args.args[0]
            capture = json.loads((script.parent / 'capture.json').read_text(encoding='utf-8'))
        self.assertEqual(capture['signals'], [
            {'name': 'a', 'time': [0, .001], 'values': [1, 2]},
            {'name': 'b', 'time': [.001, .002], 'values': [5, 6]},
        ])

    def test_csv_asynchronous_signals_and_duplicate_times_keep_values(self):
        buffer = self.window.observation_tab.buffer
        buffer.append_batch([(0, {'A': 1}), (0, {'A': 2, 'B': 3}), (.001, {'B': 4})])
        rows = buffer.rows()
        self.assertEqual([values['A'] for _, values in rows if 'A' in values], [1, 2])
        self.assertEqual([values['B'] for _, values in rows if 'B' in values], [3, 4])

    def test_no_source_encoding_replacement_characters(self):
        for path in (Path(__file__).parents[1] / 'qt_host').glob('*.py'):
            self.assertNotIn('\ufffd', path.read_text(encoding='utf-8'), path.name)


if __name__ == '__main__':
    unittest.main()
