"""No-network Qt deployment regressions; run with QT_QPA_PLATFORM=offscreen."""

import os
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMenu

from qt_host.target import TargetWorkspace


class FakeCredentialStore:
    available = True

    def __init__(self, record=None):
        self.record = record
        self.saved = []
        self.cleared = 0

    def load(self):
        return self.record

    def save(self, host, username, password, port):
        self.record = dict(host=host, username=username, password=password, port=port)
        self.saved.append(dict(self.record))

    def clear(self):
        self.cleared += 1
        self.record = None


def make_payload(directory):
    directory = Path(directory)
    directory.mkdir(exist_ok=True)
    header = bytearray(64)
    header[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', header, 16, 2, 62, 1)
    struct.pack_into('<H', header, 52, 64)
    (directory / 'model.elf').write_bytes(header)
    a2l = b'/begin PROJECT test "fixture" /end PROJECT'
    (directory / 'model.a2l').write_bytes(a2l)
    (directory / 'model.xcp-manifest.json').write_text(json.dumps(dict(SchemaVersion=2,
        ELFFile='model.elf', A2LFile='model.a2l', ELFSHA256=hashlib.sha256(header).hexdigest(),
        A2LSHA256=hashlib.sha256(a2l).hexdigest(), XCPTransport='UDP', XCPPort=17725,
        TargetAddress='192.0.2.5', RuntimeFiles={})))
    return directory


class FakeDeployment:
    def __init__(self):
        self.connected = False
        self.calls = []
        self.process = {'running': False, 'pid': None, 'state': 'stopped', 'elf_path': ''}
        self.autostart = {'enabled': False, 'elf_path': '', 'linger': True}
        self.upload_entered = threading.Event()
        self.upload_release = threading.Event()
        self.block_upload = False
        self._home = '/home/zh'

    def connect(self, *settings):
        self.calls.append(('connect', settings))
        self.connected = True
        return {'host': settings[0], 'home': '/home/zh'}

    def status(self, path=None):
        self.calls.append(('status', path))
        if path:
            self.process['elf_path'] = path
        return dict(self.process)

    def close(self):
        self.calls.append(('close',))
        self.connected = False

    def cancel(self):
        self.calls.append(('cancel',))
        self.upload_release.set()

    def deploy_payload(self, local, remote):
        self.calls.append(('deploy_payload', str(local), remote))
        self.upload_entered.set()
        if self.block_upload:
            self.upload_release.wait(3)
        return dict(verified=True, file_count=3, elf_path=remote + '/model.elf',
                    a2l_path=remote + '/model.a2l', files={})

    def start(self, path, arguments=''):
        self.calls.append(('start', path, arguments))
        self.process.update(running=True, pid=91, state='running', elf_path=path)
        return 91

    def stop(self):
        self.calls.append(('stop',))
        self.process.update(running=False, pid=None, state='stopped')
        return True

    def read_log(self):
        self.calls.append(('read_log',))
        return 'runtime log'

    def autostart_status(self):
        return dict(self.autostart)

    def set_autostart(self, path, arguments):
        self.calls.append(('set_autostart', path, arguments))
        self.autostart.update(enabled=bool(path), elf_path=path or '')
        return dict(self.autostart)

    def delete_model(self, path, root='MATLAB_ws'):
        self.calls.append(('delete_model', path, root))
        cleared = self.autostart['elf_path'] == path
        if cleared:
            self.autostart.update(enabled=False, elf_path='')
        return dict(deleted=True, elf_path=path, directory=path.rsplit('/', 1)[0],
                    autostart_cleared=cleared)


def model(name='model', running=False, owned=False):
    return {'name': name, 'path': '/home/zh/MATLAB_ws/' + name + '.elf',
            'running': running, 'owned': owned, 'pids': [91] if running else [],
            'size': 1024, 'mtime': 1600000000}


class FakeMonitor:
    def __init__(self):
        self.models = []
        self.calls = []
        self.last_scan = {}

    def snapshot(self):
        self.calls.append('snapshot')
        return {'host': 'x280', 'architecture': 'x86_64', 'kernel': 'PREEMPT_RT',
                'cpu_percent': 24.5, 'memory_percent': 40.0, 'disk_percent': 10.0,
                'memory_used': 2 * 1024 ** 3, 'memory_total': 5 * 1024 ** 3,
                'disk_used': 10 * 1024 ** 3, 'disk_total': 100 * 1024 ** 3,
                'load_average': [1.0, 0.5, 0.25], 'uptime': 90061,
                'core_percents': [20.0, 30.0]}

    def list_models(self, root):
        self.calls.append(('models', root))
        return list(self.models)


class TargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = FakeDeployment()
        self.monitor = FakeMonitor()
        self.credentials = FakeCredentialStore()
        self.widget = TargetWorkspace(service=self.service, monitor=self.monitor, credential_store=self.credentials)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.payload = make_payload(temporary.name)
        self.widget.local_edit.setText(str(self.payload))
        self.logs = []
        self.widget.logMessage.connect(self.logs.append)
        self.widget.timer.stop()

    def tearDown(self):
        self.service.upload_release.set()
        self.spin_until(lambda: self.widget.close_workspace())
        self.widget.deleteLater()
        self.app.processEvents()

    def spin_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.app.processEvents()
            if time.monotonic() >= deadline:
                self.fail('Qt operation did not finish within {} seconds'.format(timeout))
            time.sleep(0.002)
        self.app.processEvents()

    def settle(self):
        self.spin_until(lambda: not self.widget.worker.busy)

    def render(self, models):
        self.service.connected = True
        self.widget._render((self.monitor.snapshot(), models, dict(self.service.autostart), '', self.service.status()))
        self.widget._policy()

    def test_layout_preserves_horizontal_deployment_and_target(self):
        self.widget.resize(1000, 720)
        self.widget.show()
        self.app.processEvents()
        self.assertEqual(self.widget.splitter.orientation(), Qt.Orientation.Horizontal)
        self.assertEqual(self.widget.splitter.count(), 2)
        self.assertLess(self.widget.splitter.widget(0).width(), self.widget.splitter.widget(1).width())
        self.assertEqual(self.widget.table.columnCount(), 7)
        self.assertFalse(hasattr(self.widget, 'log_view'))
        for name, button in self.widget.buttons.items():
            self.assertGreater(button.height(), 0, name)
            self.assertLessEqual(button.geometry().right(), button.parentWidget().width(), name)

    def test_connect_password_cleared_and_never_logged(self):
        self.widget.host_edit.setText('192.168.219.86')
        self.widget.user_edit.setText('zh')
        self.widget.password_edit.setText('temporary-password')
        self.assertTrue(self.widget.connect_ssh())
        self.assertEqual(self.widget.password_edit.text(), '')
        self.settle()
        self.assertEqual(self.service.calls[0], ('connect', ('192.168.219.86', 'zh', 'temporary-password', 22)))
        self.assertNotIn('temporary-password', '\n'.join(self.logs))
        self.assertTrue(self.service.connected)

    def test_connect_triggers_initial_inventory_load_without_refresh_control(self):
        self.assertFalse(hasattr(self.widget, 'auto_refresh'))
        self.service.connected = True
        self.widget._tick()
        self.settle()
        self.assertIn('snapshot', self.monitor.calls)
        self.assertIn('x280', self.widget.machine_label.text())

    def test_resource_display_and_selection_survive_refresh(self):
        self.render([model('alpha'), model('beta')])
        self.widget.table.selectRow(1)
        self.widget._render((self.monitor.snapshot(), [model('beta'), model('alpha')], {}, '', self.service.status()))
        self.assertEqual(self.widget.selected()['name'], 'beta')
        self.assertEqual(self.widget.metric_bars['cpu'].value(), 245)
        self.assertIn('2.00 GiB', self.widget.metric_labels['memory'].text())

    def test_foreign_running_model_cannot_be_stopped(self):
        self.render([model(running=True, owned=False)])
        self.widget.table.selectRow(0)
        self.assertFalse(self.widget.buttons['stop_model'].isEnabled())
        self.assertFalse(self.widget.stop_model())
        self.assertNotIn(('stop',), self.service.calls)
        self.assertEqual(self.widget.table.item(0, 2).text(), '外部运行中')

    def test_stop_waits_for_xcp_guard_and_freezes_other_operations(self):
        pending = []
        self.widget.stop_guard = lambda action, failure: pending.append((action, failure))
        self.render([model(running=True, owned=True)])
        self.widget.table.selectRow(0)
        self.assertTrue(self.widget.stop_model())
        self.assertTrue(self.widget.control_pending)
        self.assertFalse(self.widget.refresh())
        self.assertFalse(self.widget.upload())
        self.assertNotIn(('stop',), self.service.calls)
        self.assertTrue(pending[0][0]())
        self.settle()
        self.assertIn(('status', '/home/zh/MATLAB_ws/model.elf'), self.service.calls)
        self.assertIn(('stop',), self.service.calls)
        self.assertFalse(self.widget.control_pending)

    def test_failed_guard_releases_controls_without_stop(self):
        self.render([model(running=True, owned=True)])
        self.widget.table.selectRow(0)
        self.widget.stop_guard = lambda action, failure: failure()
        self.widget.stop_model()
        self.assertFalse(self.widget.control_pending)
        self.assertNotIn(('stop',), self.service.calls)

    def test_running_deployment_blocks_upload_and_start(self):
        self.service.connected = True
        self.widget._process_state({'running': True, 'pid': 91, 'state': 'running'})
        self.assertFalse(self.widget.upload())
        self.assertFalse(self.widget.start_elf())
        for name in ('upload', 'start'):
            self.assertFalse(self.widget.buttons[name].isEnabled())

    def test_ssh_and_monitor_operations_are_serialized(self):
        self.service.connected = True
        self.service.block_upload = True
        self.assertTrue(self.widget.upload())
        self.spin_until(self.service.upload_entered.is_set)
        self.assertFalse(self.widget.refresh())
        self.assertEqual(self.monitor.calls, [])
        self.widget.cancel()
        self.settle()
        self.assertIn(('cancel',), self.service.calls)
        self.assertTrue(self.widget.refresh())
        self.settle()

    def test_autostart_single_choice_and_never_starts_immediately(self):
        self.render([model('alpha'), model('beta')])
        self.widget.table.selectRow(0)
        self.assertTrue(self.widget.toggle_autostart())
        self.settle()
        self.widget.table.selectRow(1)
        self.assertTrue(self.widget.toggle_autostart())
        self.settle()
        self.assertEqual(self.widget.table.item(0, 0).checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(self.widget.table.item(1, 0).checkState(), Qt.CheckState.Checked)
        self.assertFalse(any(call[0] in ('start', 'stop') for call in self.service.calls))
        self.widget.toggle_autostart()
        self.settle()
        self.assertFalse(self.service.autostart['enabled'])

    def test_demo_loading_is_nonconnecting_and_clears_password(self):
        self.widget.password_edit.setText('secret')
        self.widget.apply_demo(SimpleNamespace(host='host', username='user', payload_dir=Path('payload'),
                                               remote_dir='MATLAB_ws/demo', elf_name='model.elf'))
        self.assertEqual(self.service.calls, [])
        self.assertEqual(self.widget.host_edit.text(), 'host')
        self.assertEqual(self.widget.root_edit.text(), 'MATLAB_ws/demo')
        self.assertFalse(hasattr(self.widget, 'command_edit'))
        self.assertEqual(self.widget.password_edit.text(), '')

    def test_delete_model_confirmed_removes_folder_rows_and_autostart(self):
        selected, other = model('alpha'), model('beta')
        selected['path'] = '/home/zh/MATLAB_ws/alpha/alpha.elf'
        other['path'] = '/home/zh/MATLAB_ws/beta/beta.elf'
        self.service.autostart.update(enabled=True, elf_path=selected['path'])
        self.render([selected, other])
        self.widget.table.selectRow(0)
        with patch.object(self.widget, '_confirm_model_delete', return_value=True) as confirm:
            self.assertTrue(self.widget.delete_model())
            self.settle()
        confirm.assert_called_once_with(selected)
        self.assertIn(('delete_model', selected['path'], 'MATLAB_ws'), self.service.calls)
        self.assertEqual(self.widget.models, [other])
        self.assertEqual(self.widget.table.rowCount(), 1)
        self.assertIsNone(self.widget.selected())
        self.assertFalse(self.widget.autostart.get('enabled'))
        self.assertFalse(self.widget.control_pending)
        self.assertTrue(self.widget._inventory_dirty)
        self.assertIn('已删除远程文件夹：/home/zh/MATLAB_ws/alpha', '\n'.join(self.logs))

    def test_delete_cancel_freezes_refresh_and_never_calls_service(self):
        self.render([model()])
        self.widget.table.selectRow(0)

        def cancel(_):
            self.assertTrue(self.widget.control_pending)
            self.assertFalse(self.widget.refresh())
            self.assertFalse(self.widget.toggle_autostart())
            return False

        with patch.object(self.widget, '_confirm_model_delete', side_effect=cancel):
            self.assertFalse(self.widget.delete_model())
        self.assertFalse(self.widget.control_pending)
        self.assertEqual(self.widget.table.rowCount(), 1)
        self.assertFalse(any(call[0] == 'delete_model' for call in self.service.calls))

    def test_delete_running_or_unavailable_model_never_opens_confirmation(self):
        with patch.object(self.widget, '_confirm_model_delete') as confirm:
            self.assertFalse(self.widget.delete_model())
            for owned in (True, False):
                self.render([model(running=True, owned=owned)])
                self.widget.table.selectRow(0)
                self.assertFalse(self.widget.delete_model())
            self.render([model()])
            self.widget.table.selectRow(0)
            self.widget.control_pending = True
            self.assertFalse(self.widget.delete_model())
            self.widget.control_pending = False
            self.service.connected = False
            self.assertFalse(self.widget.delete_model())
            confirm.assert_not_called()

    def test_delete_failure_preserves_model_and_releases_controls(self):
        self.render([model()])
        self.widget.table.selectRow(0)
        with patch.object(self.widget, '_confirm_model_delete', return_value=True), \
                patch.object(self.service, 'delete_model', side_effect=RuntimeError('Model is now running')):
            self.assertTrue(self.widget.delete_model())
            self.settle()
        self.assertEqual(self.widget.table.rowCount(), 1)
        self.assertFalse(self.widget.control_pending)
        self.assertIn('Model is now running', '\n'.join(self.logs))

    def test_delete_captures_confirmed_path_despite_selection_change(self):
        alpha, beta = model('alpha'), model('beta')
        self.render([alpha, beta])
        self.widget.table.selectRow(0)

        def confirm(_):
            self.widget.table.selectRow(1)
            return True

        with patch.object(self.widget, '_confirm_model_delete', side_effect=confirm):
            self.widget.delete_model()
            self.settle()
        self.assertIn(('delete_model', alpha['path'], 'MATLAB_ws'), self.service.calls)

    def test_context_menu_delete_targets_clicked_row_and_disables_running(self):
        self.render([model('alpha'), model('beta', running=True, owned=True)])
        self.widget.resize(1100, 740)
        self.widget.show()
        self.app.processEvents()
        self.widget.table.selectRow(0)

        def close_menu():
            menu = QApplication.activePopupWidget()
            if isinstance(menu, QMenu):
                menus.append(menu)
                menu.close()

        for row, enabled in ((1, False), (0, True)):
            menus = []
            QTimer.singleShot(20, close_menu)
            point = self.widget.table.visualItemRect(self.widget.table.item(row, 1)).center()
            self.widget._model_context_menu(point)
            action = next(action for action in menus[0].actions() if action.text() == '删除模型')
            self.assertEqual(action.isEnabled(), enabled)
            self.assertEqual(self.widget.selected()['name'], ('alpha', 'beta')[row])
        menus = []
        QTimer.singleShot(20, close_menu)
        self.widget._model_context_menu(QPoint(5, self.widget.table.viewport().height() - 2))
        action = next(action for action in menus[0].actions() if action.text() == '删除模型')
        self.assertFalse(action.isEnabled())

    def test_elf_path_rejects_traversal_absolute_and_backslash(self):
        for path in ('../escape.elf', '/etc/run.elf', 'nested\\run.elf', ''):
            self.widget.elf_edit.setText(path)
            with self.assertRaises(ValueError):
                self.widget._elf_path()

    def test_disconnect_clears_target_state(self):
        self.render([model()])
        self.assertTrue(self.widget.disconnect_ssh())
        self.settle()
        self.assertEqual(self.widget.table.rowCount(), 0)
        self.assertEqual(self.widget.machine_label.text(), '目标机资源')
        self.assertFalse(self.widget.running)

    def test_close_is_nonblocking_and_cancels_worker_without_stopping_model(self):
        self.service.connected = True
        self.service.block_upload = True
        self.widget.upload()
        self.spin_until(self.service.upload_entered.is_set)
        start = time.monotonic()
        self.assertFalse(self.widget.close_workspace())
        self.assertLess(time.monotonic() - start, 0.2)
        self.spin_until(self.widget.close_workspace)
        self.assertIn(('cancel',), self.service.calls)
        self.assertIn(('close',), self.service.calls)
        self.assertNotIn(('stop',), self.service.calls)

    def test_late_guard_after_close_cannot_stop_model(self):
        pending = []
        self.widget.stop_guard = lambda action, failure: pending.append(action)
        self.render([model(running=True, owned=True)])
        self.widget.table.selectRow(0)
        self.widget.stop_model()
        self.spin_until(self.widget.close_workspace)
        self.assertFalse(pending[0]())
        self.assertNotIn(('stop',), self.service.calls)

    def test_log_queue_is_bounded(self):
        for index in range(1000):
            self.widget._enqueue_log(str(index))
        self.assertLessEqual(self.widget._logs.qsize(), 256)

    def test_selected_payload_emits_matching_a2l_and_updates_elf_without_network(self):
        selected = []
        self.widget.payloadSelected.connect(selected.append)
        self.assertTrue(self.widget.select_payload(self.payload))
        self.assertEqual(self.widget.elf_edit.text(), 'model.elf')
        self.assertEqual(Path(selected[0]['a2l']), self.payload / 'model.a2l')
        self.assertEqual(selected[0]['protocol'], 'UDP')
        self.assertFalse(self.service.calls)

    def test_tampered_payload_is_rejected_before_upload(self):
        self.service.connected = True
        (self.payload / 'model.elf').write_bytes(b'changed ELF')
        self.assertFalse(self.widget.upload())
        self.assertFalse(any(call[0] == 'deploy_payload' for call in self.service.calls))
        self.assertIn('SHA256', '\n'.join(self.logs))

    def test_upload_uses_verified_payload_service_and_reports_remote_hash_check(self):
        self.service.connected = True
        self.widget.remote_edit.setText('MATLAB_ws/current')
        self.assertTrue(self.widget.upload())
        self.settle()
        self.assertIn(('deploy_payload', str(self.payload), 'MATLAB_ws/current'), self.service.calls)
        self.assertEqual(self.widget.elf_edit.text(), 'model.elf')
        self.assertIn('目标机校验通过：3 个文件', '\n'.join(self.logs))
        self.assertFalse({'build', 'download'} & self.widget.buttons.keys())

    def make_zip(self):
        path = self.payload.parent / (self.payload.name + '.zip')
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        with zipfile.ZipFile(path, 'w') as archive:
            for entry in self.payload.iterdir():
                archive.write(entry, '20260919_120000/' + entry.name)
        return path

    def test_zip_load_identifies_files_and_uploads_extracted_payload(self):
        archive = self.make_zip()
        selected = []
        self.widget.payloadSelected.connect(selected.append)
        self.assertTrue(self.widget.select_payload(archive))
        self.settle()
        self.assertEqual(self.widget.local_edit.text(), str(archive))
        self.assertEqual(self.widget.elf_edit.text(), 'model.elf')
        extracted = Path(selected[-1]['directory'])
        self.assertEqual(len(list(extracted.iterdir())), 3)
        self.assertTrue(Path(selected[-1]['a2l']).is_file())
        self.assertFalse(self.service.calls)
        self.service.connected = True
        self.assertTrue(self.widget.upload())
        self.settle()
        uploaded = next(call for call in self.service.calls if call[0] == 'deploy_payload')
        self.assertEqual(uploaded[1], str(extracted))
        self.spin_until(self.widget.close_workspace)
        self.assertFalse(extracted.exists())

    def test_invalid_zip_preserves_active_payload_and_never_uploads(self):
        self.assertTrue(self.widget.select_payload(self.payload))
        previous = self.widget.local_edit.text()
        archive = self.make_zip()
        with zipfile.ZipFile(archive, 'a') as output:
            output.writestr('extra.txt', b'bad')
        self.assertTrue(self.widget.select_payload(archive))
        self.settle()
        self.assertEqual(self.widget.local_edit.text(), previous)
        self.service.connected = True
        self.widget.local_edit.setText(str(archive))
        self.assertTrue(self.widget.upload())
        self.settle()
        self.assertFalse(any(call[0] == 'deploy_payload' for call in self.service.calls))

    def test_periodic_monitoring_does_not_rescan_or_recreate_rows(self):
        self.monitor.models = [model('alpha'), model('beta')]
        self.service.connected = True
        self.widget._tick()
        self.settle()
        self.widget.table.selectRow(1)
        item = self.widget.table.item(1, 1)
        initial_logs = list(self.logs)
        for _ in range(3):
            self.widget._next_refresh = 0
            self.widget._tick()
            self.settle()
        self.assertEqual(sum(isinstance(call, tuple) for call in self.monitor.calls), 1)
        self.assertIs(self.widget.table.item(1, 1), item)
        self.assertEqual(self.widget.selected()['name'], 'beta')
        self.assertEqual(self.logs, initial_logs)
        self.assertNotIn('|', self.widget.target_status.text())
        self.widget.root_edit.setText('MATLAB_ws/other')
        self.widget.root_edit.editingFinished.emit()
        self.widget._tick()
        self.settle()
        self.assertEqual(self.monitor.calls[-1], ('models', 'MATLAB_ws/other'))

    def test_click_during_background_monitoring_queues_captured_model(self):
        self.render([model('alpha'), model('beta')])
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        snapshot = self.monitor.snapshot()

        def blocked_snapshot():
            entered.set()
            release.wait(3)
            return snapshot

        with patch.object(self.monitor, 'snapshot', side_effect=blocked_snapshot):
            self.widget._poll_resources()
            self.spin_until(entered.is_set)
            self.widget.table.selectRow(0)
            self.assertTrue(self.widget.buttons['start_model'].isEnabled())
            self.assertFalse(self.widget.busy)
            self.widget.buttons['start_model'].click()
            self.widget.table.selectRow(1)
            self.assertTrue(self.widget.busy)
            self.assertFalse(any(call[0] == 'start' for call in self.service.calls))
            release.set()
            self.settle()
        self.assertIn(('start', model('alpha')['path'], ''), self.service.calls)
        self.assertEqual(self.widget.table.item(0, 2).text(), '运行中')
        self.assertFalse(self.widget.busy)

    def trigger_menu(self, label, row=0):
        self.widget.resize(1100, 740)
        self.widget.show()
        self.app.processEvents()
        errors = []

        def trigger():
            menu = QApplication.activePopupWidget()
            try:
                self.assertIsInstance(menu, QMenu)
                self.assertTrue(self.widget._context_menu_open)
                for action in menu.actions():
                    self.assertFalse(action.icon().isNull(), action.text())
                action = next(action for action in menu.actions() if action.text() == label)
                self.assertTrue(action.isEnabled(), label)
                action.trigger()
            except Exception as error:
                errors.append(error)
            finally:
                if menu:
                    menu.close()

        QTimer.singleShot(20, trigger)
        point = self.widget.table.visualItemRect(self.widget.table.item(row, 1)).center()
        self.widget._model_context_menu(point)
        self.settle()
        if errors:
            raise errors[0]

    def test_every_target_menu_action_performs_its_operation(self):
        first, second = model('alpha'), model('beta')
        first['path'] = '/home/zh/MATLAB_ws/alpha/alpha.elf'
        second['path'] = '/home/zh/MATLAB_ws/beta/beta.elf'
        self.monitor.models = [first, second]
        self.render(self.monitor.models)
        self.trigger_menu('选择模型', 1)
        self.assertEqual(self.widget.elf_edit.text(), 'beta.elf')
        self.trigger_menu('复制远程路径', 0)
        self.assertEqual(QApplication.clipboard().text(), first['path'])
        self.trigger_menu('设为开机自启', 1)
        self.assertEqual(self.service.autostart['elf_path'], second['path'])
        self.trigger_menu('取消开机自启', 1)
        self.assertFalse(self.service.autostart['enabled'])
        self.trigger_menu('启动模型', 1)
        self.assertIn(('start', second['path'], ''), self.service.calls)
        self.assertEqual(self.widget.table.item(1, 2).text(), '运行中')
        self.trigger_menu('停止模型', 1)
        self.assertIn(('stop',), self.service.calls)
        self.assertEqual(self.widget.table.item(1, 2).text(), '已停止')
        with patch.object(self.widget, '_confirm_model_delete', return_value=True):
            self.trigger_menu('删除模型', 1)
        self.assertIn(('delete_model', second['path'], 'MATLAB_ws'), self.service.calls)
        self.assertEqual(self.widget.models, [first])
        self.monitor.models = [first]
        self.trigger_menu('刷新', 0)
        self.assertIn(('models', 'MATLAB_ws'), self.monitor.calls)

    def test_open_menu_defers_inventory_changes(self):
        self.render([model('alpha')])
        self.widget._context_menu_open = True
        self.widget._render((self.monitor.snapshot(), [model('beta')], {}, '', self.service.status()))
        self.assertEqual(self.widget.models[0]['name'], 'alpha')
        self.assertIsNotNone(self.widget._deferred_render)
        calls = list(self.monitor.calls)
        self.widget._next_refresh = 0
        self.widget._tick()
        self.assertEqual(self.monitor.calls, calls)
        self.widget._context_menu_open = False

    def test_credentials_saved_only_after_success_and_removed_on_uncheck(self):
        self.widget.host_edit.setText('192.0.2.5')
        self.widget.user_edit.setText('tester')
        self.widget.password_edit.setText('never-log-this')
        self.widget.remember_credentials.setChecked(True)
        self.assertFalse(self.credentials.saved)
        self.widget.connect_ssh()
        self.settle()
        self.assertEqual(self.credentials.saved, [dict(host='192.0.2.5', username='tester', password='never-log-this', port=22)])
        self.assertNotIn('never-log-this', '\n'.join(self.logs))
        self.widget.remember_credentials.setChecked(False)
        self.assertEqual(self.credentials.cleared, 1)
        self.assertIsNone(self.credentials.record)

    def test_failed_login_does_not_save_password_and_redacts_error(self):
        self.widget.host_edit.setText('192.0.2.5')
        self.widget.user_edit.setText('tester')
        self.widget.password_edit.setText('never-log-this')
        self.widget.remember_credentials.setChecked(True)
        with patch.object(self.service, 'connect', side_effect=RuntimeError('failed: never-log-this')):
            self.widget.connect_ssh()
            self.settle()
        self.assertFalse(self.credentials.saved)
        self.assertNotIn('never-log-this', '\n'.join(self.logs))

    def test_restored_login_survives_demo_preset_without_connecting(self):
        self.credentials.record = dict(host='192.0.2.5', username='tester', password='saved-password', port=2222)
        self.widget._restore_credentials()
        self.widget.apply_demo(SimpleNamespace(host='default', username='default', payload_dir=self.payload,
            remote_dir='MATLAB_ws/current', elf_name='model.elf'))
        self.assertEqual(self.widget.host_edit.text(), '192.0.2.5')
        self.assertEqual(self.widget.password_edit.text(), 'saved-password')
        self.assertEqual(self.widget.port_spin.value(), 2222)
        self.assertTrue(self.widget.remember_credentials.isChecked())
        self.assertFalse(self.service.calls)


if __name__ == '__main__':
    unittest.main()
