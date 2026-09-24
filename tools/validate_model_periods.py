"""Validate generated model call periods independently from XCP DAQ integrity."""

import argparse
from datetime import datetime, timezone
import getpass
import inspect
import json
import math
from pathlib import Path, PurePosixPath
import shlex
import sys
import time

from validate_realtime_models import (SSHDeployment, HostViewModel, cleanup_operation,
                                      log_offset, required_measurements, select_stopped_model)

sys.excepthook = sys.__excepthook__
HOST = '192.168.219.86'
STANDALONE_SECONDS = 3.0
DAQ_ERROR_COUNTERS = (
    'queue_dropped_samples', 'invalid_frames', 'incomplete_events',
    'transport_counter_gaps', 'reordered_frames', 'timestamp_gap_samples',
    'timestamp_reorders', 'overload_events',
)


def analyze_log_stream(stream, offset):
    """Scan every new line remotely, returning bounded examples and one summary."""
    import json
    import re

    stream.seek(0, 2)
    end = stream.tell()
    if offset < 0 or end < offset:
        raise ValueError('Runtime log was truncated or has an invalid start offset')
    stream.seek(offset)
    result = dict(start_bytes=offset, end_bytes=end, new_bytes=end - offset,
                  line_count=0, error_line_count=0, error_examples=[],
                  summary_count=0, runtime=None)
    errors = re.compile(r'\b(?:error|fatal|failed|failure|overflow|overrun|assert|assertion)\b|\bERR_[A-Z_0-9]+\b', re.I)
    for raw in stream:
        line = raw.decode('utf-8', errors='replace').strip()
        result['line_count'] += 1
        if errors.search(line):
            result['error_line_count'] += 1
            if len(result['error_examples']) < 10:
                result['error_examples'].append(line[:512])
        if line.startswith('{'):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get('event') == 'x280_rt_summary':
                result['summary_count'] += 1
                result['runtime'] = value
    return result


def remote_log_evidence(service, path, offset):
    script = ('import json, sys\n' + inspect.getsource(analyze_log_stream)
              + "\nwith open(sys.argv[1], 'rb') as stream:\n"
              + '    print(json.dumps(analyze_log_stream(stream, int(sys.argv[2]))))\n')
    return json.loads(service._execute('python3 -c {} {} {}'.format(
        shlex.quote(script), shlex.quote(path), int(offset)), timeout=60))


def process_snapshot(service, pid, elf_path):
    script = r'''import json, os, re, sys, time
from pathlib import Path
pid, expected_elf = int(sys.argv[1]), sys.argv[2]
base = Path('/proc') / str(pid)
actual_elf = os.readlink(str(base / 'exe'))
if actual_elf != expected_elf or base.stat().st_uid != os.getuid():
    raise RuntimeError('Process identity no longer matches the validation model')
fields = (base / 'stat').read_text().rsplit(')', 1)[1].split()
status = dict(line.split(':', 1) for line in (base / 'status').read_text().splitlines() if ':' in line)
limits = {}
for line in (base / 'limits').read_text().splitlines()[1:]:
    parts = re.split(r'\s{2,}', line.strip())
    if len(parts) >= 3:
        limits[parts[0]] = dict(soft=parts[1], hard=parts[2], units=parts[3] if len(parts) > 3 else '')
policies = {0:'SCHED_OTHER', 1:'SCHED_FIFO', 2:'SCHED_RR', 3:'SCHED_BATCH', 5:'SCHED_IDLE', 6:'SCHED_DEADLINE'}
threads = []
for task in sorted((base / 'task').iterdir(), key=lambda value: int(value.name)):
    tid = int(task.name)
    threads.append(dict(tid=tid, name=(task / 'comm').read_text().strip(),
                        policy=policies.get(os.sched_getscheduler(tid), 'UNKNOWN'),
                        priority=os.sched_getparam(tid).sched_priority,
                        affinity=sorted(os.sched_getaffinity(tid))))
print(json.dumps(dict(pid=pid, elf_path=actual_elf, start_time_ticks=int(fields[19]),
                      monotonic_ns=time.monotonic_ns(), user_ticks=int(fields[11]), system_ticks=int(fields[12]),
                      vm_locked_kb=int(status.get('VmLck', '0 kB').split()[0]),
                      process_allowed_cpus=status.get('Cpus_allowed_list', '').strip(),
                      limits=limits, threads=threads)))
'''
    return json.loads(service._execute('python3 -c {} {} {}'.format(
        shlex.quote(script), int(pid), shlex.quote(elf_path))))


