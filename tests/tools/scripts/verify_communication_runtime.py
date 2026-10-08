"""Run locally cross-compiled loopback/PTY/mock tests on the Linux target."""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='zh')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    files = [ROOT / 'tests/validation/network_runtime/test_network_runtime.elf',
             ROOT / 'tests/drivers/serial/test_serial_runtime.elf',
             ROOT / 'tests/drivers/ethercat/test_ethercat_runtime.elf',
             ROOT / 'tests/drivers/ethercat/test_soem_link.elf']
    for path in files:
        if path.read_bytes()[:4] != b'\x7fELF':
            raise ValueError('Expected locally compiled ELF: ' + str(path))
    service = SSHDeployment()
    report = dict(host=args.host, tests=[], physical_bus_test=False, passed=False)
    password = os.environ.get('SIMRT_SSH_PASSWORD') or getpass.getpass('SSH password: ')
    try:
        identity = service.connect(args.host, args.user, password=password)
        password = None
        directory = identity['home'] + '/.local/lib/simrt-communication-tests-20260927'
        service._execute('mkdir -p ' + shlex.quote(directory))
        with service._client.open_sftp() as sftp:
            for path in files:
                remote = directory + '/' + path.name
                sftp.put(str(path), remote)
                sftp.chmod(remote, 0o700)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                with sftp.open(remote, 'rb') as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != digest:
                        raise RuntimeError('Uploaded test hash mismatch')
                output = service._execute('timeout 30 ' + shlex.quote(remote), timeout=40)
                report['tests'].append(dict(name=path.name, sha256=digest, output=output, passed=True))
        capture = service._execute('tmux -L simrt-console capture-pane -p -t simrt-console:0.0')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_name('live_console_capture.txt').write_text(capture, encoding='utf-8')
        report['passed'] = True
    finally:
        service.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
