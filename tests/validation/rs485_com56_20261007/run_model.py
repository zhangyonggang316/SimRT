"""Run the generated COM5/6 model briefly, capture counters, then restore state."""
import argparse
import json
from pathlib import Path
import shlex
import sys
import time
import uuid

from preflight import AUDIT, ROOT, SSHDeployment, credentials, sudo_python
from pyxcp_host.services.payload_archive import PayloadArchive
from pyxcp_host.viewmodel import HostViewModel

sys.path.insert(0, str(ROOT / 'tools'))
from validate_realtime_models import summary_from_log

SERIAL_STATE = r'''
import array, fcntl, json, os, termios
records = []
for path in ('/dev/ttyS6', '/dev/ttyS7'):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if RESTORE is not None:
            saved = next(item for item in RESTORE if item['device'] == path)
            termios.tcflush(fd, termios.TCIOFLUSH)
            termios.tcsetattr(fd, termios.TCSANOW, saved['termios'])
            current = array.array('I', [0]*8)
            fcntl.ioctl(fd, 0x542e, current, True)
            if current.tolist() != saved['rs485']:
                fcntl.ioctl(fd, 0x542f, array.array('I', saved['rs485']))
        attrs = termios.tcgetattr(fd)
        attrs[6] = [value[0] if isinstance(value, bytes) else value for value in attrs[6]]
        words = array.array('I', [0]*8)
        fcntl.ioctl(fd, 0x542e, words, True)
        records.append(dict(device=path, termios=attrs, rs485=words.tolist()))
    finally:
        os.close(fd)
if RESTORE is not None:
    assert records == RESTORE, 'Serial configuration restore verification failed'
print(json.dumps(records))
'''


