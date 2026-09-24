"""Non-network tests for model timing, DAQ, and fresh validation evidence."""

import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_model_periods as validation


def runtime(period=.001, **changes):
    ns = round(period * 1e9)
    calls = round(34 / period)
    result = dict(event='x280_rt_summary', period_ns=ns, model_step_calls=calls,
                  model_step_completed_calls=calls, model_step_interval_samples=calls - 1,
                  model_step_interval_min_ns=ns - 1000, model_step_interval_max_ns=ns + 1000,
                  model_step_interval_mean_ns=ns, model_step_execution_min_ns=100,
                  model_step_execution_mean_ns=200, model_step_execution_max_ns=300,
                  model_step_interval_scope='generated_model_step_entry_to_entry',
                  measurement_clock='CLOCK_MONOTONIC', cycles=calls, completed_cycles=calls,
                  cycle_interval_samples=calls - 1, cycle_interval_min_ns=ns - 1000,
                  cycle_interval_mean_ns=ns, cycle_interval_max_ns=ns + 1000,
                  deadline_misses=0, skipped_releases=0, policy='SCHED_FIFO',
                  memory_locked=True, realtime_kernel=True, kernel_required=True,
                  priority=40, cpu=7)
    result.update(changes)
    return result


def clean_daq(count=30000):
    return dict({key: 0 for key in validation.DAQ_ERROR_COUNTERS},
                received_samples=count, queued_samples=0, host_error='')


def good_calibration():
    return dict(write_readback_ok=True, restore_readback_ok=True,
                write_daq_continues=True, restore_daq_continues=True)


def build_models():
    return [dict(model=name, remote_directory='MATLAB_ws/' + name, period_seconds=period,
                 payload=name + '_payload', local_elf=name + '.elf') for name, period in [
                     ('x280_rt_single', .001)]]


class ModelAcceptanceTests(unittest.TestCase):
    def test_each_supported_period_uses_its_actual_model_interval(self):
        for period in (.001, .01, .1):
            with self.subTest(period=period):
                checks = validation.model_period_checks(runtime(period), period, 3, 30, round(30 / period))
                self.assertTrue(all(checks.values()), checks)

    def test_bad_actual_period_fails_even_when_daq_metadata_would_match(self):
        checks = validation.model_period_checks(runtime(model_step_interval_mean_ns=1100000), .001, 3, 30, 30000)
        self.assertTrue(checks['configured_period'])
        self.assertFalse(checks['measured_step_mean'])

    def test_one_percent_mean_tolerance(self):
        for value, accepted in [(990000, True), (1010000, True), (989999, False), (1010001, False)]:
            with self.subTest(value=value):
                checks = validation.model_period_checks(runtime(model_step_interval_mean_ns=value), .001, 3, 30, 30000)
                self.assertEqual(checks['measured_step_mean'], accepted)

    def test_calls_and_intervals_must_be_complete(self):
        for changes, key in [
            ({'model_step_calls': 0}, 'step_calls_complete'),
            ({'model_step_completed_calls': 33999}, 'step_calls_complete'),
            ({'model_step_interval_samples': 34000}, 'step_interval_count'),
            ({'completed_cycles': 33999}, 'cycle_calls_complete'),
            ({'cycle_interval_samples': 1}, 'cycle_interval_count'),
        ]:
            with self.subTest(changes=changes):
                self.assertFalse(validation.model_period_checks(runtime(**changes), .001, 3, 30, 30000)[key])

    def test_deadline_misses_and_skips_fail_finite_acceptance(self):
        for changes, key in [({'deadline_misses': 1}, 'no_deadline_misses'),
                             ({'skipped_releases': 1}, 'no_skipped_releases')]:
            with self.subTest(changes=changes):
                self.assertFalse(validation.model_period_checks(runtime(**changes), .001, 3, 30, 30000)[key])

    def test_period_evidence_requires_generated_scope_and_monotonic_clock(self):
        checks = validation.model_period_checks(runtime(model_step_interval_scope='daq_timestamp',
                                                         measurement_clock='wall'), .001, 3, 30, 30000)
        self.assertFalse(checks['measured_step_scope'])
        self.assertFalse(checks['monotonic_clock'])

    def test_standalone_calls_cannot_be_inferred_from_daq_only_runtime(self):
        summary = runtime(model_step_calls=30000, model_step_completed_calls=30000,
                          model_step_interval_samples=29999, cycles=30000, completed_cycles=30000)
        checks = validation.model_period_checks(summary, .001, 3, 30, 30000)
        self.assertFalse(checks['cycles_cover_standalone_and_daq'])
        self.assertFalse(checks['calls_beyond_daq_cover_standalone'])

    def test_nonfinite_timing_statistics_fail(self):
        checks = validation.model_period_checks(runtime(model_step_interval_mean_ns=float('nan'),
                                                         model_step_execution_max_ns=float('inf')), .001, 3, 30, 30000)
        self.assertFalse(checks['measured_step_mean'])
        self.assertFalse(checks['step_execution_statistics'])

    def test_process_evidence_requires_actual_fifo_affinity_and_locked_memory(self):
        snapshot = dict(vm_locked_kb=1024, limits={'Max realtime priority': {'soft': '80'}},
                        threads=[dict(policy='SCHED_FIFO', priority=40, affinity=[7])])
        self.assertTrue(all(validation.process_checks(snapshot, runtime()).values()))
        snapshot['threads'][0]['affinity'] = [0, 7]
        self.assertFalse(validation.process_checks(snapshot, runtime())['model_thread_fifo_affinity'])


class DaqAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.names = ['m_B.MeasuredOutput', 'm_B.SlowSampledOutput']
        self.stats = {name: dict(all_finite=True, minimum=-1, maximum=1, repeat_fraction=.9)
                      for name in self.names}

    def checks(self, period=.001, count=30000, diagnostics=None, calibration=None, multirate=True):
        return validation.daq_integrity_checks(dict(period_seconds=period), diagnostics or clean_daq(count),
            period, 30, count, self.stats, self.names, calibration or good_calibration(), multirate)

    def test_sample_threshold_scales_with_period(self):
        for period, count in [(.001, 30000), (.01, 3000), (.1, 300)]:
            with self.subTest(period=period):
                self.assertTrue(all(self.checks(period, count).values()))
        self.assertFalse(self.checks(.1, 200)['sufficient_samples'])

    def test_every_daq_error_counter_must_be_zero_and_present(self):
        for name in validation.DAQ_ERROR_COUNTERS:
            with self.subTest(name=name):
                diagnostics = clean_daq()
                diagnostics[name] = 1
                self.assertFalse(self.checks(diagnostics=diagnostics)['no_' + name])
                del diagnostics[name]
                self.assertFalse(self.checks(diagnostics=diagnostics)['no_' + name])

    def test_constant_primary_and_slow_signals_are_not_accepted(self):
        self.stats[self.names[0]].update(minimum=1, maximum=1)
        self.stats[self.names[1]].update(repeat_fraction=1)
        checks = self.checks()
        self.assertFalse(checks['dynamic_primary_signal'])
        self.assertFalse(checks['multirate_10ms_hold'])

    def test_multirate_repeat_fraction_has_lower_and_upper_limits(self):
        for fraction, accepted in [(.79, False), (.8, True), (.9, True), (.98, True), (.99, False)]:
            with self.subTest(fraction=fraction):
                self.stats[self.names[1]]['repeat_fraction'] = fraction
                self.assertEqual(self.checks()['multirate_10ms_hold'], accepted)

    def test_calibration_requires_readback_restore_and_continued_daq(self):
        for name, check in [('write_readback_ok', 'calibration_write_readback'),
                            ('restore_readback_ok', 'calibration_restore_readback'),
                            ('write_daq_continues', 'calibration_write_daq_continues'),
                            ('restore_daq_continues', 'calibration_restore_daq_continues')]:
            with self.subTest(name=name):
                calibration = good_calibration()
                calibration[name] = False
                self.assertFalse(self.checks(calibration=calibration)[check])

    def test_signal_statistics_reject_missing_and_nonfinite_values(self):
        samples = [SimpleNamespace(values={'a': 1}), SimpleNamespace(values={'a': float('nan')})]
        stats = validation.signal_statistics(samples, ['a', 'missing'])
        self.assertFalse(stats['a']['all_finite'])
        self.assertFalse(stats['missing']['all_finite'])

    def test_calibration_failure_still_attempts_restore(self):
        vm, record = Mock(), {}
        vm.read_calibrations.return_value = {'CalOffset': 0}
        vm.daq_diagnostics = {'received_samples': 100}
        vm.daq_active = True
        vm.write_calibrations.side_effect = RuntimeError('write failed')
        with self.assertRaisesRegex(RuntimeError, 'write failed'):
            validation.calibrate_during_daq(vm, [], .001, record)
        vm.restore_calibrations.assert_called_once_with(['CalOffset'])


