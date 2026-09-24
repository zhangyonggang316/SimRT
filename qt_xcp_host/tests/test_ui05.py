"""UI-05: unified diagnostics, simpler deployment controls and default arguments."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QLineEdit, QPushButton, QLabel, QMenu
from qt_host.window import MainWindow
from test_window import ViewModel, Dialogs, DeferredExecutor
from test_target import FakeCredentialStore, FakeDeployment, FakeMonitor, make_payload, model


class Ui05Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service, self.monitor = FakeDeployment(), FakeMonitor()
        self.executor, self.dialogs = DeferredExecutor(), Dialogs()
        with patch('qt_host.target.CredentialStore', return_value=FakeCredentialStore()):
            self.window = MainWindow(ViewModel(), self.executor, self.dialogs, self.service, self.monitor)
        self.target, self.diagnostics = self.window.target_tab, self.window.diagnostics_tab
        self.target.timer.stop()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.target.local_edit.setText(str(make_payload(temporary.name)))

    def spin(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.app.processEvents()
            self.assertLess(time.monotonic(), deadline, 'Qt completion timeout')
            time.sleep(.002)
        self.app.processEvents()

    def settle(self):
        self.spin(lambda: not self.target.worker.busy)

    def tearDown(self):
        self.service.upload_release.set()
        self.window.close()
        while self.executor.pending:
            self.executor.complete()
            self.window._drain_ui_queue()
        self.spin(lambda: self.window._closed)
        self.window.deleteLater()
        self.app.processEvents()

    def enable_ssh(self):
        self.service.connected = True
        self.target._policy()

    def test_removed_deployment_controls_and_log_pane_are_absent(self):
        self.assertFalse(self.target.findChildren(QPlainTextEdit))
        self.assertFalse(hasattr(self.target, 'arguments_edit'))
        self.assertFalse({'refresh_process', 'read_log', 'cancel', 'build', 'download'} & self.target.buttons.keys())
        self.assertFalse(hasattr(self.target, 'command_edit'))
        self.assertFalse(hasattr(self.target, 'timeout_spin'))
        text = [item.text() for item in self.target.findChildren(QLabel) + self.target.findChildren(QPushButton)]
        for label in ('启动参数', '部署与运行日志', '刷新状态', '读取日志', '取消任务'):
            self.assertNotIn(label, text)
        self.assertIsInstance(self.target.elf_edit, QLineEdit)
        self.assertEqual(len(self.diagnostics.findChildren(QPlainTextEdit)), 1)

    def test_model_context_menu_has_no_duplicate_log_command(self):
        class Menu(QMenu):
            labels = []
            def exec(self, position):
                self.labels.extend(action.text() for action in self.actions())
        with patch('qt_host.target.QMenu', Menu):
            self.target._model_context_menu(self.target.table.rect().center())
        self.assertFalse(any('日志' in label for label in Menu.labels))

    def test_direct_list_and_autostart_use_empty_arguments(self):
        self.enable_ssh()
        self.target.start_elf()
        self.settle()
        self.assertEqual(self.service.calls[-2][0], 'start')
        self.assertEqual(next(call for call in self.service.calls if call[0] == 'start')[2], '')
        self.service.process['running'] = False
        self.target._process_state(self.service.status())
        self.monitor.models = [model('selected')]
        self.target.refresh()
        self.settle()
        self.target.table.selectRow(0)
        self.target.start_model()
        self.settle()
        self.assertEqual([call for call in self.service.calls if call[0] == 'start'][-1][2], '')
        self.target.toggle_autostart()
        self.settle()
        self.assertEqual([call for call in self.service.calls if call[0] == 'set_autostart'][-1][2], '')

    def test_worker_and_application_logs_reach_one_diagnostics_stream(self):
        self.window.log('xcp-marker')
        worker = threading.Thread(target=lambda: self.target._enqueue_log('ssh-marker'))
        worker.start()
        worker.join()
        self.target._tick()
        text = self.diagnostics.log_text_value()
        self.assertEqual(text.count('xcp-marker'), 1)
        self.assertEqual(text.count('ssh-marker'), 1)

    def test_remote_read_uses_selected_model_and_appends_once(self):
        self.enable_ssh()
        self.monitor.models = [model('selected')]
        self.target.refresh()
        self.settle()
        self.target.table.selectRow(0)
        self.diagnostics.read_log_button.click()
        self.assertFalse(self.diagnostics.read_log_button.isEnabled())
        self.assertFalse(self.target.read_log())
        self.settle()
        self.assertIn(('status', '/home/zh/MATLAB_ws/selected.elf'), self.service.calls)
        self.assertEqual(self.diagnostics.log_text_value().count('runtime log'), 1)
        self.assertEqual(self.service.calls.count(('read_log',)), 1)
        self.assertTrue(self.diagnostics.read_log_button.isEnabled())

    def test_remote_read_without_selection_uses_configured_elf(self):
        self.enable_ssh()
        self.target.remote_edit.setText('MATLAB_ws/current')
        self.target.elf_edit.setText('current.elf')
        self.diagnostics.read_log_button.click()
        self.settle()
        self.assertIn(('status', 'MATLAB_ws/current/current.elf'), self.service.calls)

    def test_remote_read_policy_tracks_ssh_busy_guard_and_close(self):
        self.assertFalse(self.diagnostics.read_log_button.isEnabled())
        self.enable_ssh()
        self.assertTrue(self.diagnostics.read_log_button.isEnabled())
        self.service.block_upload = True
        self.target.upload()
        self.spin(self.service.upload_entered.is_set)
        self.assertFalse(self.diagnostics.read_log_button.isEnabled())
        self.service.upload_release.set()
        self.settle()
        self.target.control_pending = True
        self.target._policy()
        self.assertFalse(self.diagnostics.read_log_button.isEnabled())
        self.assertFalse(self.target.read_log())
        self.target.control_pending = False
        self.target._policy()
        self.window.close()
        self.assertFalse(self.diagnostics.read_log_button.isEnabled())

    def test_copy_clear_and_save_share_the_combined_log(self):
        self.target._append('deployment-marker')
        self.window.log('observation-marker')
        original = self.diagnostics.log_text_value()
        self.diagnostics.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), original)
        with tempfile.TemporaryDirectory() as directory:
            self.dialogs.path = str(Path(directory) / 'diagnostics.log')
            self.diagnostics.save_button.click()
            self.executor.complete()
            self.window._drain_ui_queue()
            self.assertEqual(Path(self.dialogs.path).read_text(encoding='utf-8'), original)
        self.diagnostics.clear_button.click()
        self.assertEqual(self.diagnostics.log_text_value(), '')
        self.assertFalse(self.diagnostics.copy_button.isEnabled())
        self.assertFalse(self.diagnostics.clear_button.isEnabled())
        self.assertFalse(self.diagnostics.save_button.isEnabled())
        self.assertNotIn(('cancel',), self.service.calls)

    def test_failed_remote_log_is_reported_and_read_can_retry(self):
        self.enable_ssh()
        with patch.object(self.service, 'read_log', side_effect=RuntimeError('log unavailable')):
            self.diagnostics.read_log_button.click()
            self.settle()
        self.assertIn('log unavailable', self.diagnostics.log_text_value())
        self.assertTrue(self.dialogs.errors)
        self.assertTrue(self.diagnostics.read_log_button.isEnabled())

    def test_automatic_refresh_updates_process_after_external_exit(self):
        self.enable_ssh()
        self.target._process_state(dict(running=True, pid=91))
        self.assertFalse(self.target.buttons['start'].isEnabled())
        self.service.process.update(running=False, pid=None)
        self.target._was_connected = True
        self.target._next_refresh = 0
        self.target._tick()
        self.settle()
        self.assertFalse(self.target.running)
        self.assertEqual(self.target.process_status.text(), 'ELF 已停止')
        self.assertTrue(self.target.buttons['start'].isEnabled())
