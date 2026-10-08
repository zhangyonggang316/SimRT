"""Offline checks for idle scheduling, host time and privileged clock requests."""

from datetime import datetime, timedelta, timezone
import json
import shlex
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pyxcp_host.services import target_clock as clock


class ClockServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.service = Mock()
        self.service._operation_lock = threading.RLock()
        self.service.status.return_value = {'running': False}
        self.epoch = Mock(return_value=1791160000.25)
        self.sync = clock.TargetClockSync(self.service, lambda: 'Asia/Shanghai',
                                         monotonic=lambda: self.now, epoch=self.epoch)
        self.sync.arm('private-password')
        self.snapshot = {'cpu_percent': 20.0, 'core_percents': [10.0, 30.0]}
        self.process = {'running': False}
        self.requests = []
        self.service._execute.side_effect = self.execute

    def execute(self, command, **kwargs):
        arguments = shlex.split(command)
        payload = json.loads(arguments[-1])
        self.requests.append((arguments, payload, kwargs))
        if payload['action'] == 'probe':
            return json.dumps({'idle': True, 'epoch': 1791160000.0})
        return json.dumps({'status': 'synchronized', 'timezone': 'Asia/Shanghai',
                           'method': 'already_aligned', 'ntp_preserved': True})

    def make_ready(self):
        for value in (0, 2, 4):
            self.now = value
            self.sync.observe(self.snapshot, self.process)
        self.assertTrue(self.sync.ready)

    def test_requires_three_samples_over_four_seconds(self):
        for value in (0, .1, .2):
            self.now = value
            self.sync.observe(self.snapshot, self.process)
        self.assertFalse(self.sync.ready)
        self.now = 4
        self.sync.observe(self.snapshot, self.process)
        self.assertTrue(self.sync.ready)

    def test_cpu_model_and_missing_measurements_reset_idle_window(self):
        for snapshot, process in ((dict(self.snapshot, cpu_percent=50), self.process),
                                  (dict(self.snapshot, core_percents=[51]), self.process),
                                  (dict(self.snapshot, cpu_percent=None), self.process),
                                  (dict(self.snapshot, cpu_percent=float('nan')), self.process),
                                  (self.snapshot, {'running': True}), (self.snapshot, {})):
            with self.subTest(snapshot=snapshot, process=process):
                self.sync.arm('private-password')
                self.make_ready()
                self.sync.observe(snapshot, process)
                self.assertFalse(self.sync.ready)

    def test_stale_samples_never_trigger_a_sync(self):
        self.make_ready()
        self.now = 11
        self.assertFalse(self.sync.ready)
        self.sync.observe(self.snapshot, self.process)
        self.assertFalse(self.sync.ready)

    def test_current_epoch_is_read_after_probe_and_not_when_armed(self):
        self.make_ready()
        self.epoch.assert_not_called()
        result = self.sync.synchronize()
        self.assertEqual(result['status'], 'synchronized')
        self.assertEqual([item[1]['action'] for item in self.requests], ['probe', 'apply'])
        application = self.requests[1]
        self.assertEqual(application[1]['epoch'], self.epoch.return_value)
        self.assertEqual(application[1]['timezone'], 'Asia/Shanghai')
        self.assertNotIn('private-password', ' '.join(application[0]))
        self.assertEqual(application[2]['input_data'], b'private-password\n')
        self.assertFalse(self.sync.pending)
        self.assertEqual(self.sync._password, '')

    def test_rechecks_running_model_before_sending_clock_requests(self):
        self.make_ready()
        self.service.status.return_value = {'running': True}
        self.assertEqual(self.sync.synchronize()['reason'], 'model_running')
        self.service._execute.assert_not_called()
        self.epoch.assert_not_called()
        self.assertTrue(self.sync.pending)

    def test_busy_remote_probe_defers_without_reading_epoch(self):
        self.make_ready()
        self.service._execute.return_value = json.dumps({'idle': False})
        self.service._execute.side_effect = None
        self.assertEqual(self.sync.synchronize()['status'], 'deferred')
        self.epoch.assert_not_called()

    def test_slow_link_defers_without_privileged_request(self):
        self.make_ready()
        def slow(*args, **kwargs):
            self.now += 2
            return self.execute(*args, **kwargs)
        self.service._execute.side_effect = slow
        self.assertEqual(self.sync.synchronize()['status'], 'deferred')
        self.assertEqual(len(self.requests), 1)

    def test_failures_are_redacted_bounded_and_release_session_password(self):
        self.service._execute.side_effect = RuntimeError('bad private-password')
        for attempt in range(3):
            base = 40 * attempt
            for offset in (0, 2, 4):
                self.now = base + offset
                self.sync.observe(self.snapshot, self.process)
            result = self.sync.synchronize()
            self.assertEqual(result['status'], 'failed')
            self.assertNotIn('private-password', result['error'])
            self.assertEqual(result['retry'], attempt < 2)
        self.assertFalse(self.sync.pending)
        self.assertEqual(self.sync._password, '')

    def test_disconnect_during_probe_cancels_before_apply(self):
        self.make_ready()
        def disconnect(*args, **kwargs):
            result = self.execute(*args, **kwargs)
            self.sync.cancel()
            return result
        self.service._execute.side_effect = disconnect
        self.assertEqual(self.sync.synchronize()['status'], 'cancelled')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.sync._password, '')

    def test_reconnect_requires_new_idle_samples_and_new_credentials(self):
        self.make_ready()
        self.sync.cancel()
        self.sync.arm('new-password')
        self.assertFalse(self.sync.ready)
        self.make_ready()
        self.sync.synchronize()
        self.assertEqual(self.requests[-1][2]['input_data'], b'new-password\n')


