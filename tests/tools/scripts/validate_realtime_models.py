"""Shared evidence and cleanup helpers for local-build model validation."""

import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.viewmodel import HostViewModel
sys.excepthook = sys.__excepthook__

HARNESS_MATH_TESTS = 38
HARNESS_REJECTION_MESSAGES = {
    '--bad-period': 'runtime requires a 1 ms, 10 ms, or 100 ms model base period',
    '--bad-subrates': 'runtime requires exactly one model task',
}




def summary_from_log(text):
    for line in reversed(text.splitlines()):
        if line.startswith('{'):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict) and value.get('event') == 'simrt_rt_summary':
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




