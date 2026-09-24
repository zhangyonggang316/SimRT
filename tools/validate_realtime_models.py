"""Opt-in 1 ms model/DAQ timing validation without disturbing existing models."""

import argparse
import getpass
import json
from pathlib import Path
import shlex
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.viewmodel import HostViewModel
sys.excepthook = sys.__excepthook__

HARNESS_MATH_TESTS = 16
HARNESS_REJECTION_MESSAGES = {
    '--bad-period': 'runtime requires a 1 ms, 10 ms, or 100 ms model base period',
    '--bad-subrates': 'runtime requires exactly one model task',
}


def build_current_harness(service, harness_dir, header_directory):
    service.upload(ROOT / 'x280_linux_target' / 'tests', harness_dir)
    service.upload(ROOT / 'x280_linux_target' / 'src', harness_dir + '/runtime')
    command = ('gcc -O2 -Wall -Wextra -pthread -DMT=0 -I{headers} runtime/x280_rt_runtime.c '
               'rt_runtime_harness.c -Wl,--wrap=sem_wait -Wl,--wrap=sem_post -o rt_runtime_harness').format(
                   headers=shlex.quote(header_directory))
    return service.build(harness_dir, command)


def summary_from_log(text):
    for line in reversed(text.splitlines()):
        if line.startswith('{'):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get('event') == 'x280_rt_summary':
                return value
    raise ValueError('Runtime timing summary was not emitted')


def log_offset(service, path):
    script = ('import os, sys; path = sys.argv[1]; '
              'print(os.path.getsize(path) if os.path.isfile(path) else 0)')
    return int(service._execute('python3 -c {} {}'.format(
        shlex.quote(script), shlex.quote(path))).strip())


def new_log_text(service, path, offset):
    script = '''import os, sys
path, offset = sys.argv[1], int(sys.argv[2])
with open(path, 'rb') as stream:
    if os.fstat(stream.fileno()).st_size < offset:
        raise RuntimeError('Runtime log was truncated during validation')
    # The final summary is small. Keep the response bounded even when a target
    # emits a diagnostic for every sample; never include bytes from an older run.
    stream.seek(max(offset, os.fstat(stream.fileno()).st_size - 16384))
    sys.stdout.buffer.write(stream.read(16384))
'''
    return service._execute('python3 -c {} {} {}'.format(
        shlex.quote(script), shlex.quote(path), offset))


def required_measurements(measurements, multirate):
    suffixes = ['_B.MeasuredOutput']
    if multirate:
        suffixes.append('_B.SlowSampledOutput')
    names = []
    for suffix in suffixes:
        matches = [item.name for item in measurements if item.name.endswith(suffix)]
        if len(matches) != 1:
            raise ValueError('Expected exactly one measurement ending with {}, found {}'.format(
                suffix, len(matches)))
        names.append(matches[0])
    return names


def runtime_checks(summary, baseline):
    return dict(
        runtime_period_1ms=summary.get('period_ns') == 1000000,
        cycles_completed=(summary.get('cycles', 0) > 0
                          and summary.get('completed_cycles') == summary.get('cycles')),
        fifo_mlock=(summary.get('policy') == 'SCHED_FIFO'
                    and summary.get('memory_locked') is True),
        kernel=(baseline or (summary.get('realtime_kernel') is True
                             and summary.get('kernel_required') is True)),
        timing_counters=(isinstance(summary.get('deadline_misses'), int)
                         and summary['deadline_misses'] >= 0
                         and isinstance(summary.get('skipped_releases'), int)
                         and summary['skipped_releases'] >= 0),
    )


def select_stopped_model(service, remote_elf):
    status = service.status(remote_elf)
    if status['running']:
        raise RuntimeError('Selected model is already running (PID {}); validation will not reuse or stop it'.format(
            status.get('pid')))
    return status


def cleanup_operation(report, name, operation):
    try:
        operation()
    except BaseException as error:
        report.setdefault('cleanup_errors', []).append(dict(
            operation=name, error_type=type(error).__name__, error=str(error)))


