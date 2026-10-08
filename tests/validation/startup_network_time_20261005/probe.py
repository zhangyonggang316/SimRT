"""Read target startup, network and clock state without changing the target."""
import getpass
import json
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

PROBE = r'''
import json, subprocess
from pathlib import Path
import yaml

def redact(value):
    if isinstance(value, dict):
        return {key: '[redacted]' if any(word in str(key).lower() for word in ('password', 'secret', 'psk')) else redact(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value

commands = {
    'boot_time': ['systemd-analyze', 'time'],
    'boot_blame': ['systemd-analyze', 'blame', '--no-pager'],
    'boot_chain': ['systemd-analyze', 'critical-chain', '--no-pager'],
    'network': ['ip', '-j', 'address', 'show'],
    'network_status': ['networkctl', 'status', '--all', '--no-pager'],
    'network_log': ['journalctl', '-b', '-u', 'systemd-networkd', '--no-pager', '-n', '70'],
    'clock': ['timedatectl'],
    'wait_online': ['systemctl', 'is-enabled', 'systemd-networkd-wait-online.service', 'NetworkManager-wait-online.service'],
    'failed_units': ['systemctl', '--failed', '--no-pager'],
    'netplan_version': ['dpkg-query', '-W', 'netplan.io', 'systemd'],
    'startup_units': ['systemctl', 'cat', 'apport.service', 'ModemManager.service', 'networkd-dispatcher.service', 'snapd.seeded.service', 'getty@tty1.service', 'systemd-user-sessions.service'],
    'display_chain': ['systemd-analyze', 'critical-chain', 'getty@tty1.service', 'user@1000.service', '--no-pager'],
    'dispatcher_hooks': ['find', '/etc/networkd-dispatcher', '/usr/lib/networkd-dispatcher', '-maxdepth', '2', '-type', 'f'],
    'modems': ['mmcli', '-L'],
    'startup_dependencies': ['systemctl', 'list-dependencies', '--reverse', '--no-pager', 'snapd.seeded.service'],
    'initrd_log': ['journalctl', '-b', '-u', 'dracut-initqueue.service', '--no-pager'],
    'fstab': ['findmnt', '--fstab', '--json'],
    'boot_dependencies': ['systemctl', 'show', 'remote-fs-pre.target', 'remote-fs.target', 'network.target', 'systemd-user-sessions.service', 'sysinit.target', 'netplan-configure.service', '-p', 'After', '-p', 'Before', '-p', 'ActiveEnterTimestampMonotonic', '-p', 'Wants', '-p', 'Requires'],
    'initrd_modules': ['lsinitrd', '-m', '/boot/initrd.img-7.0.0-34-realtime'],
    'dracut_defaults': ['dracut', '--version'],
    'device_events': ['journalctl', '-b', '-k', '-o', 'short-monotonic', '--no-pager'],
}
result = {'netplan': {}, 'network_units': {}}
for key, command in commands.items():
    item = subprocess.run(command, text=True, capture_output=True, timeout=20)
    result[key] = dict(code=item.returncode, stdout=item.stdout[:30000], stderr=item.stderr[:3000])
for folder in ('/lib/netplan', '/etc/netplan', '/run/netplan'):
    for path in Path(folder).glob('*.yaml'):
        result['netplan'][str(path)] = redact(yaml.safe_load(path.read_text()))
for folder in ('/etc/systemd/network', '/run/systemd/network'):
    for path in Path(folder).glob('*.network'):
        result['network_units'][str(path)] = path.read_text()
for filename in ('/etc/default/grub', '/etc/default/console-setup', '/proc/uptime', '/etc/timezone'):
    path = Path(filename)
    if path.is_file():
        result[filename] = path.read_text()
print(json.dumps(result))
'''

if __name__ == '__main__':
    service = SSHDeployment()
    password = getpass.getpass('SSH/admin password: ')
    try:
        service.connect('192.168.193.195', 'zh', password=password)
        result = json.loads(service._execute('sudo -S -p ' + shlex.quote('') + ' -- python3 -c ' +
            shlex.quote(PROBE), timeout=90, input_data=(password + '\n').encode()))
        destination = Path(__file__).parent / ('before.json' if not (Path(__file__).parent / 'before.json').exists() else 'probe_followup.json')
        destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({key: value for key, value in result.items() if key in (
            'boot_time', 'boot_dependencies', 'initrd_modules', 'dracut_defaults')}, indent=2))
    finally:
        service.close()
