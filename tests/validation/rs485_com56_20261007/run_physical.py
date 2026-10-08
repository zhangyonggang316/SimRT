"""Exercise only the two COM5/6 candidate UARTs with the existing serial backend."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex

from preflight import AUDIT, ROOT, SSHDeployment, credentials, sudo_python

LOCAL = ROOT / 'simrt_linux_target/drivers/serial/tests/physical_loopback_results/serial_physical_loopback.elf'
REMOTE = '/home/zh/.simrt-validation/rs485_com56_20261007/serial_physical_loopback.elf'

RUN = r'''
import time
errors = []
if owners or inaccessible: errors.append('Serial ownership is not clear')
for name in ('ttyS6', 'ttyS7'):
    if name in (read('/sys/class/tty/console/active') or '').split():
        errors.append('Active console: ' + name)
    if re.search(r'(?:^|\s)console=' + name + r'(?:,|\s|$)', read('/proc/cmdline') or ''):
        errors.append('Kernel console: ' + name)
state = command(['systemctl','show','serial-getty@ttyS6.service','serial-getty@ttyS7.service',
                 '--property=ActiveState'])
if state['code'] or re.findall(r'^ActiveState=(.*)$', state['stdout'], re.M) != ['inactive','inactive']:
    errors.append('Serial getty is not confirmed inactive')
for index, address in ((6,'00000210'), (7,'00000218')):
    expected = r'^' + str(index) + r': uart:16550A port:' + address + r'\b'
    if not re.search(expected, read('/proc/tty/driver/serial') or '', re.M):
        errors.append('Unexpected UART identity')
elf = Path(REMOTE)
if elf.is_symlink() or hashlib.sha256(elf.read_bytes()).hexdigest() != EXPECTED_SHA256:
    errors.append('Harness hash mismatch')
if errors: raise RuntimeError('; '.join(errors))
before = read('/proc/tty/driver/serial')
devices = ['/dev/ttyS7', '/dev/ttyS6'] if REVERSE else ['/dev/ttyS6', '/dev/ttyS7']
args = [REMOTE, *devices, MODE, '115200', '32', '5000']
start = time.monotonic()
p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
forced = False
try:
    stdout, stderr = p.communicate(timeout=8)
except subprocess.TimeoutExpired:
    p.terminate()
    try: stdout, stderr = p.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        forced = True
        p.kill()
        stdout, stderr = p.communicate(timeout=2)
print(json.dumps(dict(command=args, returncode=p.returncode, forced_kill=forced,
    elapsed_seconds=time.monotonic()-start, stdout=stdout, stderr=stderr,
    result=json.loads(stdout) if stdout.strip() else None,
    uart_before=before, uart_after=read('/proc/tty/driver/serial'))))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reverse', action='store_true')
    parser.add_argument('--mode', choices=('rs485-auto', 'rs485-rts-high'), default='rs485-auto')
    args = parser.parse_args()
    name = 'physical_reverse' if args.reverse else 'physical_test'
    if args.mode != 'rs485-auto': name += '_linux_rts'
    destination = Path(__file__).with_name(name + '.json')
    if destination.exists():
        raise FileExistsError('Preserve earlier results; no automatic repeat')
    digest = hashlib.sha256(LOCAL.read_bytes()).hexdigest()
    login = credentials()
    service = SSHDeployment()
    try:
        service.connect(**login)
        prepare = 'from pathlib import Path\np=Path(' + repr(REMOTE) + ')\n' + (
            'assert all(not q.is_symlink() for q in [p,*p.parents])\n'
            'p.parent.mkdir(parents=True,exist_ok=True)\n')
        service._execute('python3 -c ' + shlex.quote(prepare), timeout=15)
        with service._client.open_sftp() as sftp:
            sftp.put(str(LOCAL), REMOTE)
            sftp.chmod(REMOTE, 0o700)
        program = ('REMOTE=' + repr(REMOTE) + '\nEXPECTED_SHA256=' + repr(digest) +
                   '\nREVERSE=' + repr(args.reverse) + '\nMODE=' + repr(args.mode) + '\n' + AUDIT + '\n' + RUN)
        lines = sudo_python(service, login, program, timeout=30).splitlines()
        preflight, result = [json.loads(line) for line in lines]
        report = dict(host=login['host'], preflight=preflight, test=result, harness_sha256=digest)
        destination.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
