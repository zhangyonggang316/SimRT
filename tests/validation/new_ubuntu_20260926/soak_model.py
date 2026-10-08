"""Exercise the real APP services and live status; generic-kernel runs are diagnostic only."""

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'qt_xcp_host')]
from pyxcp_host.services.payload_archive import PayloadArchive
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.viewmodel import HostViewModel
from validate_model_periods import calibrate_during_daq
from validate_realtime_models import required_measurements, summary_from_log
from target_session import HOST, USER, connect


def host_resources():
    command = ("Get-Process -Id " + str(os.getpid()) +
               " | Select-Object Id,WorkingSet64,PrivateMemorySize64,HandleCount,"
               "@{Name='ThreadCount';Expression={$_.Threads.Count}} | ConvertTo-Json -Compress")
    process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                             capture_output=True, text=True, timeout=15, check=True)
    result = json.loads(process.stdout)
    assert result['Id'] == os.getpid() and result['WorkingSet64'] > 0
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--seconds', type=float, default=5400)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-non-rt-diagnostic', action='store_true')
    args = parser.parse_args()
    if args.output.exists() or args.seconds < 30:
        parser.error('Use a new evidence file and at least 30 seconds')
    password = getpass.getpass('SSH password: ')
    pinned = connect(password)
    pinned.close()
    archives, service, vm = PayloadArchive(), SSHDeployment(), HostViewModel()
    report = dict(started_utc=datetime.now(timezone.utc).isoformat(), host=HOST,
                  host_process_id=os.getpid(), initial_host_resources=host_resources(),
                  diagnostic_only=args.allow_non_rt_diagnostic, strict_realtime_acceptance=False,
                  requested_seconds=args.seconds, cycles=[], cleanup_errors=[], passed=False)
    remote_elf = None
    cycle = None

    def persist():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        temporary.replace(args.output)

    def reconnect():
        service.connect(HOST, USER, password=password)

    def snapshot(pid):
        with service._client.open_sftp() as sftp:
            with sftp.open(remote_elf + '.simrt-status.json', 'r') as stream:
                result = json.loads(stream.read(65536))
        assert result['pid'] == pid and result['state'] == 'RUNNING'
        assert result['model_step_completed_calls'] == result['model_step_calls']
        assert result['model_step_execution_current_ns'] <= result['model_step_execution_max_ns']
        return result

    persist()
    try:
        payload = archives.load(args.archive)
        assert payload['model'] == 'simrt_rt_single' and payload['port'] == 17725
        report['archive'] = str(args.archive.resolve())
        reconnect()
        report['kernel'] = service._execute('uname -r').strip()
        probe = "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.bind(('0.0.0.0',17725));s.close()"
        service._execute('python3 -c ' + shlex.quote(probe))
        remote = 'MATLAB_ws/console_soak_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        report['deployment'] = service.deploy_payload(payload['directory'], remote)
        remote_elf = report['deployment']['remote_directory'] + '/simrt_rt_single.elf'
        if args.allow_non_rt_diagnostic:
            try:
                service.start(remote_elf)
            except RuntimeError:
                log = service.read_log()
                assert 'PREEMPT_RT kernel required' in log and not service.status()['running']
                report['strict_kernel_guard'] = dict(passed=True, log=log)
            else:
                service.stop()
                raise RuntimeError('Diagnostic run expected the installed generic kernel')
        environment = {'SIMRT_RT_REQUIRE_KERNEL': '0'} if args.allow_non_rt_diagnostic else None
        pid = service.start(remote_elf, runtime_environment=environment)
        report['pid'] = pid
        vm.load_a2l(payload['a2l'])
        names = required_measurements(vm.measurements, False)
        started = time.monotonic()
        time.sleep(1.2)
        while time.monotonic() - started < args.seconds:
            cycle = dict(index=len(report['cycles']), started_utc=datetime.now(timezone.utc).isoformat())
            cycle['before'] = snapshot(pid)
            vm.connect('UDP', HOST, payload['port'])
            vm.start_daq(names)
            observed = []
            calibration = {}
            calibrate_during_daq(vm, observed, .001, calibration)
            cycle['calibration'] = calibration
            deadline = time.monotonic() + min(30, args.seconds - (time.monotonic() - started))
            while time.monotonic() < deadline:
                observed.extend(vm.drain_daq())
                time.sleep(.02)
            vm.stop_daq()
            observed.extend(vm.drain_daq(20000))
            cycle['daq'] = dict(vm.daq_diagnostics)
            cycle['sample_count'] = len(observed)
            values = [item.values[names[0]] for item in observed if names[0] in item.values]
            cycle['dynamic_signal'] = len(values) >= 10 and max(values) > min(values)
            assert cycle['dynamic_signal']
            assert calibration['write_readback_ok'] and calibration['restore_readback_ok']
            assert calibration['write_daq_continues'] and calibration['restore_daq_continues']
            vm.disconnect()
            cycle['before_disconnect'] = snapshot(pid)
            service.close()
            time.sleep(min(15, max(0, args.seconds - (time.monotonic() - started))))
            reconnect()
            current = service.status(remote_elf)
            assert current['running'] and current['pid'] == pid
            cycle['after_disconnect'] = snapshot(pid)
            cycle['autonomous_step_progress'] = (
                cycle['after_disconnect']['model_step_calls'] > cycle['before_disconnect']['model_step_calls'])
            if time.monotonic() - started < args.seconds:
                assert cycle['autonomous_step_progress']
            cycle['passed'] = True
            cycle['host_resources'] = host_resources()
            report['cycles'].append(cycle)
            report['elapsed_seconds'] = time.monotonic() - started
            persist()
            print(json.dumps(dict(cycle=cycle['index'], samples=cycle['sample_count'],
                                  elapsed_seconds=report['elapsed_seconds'], passed=True)), flush=True)
        report['passed'] = bool(report['cycles'])
    except Exception as error:
        report['error'] = '{}: {}'.format(type(error).__name__, error)
        if cycle and not cycle.get('passed'):
            report['failed_cycle'] = cycle
        print(report['error'], flush=True)
    finally:
        try:
            vm.close()
        except Exception as error:
            report['cleanup_errors'].append('XCP restore/disconnect: ' + str(error))
        if remote_elf:
            try:
                if not service.connected:
                    reconnect()
                service.stop()
                log = service.read_log()
                report['target_log'] = log
                report['runtime'] = summary_from_log(log)
                report['stopped'] = not service.status()['running']
            except Exception as error:
                report['cleanup_errors'].append('Model stop/report: ' + str(error))
        service.close()
        archives.close()
        try:
            report['final_host_resources'] = host_resources()
        except Exception as error:
            report['cleanup_errors'].append('Host resource sample: ' + str(error))
        report['passed'] = bool(report['passed'] and not report.get('error') and not report['cleanup_errors'])
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        persist()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
