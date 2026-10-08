"""Deploy and verify the console network display on the existing target."""
import datetime
import getpass
import hashlib
import ipaddress
import json
from pathlib import Path
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment


def main():
    output = Path(__file__).resolve().parent
    service = SSHDeployment()
    password = getpass.getpass('SSH password: ')
    sftp = None
    installed = False
    report = {'host': '192.168.193.195', 'passed': False, 'reboot_performed': False}
    try:
        identity = service.connect(report['host'], 'zh', password=password)
        password = None
        remote = identity['home'] + '/.local/lib/simrt-console/simrt_console.py'
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        stage = remote + '.network-mac-' + stamp
        backup = remote + '.before-network-mac-' + stamp
        pane_command = "tmux -L simrt-console list-panes -t simrt-console:0 -F '#{pane_index}|#{pane_pid}|#{pane_width}|#{pane_height}|#{pane_dead}'"
        capture_command = 'tmux -L simrt-console capture-pane -p -t simrt-console:0.0'
        restart_command = ('tmux -L simrt-console respawn-pane -k -t simrt-console:0.0 ' +
                           shlex.quote('exec python3 ' + shlex.quote(remote)))
        before_pane = service._execute(pane_command).strip()
        assert len(before_pane.splitlines()) == 1 and before_pane.split('|')[0] == '0'
        before = json.loads(service._execute('python3 ' + shlex.quote(remote) + ' --json'))
        interfaces = json.loads(service._execute('ip -j address show'))
        sftp = service._client.open_sftp()
        with sftp.open(remote, 'rb') as stream:
            previous = stream.read()
        with sftp.open(backup, 'wb') as stream:
            stream.write(previous)
        sftp.chmod(backup, 0o644)
        data = (ROOT / 'simrt_linux_target/console/simrt_console.py').read_bytes().replace(b'\r\n', b'\n')
        with sftp.open(stage, 'wb') as stream:
            stream.write(data)
        sftp.chmod(stage, 0o644)
        with sftp.open(stage, 'rb') as stream:
            assert stream.read() == data
        staged = json.loads(service._execute('python3 ' + shlex.quote(stage) + ' --json'))
        expected = []
        for interface in interfaces:
            if interface.get('link_type') == 'loopback' or 'LOOPBACK' in interface.get('flags', []):
                continue
            label = '{} [{}]: '.format(interface['ifname'], interface['operstate'])
            mac = interface['address']
            addresses = [ipaddress.ip_interface('{}/{}'.format(item['local'], item['prefixlen']))
                         for item in interface['addr_info'] if item['family'] in ('inet', 'inet6')]
            for address in addresses or [None]:
                text = ('{} / {}'.format(address.ip, address.netmask) if address.version == 4 else str(address)) if address else 'no IP address'
                expected.append(label + text + ' (' + mac + ')')
        assert expected and staged['network_rows'] == expected, staged['network_rows']
        assert not any(row.startswith('lo ') for row in staged['network_rows'])
        snapshot = service._execute('python3 ' + shlex.quote(stage) + ' --once --width 119 --height 33')
        assert all(row in snapshot for row in expected)
        assert '-- LOG' in snapshot and len(snapshot.splitlines()) <= 33
        (output / 'staged_snapshot.txt').write_text(snapshot, encoding='utf-8')
        sftp.posix_rename(stage, remote)
        installed = True
        service._execute(restart_command)
        deadline = time.monotonic() + 10
        while True:
            first = service._execute(capture_command)
            if all(row in first for row in expected) and '-- LOG' in first:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('Live console did not render the expected network rows')
            time.sleep(1)
        time.sleep(2)
        second = service._execute(capture_command)
        after_pane = service._execute(pane_command).strip()
        after = json.loads(service._execute('python3 ' + shlex.quote(remote) + ' --json'))
        assert after_pane.split('|')[2:] == before_pane.split('|')[2:]
        assert after_pane.split('|')[-1] == '0'
        assert first != second, 'Dashboard did not refresh'
        assert all(row in second for row in expected) and 'lo [UNKNOWN]' not in second
        assert {item['pid'] for item in before['models']} == {item['pid'] for item in after['models']}
        font_config = service._execute('cat /etc/default/console-setup')
        assert 'FONTSIZE="16x32"' in font_config
        with sftp.open(remote, 'rb') as stream:
            assert stream.read() == data
        report.update(passed=True, backup=backup, sha256=hashlib.sha256(data).hexdigest(),
                      pane_before=before_pane, pane_after=after_pane, network_rows=expected,
                      dashboard_refreshing=True, model_pids_unchanged=True,
                      model_pids=[item['pid'] for item in after['models']], font='16x32')
        (output / 'console_after.txt').write_text(second, encoding='utf-8')
    except Exception as exc:
        report['error'] = '{}: {}'.format(type(exc).__name__, exc)
        if installed:
            with sftp.open(stage, 'wb') as stream:
                stream.write(previous)
            sftp.chmod(stage, 0o644)
            sftp.posix_rename(stage, remote)
            service._execute(restart_command)
            report['rolled_back'] = True
        raise
    finally:
        (output / 'deployment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if sftp is not None:
            sftp.close()
        service.close()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
