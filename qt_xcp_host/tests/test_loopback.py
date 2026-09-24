"""Real Qt buttons through pyxcp TCP/UDP sockets and the C++ history core."""
import importlib.util
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qt_host.window import MainWindow
from qt_host.state import HostState
from test_window import Dialogs
from test_target import FakeCredentialStore, FakeDeployment, FakeMonitor

fixture_path = Path(__file__).parents[1] / 'service_tests/test_daq_transport.py'
spec = importlib.util.spec_from_file_location('_baseline_daq_slave', fixture_path)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)

A2L = '''/begin PROJECT D "" /begin MODULE D ""
 /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
 /begin RECORD_LAYOUT R FNC_VALUES 1 FLOAT32_IEEE COLUMN_DIR DIRECT /end RECORD_LAYOUT
 /begin MEASUREMENT Output "" FLOAT32_IEEE NO_COMPU_METHOD 0 0 -100 100 ECU_ADDRESS 0x10 /end MEASUREMENT
 /begin CHARACTERISTIC Gain "" VALUE 0x20 R 0 NO_COMPU_METHOD -100 100 /end CHARACTERISTIC
 /begin IF_DATA XCP /begin DAQ
 /begin EVENT "1ms" "1ms" 0 DAQ 255 1 6 0 /end EVENT
 /end DAQ /end IF_DATA
 /end MODULE /end PROJECT'''


class QtLoopbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def spin(self, condition, timeout=10):
        deadline = time.monotonic() + timeout
        while not condition():
            self.app.processEvents()
            QTest.qWait(5)
            if time.monotonic() > deadline:
                self.fail('Qt socket operation timeout: ' + repr(self.window.dialogs.errors) + '\n' + self.window.diagnostics_tab.log_text_value())

    def exercise(self, protocol):
        with tempfile.TemporaryDirectory() as directory, fixture.DaqSlave(protocol) as slave:
            path = Path(directory) / 'loopback.a2l'
            transport = '/begin XCP_ON_{}_IP 0x0100 {} ADDRESS "127.0.0.1" /end XCP_ON_{}_IP'.format(protocol, slave.port, protocol)
            path.write_text(A2L.replace('/begin IF_DATA XCP', '/begin IF_DATA XCP ' + transport), encoding='ascii')
            self.window = MainWindow(dialogs=Dialogs(), target_service=FakeDeployment(), target_monitor=FakeMonitor(),
                                     credential_store=FakeCredentialStore())
            window = self.window
            try:
                bar = window.connection_bar
                window.dialogs.a2l_path = str(path)
                bar.load_button.click()
                self.spin(lambda: window._state == HostState.LOADED)
                self.assertEqual(bar.protocol_var.get(), protocol)
                self.assertEqual(int(bar.port_var.get()), slave.port)
                bar.connect_button.click()
                self.spin(lambda: window._state == HostState.CONNECTED)
                observation, calibration = window.observation_tab, window.calibration_tab
                observation._set_selected(['Output'], True)
                observation.start_button.click()
                self.spin(lambda: len(observation.buffer) >= 5)
                self.assertEqual(observation.daq_metadata['period_seconds'], .001)
                self.assertEqual(observation.buffer.stats()['Output'][0], 1.5)
                calibration._edit_name('Gain')
                calibration.write_button.click()
                self.spin(lambda: not window._calibration_pending and observation.buffer.stats()['Output'][0] == 2.5)
                self.assertTrue(slave.running)
                self.assertTrue(window.vm.daq_active)
                self.assertEqual(slave.command_ids.count(0xDD), 1)
                calibration.restore_button.click()
                self.spin(lambda: not window._calibration_pending and observation.buffer.stats()['Output'][0] == 1.5)
                observation.stop_button.click()
                self.spin(lambda: window._state == HostState.CONNECTED)
                self.assertFalse(slave.running)
                self.assertEqual(slave.command_ids.count(0xDD), 2)
                points = observation.buffer.snapshot()['Output']
                self.assertTrue(any(point.value == 2.5 for point in points))
                self.assertTrue(all(left.elapsed_seconds < right.elapsed_seconds for left, right in zip(points, points[1:])))
                bar.disconnect_button.click()
                self.spin(lambda: window._state == HostState.LOADED)
                self.assertFalse(window.vm.connected)
                self.assertEqual(struct.unpack('<f', slave.memory[0x20:0x24])[0], 1.5)
                self.assertFalse(window.dialogs.errors)
            finally:
                window.close()
                self.spin(lambda: window._closed)
                window.deleteLater()
                self.app.processEvents()

    def test_tcp_buttons_daq_calibration_restore_and_disconnect(self):
        self.exercise('TCP')

    def test_udp_buttons_daq_calibration_restore_and_disconnect(self):
        self.exercise('UDP')
