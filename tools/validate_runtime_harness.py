"""Isolated current-runtime tests; never select models or alter autostart."""

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shlex
import sys
import uuid

from validate_realtime_models import (ROOT, SSHDeployment, HARNESS_MATH_TESTS,
    HARNESS_REJECTION_MESSAGES, build_current_harness, cleanup_operation, summary_from_log)

sys.excepthook = sys.__excepthook__

_CASE_RUNNER = r'''import json, os, signal, subprocess, sys, time
request = json.loads(sys.argv[1])
result = dict(returncode=None, timed_out=False, sent_sigterm=False, forced_kill=False, output='')
child = None
try:
    environment = dict(os.environ, X280_RT_REQUIRE_KERNEL='1')
    child = subprocess.Popen(request['arguments'], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=environment)
    if request['sigterm']:
        time.sleep(0.4)
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
            result['sent_sigterm'] = True
    try:
        result['output'] = child.communicate(timeout=request['timeout'])[0]
    except subprocess.TimeoutExpired:
        result['timed_out'] = True
        child.terminate()
        try:
            result['output'] = child.communicate(timeout=3)[0]
        except subprocess.TimeoutExpired:
            child.kill()
            result['forced_kill'] = True
            result['output'] = child.communicate(timeout=3)[0]
    result['returncode'] = child.returncode
except BaseException as error:
    result['error'] = dict(error_type=type(error).__name__, error=str(error))
finally:
    if child is not None and child.poll() is None:
        child.kill()
        result['forced_kill'] = True
        child.communicate(timeout=3)
    print(json.dumps(result))
'''


def run_remote_case(service, remote_dir, harness, arguments, sigterm=False, timeout=15):
    request = dict(arguments=[harness] + arguments, sigterm=sigterm, timeout=timeout)
    command = 'python3 -c {} {}'.format(shlex.quote(_CASE_RUNNER), shlex.quote(json.dumps(request)))
    # SSHDeployment's build wrapper terminates this child process group on cancellation.
    return json.loads(service.build(remote_dir, command, timeout=timeout + 15))


def assess_runtime(summary, period_ms, mode, expected_calls=None):
    calls = summary.get('model_step_calls', 0)
    period_ns = period_ms * 1000000
    mean = summary.get('model_step_interval_mean_ns')
    checks = dict(
        period=summary.get('period_ns') == period_ns,
        kernel=summary.get('realtime_kernel') is True and summary.get('kernel_required') is True,
        fifo_mlock=summary.get('policy') == 'SCHED_FIFO' and summary.get('memory_locked') is True,
        cycles_completed=summary.get('cycles', 0) > 0 and summary.get('completed_cycles') == summary.get('cycles'),
        model_steps_completed=calls > 0 and summary.get('model_step_completed_calls') == calls,
        model_step_intervals=calls > 0 and summary.get('model_step_interval_samples') == calls - 1,
        model_step_scope=summary.get('model_step_interval_scope') == 'generated_model_step_entry_to_entry',
        monotonic_clock=summary.get('measurement_clock') == 'CLOCK_MONOTONIC',
    )
    if expected_calls is not None:
        checks['expected_calls'] = calls == expected_calls
    if mode == 'overrun':
        checks['overrun_reported'] = summary.get('deadline_misses', 0) >= 10 and summary.get('skipped_releases', 0) > 0
    else:
        checks['no_deadline_misses'] = summary.get('deadline_misses') == 0
        checks['no_skipped_releases'] = summary.get('skipped_releases') == 0
        checks['measured_period'] = (isinstance(mean, (int, float)) and math.isfinite(mean)
                                     and abs(mean - period_ns) <= period_ns * .01)
    checks['stop_signal'] = summary.get('stop_signal') == (15 if mode == 'sigterm' else 0)
    if mode == 'sigterm':
        checks['stopped_before_natural_limit'] = 0 < calls < 60000
    return checks


