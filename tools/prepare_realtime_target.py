"""Apply narrow user runtime prerequisites, without changing or rebooting kernels."""

import argparse
import getpass
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__


SETUP = r'''
import json, os, pwd, subprocess
from pathlib import Path

user = 'zh'
uid = pwd.getpwnam(user).pw_uid
files = {
    Path('/etc/security/limits.d/90-pyxcp-zh-realtime.conf'):
        '# Managed by PyXCP Host RT prerequisites\nzh - rtprio 80\nzh - memlock 1048576\n',
    Path('/etc/systemd/system/user@' + str(uid) + '.service.d/90-pyxcp-realtime.conf'):
        '# Managed by PyXCP Host RT prerequisites\n[Service]\nLimitRTPRIO=80\nLimitMEMLOCK=1073741824\n',
}
before = {}
for path, content in files.items():
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: ' + str(path))
    previous = path.read_text() if path.exists() else None
    if previous is not None and not previous.startswith('# Managed by PyXCP Host RT prerequisites\n'):
        raise RuntimeError('Refusing unrelated configuration: ' + str(path))
    before[str(path)] = previous
for path, content in files.items():
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as stream:
        stream.write(content)
    path.chmod(0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['loginctl', 'enable-linger', user], check=True)
print(json.dumps({'files': {str(p): c for p,c in files.items()}, 'before': before,
                  'linger': True, 'rebooted': False,
                  'note': 'New SSH logins get PAM limits; user manager limit applies on next boot.'}))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='192.168.219.86')
    parser.add_argument('--user', default='zh', choices=['zh'])
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.apply:
        print('Plan: enable linger for zh; allow rtprio <=80 and memlock <=1GiB for zh only.')
        print('No global sudo changes, boot kernel changes, reboot, or service restart.')
        return
    service = SSHDeployment()
    password = getpass.getpass('SSH password: ')
    try:
        service.connect(args.host, args.user, password=password)
        password = None
        result = json.loads(service._execute('sudo -n python3 -c ' + shlex.quote(SETUP)))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally:
        service.close()


if __name__ == '__main__':
    main()
