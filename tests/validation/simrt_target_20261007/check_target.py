"""Record read-only target state using this user's encrypted APP credentials."""
import hashlib
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from qt_host.credential_store import CredentialStore
from pyxcp_host.services.ssh_deployment import SSHDeployment

SCRIPT = r'''
import hashlib, json, os, subprocess
from pathlib import Path
def read(path):
    try: return Path(path).read_text().strip()
    except OSError: return None
def command(args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=20)
    return dict(code=p.returncode,stdout=p.stdout,stderr=p.stderr)
processes=[]
for process in Path('/proc').iterdir():
    if not process.name.isdigit(): continue
    try:
        elf=os.readlink(process/'exe')
        if not elf.endswith('.elf') or process.stat().st_uid!=os.getuid(): continue
        data=Path(elf).read_bytes()
        arguments=(process/'cmdline').read_bytes().split(b'\0')
        marker=read(elf+'.pyxcp-host.json')
        processes.append(dict(pid=int(process.name),elf=elf,sha256=hashlib.sha256(data).hexdigest(),
            arguments=[a.decode() for a in arguments if a],marker=json.loads(marker) if marker else None,
            realtime_status=read(elf+'.simrt-status.json')))
    except (OSError,ValueError): pass
print(json.dumps(dict(hostname=os.uname().nodename,kernel=os.uname().release,
    realtime=read('/sys/kernel/realtime'),boot_id=read('/proc/sys/kernel/random/boot_id'),
    cmdline=read('/proc/cmdline'),isolated_cpus=read('/sys/devices/system/cpu/isolated'),
    processes=processes,addresses=command(['ip','-j','address']),
    listeners=command(['ss','-lupn']),usb=command(['lsusb']),
    console=command(['tmux','-L','simrt-console','list-panes','-t','simrt-console:0','-F','#{pane_index}|#{pane_current_command}']),
    tuning=read('/run/simrt-rt-tuning.json'))))
'''


def credentials():
    value = CredentialStore().load()
    preset = json.loads((ROOT / 'Demo_XCP_Qt/demo.json').read_text(encoding='utf-8'))
    if not value or value['host'] != preset['host'] or value['username'] != preset['username']:
        raise RuntimeError('Saved APP credentials must match the selected demo target')
    return value


def main():
    destination = Path(sys.argv[1])
    if destination.exists():
        raise FileExistsError(destination)
    service = SSHDeployment()
    try:
        identity = service.connect(**credentials())
        report = json.loads(service._execute('python3 -c ' + shlex.quote(SCRIPT), timeout=90))
        report['identity'] = identity
        report['autostart'] = service.autostart_status()
        report['owned_status'] = [service.status(item['elf']) for item in report['processes']]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