def finish_validation(service, vm, report, original_autostart, started_model, autostart_touched):
    cleanup_operation(report, 'xcp_close', vm.close)
    try:
        if service.connected:
            if started_model:
                cleanup_operation(report, 'model_stop', service.stop)
            if autostart_touched and original_autostart is not None:
                old_path = original_autostart.get('elf_path', '')
                if old_path:
                    cleanup_operation(report, 'autostart_restore_selection', lambda: service.set_autostart(
                        old_path, shlex.join(original_autostart.get('arguments', []))))
                if not original_autostart['enabled']:
                    cleanup_operation(report, 'autostart_restore_disabled', lambda: service.set_autostart(None))
        elif started_model or autostart_touched:
            report.setdefault('cleanup_errors', []).append(dict(
                operation='remote_cleanup', error_type='ConnectionError',
                error='SSH disconnected before model/autostart cleanup could be confirmed'))
    finally:
        cleanup_operation(report, 'ssh_close', service.close)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    folder = args.folder.resolve()
    build = json.loads((folder / 'build_report.json').read_text())
    service = SSHDeployment()
    vm = HostViewModel()
    password = getpass.getpass('SSH password: ')
    report = dict(passed=False, baseline=args.baseline, checks={}, models=[], cleanup_errors=[],
                  timing_scope='Soft real-time measurements; deadline misses are reported, not a hard real-time guarantee')
    original_autostart = None
    started_model = False
    autostart_touched = False
    try:
        service.connect('192.168.219.86', 'zh', password=password)
        password = None
        report['kernel'] = service._execute('uname -r').strip()
        original_autostart = service.autostart_status()
        harness_dir = 'MATLAB_ws/rt_harness_' + uuid.uuid4().hex[:12]
        source = '/home/zh/' + build['models'][0]['remote_directory'] + '/src'
        build_current_harness(service, harness_dir, source)
        harness = '/home/zh/' + harness_dir + '/rt_runtime_harness'
        report['harness_math'] = service._execute(shlex.quote(harness) + ' --math')
        math_result = json.loads(report['harness_math'])
        report['checks']['harness_math'] = (math_result.get('event') == 'x280_rt_math_tests'
                                            and math_result.get('passed') == HARNESS_MATH_TESTS)
        for option in ('--bad-period', '--bad-subrates'):
            try:
                service._execute(shlex.quote(harness) + ' ' + option)
                report['checks'][option] = False
            except RuntimeError as error:
                report['checks'][option] = HARNESS_REJECTION_MESSAGES[option] in str(error)
        harness_environment = 'env X280_RT_REQUIRE_KERNEL=0 ' if args.baseline else ''
        report['harness_overrun'] = summary_from_log(service._execute(
            harness_environment + shlex.quote(harness)))
        report['checks']['overrun_is_reported'] = (
            report['harness_overrun']['skipped_releases'] > 0
            and report['harness_overrun']['deadline_misses'] > 0)
        report['checks'].update({'harness_' + key: value for key, value in runtime_checks(
            report['harness_overrun'], args.baseline).items()})

        for index, model in enumerate(build['models']):
            name = model['model']
            payload = folder / ('single_payload' if index == 0 else 'multirate_payload')
            remote_elf = model['remote_directory'] + '/' + name + '.elf'
            port = 17727 + index
            record = dict(model=name, port=port)
            report['models'].append(record)
            environment = {'X280_RT_REQUIRE_KERNEL': '0'} if args.baseline else None
            status = select_stopped_model(service, remote_elf)
            record['log_start_bytes'] = log_offset(service, status['log_path'])
            # Cleanup may be necessary even if SSH fails after the remote start succeeds.
            started_model = True
            service.start(remote_elf, '-port ' + str(port), runtime_environment=environment)
            vm.load_a2l(payload / (name + '.a2l'))
            vm.connect('UDP', '192.168.219.86', port)
            names = required_measurements(vm.measurements, multirate=bool(index))
            report['checks'][name + '_required_signals'] = True
            record['daq_metadata'] = vm.start_daq(names)
            report['checks'][name + '_period_1ms'] = abs(record['daq_metadata']['period_seconds'] - .001) < 1e-12
            report['checks'][name + '_calibration_independent'] = False
            deadline = time.monotonic() + max(3, args.seconds)
            calibrated = False
            observed = []
            while time.monotonic() < deadline:
                observed.extend(vm.drain_daq())
                if not calibrated and len(observed) > 500:
                    before = vm.daq_diagnostics['received_samples']
                    vm.write_calibrations({'CalOffset': .25})
                    vm.restore_calibrations()
                    time.sleep(.03)
                    report['checks'][name + '_calibration_independent'] = vm.daq_active and vm.daq_diagnostics['received_samples'] > before
                    calibrated = True
                time.sleep(.02)
            vm.stop_daq()
            observed.extend(vm.drain_daq())
            record['daq'] = vm.daq_diagnostics
            record['sample_count'] = len(observed)
            report['checks'][name + '_samples'] = len(observed) > 500
            if index:
                slow = [sample.values[names[1]] for sample in observed]
                record['slow_repeat_fraction'] = sum(a == b for a,b in zip(slow, slow[1:])) / max(1, len(slow)-1)
                report['checks']['multirate_10ms_hold'] = record['slow_repeat_fraction'] > .8
            vm.disconnect()
            service.stop()
            started_model = False
            record['runtime'] = summary_from_log(new_log_text(
                service, status['log_path'], record['log_start_bytes']))
            report['checks'].update({name + '_' + key: value for key, value in runtime_checks(
                record['runtime'], args.baseline).items()})
            autostart_touched = True
            record['autostart'] = service.set_autostart(remote_elf, '-port ' + str(port))
            report['checks'][name + '_autostart_selection'] = record['autostart']['enabled'] and record['autostart']['elf_path'].endswith('/' + name + '.elf')
            report['checks'][name + '_autostart_does_not_launch'] = not service.status()['running']
            print(json.dumps(record), flush=True)
    except BaseException as error:
        report['error'] = dict(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        cleanup_operation(report, 'validation_cleanup', lambda: finish_validation(
            service, vm, report, original_autostart, started_model, autostart_touched))
        report['passed'] = (bool(report['checks']) and all(report['checks'].values())
                            and not report.get('error') and not report['cleanup_errors'])
        destination = folder / ('baseline_validation.json' if args.baseline else 'rt_validation.json')
        destination.write_text(json.dumps(report, indent=2), encoding='utf-8')
    if not report['passed']:
        raise AssertionError('Realtime validation checks failed')
    print('Validation passed; report: ' + str(destination))


if __name__ == '__main__':
    main()
