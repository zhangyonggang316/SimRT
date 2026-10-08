"""Run as root on the audited ark2120 host; no passwords are stored."""

import json
import os
from pathlib import Path
import platform
import pwd
import subprocess

if os.geteuid() != 0 or platform.node() != 'ark2120':
    raise RuntimeError('Expected root on ark2120')
user = pwd.getpwnam('zh')
if user.pw_dir != '/home/zh':
    raise RuntimeError('Unexpected target home')
files = {
    Path('/etc/security/limits.d/90-simrt-zh.conf'):
        '# Managed by SimRT new Ubuntu deployment\nzh - rtprio 80\nzh - memlock 1048576\n',
    Path('/etc/systemd/system/user@' + str(user.pw_uid) + '.service.d/90-simrt.conf'):
        '# Managed by SimRT new Ubuntu deployment\n[Service]\nLimitRTPRIO=80\nLimitMEMLOCK=1073741824\n',
    Path('/etc/udev/rules.d/70-simrt-tc1013.rules'):
        '# Managed by SimRT new Ubuntu deployment\n'
        'SUBSYSTEM=="usb", ATTR{idVendor}=="5453", ATTR{idProduct}=="0001", GROUP="plugdev", MODE="0660"\n',
}
previous = {}
for path, content in files.items():
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: ' + str(path))
    previous[str(path)] = path.read_text() if path.exists() else None
    if previous[str(path)] is not None and previous[str(path)] != content:
        raise RuntimeError('Refusing to replace existing configuration: ' + str(path))
before_file = Path('/var/lib/simrt/new-ubuntu-20260926-before.json')
before_file.parent.mkdir(mode=0o755, exist_ok=True)
if not before_file.exists():
    before_file.write_text(json.dumps(previous, indent=2))
for path, content in files.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o644)
commands = [
    ['systemctl', 'daemon-reload'],
    ['loginctl', 'enable-linger', 'zh'],
    ['systemctl', 'disable', 'systemd-networkd-wait-online.service'],
    ['systemctl', 'mask', 'systemd-networkd-wait-online.service'],
    ['systemctl', 'reset-failed', 'systemd-networkd-wait-online.service'],
    ['udevadm', 'control', '--reload-rules'],
    ['udevadm', 'trigger', '--subsystem-match=usb', '--attr-match=idVendor=5453',
     '--attr-match=idProduct=0001', '--action=change'],
    ['udevadm', 'settle'],
]
for command in commands:
    subprocess.run(command, check=True)
print(json.dumps({'files': {str(p): c for p, c in files.items()}, 'before': previous,
                  'commands': commands, 'rebooted': False,
                  'note': 'Existing Wi-Fi/netplan configuration preserved. User service limits apply after reboot.'}, indent=2))