class RemoteClockTests(unittest.TestCase):
    def setUp(self):
        self.remote = {'__name__': 'clock_test'}
        exec(clock._CLOCK_HELPER, self.remote)
        self.commands = []
        self.remote['idle'] = lambda: True
        self.remote['model_running'] = lambda: False
        self.remote['timezone_name'] = lambda: 'Asia/Shanghai'
        self.remote['time'] = SimpleNamespace(monotonic=lambda: 10, time=lambda: 1791160000,
                                              tzset=lambda: None)
        fixed = Mock()
        fixed.astimezone.return_value.utcoffset.return_value = timedelta(0)
        fake_datetime = Mock(wraps=datetime)
        fake_datetime.fromtimestamp.side_effect = lambda value, tz=None: (
            datetime.fromtimestamp(value, tz) if tz else fixed)
        self.remote['datetime'] = SimpleNamespace(datetime=fake_datetime, timezone=timezone)
        self.remote['os'] = SimpleNamespace(environ={})
        self.remote['pathlib'] = SimpleNamespace(Path=lambda _: Mock(
            __truediv__=Mock(return_value=SimpleNamespace(is_file=lambda: True))))
        self.request = {'epoch': 1791160000, 'timezone': 'Asia/Shanghai', 'utc_offset': 0}
        self.remote['command'] = self.command

    def command(self, args):
        self.commands.append(args)
        return SimpleNamespace(returncode=0, stdout='200 OK', stderr='')

    def test_aligned_epoch_only_updates_timezone_without_chrony_or_ntp_changes(self):
        zones = iter(['Etc/UTC', 'Asia/Shanghai'])
        self.remote['timezone_name'] = lambda: next(zones)
        result = self.remote['apply'](self.request)
        self.assertEqual(result['method'], 'already_aligned')
        self.assertEqual(self.commands, [['timedatectl', 'set-timezone', 'Asia/Shanghai']])
        self.assertTrue(result['ntp_preserved'])

    def test_busy_target_does_not_change_clock_or_timezone(self):
        self.remote['idle'] = lambda: False
        self.assertEqual(self.remote['apply'](self.request)['status'], 'deferred')
        self.assertEqual(self.commands, [])

    def test_offset_mismatch_is_rejected_before_system_changes(self):
        with self.assertRaisesRegex(ValueError, 'timezone offsets differ'):
            self.remote['apply'](dict(self.request, utc_offset=28800))
        self.assertEqual(self.commands, [])

    def test_clock_drift_uses_chrony_utc_input_and_preserves_existing_manual_mode(self):
        result = self.remote['apply'](dict(self.request, epoch=self.request['epoch'] + 10))
        self.assertEqual(result['method'], 'chrony')
        self.assertEqual(len(self.commands), 1)
        self.assertEqual(self.commands[0][:5], ['chronyc', '-n', '-t', '1', 'settime'])
        self.assertTrue(self.commands[0][-1].endswith(' UTC'))

    def test_disabled_manual_mode_is_restored_after_chrony_failure(self):
        def failed(args):
            self.commands.append(args)
            if args[4] == 'settime':
                return SimpleNamespace(returncode=1,
                    stdout='505 Facility not enabled' if len(self.commands) == 1 else '500 Failure', stderr='')
            return SimpleNamespace(returncode=0, stdout='200 OK', stderr='')
        self.remote['command'] = failed
        with self.assertRaisesRegex(RuntimeError, '500 Failure'):
            self.remote['apply'](dict(self.request, epoch=self.request['epoch'] + 10))
        self.assertEqual(self.commands[-1], ['chronyc', '-n', '-t', '1', 'manual', 'off'])
        self.assertFalse(any('makestep' in args or 'set-time' in args or 'set-ntp' in args for args in self.commands))

    def test_running_model_recheck_prevents_chrony_adjustment(self):
        self.remote['model_running'] = lambda: True
        self.assertEqual(self.remote['apply'](dict(self.request, epoch=self.request['epoch'] + 10))['status'],
                         'deferred')
        self.assertEqual(self.commands, [])

    def test_timezone_traversal_and_invalid_epoch_are_rejected(self):
        for changes in ({'timezone': '../UTC'}, {'timezone': '/etc/passwd'}, {'epoch': float('nan')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.remote['apply'](dict(self.request, **changes))
        self.assertFalse(self.commands)


if __name__ == '__main__':
    unittest.main()