def reject_untracked_process(service, elf_path):
    script = r'''import json, os, sys
from pathlib import Path
matches = []
for item in Path('/proc').iterdir():
    if not item.name.isdigit():
        continue
    try:
        if item.stat().st_uid == os.getuid() and os.readlink(str(item / 'exe')) == sys.argv[1]:
            matches.append(int(item.name))
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
print(json.dumps(matches))
'''
    matches = json.loads(service._execute('python3 -c {} {}'.format(
        shlex.quote(script), shlex.quote(elf_path))))
    if matches:
        raise RuntimeError('Selected ELF has an existing process; refusing to start or stop PIDs {}'.format(matches))


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def ordered_statistics(summary, prefix, positive=False):
    values = [summary.get(prefix + suffix) for suffix in ('_min_ns', '_mean_ns', '_max_ns')]
    return (all(finite_number(value) for value in values)
            and (values[0] > 0 if positive else values[0] >= 0)
            and values[0] <= values[1] <= values[2])


def model_period_checks(summary, period_seconds, standalone_seconds, daq_seconds, sample_count):
    expected_ns = round(period_seconds * 1e9)
    calls = summary.get('model_step_calls', 0)
    intervals = summary.get('model_step_interval_samples')
    measured_mean = summary.get('model_step_interval_mean_ns')
    cycles = summary.get('cycles', 0)
    minimum_total = max(1, math.floor((standalone_seconds + daq_seconds) / period_seconds * .99) - 2)
    minimum_standalone = max(1, math.floor(standalone_seconds / period_seconds * .99) - 2)
    return dict(
        configured_period=summary.get('period_ns') == expected_ns,
        measured_step_mean=(finite_number(measured_mean) and abs(measured_mean - expected_ns) <= expected_ns * .01),
        step_calls_complete=(isinstance(calls, int) and calls > 0
                             and summary.get('model_step_completed_calls') == calls),
        step_interval_count=(isinstance(calls, int) and calls > 0 and intervals == calls - 1),
        step_interval_statistics=ordered_statistics(summary, 'model_step_interval', positive=True),
        step_execution_statistics=ordered_statistics(summary, 'model_step_execution'),
        measured_step_scope=summary.get('model_step_interval_scope') == 'generated_model_step_entry_to_entry',
        monotonic_clock=summary.get('measurement_clock') == 'CLOCK_MONOTONIC',
        cycle_calls_complete=(isinstance(cycles, int) and cycles > 0 and summary.get('completed_cycles') == cycles),
        cycle_interval_count=(isinstance(cycles, int) and cycles > 0 and summary.get('cycle_interval_samples') == cycles - 1),
        cycle_interval_statistics=ordered_statistics(summary, 'cycle_interval', positive=True),
        no_deadline_misses=summary.get('deadline_misses') == 0,
        no_skipped_releases=summary.get('skipped_releases') == 0,
        fifo_and_locked_memory=(summary.get('policy') == 'SCHED_FIFO' and summary.get('memory_locked') is True),
        strict_rt_kernel=(summary.get('realtime_kernel') is True and summary.get('kernel_required') is True),
        standalone_phase_duration=standalone_seconds >= STANDALONE_SECONDS,
        cycles_cover_standalone_and_daq=(isinstance(calls, int) and calls >= minimum_total
                                        and isinstance(cycles, int) and cycles >= minimum_total),
        calls_beyond_daq_cover_standalone=(isinstance(calls, int) and calls - sample_count >= minimum_standalone),
    )


