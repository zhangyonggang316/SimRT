"""Grant the configured model user standard dialout access, then reconnect."""
import json
import shlex
from pathlib import Path

from preflight import SSHDeployment, credentials, sudo_python

PROGRAM = r'''
import grp, json, os, pwd, stat, subprocess
user = pwd.getpwnam(USERNAME)
group = grp.getgrnam('dialout')
nodes = []
for device in ('/dev/ttyS6', '/dev/ttyS7'):
    info = os.stat(device)
    assert stat.S_ISCHR(info.st_mode) and info.st_gid == group.gr_gid
    assert info.st_mode & stat.S_IRGRP and info.st_mode & stat.S_IWGRP
    nodes.append(dict(device=device, group=group.gr_name, mode=oct(stat.S_IMODE(info.st_mode))))
before = sorted(os.getgrouplist(user.pw_name, user.pw_gid))
if group.gr_gid not in before:
    subprocess.run(['usermod', '-a', '-G', 'dialout', user.pw_name], check=True, timeout=10)
after = sorted(os.getgrouplist(user.pw_name, user.pw_gid))
assert set(before) <= set(after) and group.gr_gid in after
print(json.dumps(dict(username=user.pw_name, group_added=group.gr_gid not in before,
                     groups_before=before, groups_after=after, devices=nodes)))
'''

CHECK = r'''
import json, os
print(json.dumps(dict(groups=os.getgroups(), access={p: os.access(p, os.R_OK | os.W_OK)
    for p in ('/dev/ttyS6', '/dev/ttyS7')})))
'''


def main():
    destination = Path(__file__).with_name('serial_access.json')
    if destination.exists():
        raise FileExistsError('Preserve the previous access receipt')
    login = credentials()
    service = SSHDeployment()
    try:
        service.connect(**login)
        report = json.loads(sudo_python(service, login, 'USERNAME=' + repr(login['username']) + '\n' + PROGRAM))
        destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        service.close()
        service.connect(**login)
        report['new_ssh_session'] = json.loads(service._execute('python3 -c ' + shlex.quote(CHECK)))
        report['passed'] = all(report['new_ssh_session']['access'].values())
        destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
        assert report['passed'], 'New SSH session still cannot access the selected serial devices'
    finally:
        service.close()


if __name__ == '__main__':
    main()