def run_suite(service, remote_dir, harness, records=None):
    records = [] if records is None else records
    cases = [('math', ['--math'], None, None),
             ('bad_period', ['--bad-period'], None, None),
             ('bad_subrates', ['--bad-subrates'], None, None)]
    cases += [('normal_{}ms'.format(period), ['--period-ms', str(period), '--normal-load', '--cycles', str(calls)],
               period, calls) for period, calls in [(1, 2000), (10, 200), (100, 30)]]
    cases += [('overrun', ['--period-ms', '1', '--cycles', '200'], 1, 200),
              ('sigterm', ['--period-ms', '1', '--normal-load', '--long'], 1, None)]
    for name, arguments, period, calls in cases:
        record = dict(name=name, arguments=arguments, checks={}, passed=False)
        records.append(record)
        result = run_remote_case(service, remote_dir, harness, arguments, sigterm=name == 'sigterm')
        record['result'] = result
        checks = record['checks']
        checks['clean_process_exit'] = not result.get('error') and not result['timed_out'] and not result['forced_kill']
        try:
            if name == 'math':
                value = json.loads(result['output'])
                checks['math16'] = (result['returncode'] == 0 and value.get('event') == 'x280_rt_math_tests'
                                    and value.get('passed') == HARNESS_MATH_TESTS)
            elif name.startswith('bad_'):
                checks['rejected'] = (result['returncode'] not in (0, None)
                                      and HARNESS_REJECTION_MESSAGES[arguments[0]] in result['output'])
            else:
                record['runtime'] = summary_from_log(result['output'])
                checks['success_exit'] = result['returncode'] == 0
                checks.update(assess_runtime(record['runtime'], period, name if name in ('overrun', 'sigterm') else 'normal', calls))
                if name == 'sigterm':
                    checks['sigterm_sent'] = result['sent_sigterm'] is True
        except (ValueError, TypeError, KeyError) as error:
            record['error'] = dict(error_type=type(error).__name__, error=str(error))
        record['passed'] = all(checks.values()) and not record.get('error')
        print(json.dumps(record), flush=True)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True, help='Build report folder; existing model bundle supplies headers only')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, created_utc=datetime.now(timezone.utc).isoformat(),
                  host='192.168.219.86', checks={}, cases=[], cleanup_errors=[],
                  timing_scope='Finite runtime harness tests; not a hard real-time guarantee')
    with output.open('x', encoding='utf-8') as report_file:
        json.dump(report, report_file, indent=2)
        report_file.flush()
        service = SSHDeployment()
        try:
            build = json.loads((args.folder / 'build_report.json').read_text(encoding='utf-8'))
            password = getpass.getpass('SSH password: ')
            try:
                service.connect(report['host'], 'zh', password=password)
            finally:
                password = None
            report['kernel'] = service._execute('uname -r').strip()
            header_dir = str(PurePosixPath(service._home, build['models'][0]['remote_directory'], 'src'))
            remote_dir = 'MATLAB_ws/runtime_harness_' + uuid.uuid4().hex
            report['remote_directory'] = str(PurePosixPath(service._home, remote_dir))
            report['header_directory'] = header_dir
            sources = {'runtime/x280_rt_runtime.c': ROOT / 'x280_linux_target/src/x280_rt_runtime.c',
                       'rt_runtime_harness.c': ROOT / 'x280_linux_target/tests/rt_runtime_harness.c'}
            report['local_source_sha256'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in sources.items()}
            report['build_output'] = build_current_harness(service, remote_dir, header_dir)
            hash_script = ('import hashlib,json; from pathlib import Path; '
                           'print(json.dumps({name:hashlib.sha256(Path(name).read_bytes()).hexdigest() '
                           'for name in ["runtime/x280_rt_runtime.c", "rt_runtime_harness.c"]}))')
            report['remote_source_sha256'] = json.loads(service.build(remote_dir, 'python3 -c ' + shlex.quote(hash_script)))
            report['checks']['current_source_hashes'] = report['local_source_sha256'] == report['remote_source_sha256']
            harness = str(PurePosixPath(report['remote_directory'], 'rt_runtime_harness'))
            run_suite(service, remote_dir, harness, report['cases'])
        except BaseException as error:
            report['error'] = dict(error_type=type(error).__name__, error=str(error))
            raise
        finally:
            cleanup_operation(report, 'ssh_close', service.close)
            report['passed'] = (len(report['cases']) == 8 and all(case['passed'] for case in report['cases'])
                                and all(report['checks'].values()) and not report.get('error') and not report['cleanup_errors'])
            report['finished_utc'] = datetime.now(timezone.utc).isoformat()
            report_file.seek(0)
            json.dump(report, report_file, indent=2)
            report_file.truncate()
            report_file.flush()
    if not report['passed']:
        raise AssertionError('Runtime harness checks failed; report: ' + str(output))
    print('Runtime harness passed; report: ' + str(output))


if __name__ == '__main__':
    main()
