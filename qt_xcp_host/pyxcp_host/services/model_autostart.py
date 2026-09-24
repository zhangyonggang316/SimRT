"""A single, user-owned systemd boot selection, with no implicit process restart."""

import json
import shlex


UNIT_NAME = 'pyxcp-host-model.service'

_RUNNER = r'''# Managed by PyXCP Host: model runner v1
import fcntl, hashlib, json, os, stat, sys, uuid
from pathlib import Path

home = Path.home().resolve()
base = home / '.local' / 'share' / 'pyxcp-host'
config = json.loads((base / 'autostart.json').read_text())
elf = Path(config['elf_path'])
for path in [elf] + list(elf.parents):
    if path.is_symlink():
        raise RuntimeError('Autostart ELF path cannot contain symlinks')
if home not in elf.resolve().parents or not elf.is_file():
    raise RuntimeError('Autostart ELF must be a file below the SSH home')
with elf.open('rb') as stream:
    if stream.read(4) != b'\x7fELF':
        raise RuntimeError('Autostart file is not an ELF executable')
pending = elf.parent / '.pyxcp-payload.pending'
receipt = elf.parent / '.pyxcp-payload.json'
if pending.is_symlink() or pending.exists() or receipt.is_symlink():
    raise RuntimeError('Payload deployment is incomplete or invalid')
if receipt.exists():
    payload = json.loads(receipt.read_text())
    if payload.get('elf_name') != elf.name or elf.name not in payload.get('files', {}):
        raise RuntimeError('Autostart ELF is not in the verified payload')
    for name, expected in payload['files'].items():
        relative = Path(name)
        candidate = elf.parent / relative
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or any(part.is_symlink() for part in [candidate] + list(candidate.parents))
                or not candidate.is_file()):
            raise RuntimeError('Invalid payload dependency')
        digest = hashlib.sha256()
        with candidate.open('rb') as stream:
            for block in iter(lambda: stream.read(1048576), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise RuntimeError('Payload SHA256 mismatch: ' + name)
lock_fd = os.open(str(base / 'model.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
os.set_inheritable(lock_fd, True)
for process in Path('/proc').iterdir():
    if not process.name.isdigit() or int(process.name) == os.getpid():
        continue
    try:
        if process.stat().st_uid == os.getuid() and os.readlink(str(process / 'exe')) == str(elf):
            raise RuntimeError('Selected model is already running')
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        pass
marker = Path(str(elf) + '.pyxcp-host.json')
log = Path(str(elf) + '.pyxcp-host.log')
if marker.is_symlink() or log.is_symlink():
    raise RuntimeError('Autostart metadata paths cannot be symlinks')
fields = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()
identity = dict(pid=os.getpid(), start_time=fields[19], elf_path=str(elf),
                uid=os.getuid(), token=uuid.uuid4().hex)
temporary = marker.with_name(marker.name + '.' + uuid.uuid4().hex + '.tmp')
with temporary.open('x') as stream:
    json.dump(identity, stream)
temporary.chmod(0o600)
os.replace(str(temporary), str(marker))
elf.chmod(elf.stat().st_mode | stat.S_IXUSR)
log_fd = os.open(str(log), os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
os.dup2(log_fd, 1)
os.dup2(log_fd, 2)
os.close(log_fd)
os.chdir(str(elf.parent))
os.execv(str(elf), [str(elf)] + config.get('arguments', []))
'''

