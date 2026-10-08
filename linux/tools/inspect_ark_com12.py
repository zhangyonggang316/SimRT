"""Inspect COM1/COM2 metadata; optionally read configuration without sending data."""

import argparse
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment

sys.excepthook = sys.__excepthook__

AUDIT = r'''
import json, os, subprocess
from pathlib import Path

def read(path):
    try:
        return Path(path).read_text(errors='replace').strip()
    except OSError:
        return None

def command(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=10)
    return dict(code=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip())

ports = []
for name in ('ttyS0', 'ttyS1'):
    node = Path('/dev') / name
    device = Path('/sys/class/tty') / name / 'device'
    ancestors = []
    resolved = device.resolve()
    for parent in [resolved, *resolved.parents]:
        if not str(parent).startswith('/sys/devices/'):
            continue
        attributes = {attribute: read(parent / attribute) for attribute in
                      ('id', 'name', 'resources', 'uevent', 'firmware_node/hid',
                       'firmware_node/uid', 'firmware_node/path')}
        attributes = {key: value for key, value in attributes.items() if value is not None}
        if attributes:
            ancestors.append(dict(path=str(parent), attributes=attributes))
    info = node.stat()
    ports.append(dict(node=str(node), sysfs_device=str(resolved), major=os.major(info.st_rdev),
                      minor=os.minor(info.st_rdev), uid=info.st_uid, gid=info.st_gid,
                      ancestors=ancestors))

owners = []
denied = []
for process in Path('/proc').iterdir():
    if not process.name.isdigit():
        continue
    try:
        for fd in (process / 'fd').iterdir():
            try:
                destination = os.readlink(fd)
            except FileNotFoundError:
                continue
            if destination in ('/dev/ttyS0', '/dev/ttyS1'):
                owners.append(dict(pid=int(process.name), name=read(process / 'comm'),
                                   fd=fd.name, device=destination))
    except PermissionError:
        denied.append(int(process.name))
    except FileNotFoundError:
        pass

serial_state=[]
if READ_SERIAL_STATE:
    import array, fcntl, termios
    for name in ('ttyS0','ttyS1'):
        fd=os.open('/dev/'+name,os.O_RDONLY|os.O_NOCTTY|os.O_NONBLOCK|os.O_CLOEXEC)
        try:
            attributes=termios.tcgetattr(fd)
            state=dict(device='/dev/'+name, termios_flags=attributes[:4],
                       input_speed=attributes[4],output_speed=attributes[5])
            data=array.array('I',[0]*8)
            try:
                fcntl.ioctl(fd,0x542E,data,True)  # Linux TIOCGRS485, read only.
                state['rs485_words']=data.tolist()
                state['linux_rs485_enabled']=bool(data[0]&1)
            except OSError as error:
                state['rs485_read_errno']=error.errno
            serial_state.append(state)
        finally:
            os.close(fd)

print(json.dumps(dict(
    scope=('Read-only metadata and termios/RS485 queries; no writes or data sent' if READ_SERIAL_STATE
           else 'Read-only metadata; no serial device opened or data sent'),
    serial_state=serial_state,
    effective_uid=os.geteuid(), serial_driver=read('/proc/tty/driver/serial'), ports=ports,
    open_file_owners=owners, inaccessible_process_count=len(denied),
    getty=command(['systemctl', 'show', 'serial-getty@ttyS0.service', 'serial-getty@ttyS1.service',
                   '--property=Id,LoadState,ActiveState,SubState,UnitFileState']),
    all_serial_getty=command(['systemctl', 'list-units', '--all', '--no-pager',
                             '--no-legend', 'serial-getty@*.service']),
    kernel_command_line=read('/proc/cmdline'),
    active_consoles=read('/sys/class/tty/console/active'),
    proc_consoles=read('/proc/consoles'),
    mapping_assessment='ttyS0/ttyS1 are COM1/COM2 candidates by standard legacy resources; chassis label correspondence still requires physical verification.'
)))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='zh')
    parser.add_argument('--read-serial-state', action='store_true',
                        help='Open the two ports read-only to query termios and Linux RS485 state')
    parser.add_argument('--output', type=Path, default=ROOT / 'tests/validation/ark_serial_install_20261005/com12_preflight.json')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose another report path')
    password = getpass.getpass('SSH password: ')
    service = SSHDeployment()
    try:
        service.connect(args.host, args.user, password=password)
        program='READ_SERIAL_STATE = '+repr(args.read_serial_state)+'\n'+AUDIT
        result = json.loads(service._execute(
            "sudo -S -p '' -- python3 -c " + shlex.quote(program),
            timeout=45, input_data=(password + '\n').encode()))
        result.update(target_address=args.host, collected_utc=datetime.now(timezone.utc).isoformat())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(result, indent=2))
    finally:
        password = None
        service.close()


if __name__ == '__main__':
    main()
