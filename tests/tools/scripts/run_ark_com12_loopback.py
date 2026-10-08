"""Run one bounded RS-232 diagnostic on the authorized ARK COM1/COM2 pair."""

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment

sys.excepthook = sys.__excepthook__
EXPECTED_SHA256 = '3180147d51f43dc234bc6a7f164fa93f852a8efcb98749e30fac956d526ffe27'
LOCAL_ELF = ROOT / 'tests/drivers/serial/physical_loopback_results/serial_physical_loopback.elf'

RUN = r'''
import hashlib, json, os, re, stat, subprocess, time
from pathlib import Path

PORTS = ('/dev/ttyS0', '/dev/ttyS1')
ELF = Path('/home/zh/.simrt-validation/ark_serial_install_20261005/serial_physical_loopback.elf')

def read(path):
    return Path(path).read_text(errors='replace').strip()

def uart_counts():
    result = {}
    for line in read('/proc/tty/driver/serial').splitlines():
        match = re.match(r'([01]):\s+(.*)', line)
        if match:
            values = dict(re.findall(r'(\w+):(\S+)', match.group(2)))
            result['/dev/ttyS' + match.group(1)] = values
    return result

def owners():
    devices = {os.stat(path).st_rdev: path for path in PORTS}
    found, denied = [], []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            for descriptor in (process / 'fd').iterdir():
                try:
                    info = descriptor.stat()
                except FileNotFoundError:
                    continue
                if stat.S_ISCHR(info.st_mode) and info.st_rdev in devices:
                    found.append(dict(pid=int(process.name), name=read(process / 'comm'),
                                      fd=descriptor.name, device=devices[info.st_rdev]))
        except PermissionError:
            denied.append(int(process.name))
        except FileNotFoundError:
            pass
    return found, denied

def main():
    result = dict(test_kind='Existing COM1/COM2 wiring RS-232 diagnostic; not an RS-485 test',
                  physical_test=True, attempted=False, command=[str(ELF), *PORTS, 'rs232',
                  '115200', '32', '3000'], expected_sha256=EXPECTED_SHA256)
    errors = []
    result['elf_sha256'] = hashlib.sha256(ELF.read_bytes()).hexdigest()
    if ELF.is_symlink() or result['elf_sha256'] != EXPECTED_SHA256:
        errors.append('Remote ELF does not match the PTY-verified binary')
    result['uart_before'] = uart_counts()
    for index, path in enumerate(PORTS):
        info = os.stat(path)
        if not stat.S_ISCHR(info.st_mode) or info.st_rdev != os.makedev(4, 64 + index):
            errors.append('Unexpected character-device identity: ' + path)
        if result['uart_before'].get(path, {}).get('uart') != '16550A':
            errors.append('Expected UART is not present: ' + path)
    result['kernel_command_line'] = read('/proc/cmdline')
    result['active_consoles'] = read('/sys/class/tty/console/active')
    result['proc_consoles'] = read('/proc/consoles')
    for name in ('ttyS0', 'ttyS1'):
        if re.search(r'(?:^|\s)console=' + name + r'(?:,|\s|$)', result['kernel_command_line']):
            errors.append('Port is configured as a kernel console: ' + name)
        if name in result['active_consoles'].split() or re.search(r'^' + name + r'\s', result['proc_consoles'], re.M):
            errors.append('Port is an active console: ' + name)
    getty = subprocess.run(['systemctl', 'show', 'serial-getty@ttyS0.service',
        'serial-getty@ttyS1.service', '--property=Id,ActiveState,SubState'],
        capture_output=True, text=True, timeout=5)
    result['serial_getty'] = dict(returncode=getty.returncode, stdout=getty.stdout, stderr=getty.stderr)
    states = re.findall(r'^ActiveState=(.*)$', getty.stdout, re.M)
    if getty.returncode or len(states) != 2 or any(state != 'inactive' for state in states):
        errors.append('Serial getty inactivity not confirmed')
    result['open_file_owners'], denied = owners()
    result['inaccessible_process_count'] = len(denied)
    if result['open_file_owners'] or denied:
        errors.append('Ports are occupied or process ownership could not be fully checked')
    result['preflight_errors'] = errors
    if errors:
        return result

    started = time.monotonic()
    process = subprocess.Popen(result['command'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    result['attempted'] = True
    result['wrapper_timeout'] = False
    result['forced_kill'] = False
    try:
        stdout, stderr = process.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        result['wrapper_timeout'] = True
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            result['forced_kill'] = True
            process.kill()
            stdout, stderr = process.communicate(timeout=2)
    result.update(returncode=process.returncode, stdout=stdout, stderr=stderr,
                  elapsed_ms=round((time.monotonic() - started) * 1000), uart_after=uart_counts())
    try:
        result['harness_result'] = json.loads(stdout)
        result['restore_ok'] = result['harness_result'].get('restore_ok')
    except json.JSONDecodeError:
        result['harness_result'] = None
        result['restore_ok'] = None
    result['uart_delta'] = {path: {counter: int(result['uart_after'][path].get(counter, 0)) -
        int(result['uart_before'][path].get(counter, 0)) for counter in ('tx', 'rx')} for path in PORTS}
    return result

print(json.dumps(main()))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='zh')
    parser.add_argument('--output', type=Path, default=ROOT / 'tests/validation/ark_serial_install_20261005/com12_physical_test.json')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('An earlier result already exists; no automatic retry is allowed')
    if hashlib.sha256(LOCAL_ELF.read_bytes()).hexdigest() != EXPECTED_SHA256:
        parser.error('Local binary differs from the PTY-verified artifact')
    password = getpass.getpass('SSH password: ')
    service = SSHDeployment()
    try:
        service.connect(args.host, args.user, password=password)
        program = 'EXPECTED_SHA256 = ' + repr(EXPECTED_SHA256) + '\n' + RUN
        result = json.loads(service._execute("sudo -S -p '' -- python3 -c " + shlex.quote(program),
            timeout=35, input_data=(password + '\n').encode()))
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
