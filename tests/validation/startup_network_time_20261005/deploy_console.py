"""Update only the target display and verify its live terminal output."""
import datetime
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

if __name__ == '__main__':
    service = SSHDeployment()
    password = getpass.getpass('SSH password: ')
    installed = False
    sftp = None
    try:
        identity = service.connect('192.168.193.195', 'zh', password=password)
        password = None
        remote = identity['home'] + '/.local/lib/simrt-console/simrt_console.py'
        backup = remote + '.before-startup-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        stage = remote + '.update'
        sftp = service._client.open_sftp()
        with sftp.open(remote, 'rb') as stream:
            old = stream.read()
        with sftp.open(backup, 'wb') as stream:
            stream.write(old)
        data = (ROOT / 'simrt_linux_target/console/simrt_console.py').read_bytes().replace(b'\r\n', b'\n')
        with sftp.open(stage, 'wb') as stream:
            stream.write(data)
        sftp.chmod(stage, 0o644)
        snapshot = json.loads(service._execute('python3 ' + shlex.quote(stage) + ' --json'))
        rows = snapshot['network_rows']
        assert len(rows) == 4 and not any('fe80:' in row or row.startswith('lo ') for row in rows), rows
        assert all(any(address in row for row in rows) for address in ('192.168.7.1', '192.168.8.1', '192.168.9.1', '192.168.193.195'))
        restart = 'tmux -L simrt-console respawn-pane -k -t simrt-console:0.0 ' + shlex.quote('exec python3 ' + shlex.quote(remote))
        sftp.posix_rename(stage, remote)
        installed = True
        service._execute(restart)
        time.sleep(2)
        capture = service._execute('tmux -L simrt-console capture-pane -p -t simrt-console:0.0')
        assert all(row in capture for row in rows) and '-- LOG' in capture
        later = json.loads(service._execute('python3 ' + shlex.quote(remote) + ' --json'))
        assert [model['pid'] for model in snapshot['models']] == [model['pid'] for model in later['models']]
        output = Path(__file__).parent
        (output / 'console_after.txt').write_text(capture, encoding='utf-8')
        report = dict(passed=True, backup=backup, sha256=hashlib.sha256(data).hexdigest(), network_rows=rows,
                      model_pids=[model['pid'] for model in later['models']])
        (output / 'console_deployment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    except Exception:
        if installed:
            with sftp.open(stage, 'wb') as stream:
                stream.write(old)
            sftp.chmod(stage, 0o644)
            sftp.posix_rename(stage, remote)
            service._execute(restart)
        raise
    finally:
        if sftp:
            sftp.close()
        service.close()
