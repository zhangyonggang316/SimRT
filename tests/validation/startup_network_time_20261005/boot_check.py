"""Inspect boot state or perform one reboot and verify existing model autostart."""
import argparse
import getpass
import json
from pathlib import Path
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.target_clock import TargetClockSync
from pyxcp_host.services.target_monitor import TargetMonitor
sys.excepthook = sys.__excepthook__

SNAPSHOT = r'''
import json, os, subprocess
from pathlib import Path
def command(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    return dict(code=result.returncode, stdout=result.stdout, stderr=result.stderr)
result = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    kernel=os.uname().release, realtime=Path('/sys/kernel/realtime').read_text().strip(),
    uptime=Path('/proc/uptime').read_text().strip())
for name, args in {
    'time': ['systemd-analyze', 'time'],
    'chain': ['systemd-analyze', 'critical-chain', '--no-pager'],
    'getty': ['systemctl', 'show', 'getty@tty1.service', '-p', 'ActiveEnterTimestampMonotonic', '-p', 'Type'],
    'clock': ['timedatectl'],
    'network': ['ip', '-j', 'address', 'show'],
    'autostart': ['systemctl', '--user', 'show', 'pyxcp-host-model.service', '-p', 'ActiveState', '-p', 'MainPID', '-p', 'ExecMainStartTimestampMonotonic'],
    'console': ['tmux', '-L', 'simrt-console', 'capture-pane', '-p', '-t', 'simrt-console:0.0'],
    'failed': ['systemctl', '--failed', '--no-pager'],
    'initrd_modules': ['lsinitrd', '-m', '/boot/initrd.img-' + os.uname().release],
    'disk': ['df', '-h', '/boot'],
    'cmdline': ['cat', '/proc/cmdline'],
}.items():
    result[name] = command(args)
result['boot_files'] = {str(path): path.stat().st_size for path in Path('/boot').glob('*' + os.uname().release)}
result['dracut_config'] = {str(path): path.read_text() for path in Path('/etc/dracut.conf.d').glob('*.conf')}
result['models'] = []
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    try:
        executable = os.readlink(str(entry / 'exe'))
        if executable.endswith('.elf') and entry.stat().st_uid == os.getuid():
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            arguments = (entry / 'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')[1:]
            environment = dict(item.split('=', 1) for item in (entry / 'environ').read_bytes().decode().split('\0') if item.startswith('SIMRT_') and '=' in item)
            result['models'].append(dict(pid=int(entry.name), executable=executable, arguments=arguments,
                runtime_environment=environment, started_seconds=int(fields[19])/os.sysconf('SC_CLK_TCK')))
    except (OSError, ValueError):
        pass
print(json.dumps(result))
'''

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reboot', action='store_true')
    parser.add_argument('--name', default='boot_inspection')
    parser.add_argument('--check-clock', action='store_true')
    args = parser.parse_args()
    password = getpass.getpass('SSH/admin password: ')
    output = Path(__file__).parent
    service = SSHDeployment()
    def snapshot():
        return json.loads(service._execute('python3 -c ' + shlex.quote(SNAPSHOT), timeout=80))
    try:
        service.connect('192.168.193.195', 'zh', password=password)
        before = snapshot()
        (output / (args.name + '_before.json')).write_text(json.dumps(before, indent=2), encoding='utf-8')
        if not args.reboot:
            print(json.dumps({key: before[key] for key in ('time', 'models', 'getty', 'boot_files', 'initrd_modules', 'disk', 'cmdline', 'dracut_config')}, indent=2))
        else:
            autostart = service.autostart_status()
            assert len(before['models']) == 1
            previous_model = before['models'][0]
            if autostart['enabled']:
                assert previous_model['executable'] == autostart['elf_path']
            if args.check_clock:
                from PySide6.QtCore import QTimeZone
                clock = TargetClockSync(service, lambda: bytes(QTimeZone.systemTimeZoneId()).decode('ascii'))
                clock.arm(password)
                assert clock._request('probe')['idle'] is False
                service.status(previous_model['executable'])
                assert service.stop()
                monitor = TargetMonitor(service)
                clock_results = []
                for attempt in range(15):
                    clock.observe(monitor.snapshot(), service.status())
                    if clock.ready:
                        result = clock.synchronize()
                        clock_results.append(result)
                        if result['status'] == 'synchronized':
                            break
                    time.sleep(2)
                before['clock_validation'] = clock_results
                clock.cancel()
                (output / (args.name + '_before.json')).write_text(json.dumps(before, indent=2), encoding='utf-8')
                if not clock_results or clock_results[-1]['status'] != 'synchronized':
                    service.start(previous_model['executable'], shlex.join(previous_model['arguments']),
                                  runtime_environment=previous_model['runtime_environment'])
                    raise RuntimeError('Clock validation did not complete; model restored')
            print('Rebooting; existing autostart settings will remain unchanged.', flush=True)
            started = time.monotonic()
            try:
                service._execute('sudo -S -p ' + shlex.quote('') + ' -- systemctl reboot',
                    input_data=(password + '\n').encode(), timeout=10)
            except (EOFError, OSError):
                pass
            service.close()
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    service.connect('192.168.193.195', 'zh', password=password)
                    boot_id = service._execute('cat /proc/sys/kernel/random/boot_id').strip()
                    if boot_id == before['boot_id']:
                        service.close()
                        continue
                    after = snapshot()
                    if not autostart['enabled'] and not after['models']:
                        service.start(previous_model['executable'], shlex.join(previous_model['arguments']),
                                      runtime_environment=previous_model['runtime_environment'])
                        time.sleep(2)
                        after = snapshot()
                    if not after['models'] or 'SimRT:' not in after['console']['stdout']:
                        service.close()
                        continue
                    break
                except (OSError, EOFError, RuntimeError) as error:
                    print('Waiting for reboot: ' + type(error).__name__, flush=True)
                    service.close()
            else:
                raise RuntimeError('Target did not return with its model and console within 240 seconds')
            after['wall_seconds_until_ssh_check'] = time.monotonic() - started
            after['model_restored'] = after['models'][0]['executable'] == before['models'][0]['executable']
            after['autostart_before'] = autostart
            after['autostart_after'] = service.autostart_status()
            assert after['autostart_after'] == autostart
            interfaces = json.loads(after['network']['stdout'])
            for name, address in [('enp1s0', '192.168.7.1'), ('enp3s0', '192.168.8.1'), ('enp4s0', '192.168.9.1')]:
                interface = next(item for item in interfaces if item['ifname'] == name)
                assert any(item['local'] == address for item in interface['addr_info']), interface
            assert after['realtime'] == '1' and after['kernel'] == before['kernel']
            assert after['model_restored']
            assert 'lo [UNKNOWN]' not in after['console']['stdout'] and 'fe80::' not in after['console']['stdout']
            after['passed'] = True
            (output / (args.name + '_after.json')).write_text(json.dumps(after, indent=2), encoding='utf-8')
            print(json.dumps({key: after[key] for key in ('passed', 'time', 'models', 'getty', 'clock', 'wall_seconds_until_ssh_check')}, indent=2))
    finally:
        service.close()
