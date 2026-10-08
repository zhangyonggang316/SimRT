"""Upload the serial harness and run Linux PTY integration tests only."""

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment

sys.excepthook = sys.__excepthook__

REMOTE = '/home/zh/.simrt-validation/ark_serial_install_20261005'
TESTS = ROOT / 'tests/drivers/serial'
FILES = (
    TESTS / 'physical_loopback_results/serial_physical_loopback.elf',
    TESTS / 'physical_loopback_results/test_serial_restore.elf',
    TESTS / 'verify_serial_loopback_pty.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='zh')
    parser.add_argument('--output', type=Path, default=ROOT / 'tests/validation/ark_serial_install_20261005/pty_tests.json')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new report path')
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FILES}
    password = getpass.getpass('SSH password: ')
    service = SSHDeployment()
    try:
        service.connect(args.host, args.user, password=password)
        password = None
        prepare = (
            'from pathlib import Path\n'
            f'p = Path({REMOTE!r})\n'
            'assert all(not q.is_symlink() for q in [p, *p.parents]), "Symlink in validation path"\n'
            'p.mkdir(parents=True, exist_ok=True)\n'
            'assert p.is_dir()\n'
        )
        service._execute('python3 -c ' + shlex.quote(prepare), timeout=15)
        with service._client.open_sftp() as sftp:
            sftp.get_channel().settimeout(15)
            for path in FILES:
                destination = REMOTE + '/' + path.name
                temporary = destination + '.upload-' + uuid.uuid4().hex
                try:
                    sftp.put(str(path), temporary)
                    sftp.chmod(temporary, 0o700 if path.suffix == '.elf' else 0o600)
                    sftp.posix_rename(temporary, destination)
                finally:
                    try:
                        sftp.remove(temporary)
                    except OSError:
                        pass
        verify = (
            'import hashlib\nfrom pathlib import Path\n'
            f'root = Path({REMOTE!r})\nexpected = {hashes!r}\n'
            'for name, digest in expected.items():\n'
            '    p = root / name\n'
            '    assert not p.is_symlink() and p.is_file(), name\n'
            '    assert hashlib.sha256(p.read_bytes()).hexdigest() == digest, name\n'
        )
        service._execute('python3 -c ' + shlex.quote(verify), timeout=15)
        stdout = service._execute(
            'python3 ' + shlex.quote(REMOTE + '/verify_serial_loopback_pty.py') + ' ' +
            shlex.quote(REMOTE + '/serial_physical_loopback.elf'), timeout=45)
        result = json.loads(stdout)
        assert result['passed'] is True and result['physical_test'] is False, result
        assert len(result['tests']) == 6, result
        assert all(case['result']['restore_ok'] for case in result['tests']), result
        restoration = json.loads(service._execute(shlex.quote(REMOTE + '/test_serial_restore.elf'), timeout=10))
        assert restoration['passed'] and restoration['tests'] == 6, restoration
        result['rs485_restoration_tests'] = restoration
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(dict(report=str(args.output.resolve()), uploaded_sha256=hashes,
                              tests=result), indent=2))
    finally:
        password = None
        service.close()


if __name__ == '__main__':
    main()