class FreshLogTests(unittest.TestCase):
    def test_counts_all_errors_beyond_tail_and_bounds_examples(self):
        old = (json.dumps(runtime()) + '\nERROR previous run\n').encode()
        errors = b'ERROR current run\n' * 10000
        fresh = json.dumps(runtime(model_step_calls=35000)).encode() + b'\n'
        result = validation.analyze_log_stream(io.BytesIO(old + errors + fresh), len(old))
        self.assertEqual(result['error_line_count'], 10000)
        self.assertEqual(len(result['error_examples']), 10)
        self.assertEqual(result['summary_count'], 1)
        self.assertEqual(result['runtime']['model_step_calls'], 35000)
        self.assertLess(len(json.dumps(result)), 10000)

    def test_old_summary_is_never_accepted(self):
        old = (json.dumps(runtime()) + '\n').encode()
        result = validation.analyze_log_stream(io.BytesIO(old + b'new startup\n'), len(old))
        self.assertEqual(result['summary_count'], 0)
        self.assertIsNone(result['runtime'])

    def test_malformed_and_duplicate_summaries_are_visible(self):
        encoded = (json.dumps(runtime()) + '\n{malformed\n' + json.dumps(runtime()) + '\n').encode()
        result = validation.analyze_log_stream(io.BytesIO(encoded), 0)
        self.assertEqual(result['summary_count'], 2)

    def test_truncated_log_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'truncated'):
            validation.analyze_log_stream(io.BytesIO(b'new'), 100)

    def test_remote_parser_executes_same_streaming_logic_locally(self):
        service = Mock()

        def execute(command, timeout):
            arguments = shlex.split(command)
            result = subprocess.run([sys.executable] + arguments[1:], capture_output=True, check=True)
            return result.stdout.decode()

        service._execute.side_effect = execute
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "model's log.txt"
            log.write_bytes(b'old\nError first\n' + (json.dumps(runtime()) + '\n').encode())
            result = validation.remote_log_evidence(service, str(log), 4)
            self.assertEqual(result['error_line_count'], 1)
            self.assertEqual(result['summary_count'], 1)


class SafetyTests(unittest.TestCase):
    def test_build_requires_only_the_1ms_model_and_a_dedicated_directory(self):
        models = build_models()
        self.assertEqual(validation.validate_build({'models': models}), models)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            validation.validate_build({'models': models[:-1]})
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            validation.validate_build({'models': models + models})
        models[0]['remote_directory'] = 'MATLAB_ws/../other'
        with self.assertRaisesRegex(ValueError, 'distinct'):
            validation.validate_build({'models': models})

    def test_running_model_is_not_stopped_and_autostart_is_not_changed(self):
        service, vm, record = Mock(), Mock(), {}
        service.status.return_value = dict(running=True, pid=123)
        validation.run_model(service, Path('.'), build_models()[0], 0, 30, record, vm_factory=lambda: vm)
        self.assertFalse(record['passed'])
        self.assertIn('already running', record['error']['error'])
        service.start.assert_not_called()
        service.stop.assert_not_called()
        service.set_autostart.assert_not_called()
        vm.close.assert_called_once()

    def test_untracked_existing_model_is_rejected(self):
        service = Mock()
        service._execute.return_value = '[123, 456]'
        with self.assertRaisesRegex(RuntimeError, 'existing process'):
            validation.reject_untracked_process(service, '/home/zh/model.elf')

    def test_failed_start_still_attempts_independent_cleanup_and_log_scan(self):
        service, vm, record = Mock(), Mock(), {}
        service.status.return_value = dict(running=False, pid=None, elf_path='/home/zh/model.elf',
                                           log_path='/home/zh/model.elf.log')
        service.start.side_effect = RuntimeError('start response failed')
        vm.close.side_effect = RuntimeError('XCP close failed')
        service.stop.side_effect = RuntimeError('model stop failed')
        evidence = dict(runtime=runtime(), summary_count=1, error_line_count=0)
        with patch.object(validation, 'reject_untracked_process'), \
                patch.object(validation, 'log_offset', return_value=10), \
                patch.object(validation, 'remote_log_evidence', return_value=evidence) as scan:
            validation.run_model(service, Path('.'), build_models()[0], 0, 30, record, vm_factory=lambda: vm)
        service.stop.assert_called_once()
        scan.assert_called_once_with(service, '/home/zh/model.elf.log', 10)
        self.assertEqual([item['operation'] for item in record['cleanup_errors']], ['xcp_close', 'model_stop'])
        self.assertFalse(record['passed'])

    def test_existing_output_is_not_overwritten_or_remote_connected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'existing.json'
            output.write_text('original evidence')
            with patch.object(sys, 'argv', ['validate', '--folder', directory, '--output', str(output)]), \
                    patch.object(validation, 'SSHDeployment') as deployment:
                with self.assertRaises(FileExistsError):
                    validation.main()
            self.assertEqual(output.read_text(), 'original evidence')
            deployment.assert_not_called()

    def test_failure_writes_new_report_and_closes_ssh_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'build_report.json').write_text(json.dumps(dict(models=build_models())))
            output = folder / 'new.json'
            service = Mock()
            service.connect.side_effect = RuntimeError('simulated SSH failure')
            service.close.side_effect = RuntimeError('simulated close failure')
            with patch.object(sys, 'argv', ['validate', '--folder', directory, '--output', str(output)]), \
                    patch.object(validation, 'SSHDeployment', return_value=service), \
                    patch.object(validation.getpass, 'getpass', return_value='test-only'):
                with self.assertRaisesRegex(RuntimeError, 'SSH failure'):
                    validation.main()
            report = json.loads(output.read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(report['cleanup_errors'][0]['operation'], 'ssh_close')
            self.assertNotIn('test-only', json.dumps(report))


if __name__ == '__main__':
    unittest.main()
