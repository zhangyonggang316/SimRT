"""Install the local status display and verify it through an existing SSH login."""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='zh')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    service = SSHDeployment()
    password = os.environ.get('SIMRT_SSH_PASSWORD') or getpass.getpass('SSH password: ')
    try:
        identity = service.connect(args.host, args.user, password=password)
        password = None
        remote = identity['home'] + '/.local/lib/simrt-console'
        source = ROOT / 'linux' / 'console'
        sftp = service._client.open_sftp()
        hashes = {}
        try:
            for name in ('simrt_console.py', 'start_console.sh', 'validate_tmux.py'):
                data = (source / name).read_bytes().replace(b'\r\n', b'\n')
                target = remote + '/' + name
                try:
                    with sftp.open(target, 'rb') as old:
                        previous = old.read()
                    backup_path = target + '.before-20260927'
                    try:
                        backup_size = sftp.stat(backup_path).st_size
                    except FileNotFoundError:
                        backup_size = 0
                    if backup_size == 0:
                        with sftp.open(backup_path, 'wb') as backup:
                            backup.write(previous)
                except FileExistsError:
                    pass
                except OSError as exc:
                    if getattr(exc, 'errno', None) not in (2, 17):
                        raise
                with sftp.open(target + '.update', 'wb') as stream:
                    stream.write(data)
                sftp.chmod(target + '.update', 0o755 if name.endswith('.sh') else 0o644)
                sftp.posix_rename(target + '.update', target)
                with sftp.open(target, 'rb') as stream:
                    actual = hashlib.sha256(stream.read()).hexdigest()
                expected = hashlib.sha256(data).hexdigest()
                if actual != expected:
                    raise RuntimeError('Console hash mismatch: ' + name)
                hashes[name] = actual
        finally:
            sftp.close()
        snapshot = service._execute('python3 ' + shlex.quote(remote + '/simrt_console.py') + ' --once --width 120 --height 40')
        (args.output / 'console_snapshot.txt').write_text(snapshot, encoding='utf-8')
        validation = service._execute('python3 ' + shlex.quote(remote + '/validate_tmux.py') +
            ' --duration 8 --sample-interval 2 --output ' + shlex.quote(remote + '/validation-20260927'), timeout=30)
        isolated = json.loads(validation)
        if not isolated['passed']:
            raise RuntimeError('Isolated display validation failed: ' + validation)
        # The existing dedicated local-display session is explicitly upgraded.
        service._execute('tmux -L simrt-console respawn-pane -k -t simrt-console:0.0 ' +
                         shlex.quote('exec python3 ' + shlex.quote(remote + '/simrt_console.py')))
        service._execute('tmux -L simrt-console kill-pane -a -t simrt-console:0.0')
        service._execute('tmux -L simrt-console set-option -g prefix None')
        # Repeated installs can find the prefix table already removed.
        try:
            service._execute('tmux -L simrt-console unbind-key -a')
        except RuntimeError as exc:
            if "table prefix doesn't exist" not in str(exc):
                raise
        panes = service._execute("tmux -L simrt-console list-panes -t simrt-console:0 -F '#{pane_index}|#{pane_current_command}|#{pane_width}|#{pane_height}'")
        report = dict(host=args.host, hashes=hashes, isolated=isolated, panes=panes, reboot_test=False)
        (args.output / 'console_deployment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