_AUTOSTART_LIBRARY = r'''
import json, os, pwd, stat, subprocess, sys, uuid
from pathlib import Path

UNIT = 'pyxcp-host-model.service'
MARKER = '# Managed by PyXCP Host: model autostart v1\n'
home = Path.home().resolve()
base = home / '.local' / 'share' / 'pyxcp-host'
unit = home / '.config' / 'systemd' / 'user' / UNIT
config = base / 'autostart.json'
runner = base / 'model_runner.py'

def safe_file(path):
    path = Path(path)
    for part in [path] + list(path.parents):
        if part.is_symlink():
            raise ValueError('Autostart paths cannot contain symlinks')
        if part == home:
            break
    if home not in path.resolve().parents:
        raise ValueError('Autostart files must be below the SSH home')
    if path.exists() and not path.is_file():
        raise ValueError('Autostart path is not a regular file')
    return path

def run(arguments, required=True):
    env = dict(os.environ)
    env['XDG_RUNTIME_DIR'] = '/run/user/' + str(os.getuid())
    env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + env['XDG_RUNTIME_DIR'] + '/bus'
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=10, env=env)
    if required and result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or 'systemd command failed')
    return result

def systemctl(*arguments, required=True):
    return run(['systemctl', '--user', '--no-pager', '--no-ask-password'] + list(arguments), required)

def owned_files():
    for path in (unit, config, runner):
        safe_file(path)
    if unit.exists() and not unit.read_text().startswith(MARKER):
        raise RuntimeError('An unrelated service already uses ' + UNIT)
    if config.exists() and json.loads(config.read_text()).get('owner') != 'pyxcp-host-v1':
        raise RuntimeError('Autostart configuration is not owned by PyXCP Host')
    if runner.exists() and not runner.read_text().startswith('# Managed by PyXCP Host: model runner v1\n'):
        raise RuntimeError('Autostart runner is not owned by PyXCP Host')

def status():
    owned_files()
    stored = json.loads(config.read_text()) if config.exists() else {}
    user = pwd.getpwuid(os.getuid()).pw_name
    linger = run(['loginctl', 'show-user', user, '--property=Linger', '--value'], False)
    enabled = systemctl('is-enabled', UNIT, required=False)
    return dict(elf_path=stored.get('elf_path', ''), arguments=stored.get('arguments', []),
                enabled=enabled.returncode == 0 and enabled.stdout.strip() == 'enabled',
                linger=linger.returncode == 0 and linger.stdout.strip() == 'yes',
                unit=UNIT, username=user)

def atomic_write(path, data):
    safe_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
        temporary.chmod(0o600)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()

def configure(request):
    owned_files()
    previous = status()
    if not request.get('elf_path'):
        if unit.exists():
            systemctl('disable', UNIT)
        return status()
    elf = safe_file(request['elf_path'])
    if not elf.is_file():
        raise ValueError('Autostart ELF does not exist')
    with elf.open('rb') as stream:
        if stream.read(4) != b'\x7fELF':
            raise ValueError('Autostart file is not an ELF executable')
    if not previous['linger']:
        # Do not ask for an interactive administrator password over an SSH command channel.
        raise RuntimeError('Boot autostart requires user lingering. Administrator setup: '
                           'sudo loginctl enable-linger ' + previous['username'])
    arguments = request.get('arguments', [])
    if not isinstance(arguments, list) or any(not isinstance(arg, str) or '\x00' in arg for arg in arguments):
        raise ValueError('Invalid model arguments')
    saved = {path: path.read_bytes() if path.exists() else None for path in (unit, config, runner)}
    settings = dict(owner='pyxcp-host-v1', elf_path=str(elf), arguments=arguments)
    # All variable model paths/arguments stay in JSON; ExecStart only uses systemd's home specifier.
    contents = MARKER + '[Unit]\nDescription=PyXCP Host selected model\n' \
        '[Service]\nType=simple\nExecStart=/usr/bin/python3 "%h/.local/share/pyxcp-host/model_runner.py"\n' \
        'Restart=no\nTimeoutStopSec=5\n[Install]\nWantedBy=default.target\n'
    try:
        atomic_write(config, json.dumps(settings).encode())
        atomic_write(runner, request['runner'].encode())
        atomic_write(unit, contents.encode())
        systemctl('daemon-reload')
        systemctl('enable', UNIT)
        result = status()
        if not result['enabled']:
            raise RuntimeError('systemd did not enable the selected model')
        return result
    except BaseException:
        for path, data in saved.items():
            if data is None:
                if path.exists():
                    path.unlink()
            else:
                atomic_write(path, data)
        systemctl('daemon-reload', required=False)
        systemctl('enable' if previous['enabled'] else 'disable', UNIT, required=False)
        raise

'''


_AUTOSTART_HELPER = _AUTOSTART_LIBRARY + r'''
if __name__ == '__main__':
    request = json.loads(sys.argv[1])
    print(json.dumps(status() if request['action'] == 'status' else configure(request)))
'''


def request_autostart(deployment, action, **values):
    payload = dict(values, action=action)
    if action == 'configure':
        payload['runner'] = _RUNNER
    command = 'python3 -c {} {}'.format(shlex.quote(_AUTOSTART_HELPER), shlex.quote(json.dumps(payload)))
    with deployment._operation_lock:
        deployment._begin()
        result = json.loads(deployment._execute(command, timeout=45.0))
    if not isinstance(result, dict) or not isinstance(result.get('enabled'), bool):
        raise ValueError('Invalid model autostart status returned by target')
    return result