def signal_statistics(samples, names):
    result = {}
    for name in names:
        values = [sample.values.get(name) for sample in samples]
        finite = bool(values) and all(finite_number(value) for value in values)
        result[name] = dict(count=len(values), all_finite=finite,
                            minimum=min(values) if finite else None,
                            maximum=max(values) if finite else None,
                            repeat_fraction=(sum(a == b for a, b in zip(values, values[1:])) / (len(values) - 1)
                                             if len(values) > 1 else None))
    return result


def daq_integrity_checks(metadata, diagnostics, period_seconds, daq_seconds,
                         sample_count, statistics, names, calibration, multirate):
    expected_samples = max(2, math.floor(daq_seconds / period_seconds * .95))
    checks = dict(
        metadata_period=(finite_number(metadata.get('period_seconds'))
                         and abs(metadata['period_seconds'] - period_seconds) < 1e-12),
        sufficient_samples=sample_count >= expected_samples,
        drained_all_samples=(diagnostics.get('received_samples') == sample_count
                             and diagnostics.get('queued_samples') == 0),
        dynamic_primary_signal=(bool(names) and statistics[names[0]]['all_finite']
                                and statistics[names[0]]['maximum'] - statistics[names[0]]['minimum'] > 1e-12),
        calibration_write_readback=calibration.get('write_readback_ok') is True,
        calibration_restore_readback=calibration.get('restore_readback_ok') is True,
        calibration_write_daq_continues=calibration.get('write_daq_continues') is True,
        calibration_restore_daq_continues=calibration.get('restore_daq_continues') is True,
        no_calibration_cleanup_errors=not calibration.get('cleanup_errors'),
        no_reported_host_errors=not diagnostics.get('host_error'),
    )
    checks.update({'no_' + name: diagnostics.get(name) == 0 for name in DAQ_ERROR_COUNTERS})
    if multirate:
        slow = statistics.get(names[1], {}) if len(names) == 2 else {}
        repeat = slow.get('repeat_fraction')
        checks['multirate_10ms_hold'] = (slow.get('all_finite') is True and finite_number(repeat)
                                       and .8 <= repeat <= .98
                                       and slow['maximum'] > slow['minimum'])
    return checks


def process_checks(snapshot, summary):
    return dict(
        process_memory_locked=snapshot.get('vm_locked_kb', 0) > 0,
        model_thread_fifo_affinity=any(
            thread.get('policy') == 'SCHED_FIFO'
            and thread.get('priority') == summary.get('priority')
            and thread.get('affinity') == [summary.get('cpu')]
            for thread in snapshot.get('threads', [])),
        process_limits_recorded=bool(snapshot.get('limits')),
    )


def wait_for_sample_progress(vm, observed, previous, period_seconds):
    deadline = time.monotonic() + max(1.0, period_seconds * 4)
    while time.monotonic() < deadline:
        observed.extend(vm.drain_daq())
        if vm.daq_active and vm.daq_diagnostics['received_samples'] >= previous + 2:
            return True
        time.sleep(.01)
    return False


def calibrate_during_daq(vm, observed, period_seconds, record):
    record['initial'] = vm.read_calibrations(['CalOffset'])['CalOffset']
    restored = False
    try:
        before = vm.daq_diagnostics['received_samples']
        active_before = vm.daq_active
        record['write_result'] = vm.write_calibrations({'CalOffset': .25})
        record['write_readback'] = vm.read_calibrations(['CalOffset'])['CalOffset']
        record['write_readback_ok'] = math.isclose(record['write_readback'], .25, rel_tol=0, abs_tol=1e-7)
        record['write_daq_continues'] = active_before and wait_for_sample_progress(vm, observed, before, period_seconds)
        record['samples_before_write'] = before
        record['samples_after_write'] = vm.daq_diagnostics['received_samples']
        before = vm.daq_diagnostics['received_samples']
        active_before = vm.daq_active
        record['restore_result'] = vm.restore_calibrations(['CalOffset'])
        record['restore_readback'] = vm.read_calibrations(['CalOffset'])['CalOffset']
        record['restore_readback_ok'] = math.isclose(record['restore_readback'], record['initial'], rel_tol=0, abs_tol=1e-7)
        restored = record['restore_readback_ok']
        record['restore_daq_continues'] = active_before and wait_for_sample_progress(vm, observed, before, period_seconds)
        record['samples_before_restore'] = before
        record['samples_after_restore'] = vm.daq_diagnostics['received_samples']
    finally:
        if not restored:
            cleanup_operation(record, 'calibration_restore', lambda: vm.restore_calibrations(['CalOffset']))


