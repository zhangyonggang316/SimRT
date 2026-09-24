"""Opt-in validation against an explicitly supplied Ubuntu SSH endpoint."""

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

from pyxcp_host.services.ssh_deployment import SSHDeployment

# pyXCP installs a rich traceback hook with local variables; never expose credentials.
sys.excepthook = sys.__excepthook__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--key', default='')
    parser.add_argument('--password-stdin', action='store_true')
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'validation_ssh')
    args = parser.parse_args()
    password = input() if args.password_stdin else ('' if args.key else getpass.getpass('SSH password: '))
    args.output.mkdir(parents=True, exist_ok=True)
    lines = []

    def log(line):
        lines.append(line)
        print(line, flush=True)

    deployment = SSHDeployment(log_callback=log)
    report = {'checks': {}, 'remote_directory': None}
    started = False
    try:
        info = deployment.connect(args.host, args.username, password, args.port, args.key)
        remote = info['home'] + '/pyxcp-validation-' + uuid.uuid4().hex[:12]
        report['remote_directory'] = remote
        report['checks']['connected'] = True
        count = deployment.upload(Path(__file__).parent / 'examples' / 'ssh_demo', remote)
        report['checks']['uploaded_files'] = count
        deployment.build(remote, 'make', timeout=60)
        report['checks']['compiled'] = True
        target = deployment.download_elf(remote + '/demo.elf', args.output / 'demo.elf')
        report['elf_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        report['checks']['downloaded_elf'] = target.read_bytes()[:4] == b'\x7fELF'
        first_pid = deployment.start(remote + '/demo.elf')
        started = True
        report['checks']['started'] = deployment.status()['running']
        report['checks']['duplicate_start_same_pid'] = deployment.start(remote + '/demo.elf') == first_pid
        for operation, call in (
            ('build_while_running_rejected', lambda: deployment.build(remote, 'make')),
            ('upload_while_running_rejected', lambda: deployment.upload(Path(__file__).parent / 'examples' / 'ssh_demo', remote)),
        ):
            try:
                call()
            except RuntimeError:
                report['checks'][operation] = True
            else:
                raise AssertionError(operation)
        deployment.close()
        deployment.connect(args.host, args.username, password, args.port, args.key)
        report['checks']['reconnect_retains_process'] = deployment.status()['pid'] == first_pid
        deployment.close()
        deployment = SSHDeployment(log_callback=log)
        deployment.connect(args.host, args.username, password, args.port, args.key)
        report['checks']['new_session_recovers_process'] = deployment.status(remote + '/demo.elf')['pid'] == first_pid
        time.sleep(1.1)
        report['checks']['runtime_log'] = 'tick=' in deployment.read_log()
        report['checks']['stopped'] = deployment.stop() and not deployment.status()['running']
        started = False
        report['checks']['graceful_stop_log'] = 'stopped cleanly' in deployment.read_log()
        for name, command, timeout in (
            ('compile_error_rejected', 'exit 7', 5),
            ('compile_timeout_rejected', 'sleep 10', 0.3),
        ):
            try:
                deployment.build(remote, command, timeout=timeout)
            except (RuntimeError, TimeoutError):
                report['checks'][name] = True
            else:
                raise AssertionError(name)
        report['passed'] = all(report['checks'].values())
        if not report['passed']:
            raise AssertionError('SSH validation checks failed')
    finally:
        try:
            if started and deployment.connected:
                deployment.stop()
        finally:
            deployment.close()
            (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            (args.output / 'session.log').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
