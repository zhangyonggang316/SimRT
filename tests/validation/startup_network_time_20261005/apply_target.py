"""Apply saved Ethernet configuration and scoped boot settings to this target."""
import getpass
import json
from pathlib import Path
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.network_configuration import NetworkConfiguration
sys.excepthook = sys.__excepthook__

BACKUP = r'''
import datetime, json, shutil, subprocess
from pathlib import Path
directory = Path('/var/backups') / ('simrt-startup-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
directory.mkdir(mode=0o700)
shutil.copytree('/etc/netplan', directory / 'netplan')
units = ['apport.service', 'ModemManager.service', 'networkd-dispatcher.service']
enabled = {unit: subprocess.run(['systemctl', 'is-enabled', unit], text=True, capture_output=True).stdout.strip() for unit in units}
(directory / 'enabled.json').write_text(json.dumps(enabled, indent=2))
print(json.dumps(dict(backup=str(directory), enabled=enabled)))
'''

APPLY = r'''
import json, os, subprocess, tempfile, time
from pathlib import Path
import yaml
names = ['enp1s0', 'enp3s0', 'enp4s0']
path = Path('/etc/netplan/00-installer-config.yaml')
value = yaml.safe_load(path.read_text())
for name in names:
    node = value['network']['ethernets'][name]
    assert node['ignore-carrier'] is True and node['dhcp4'] is False
    node['optional'] = True
fd, temporary = tempfile.mkstemp(prefix='.simrt-', dir=str(path.parent))
with os.fdopen(fd, 'w') as stream:
    os.fchmod(stream.fileno(), 0o600)
    stream.write(yaml.safe_dump(value, sort_keys=False))
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout
run(['netplan', 'generate'])
for name in names:
    network = Path('/run/systemd/network/10-netplan-' + name + '.network').read_text()
    assert 'ConfigureWithoutCarrier=yes' in network
run(['networkctl', 'reload'])
run(['networkctl', 'reconfigure'] + names)
time.sleep(2)
assert 'No modems were found' in run(['mmcli', '-L'])
units = ['apport.service', 'ModemManager.service']
run(['systemctl', 'disable'] + units)
dropin = Path('/etc/systemd/system/getty@tty1.service.d/95-simrt-fast-start.conf')
assert not dropin.exists() or dropin.read_text() == '[Service]\nType=simple\n'
dropin.write_text('[Service]\nType=simple\n')
run(['systemctl', 'daemon-reload'])
run(['timedatectl', 'set-timezone', 'Asia/Shanghai'])
print(json.dumps(dict(network=json.loads(run(['ip', '-j', 'address', 'show'])),
    disabled_units=units, getty_dropin=str(dropin), timezone=run(['timedatectl', 'show', '-p', 'Timezone', '--value']).strip())))
'''

if __name__ == '__main__':
    password = getpass.getpass('SSH/admin password: ')
    service = SSHDeployment()
    report = {'passed': False}
    output = Path(__file__).parent
    def sudo(source):
        return json.loads(service._execute('sudo -S -p ' + shlex.quote('') + ' -- python3 -c ' +
            shlex.quote(source), timeout=60, input_data=(password + '\n').encode()))
    try:
        service.connect('192.168.193.195', 'zh', password=password)
        existing = output / 'target_changes.json'
        if existing.exists():
            report.update(json.loads(existing.read_text(encoding='utf-8')))
        else:
            report.update(sudo(BACKUP))
            network = NetworkConfiguration(service)
            configured = []
            for name, address in [('enp1s0', '192.168.7.1'), ('enp3s0', '192.168.8.1'), ('enp4s0', '192.168.9.1')]:
                configured.append(network.configure(name, address, '24', password=password))
            report['configured'] = configured
        report.update(sudo(APPLY))
        for name, address in [('enp1s0', '192.168.7.1'), ('enp3s0', '192.168.8.1'), ('enp4s0', '192.168.9.1')]:
            interface = next(item for item in report['network'] if item['ifname'] == name)
            assert any(item['local'] == address and item['prefixlen'] == 24 for item in interface['addr_info'])
        report['passed'] = True
        print(json.dumps(report, indent=2))
    finally:
        (output / 'target_changes.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        service.close()