def run_model(service, folder, model, index, seconds, record, vm_factory=HostViewModel, ssh_reconnect=None):
    vm = vm_factory()
    started = False
    status = None
    observed = []
    names = []
    period = float(model['period_seconds'])
    multirate = model['model'] == 'x280_rt_multirate'
    port = model.get('xcp_port', 17731 + index)
    remote_elf = str(PurePosixPath(model['remote_directory']) / (model['model'] + '.elf'))
    record.update(model=model['model'], period_seconds=period, port=port, remote_elf=remote_elf,
                  model_checks={}, daq_checks={}, cleanup_errors=[], calibration={})
    try:
        status = select_stopped_model(service, remote_elf)
        reject_untracked_process(service, status['elf_path'])
        record['log_start_bytes'] = log_offset(service, status['log_path'])
        started = True
        pid = service.start(remote_elf, '' if model.get('build_mode') == 'local' else '-port ' + str(port))
        record['pid'] = pid
        record['process_before_standalone'] = process_snapshot(service, pid, status['elf_path'])
        if ssh_reconnect is not None:
            service.close()
        standalone_start = time.monotonic()
        time.sleep(STANDALONE_SECONDS)
        record['standalone_seconds'] = time.monotonic() - standalone_start
        if ssh_reconnect is not None:
            ssh_reconnect()
        record['process_after_standalone'] = process_snapshot(service, pid, status['elf_path'])
        if ssh_reconnect is not None:
            record['ssh_disconnected_autonomous'] = all(
                record['process_before_standalone'][key] == record['process_after_standalone'][key]
                for key in ('pid', 'elf_path', 'start_time_ticks'))
        record['standalone_evidence_scope'] = ('No XCP connection during the timed initial phase. '
            'Total measured model calls must cover standalone plus DAQ elapsed time, '
            'and calls exceeding received DAQ samples must cover the standalone phase; '
            'this is aggregate evidence, not a separate per-phase model-call counter.')
        payload = folder / model['payload'] / (model['model'] + '.a2l')
        vm.load_a2l(payload)
        vm.connect('UDP', model.get('host', HOST), port)
        names = required_measurements(vm.measurements, multirate)
        record['daq_metadata'] = vm.start_daq(names)
        daq_start = time.monotonic()
        deadline = daq_start + seconds
        calibration_at = daq_start + min(1.0, seconds / 4)
        calibrated = False
        while time.monotonic() < deadline:
            observed.extend(vm.drain_daq())
            if not calibrated and time.monotonic() >= calibration_at:
                calibrate_during_daq(vm, observed, period, record['calibration'])
                calibrated = True
            time.sleep(.01)
        record['daq_seconds'] = time.monotonic() - daq_start
        record['process_during_daq'] = process_snapshot(service, pid, status['elf_path'])
        vm.stop_daq()
        observed.extend(vm.drain_daq(20000))
        record['daq'] = dict(vm.daq_diagnostics, host_error=vm.last_error)
        record['sample_count'] = len(observed)
        record['signals'] = signal_statistics(observed, names)
        record['daq_checks'] = daq_integrity_checks(record['daq_metadata'], record['daq'], period,
            record['daq_seconds'], len(observed), record['signals'], names, record['calibration'], multirate)
    except BaseException as error:
        record['error'] = dict(error_type=type(error).__name__, error=str(error))
        if not isinstance(error, Exception):
            raise
    finally:
        cleanup_operation(record, 'xcp_close', vm.close)
        if started:
            cleanup_operation(record, 'model_stop', service.stop)
            if status is not None and 'log_start_bytes' in record:
                def collect_runtime():
                    record['target_log'] = remote_log_evidence(service, status['log_path'], record['log_start_bytes'])
                    summary = record['target_log']['runtime']
                    if summary is None or record['target_log']['summary_count'] != 1:
                        raise ValueError('Exactly one fresh runtime summary is required')
                    record['runtime'] = summary
                    record['model_checks'] = model_period_checks(summary, period,
                        record.get('standalone_seconds', 0), record.get('daq_seconds', 0), len(observed))
                    record['model_checks']['no_new_target_error_lines'] = record['target_log']['error_line_count'] == 0
                    if 'process_during_daq' in record:
                        record['model_checks'].update(process_checks(record['process_during_daq'], summary))
                cleanup_operation(record, 'runtime_evidence', collect_runtime)
        record['model_passed'] = (bool(record['model_checks']) and all(record['model_checks'].values())
                                  and not record['cleanup_errors'] and 'runtime' in record)
        record['daq_passed'] = bool(record['daq_checks']) and all(record['daq_checks'].values()) and not record.get('error')
        record['passed'] = record['model_passed'] and record['daq_passed'] and not record.get('error')


