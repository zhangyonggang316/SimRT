"""Local regression tests for RT validation safety and evidence handling."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_realtime_models as validation


def valid_summary(**overrides):
    result = dict(event='x280_rt_summary', period_ns=1000000, realtime_kernel=True,
                  kernel_required=True, policy='SCHED_FIFO', memory_locked=True,
                  cycles=200, completed_cycles=200, skipped_releases=10,
                  deadline_misses=10)
    result.update(overrides)
    return result


class LocalLogService:
    def _execute(self, command):
        arguments = shlex.split(command)
        assert arguments[:2] == ['python3', '-c']
        result = subprocess.run([sys.executable] + arguments[1:], capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.decode())
        return result.stdout.decode('utf-8')


class RuntimeEvidenceTests(unittest.TestCase):
    def test_harness_build_uses_uploaded_current_runtime_and_only_old_headers(self):
        service = Mock()
        validation.build_current_harness(service, 'MATLAB_ws/unique_harness', '/home/zh/old_bundle/src')
        self.assertEqual(service.upload.call_args_list, [
            call(validation.ROOT / 'x280_linux_target' / 'tests', 'MATLAB_ws/unique_harness'),
            call(validation.ROOT / 'x280_linux_target' / 'src', 'MATLAB_ws/unique_harness/runtime'),
        ])
        directory, command = service.build.call_args.args
        self.assertEqual(directory, 'MATLAB_ws/unique_harness')
        self.assertIn('-I/home/zh/old_bundle/src', command)
        self.assertIn('runtime/x280_rt_runtime.c', command)
        self.assertNotIn('/home/zh/old_bundle/src/x280_rt_runtime.c', command)

    def test_summary_ignores_other_and_malformed_json_lines(self):
        expected = valid_summary()
        text = json.dumps(expected) + '\n{"event":"another"}\n{partial\n'
        self.assertEqual(validation.summary_from_log(text), expected)

    def test_summary_is_required(self):
        with self.assertRaisesRegex(ValueError, 'was not emitted'):
            validation.summary_from_log('{"event":"other"}\n')

    def test_log_uses_byte_offset_and_only_new_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "runtime's log.txt"
            previous = (chr(0x4e2d) + '\n' + json.dumps(valid_summary(cycles=1)) + '\n').encode('utf-8')
            log.write_bytes(previous)
            service = LocalLogService()
            offset = validation.log_offset(service, str(log))
            self.assertEqual(offset, len(previous))
            with self.assertRaisesRegex(ValueError, 'was not emitted'):
                validation.summary_from_log(validation.new_log_text(service, str(log), offset))
            fresh = valid_summary(cycles=400, completed_cycles=400)
            with log.open('ab') as output:
                output.write((json.dumps(fresh) + '\n').encode())
            self.assertEqual(validation.summary_from_log(
                validation.new_log_text(service, str(log), offset)), fresh)

    def test_truncated_log_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'runtime.log'
            log.write_bytes(b'old log')
            with self.assertRaisesRegex(RuntimeError, 'truncated'):
                validation.new_log_text(LocalLogService(), str(log), 50)

    def test_noisy_target_returns_bounded_fresh_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'runtime.log'
            old = json.dumps(valid_summary(cycles=10, completed_cycles=10)) + '\n'
            fresh = valid_summary(cycles=400, completed_cycles=400)
            log.write_text(old + 'sample diagnostic\n' * 50000 + json.dumps(fresh) + '\n')
            result = validation.new_log_text(LocalLogService(), str(log), len(old))
            self.assertLessEqual(len(result.encode()), 16384)
            self.assertEqual(validation.summary_from_log(result), fresh)

    def test_missing_log_starts_at_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(validation.log_offset(LocalLogService(), str(Path(directory) / 'absent')), 0)

    def test_runtime_requires_period_completion_lock_and_strict_rt(self):
        self.assertTrue(all(validation.runtime_checks(valid_summary(), False).values()))
        for changes, key in [
            ({'period_ns': 10000000}, 'runtime_period_1ms'),
            ({'completed_cycles': 199}, 'cycles_completed'),
            ({'cycles': 0, 'completed_cycles': 0}, 'cycles_completed'),
            ({'memory_locked': False}, 'fifo_mlock'),
            ({'policy': 'SCHED_OTHER'}, 'fifo_mlock'),
            ({'realtime_kernel': False}, 'kernel'),
            ({'kernel_required': False}, 'kernel'),
            ({'deadline_misses': -1}, 'timing_counters'),
        ]:
            with self.subTest(changes=changes):
                self.assertFalse(validation.runtime_checks(valid_summary(**changes), False)[key])

    def test_soft_rt_does_not_hide_observed_deadline_misses(self):
        summary = valid_summary(deadline_misses=50, skipped_releases=100)
        self.assertTrue(all(validation.runtime_checks(summary, False).values()))
        self.assertEqual(summary['deadline_misses'], 50)

    def test_explicit_baseline_does_not_require_rt_kernel(self):
        checks = validation.runtime_checks(valid_summary(realtime_kernel=False, kernel_required=False), True)
        self.assertTrue(all(checks.values()))


class SelectionTests(unittest.TestCase):
    def test_multirate_requires_both_exact_signals(self):
        measurements = [SimpleNamespace(name='model_B.MeasuredOutput'),
                        SimpleNamespace(name='model_B.SlowSampledOutput')]
        self.assertEqual(validation.required_measurements(measurements, True),
                         [item.name for item in measurements])

    def test_missing_or_duplicate_required_signal_is_failure(self):
        for names, multirate in [([], False), (['m_B.MeasuredOutput'], True),
                                 (['m_B.MeasuredOutput', 'n_B.MeasuredOutput'], False),
                                 (['m_B.MeasuredOutput', 'm_B.OtherSlowSampledOutput'], True)]:
            with self.subTest(names=names):
                with self.assertRaisesRegex(ValueError, 'Expected exactly one'):
                    validation.required_measurements([SimpleNamespace(name=name) for name in names], multirate)

    def test_running_model_is_neither_reused_nor_stopped(self):
        service, vm = Mock(), Mock()
        service.status.return_value = dict(running=True, pid=123)
        service.connected = True
        with self.assertRaisesRegex(RuntimeError, 'already running'):
            validation.select_stopped_model(service, 'model.elf')
        validation.finish_validation(service, vm, {}, None, False, False)
        service.start.assert_not_called()
        service.stop.assert_not_called()
        service.close.assert_called_once()


class CleanupTests(unittest.TestCase):
    def test_disabled_selection_is_restored_then_disabled(self):
        service, vm, report = Mock(), Mock(), {}
        service.connected = True
        original = dict(elf_path='/home/zh/original.elf', arguments=['-name', 'two words'], enabled=False)
        validation.finish_validation(service, vm, report, original, True, True)
        self.assertEqual(service.set_autostart.call_args_list,
                         [call('/home/zh/original.elf', "-name 'two words'"), call(None)])
        service.stop.assert_called_once()
        self.assertFalse(report.get('cleanup_errors'))

    def test_absent_old_selection_does_not_create_one(self):
        service = Mock(connected=True)
        validation.finish_validation(service, Mock(), {},
                                     dict(elf_path='', arguments=[], enabled=False), False, True)
        service.set_autostart.assert_called_once_with(None)

    def test_all_cleanup_failures_are_independent(self):
        service, vm, report = Mock(connected=True), Mock(), {}
        vm.close.side_effect = RuntimeError('close XCP')
        service.stop.side_effect = RuntimeError('stop model')
        service.set_autostart.side_effect = RuntimeError('restore config')
        service.close.side_effect = RuntimeError('close SSH')
        validation.finish_validation(service, vm, report,
                                     dict(elf_path='/home/zh/a.elf', arguments=[], enabled=False), True, True)
        self.assertEqual([item['operation'] for item in report['cleanup_errors']],
                         ['xcp_close', 'model_stop', 'autostart_restore_selection',
                          'autostart_restore_disabled', 'ssh_close'])

    def test_disconnected_cleanup_is_explicit(self):
        service, report = Mock(connected=False), {}
        validation.finish_validation(service, Mock(), report, None, True, False)
        self.assertEqual(report['cleanup_errors'][0]['operation'], 'remote_cleanup')
        service.close.assert_called_once()

    def test_report_is_written_even_when_primary_and_cleanup_operations_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'build_report.json').write_text(json.dumps(dict(models=[])))
            service, vm = Mock(connected=False), Mock()
            service.connect.side_effect = RuntimeError('simulated connection failure')
            vm.close.side_effect = RuntimeError('simulated cleanup failure')
            with patch.object(sys, 'argv', ['validate', '--folder', directory]), \
                    patch.object(validation, 'SSHDeployment', return_value=service), \
                    patch.object(validation, 'HostViewModel', return_value=vm), \
                    patch.object(validation.getpass, 'getpass', return_value='test-only'):
                with self.assertRaisesRegex(RuntimeError, 'connection failure'):
                    validation.main()
            report = json.loads((folder / 'rt_validation.json').read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(report['error']['error'], 'simulated connection failure')
            self.assertEqual(report['cleanup_errors'][0]['operation'], 'xcp_close')
            self.assertNotIn('test-only', json.dumps(report))
            service.close.assert_called_once()

    def test_rt_mode_runs_overrun_harness_before_refusing_boot_model(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'build_report.json').write_text(json.dumps(dict(models=[
                dict(model='model', remote_directory='MATLAB_ws/model')])))
            service, vm = Mock(connected=True), Mock()
            service.autostart_status.return_value = dict(elf_path='/home/zh/model.elf', enabled=True)
            service.status.return_value = dict(running=True, pid=123)

            def execute(command):
                if command == 'uname -r':
                    return 'test-rt-kernel'
                if command.endswith(' --math'):
                    return '{"event":"x280_rt_math_tests","passed":16}'
                if command.endswith((' --bad-period', ' --bad-subrates')):
                    raise RuntimeError(validation.HARNESS_REJECTION_MESSAGES[command.rsplit(' ', 1)[1]])
                if command.endswith('/rt_runtime_harness'):
                    self.assertFalse(command.startswith('env '))
                    return json.dumps(valid_summary())
                raise AssertionError('Unexpected command: ' + command)

            service._execute.side_effect = execute
            with patch.object(sys, 'argv', ['validate', '--folder', directory]), \
                    patch.object(validation, 'SSHDeployment', return_value=service), \
                    patch.object(validation, 'HostViewModel', return_value=vm), \
                    patch.object(validation.getpass, 'getpass', return_value='test-only'):
                with self.assertRaisesRegex(RuntimeError, 'already running'):
                    validation.main()
            report = json.loads((folder / 'rt_validation.json').read_text())
            self.assertTrue(report['checks']['overrun_is_reported'])
            self.assertTrue(report['checks']['harness_kernel'])
            self.assertFalse(report['passed'])
            service.start.assert_not_called()
            service.stop.assert_not_called()
            service.set_autostart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
