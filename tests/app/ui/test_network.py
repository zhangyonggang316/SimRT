import os
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QMessageBox
from qt_host.network import NetworkDialog


class NetworkDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.service = Mock()
        self.service.interfaces.return_value = dict(interfaces=[
            dict(name='lo', state='UP', addresses=[dict(family='inet', address='127.0.0.1', prefix=8)]),
            dict(name='eth0', state='DOWN', addresses=[]),
            dict(name='eth1', state='UP', addresses=[dict(family='inet', address='192.0.2.5', prefix=24)], gateway='192.0.2.1'),
        ])
        self.dialog = NetworkDialog(self.service, self.submit)
        self.addCleanup(self.dialog.deleteLater)

    def submit(self, label, operation, success, on_error):
        try:
            result = operation()
        except Exception as error:
            on_error(error)
        else:
            success(result)
        return True

    def test_refresh_shows_all_interfaces_and_selection_populates_settings(self):
        self.dialog.refresh()
        self.assertEqual(self.dialog.table.rowCount(), 3)
        self.assertEqual(self.dialog.table.item(1, 2).text(), '--')
        self.dialog.table.selectRow(2)
        self.assertEqual(self.dialog.address.text(), '192.0.2.5')
        self.assertEqual(self.dialog.gateway.text(), '192.0.2.1')
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.dialog.table.selectRow(0)
        self.assertFalse(self.dialog.apply_button.isEnabled())

    def test_cancelled_confirmation_never_changes_network(self):
        self.dialog.refresh()
        self.dialog.table.selectRow(2)
        with patch.object(self.dialog, '_confirm_apply', return_value=(False, '')):
            self.assertFalse(self.dialog.apply())
        self.service.configure.assert_not_called()

    def test_invalid_ip_is_rejected_before_confirmation(self):
        self.dialog.refresh()
        self.dialog.table.selectRow(2)
        self.dialog.address.setText('not an IP')
        with patch.object(QMessageBox, 'warning'), patch.object(self.dialog, '_confirm_apply') as confirm:
            self.assertFalse(self.dialog.apply())
            confirm.assert_not_called()
        self.service.configure.assert_not_called()

    def test_success_uses_confirmed_values_and_reports_saved_configuration(self):
        self.dialog.refresh()
        self.dialog.table.selectRow(2)
        updated = deepcopy(self.service.interfaces.return_value)
        updated['interfaces'][2]['addresses'][0]['address'] = '192.0.2.9'
        updated['interfaces'].reverse()
        self.service.interfaces.return_value = updated
        self.service.configure.return_value = dict(interface='eth1', address='192.0.2.9/24', confirmed=True)
        self.dialog.address.setText('192.0.2.9')
        with patch.object(self.dialog, '_confirm_apply', return_value=(True, 'secret')):
            self.assertTrue(self.dialog.apply())
        self.service.configure.assert_called_once_with('eth1', '192.0.2.9', '24', '192.0.2.1', password='secret')
        self.assertIn('192.0.2.9/24', self.dialog.status.text())
        self.assertIn('保存', self.dialog.status.text())
        self.assertNotIn('secret', self.dialog.status.text())
        self.assertEqual(self.service.interfaces.call_count, 2)
        self.assertEqual(self.dialog.table.rowCount(), 3)
        self.assertEqual(self.dialog.selected()['name'], 'eth1')
        self.assertEqual(self.dialog.table.currentRow(), 0)
        self.assertIn('192.0.2.9/24', self.dialog.table.item(0, 2).text())
        self.assertEqual(self.dialog.address.text(), '192.0.2.9')
        self.assertEqual(self.dialog.mask.text(), '24')
        self.assertTrue(self.dialog.apply_button.isEnabled())

    def test_saved_address_remains_visible_when_automatic_refresh_fails(self):
        self.dialog.refresh()
        self.dialog.table.selectRow(2)
        self.service.interfaces.side_effect = RuntimeError('SSH read timed out')
        self.service.configure.return_value = dict(interface='eth1', address='192.0.2.9/24',
                                                   gateway='', confirmed=True)
        self.dialog.address.setText('192.0.2.9')
        self.dialog.gateway.clear()
        with patch.object(QMessageBox, 'warning') as warning, \
                patch.object(self.dialog, '_confirm_apply', return_value=(True, 'secret')):
            self.assertTrue(self.dialog.apply())
            warning.assert_not_called()
        self.assertEqual(self.dialog.table.rowCount(), 3)
        self.assertEqual(self.dialog.selected()['name'], 'eth1')
        self.assertEqual(self.dialog.table.item(2, 2).text(), '192.0.2.9/24')
        self.assertEqual(self.dialog.address.text(), '192.0.2.9')
        self.assertEqual(self.dialog.gateway.text(), '')
        self.assertIn('已应用并保存', self.dialog.status.text())
        self.assertIn('刷新失败', self.dialog.status.text())
        self.assertTrue(self.dialog.refresh_button.isEnabled())
        self.assertTrue(self.dialog.close_button.isEnabled())

    def test_management_interface_retains_old_ip_but_editor_uses_new_ip(self):
        initial = deepcopy(self.service.interfaces.return_value)
        for refresh_fails in (False, True):
            with self.subTest(refresh_fails=refresh_fails):
                self.service.interfaces.side_effect = None
                self.service.interfaces.return_value = deepcopy(initial)
                self.dialog.refresh()
                self.dialog.table.selectRow(2)
                ipv6 = dict(family='inet6', address='2001:db8::5', prefix=64)
                self.dialog.interfaces[2]['addresses'].append(ipv6)
                self.service.configure.return_value = dict(interface='eth1', address='192.0.2.9/24',
                    confirmed=True, retained_management_addresses=['192.0.2.5/24'])
                updated = deepcopy(self.service.interfaces.return_value)
                updated['interfaces'][2]['addresses'].append(dict(family='inet', address='192.0.2.9', prefix=24))
                self.service.interfaces.side_effect = RuntimeError('SSH read timed out') if refresh_fails else None
                if not refresh_fails:
                    self.service.interfaces.return_value = updated
                applied = Mock()
                self.dialog.addressApplied.connect(applied)
                self.dialog.address.setText('192.0.2.9')
                with patch.object(self.dialog, '_confirm_apply', return_value=(True, 'secret')):
                    self.dialog.apply()
                self.dialog.addressApplied.disconnect(applied)
                applied.assert_called_once_with('192.0.2.9')
                self.assertEqual(self.dialog.address.text(), '192.0.2.9')
                displayed = self.dialog.table.item(2, 2).text()
                for address in ('192.0.2.5/24', '192.0.2.9/24', '2001:db8::5/64'):
                    self.assertIn(address, displayed)

    def test_apply_and_refresh_share_one_pending_job_without_clearing_rows(self):
        self.dialog.refresh()
        self.dialog.table.selectRow(2)
        jobs = []
        self.dialog.submit = lambda *args, **kwargs: jobs.append((args, kwargs)) or True
        self.service.configure.return_value = dict(interface='eth1', address='192.0.2.9/24', confirmed=True)
        self.dialog.address.setText('192.0.2.9')
        updated = deepcopy(self.service.interfaces.return_value)
        updated['interfaces'][2]['addresses'][0]['address'] = '192.0.2.9'

        def read_after_save():
            self.assertTrue(self.dialog.pending)
            self.assertFalse(self.dialog.close_button.isEnabled())
            self.assertFalse(self.dialog.apply_button.isEnabled())
            self.assertEqual(self.dialog.table.rowCount(), 3)
            self.assertEqual(self.dialog.table.item(2, 2).text(), '192.0.2.5/24')
            self.assertFalse(self.dialog.apply())
            return updated

        self.service.interfaces.side_effect = read_after_save
        with patch.object(self.dialog, '_confirm_apply', return_value=(True, 'secret')):
            self.dialog.apply()
        args, kwargs = jobs[0]
        args[2](args[1]())
        self.assertEqual(len(jobs), 1)
        self.assertFalse(self.dialog.pending)
        self.assertEqual(self.dialog.table.rowCount(), 3)
        self.assertEqual(self.dialog.address.text(), '192.0.2.9')
        self.assertTrue(self.dialog.apply_button.isEnabled())

    def test_privilege_error_releases_controls_without_success_message(self):
        self.dialog.refresh()
        self.dialog.table.selectRow(2)
        self.service.configure.side_effect = RuntimeError('sudo: incorrect password')
        with patch.object(QMessageBox, 'warning') as warning, \
                patch.object(self.dialog, '_confirm_apply', return_value=(True, 'secret')):
            self.dialog.apply()
            warning.assert_called_once()
        self.assertFalse(self.dialog.pending)
        self.assertTrue(self.dialog.apply_button.isEnabled())
        self.assertIn('incorrect password', self.dialog.status.text())
        self.assertNotIn('已确认', self.dialog.status.text())

    def test_pending_operation_blocks_repeated_changes_and_close(self):
        self.dialog.refresh()
        self.dialog.table.selectRow(2)
        pending = []
        self.dialog.submit = lambda *args, **kwargs: pending.append((args, kwargs)) or True
        self.dialog.refresh()
        self.assertTrue(self.dialog.pending)
        self.assertFalse(self.dialog.apply())
        self.assertFalse(self.dialog.close_button.isEnabled())
        self.assertEqual(len(pending), 1)


if __name__ == '__main__':
    unittest.main()
