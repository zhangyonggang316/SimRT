"""Read COM5/6 candidates and running model state without serial data I/O."""
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from qt_host.credential_store import CredentialStore
from pyxcp_host.services.ssh_deployment import SSHDeployment

AUDIT = r'''
import hashlib, json, os, re, stat, subprocess
from pathlib import Path

def read(path):
    try: return Path(path).read_text(errors='replace').strip()
    except OSError: return None

def command(args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=10)
    return dict(code=p.returncode, stdout=p.stdout, stderr=p.stderr)

ports = []
for name in ('ttyS0', 'ttyS1', 'ttyS4', 'ttyS5', 'ttyS6', 'ttyS7'):
    node = Path('/dev') / name
    device = (Path('/sys/class/tty') / name / 'device').resolve()
    ancestors = []
    for parent in (device, *device.parents):
        if not str(parent).startswith('/sys/devices/'): continue
        attributes = {key: read(parent / key) for key in
                      ('id', 'name', 'resources', 'uevent', 'firmware_node/hid',
                       'firmware_node/uid', 'firmware_node/path')}
        attributes = {key: value for key, value in attributes.items() if value is not None}
        if attributes: ancestors.append(dict(path=str(parent), attributes=attributes))
    info = node.stat()
    ports.append(dict(device=str(node), major=os.major(info.st_rdev), minor=os.minor(info.st_rdev),
                      character_device=stat.S_ISCHR(info.st_mode), ancestors=ancestors))
identities = {os.stat('/dev/ttyS'+str(i)).st_rdev: '/dev/ttyS'+str(i) for i in (6, 7)}
owners, inaccessible, models = [], [], []
for process in Path('/proc').iterdir():
    if not process.name.isdigit(): continue
    try:
        executable = os.readlink(process / 'exe')
        if executable.endswith('.elf'):
            models.append(dict(pid=int(process.name), elf=executable,
                sha256=hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                arguments=[a.decode() for a in (process/'cmdline').read_bytes().split(b'\0') if a]))
        for descriptor in (process/'fd').iterdir():
            try: info = descriptor.stat()
            except (FileNotFoundError, ProcessLookupError): continue
            if stat.S_ISCHR(info.st_mode) and info.st_rdev in identities:
                owners.append(dict(pid=int(process.name), name=read(process/'comm'),
                                   device=identities[info.st_rdev]))
    except PermissionError: inaccessible.append(int(process.name))
    except (FileNotFoundError, ProcessLookupError): pass
print(json.dumps(dict(hostname=os.uname().nodename, kernel=os.uname().release,
    serial_driver=read('/proc/tty/driver/serial'), ports=ports,
    candidate_devices=['/dev/ttyS6','/dev/ttyS7'], owners=owners,
    inaccessible_processes=inaccessible, running_models=models,
    cmdline=read('/proc/cmdline'), consoles=read('/proc/consoles'),
    active_consoles=read('/sys/class/tty/console/active'),
    getty=command(['systemctl','show','serial-getty@ttyS6.service','serial-getty@ttyS7.service',
                   '--property=Id,ActiveState,SubState']),
    mapping_status='Candidates pending ACPI resource and physical transfer verification',
    serial_opened=False, serial_data_sent=False)))
'''


def credentials():
    login = CredentialStore().load()
    preset = json.loads((ROOT / 'Demo_XCP_Qt/demo.json').read_text(encoding='utf-8'))
    if not login or login['host'] != preset['host'] or login['username'] != preset['username']:
        raise RuntimeError('Saved APP credentials must match the selected ARK')
    return login


def sudo_python(service, login, program, timeout=45):
    return service._execute("sudo -S -p '' -- python3 -c " + shlex.quote(program),
                            input_data=(login['password'] + '\n').encode(), timeout=timeout)


def main():
    login = credentials()
    service = SSHDeployment()
    try:
        service.connect(**login)
        result = json.loads(sudo_python(service, login, AUDIT))
        result['autostart'] = service.autostart_status()
        result['host'] = login['host']
        Path(__file__).with_name('preflight.json').write_text(
            json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
