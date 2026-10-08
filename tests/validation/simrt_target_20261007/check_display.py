"""Check the live renamed model dashboard, then restore the pre-test model."""
import hashlib
import json
from pathlib import Path
import shlex
import time

from check_target import ROOT, credentials, SSHDeployment


def main():
    folder = Path(__file__).parent
    source = json.loads((folder / 'model_validation.json').read_text(encoding='utf-8'))
    destination = folder / 'display_validation.json'
    if destination.exists():
        raise FileExistsError(destination)
    candidate = source['model']['remote_elf']
    previous = source['restored_previous']
    report = dict(passed=False, previous=previous, candidate=candidate)
    service = SSHDeployment()
    stopped_previous = False
    try:
        service.connect(**credentials())
        current = service.status(previous['elf_path'])
        assert current['running'] and current['pid'] == previous['pid']
        assert service._request('elf', path=candidate)['sha256'] == source['deployment']['files']['simrt_rt_single.elf']
        service.stop()
        stopped_previous = True
        report['pid'] = service.start(candidate)
        time.sleep(3)
        console = '/home/zh/.local/lib/simrt-console/simrt_console.py'
        with service._client.open_sftp() as sftp:
            with sftp.open(console, 'rb') as stream:
                remote_hash = hashlib.sha256(stream.read()).hexdigest()
        local_hash = hashlib.sha256((ROOT / 'simrt_linux_target/console/simrt_console.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        report['console'] = dict(remote_sha256=remote_hash, local_sha256=local_hash,
                                 matches_current_source=remote_hash == local_hash)
        status = json.loads(service._execute('cat ' + shlex.quote(candidate + '.simrt-status.json')))
        report['telemetry'] = status
        snapshot = service._execute('python3 ' + shlex.quote(console) + ' --once --width 160 --height 50')
        (folder / 'renamed_model_console.txt').write_text(snapshot, encoding='utf-8')
        pane = service._execute('tmux -L simrt-console capture-pane -p -t simrt-console:0.0')
        (folder / 'physical_session_capture.txt').write_text(pane, encoding='utf-8')
        network = snapshot.split('Network:', 1)[1].split('CPU:', 1)[0]
        report['checks'] = dict(
            model_name=status['model'] == 'simrt_rt_single',
            live_pid=status['pid'] == report['pid'] and status['state'] == 'RUNNING',
            calls_progress=status['model_step_calls'] > 1000,
            renamed_dashboard='RUNNING -> simrt_rt_single' in snapshot,
            physical_session_renamed='simrt_rt_single' in pane,
            live_telemetry='Telemetry: live' in snapshot,
            elapsed_hours='Model elapsed:' in snapshot and ' h ' in snapshot,
            jitter_row='Jitter > +/-50 us' in snapshot,
            loopback_hidden='127.0.0.1' not in network and '::1/128' not in network,
            duplicate_wireless_ipv6_hidden='fe80:' not in network,
            mac_visible='(7c:3d:09:70:50:41)' in network)
        report['passed'] = all(report['checks'].values())
    finally:
        try:
            if stopped_previous:
                if service.status()['running']:
                    service.stop()
                service.start(previous['elf_path'])
                report['restored_previous'] = service.status()
                report['autostart_after'] = service.autostart_status()
        finally:
            service.close()
            destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    assert report['passed']


if __name__ == '__main__':
    main()