def serial_state(service, login, restore=None):
    return json.loads(sudo_python(service, login, 'RESTORE=' + repr(restore) + '\n' + SERIAL_STATE))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default='model_test')
    options = parser.parse_args()
    assert options.report.replace('_', '').isalnum(), 'Use a plain report name'
    folder = Path(__file__).parent
    destination = folder / (options.report + '.json')
    if destination.exists():
        raise FileExistsError('Preserve the prior model validation report')
    build = json.loads((folder / 'matlab_validation.json').read_text(encoding='utf-8'))['build']
    baseline = json.loads((folder / 'preflight.json').read_text(encoding='utf-8'))
    assert len(baseline['running_models']) == 1
    previous = baseline['running_models'][0]
    assert previous['arguments'] == [previous['elf']]
    login = credentials()
    service, archive, vm = SSHDeployment(), PayloadArchive(), HostViewModel()
    report = dict(passed=False, physical_test=True, measurement_seconds=10, cleanup_errors=[])
    previous_stopped = False
    candidate_selected = False
    saved_serial = None

    def save():
        destination.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')

    def cleanup(label, operation):
        try: return operation()
        except Exception as error:
            report['cleanup_errors'].append(dict(operation=label, error=str(error)))
            return None

    try:
        payload = archive.load(build['archive'])
        assert payload['model'] == 'simrt_serial_com56' and payload['port'] == 5555
        service.connect(**login)
        state = json.loads(sudo_python(service, login, AUDIT))
        assert not state['owners'] and not state['inaccessible_processes']
        assert len(state['running_models']) == 1, 'Expected only the previous model'
        current = state['running_models'][0]
        assert all(current[key] == previous[key] for key in ('elf', 'sha256', 'arguments')), 'Active model changed since preflight'
        assert service.autostart_status() == baseline['autostart']
        before = service.status(previous['elf'])
        assert before['running'] and before['pid'] == current['pid']
        assert service._request('elf', path=previous['elf'])['sha256'] == previous['sha256']
        report['previous_model'] = before
        report['archive'] = build['archive']
        report['archive_sha256'] = build['archive_sha256']
        saved_serial = serial_state(service, login)
        report['serial_before'] = saved_serial
        deployment = service.deploy_payload(payload['directory'], 'MATLAB_ws/com56_test_' + uuid.uuid4().hex[:8])
        report['deployment'] = deployment
        remote_elf = deployment['remote_directory'] + '/simrt_serial_com56.elf'
        service.stop()
        previous_stopped = True
        service.status(remote_elf)
        candidate_selected = True
        service.start(remote_elf)
        report['model_started'] = service.status()
        time.sleep(1)
        vm.load_a2l(Path(payload['a2l']))
        vm.connect('UDP', login['host'], 5555)
        expected = {'Serial_Ready', 'Serial_Healthy'}
        for label in ('COM5', 'COM6'):
            expected.update(label + suffix for suffix in (
                '_TxFrames', '_TxFailures', '_RxFrames', '_CrcErrors', '_SequenceGaps',
                '_Duplicates', '_ForeignFrames', '_LastSequence', '_RxAgeMs', '_FormatErrors',
                '_SetupStatus', '_ReadStatus', '_WriteStatus'))
        measurements = [item.name for item in vm.measurements if item.name.rsplit('.', 1)[-1] in expected]
        assert len(measurements) == len(expected), measurements
        assert {name.rsplit('.', 1)[-1] for name in measurements} == expected
        report['before_enable'] = vm.poll_measurements(measurements)
        assert all(value == 0 for name, value in report['before_enable'].items()
                   if name.endswith(('_SetupStatus', '_ReadStatus', '_TxFrames', '_RxFrames'))), 'Serial setup/read must succeed before transmission'
        assert vm.read_calibrations(['Serial_Enable'])['Serial_Enable'] == 0
        report['daq_metadata'] = vm.start_daq(measurements)
        vm.write_calibrations({'Serial_Enable': 1})
        report['enabled_readback'] = vm.read_calibrations(['Serial_Enable'])
        start = time.monotonic()
        count, first, last = 0, None, None
        while time.monotonic() - start < report['measurement_seconds']:
            samples = vm.drain_daq()
            if samples:
                if first is None: first = samples[0].values
                last = samples[-1].values
                count += len(samples)
            time.sleep(.02)
        vm.stop_daq()
        samples = vm.drain_daq(20000)
        if samples:
            if first is None: first = samples[0].values
            last = samples[-1].values
            count += len(samples)
        report.update(elapsed_seconds=time.monotonic()-start, samples=count,
                      first_sample=first, last_sample=last, daq=vm.daq_diagnostics)
        assert last is not None and count > 0, 'No live model counters received'
        values = {name.rsplit('.', 1)[-1]: value for name, value in last.items()}
        report['counters'] = values
        checks = dict(ready=values['Serial_Ready'] == 1, healthy=values['Serial_Healthy'] == 1)
        for label, peer in (('COM5', 'COM6'), ('COM6', 'COM5')):
            checks[label + '_tx'] = values[label + '_TxFrames'] >= 90
            checks[label + '_rx'] = values[label + '_RxFrames'] >= 90
            checks[label + '_counts_match'] = abs(values[label + '_RxFrames'] - values[peer + '_TxFrames']) <= 1
            checks[label + '_no_errors'] = all(values[label + suffix] == 0 for suffix in
                ('_TxFailures','_CrcErrors','_SequenceGaps','_Duplicates','_ForeignFrames','_FormatErrors',
                 '_SetupStatus','_ReadStatus','_WriteStatus'))
        report['checks'] = checks
        report['passed'] = all(checks.values())
        vm.write_calibrations({'Serial_Enable': 0})
        report['disabled_readback'] = vm.read_calibrations(['Serial_Enable'])
    except Exception as error:
        report['error'] = dict(type=type(error).__name__, message=str(error))
    finally:
        cleanup('xcp_close', vm.close)
        if candidate_selected:
            cleanup('stop_test_model', service.stop)
            log = cleanup('read_test_log', service.read_log)
            if log:
                (folder / (options.report + '_target.log')).write_text(log, encoding='utf-8')
                report['runtime'] = cleanup('runtime_summary', lambda: summary_from_log(log))
        if saved_serial is not None:
            restored = cleanup('restore_serial', lambda: serial_state(service, login, saved_serial))
            report['serial_restored'] = restored == saved_serial
        if previous_stopped:
            cleanup('restore_previous_model', lambda: service.start(previous['elf']))
            report['restored_previous'] = cleanup('check_previous_model', service.status)
        if service.connected:
            report['autostart_after'] = cleanup('check_autostart', service.autostart_status)
            report['autostart_unchanged'] = report['autostart_after'] == baseline['autostart']
        restored_previous = report.get('restored_previous') or {}
        report['previous_model_restored'] = bool(restored_previous.get('running')) and (
            restored_previous.get('elf_path') == previous['elf'])
        report['passed'] = (report['passed'] and not report['cleanup_errors']
                            and report.get('serial_restored', False)
                            and report['previous_model_restored'] and report.get('autostart_unchanged', False))
        save()
        archive.close()
        service.close()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