def validate_build(build):
    expected = {'x280_rt_single': .001}
    models = build.get('models', [])
    if len(models) != len(expected) or {model.get('model') for model in models} != set(expected):
        raise ValueError('Build report must contain exactly one x280_rt_single (1 ms) model')
    directories = set()
    for model in models:
        if model.get('period_seconds') != expected[model['model']]:
            raise ValueError('Unexpected model period for ' + model['model'])
        remote = PurePosixPath(model['remote_directory'])
        if '..' in remote.parts or len(remote.parts) < 2 or str(remote) in directories:
            raise ValueError('Each model requires a distinct dedicated remote directory')
        directories.add(str(remote))
        if Path(model['payload']).name != model['payload'] or model['payload'] in ('', '.', '..'):
            raise ValueError('Payload must be a folder basename')
    return models


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds < 3:
        parser.error('--seconds must be finite and at least 3')
    folder, output = args.folder.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, created_utc=datetime.now(timezone.utc).isoformat(),
                  host=HOST, username='zh', requested_daq_seconds=args.seconds,
                  requested_standalone_seconds=STANDALONE_SECONDS,
                  timing_scope='Finite soft real-time test; no hard real-time guarantee',
                  models=[], cleanup_errors=[])
    # Reserve a new report before any remote activity; existing evidence is never overwritten.
    with output.open('x', encoding='utf-8') as report_file:
        json.dump(report, report_file, indent=2)
        report_file.flush()
        service = SSHDeployment()
        try:
            models = validate_build(json.loads((folder / 'build_report.json').read_text(encoding='utf-8')))
            password = getpass.getpass('SSH password: ')
            try:
                service.connect(HOST, 'zh', password=password)
            finally:
                password = None
            report['kernel'] = service._execute('uname -r').strip()
            for index, model in enumerate(models):
                record = {}
                report['models'].append(record)
                run_model(service, folder, model, index, args.seconds, record)
                print(json.dumps(record), flush=True)
                if record['cleanup_errors']:
                    raise RuntimeError('Model cleanup or evidence failed; no further models will be started')
        except BaseException as error:
            report['error'] = dict(error_type=type(error).__name__, error=str(error))
            raise
        finally:
            cleanup_operation(report, 'ssh_close', service.close)
            report['passed'] = (len(report['models']) == 1 and all(item.get('passed') for item in report['models'])
                                and not report['cleanup_errors'] and not report.get('error'))
            report['finished_utc'] = datetime.now(timezone.utc).isoformat()
            report_file.seek(0)
            json.dump(report, report_file, indent=2)
            report_file.truncate()
            report_file.flush()
    if not report['passed']:
        raise AssertionError('Model period or DAQ acceptance checks failed; report: ' + str(output))
    print('Validation passed; report: ' + str(output))


if __name__ == '__main__':
    main()
