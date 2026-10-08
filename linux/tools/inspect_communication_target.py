"""Read-only communication and local-display inventory over the existing SSH service."""

import argparse
import getpass
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.network_configuration import NetworkConfiguration
sys.excepthook = sys.__excepthook__

AUDIT = r'''
import json, os, subprocess
from pathlib import Path
def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return dict(code=result.returncode, stdout=result.stdout[-16000:], stderr=result.stderr[-2000:])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(error=str(exc))
def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None
result = dict(
    hostname=command(['hostname']),
    dmi={name: read('/sys/class/dmi/id/' + name) for name in ('sys_vendor','product_name','product_version','board_name')},
    addresses=command(['ip','-j','address','show']),
    network_manager=command(['nmcli','-t','-f','DEVICE,TYPE,STATE,CONNECTION','device']),
    serial=command(['sudo','-n','cat','/proc/tty/driver/serial']),
    serial_nodes=command(['sh','-c','ls -l /dev/ttyS* /dev/serial/by-id/* 2>/dev/null']),
    consoles=command(['tmux','-L','simrt-console','list-panes','-a','-F','#{session_name}|#{pane_index}|#{pane_pid}|#{pane_current_command}|#{pane_width}|#{pane_height}']),
    tty1=command(['ps','-t','tty1','-o','pid,ppid,comm']),
    sudo=command(['sudo','-n','true']),
    profile_console=[line for line in (read(Path.home()/'.profile') or '').splitlines() if 'simrt' in line.lower()],
)
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='zh')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    service = SSHDeployment()
    password = os.environ.get('SIMRT_SSH_PASSWORD') or getpass.getpass('SSH password: ')
    try:
        service.connect(args.host, args.user, password=password)
        result = json.loads(service._execute('python3 -c ' + shlex.quote(AUDIT), timeout=60))
        result['app_network_inventory'] = NetworkConfiguration(service).interfaces()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
