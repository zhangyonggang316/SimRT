"""Local-only checks for the isolated current-runtime harness validator."""

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_runtime_harness as validation


def runtime(period_ms=1, calls=2000, **changes):
    result = dict(event='x280_rt_summary', period_ns=period_ms * 1000000,
                  realtime_kernel=True, kernel_required=True, policy='SCHED_FIFO', memory_locked=True,
                  cycles=calls, completed_cycles=calls, model_step_calls=calls,
                  model_step_completed_calls=calls, model_step_interval_samples=calls - 1,
                  model_step_interval_scope='generated_model_step_entry_to_entry',
                  model_step_interval_mean_ns=period_ms * 1000000, measurement_clock='CLOCK_MONOTONIC',
                  deadline_misses=0, skipped_releases=0, stop_signal=0)
    result.update(changes)
    return result


class RuntimeCasesTests(unittest.TestCase):
    def test_normal_periods_require_expected_completed_step_calls(self):
        for period, calls in [(1, 2000), (10, 200), (100, 30)]:
            with self.subTest(period=period):
                checks = validation.assess_runtime(runtime(period, calls), period, 'normal', calls)
                self.assertTrue(all(checks.values()), checks)
                checks = validation.assess_runtime(runtime(period, calls), period, 'normal', calls + 1)
                self.assertFalse(checks['expected_calls'])

    def test_normal_cases_reject_misses_and_wrong_step_scope(self):
        checks = validation.assess_runtime(runtime(deadline_misses=1, skipped_releases=1,
                                                   model_step_interval_scope='daq'), 1, 'normal', 2000)
        self.assertFalse(checks['no_deadline_misses'])
        self.assertFalse(checks['no_skipped_releases'])
        self.assertFalse(checks['model_step_scope'])

    def test_overrun_case_requires_all_ten_deliberate_overruns(self):
        checks = validation.assess_runtime(runtime(calls=200, deadline_misses=10, skipped_releases=20), 1, 'overrun', 200)
        self.assertTrue(all(checks.values()), checks)
        checks = validation.assess_runtime(runtime(calls=200, deadline_misses=9, skipped_releases=20), 1, 'overrun', 200)
        self.assertFalse(checks['overrun_reported'])

    def test_sigterm_requires_signal_summary_and_early_completion(self):
        checks = validation.assess_runtime(runtime(calls=400, stop_signal=15), 1, 'sigterm')
        self.assertTrue(all(checks.values()), checks)
        checks = validation.assess_runtime(runtime(calls=60000), 1, 'sigterm')
        self.assertFalse(checks['stop_signal'])
        self.assertFalse(checks['stopped_before_natural_limit'])

    def test_math16_all_three_periods_overrun_and_signal_are_included(self):
        def run_case(service, remote_dir, harness, arguments, sigterm=False):
            result = dict(returncode=0, timed_out=False, forced_kill=False, sent_sigterm=sigterm)
            if arguments == ['--math']:
                result['output'] = '{"event":"x280_rt_math_tests","passed":16}'
            elif arguments[0] in validation.HARNESS_REJECTION_MESSAGES:
                result.update(returncode=1, output=validation.HARNESS_REJECTION_MESSAGES[arguments[0]])
            else:
                period = int(arguments[1])
                calls = int(arguments[-1]) if arguments[-2] == '--cycles' else 400
                summary = runtime(period, calls)
                if '--normal-load' not in arguments:
                    summary.update(deadline_misses=10, skipped_releases=20)
                if sigterm:
                    summary['stop_signal'] = 15
                result['output'] = json.dumps(summary)
            return result

        with patch.object(validation, 'run_remote_case', side_effect=run_case), patch('builtins.print'):
            records = validation.run_suite(Mock(), 'unique', '/home/zh/unique/harness')
        self.assertEqual(len(records), 8)
        self.assertTrue(all(record['passed'] for record in records), records)
        self.assertEqual([record['name'] for record in records[3:6]], ['normal_1ms', 'normal_10ms', 'normal_100ms'])

    def test_partial_cases_remain_available_when_remote_operation_fails(self):
        records = []
        with patch.object(validation, 'run_remote_case', side_effect=RuntimeError('disconnected')):
            with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                validation.run_suite(Mock(), 'unique', '/home/zh/unique/harness', records)
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]['passed'])


class ExecutionSafetyTests(unittest.TestCase):
    def test_remote_case_uses_cancellable_build_wrapper_and_structured_arguments(self):
        service = Mock()
        service.build.return_value = '{"returncode":0}'
        result = validation.run_remote_case(service, 'unique', "/home/zh/space dir/harness", ['--long'], sigterm=True)
        self.assertEqual(result['returncode'], 0)
        directory, command = service.build.call_args.args
        self.assertEqual(directory, 'unique')
        arguments = shlex.split(command)
        request = json.loads(arguments[3])
        self.assertEqual(request['arguments'], ['/home/zh/space dir/harness', '--long'])
        self.assertTrue(request['sigterm'])
        service.start.assert_not_called()
        service.stop.assert_not_called()
        service.set_autostart.assert_not_called()

    def test_remote_runner_can_be_verified_with_local_child_without_ssh(self):
        request = dict(arguments=[sys.executable, '-c', 'print("test result")'], sigterm=False, timeout=2)
        result = subprocess.run([sys.executable, '-c', validation._CASE_RUNNER, json.dumps(request)],
                                check=True, capture_output=True, text=True)
        record = json.loads(result.stdout)
        self.assertEqual(record['returncode'], 0)
        self.assertEqual(record['output'].strip(), 'test result')
        self.assertFalse(record['timed_out'])

    def test_existing_report_blocks_before_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'existing.json'
            output.write_text('old evidence')
            with patch.object(sys, 'argv', ['validate', '--folder', directory, '--output', str(output)]), \
                    patch.object(validation, 'SSHDeployment') as deployment:
                with self.assertRaises(FileExistsError):
                    validation.main()
            self.assertEqual(output.read_text(), 'old evidence')
            deployment.assert_not_called()

    def test_connection_failure_still_writes_new_report_and_closes_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'build_report.json').write_text('{"models":[]}')
            output = folder / 'new.json'
            service = Mock()
            service.connect.side_effect = RuntimeError('simulated connection failure')
            with patch.object(sys, 'argv', ['validate', '--folder', directory, '--output', str(output)]), \
                    patch.object(validation, 'SSHDeployment', return_value=service), \
                    patch.object(validation.getpass, 'getpass', return_value='test-only'):
                with self.assertRaisesRegex(RuntimeError, 'connection failure'):
                    validation.main()
            report = json.loads(output.read_text())
            self.assertFalse(report['passed'])
            self.assertNotIn('test-only', json.dumps(report))
            service.close.assert_called_once()
            service.set_autostart.assert_not_called()


if __name__ == '__main__':
    unittest.main()
