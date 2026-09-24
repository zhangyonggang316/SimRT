"""Independent SSH source deployment and owned ELF process control."""

from __future__ import annotations

import base64
import codecs
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

import paramiko

from .model_payload import validate_payload


_EXCLUDED = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
             ".tox", "node_modules", "build", "dist", ".build_cache"}
_OUTPUT_LIMIT = 2 * 1024 * 1024


# The remote helper handles paths and /proc identities as data, never shell code.
_REMOTE_HELPER = r'''
import hashlib, json, os, signal, stat, subprocess, sys, time, uuid
from pathlib import Path
request = json.loads(sys.argv[1])
home = Path.home().resolve()

def safe_path(value, directory=False, create=False):
    if not value or '\x00' in value or '\n' in value or '\r' in value:
        raise ValueError('Invalid remote path')
    given = Path(value).expanduser()
    if '..' in given.parts:
        raise ValueError('Parent traversal is not allowed')
    path = given if given.is_absolute() else home / given
    if any(p.is_symlink() for p in [path] + list(path.parents) if p != home.parent):
        raise ValueError('Remote symlinks are not supported')
    path = path.resolve()
    if path == home or home not in path.parents:
        raise ValueError('Deployment must use a dedicated directory below the SSH home')
    if directory and create:
        path.mkdir(parents=True, exist_ok=True)
    if directory and path.exists() and not path.is_dir():
        raise ValueError('Remote destination is not a directory')
    return path

def fingerprint(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('ELF file does not exist or is a symlink')
    with path.open('rb') as stream:
        if stream.read(4) != b'\x7fELF':
            raise ValueError('Selected file is not an ELF executable')
        stream.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'elf_path': str(path), 'sha256': digest.hexdigest(), 'size': path.stat().st_size}

def process_identity(pid):
    try:
        process = Path('/proc') / str(int(pid))
        data = (process / 'stat').read_text()
        fields = data[data.rfind(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return {'pid': int(pid), 'start_time': fields[19],
                'elf_path': os.readlink(str(process / 'exe')), 'uid': process.stat().st_uid}
    except (OSError, ValueError, IndexError):
        return None

def state_path(elf):
    return safe_path(str(elf) + '.pyxcp-host.json')

def owned_state(elf):
    marker = state_path(elf)
    if not marker.is_file():
        return None
    stored = json.loads(marker.read_text())
    current = process_identity(stored.get('pid', 0))
    if not stored.get('token') or current is None:
        return None
    keys = ('pid', 'start_time', 'elf_path', 'uid')
    if any(stored.get(key) != current.get(key) for key in keys):
        return None
    if current['elf_path'] != str(elf) or current['uid'] != os.getuid():
        return None
    return stored

def ensure_not_running(directory):
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        current = process_identity(int(entry.name))
        if current and current['uid'] == os.getuid():
            executable_path = current['elf_path']
            if executable_path.endswith(' (deleted)'):
                executable_path = executable_path[:-10]
            executable = Path(executable_path)
            if directory in executable.parents:
                raise RuntimeError('Stop executables in the destination before upload or build')
    for base, directories, names in os.walk(str(directory), followlinks=False):
        directories[:] = [name for name in directories if not Path(base, name).is_symlink()]
        for name in names:
            if name.endswith('.pyxcp-host.json'):
                elf = Path(base, name[:-len('.pyxcp-host.json')])
                if owned_state(elf):
                    raise RuntimeError('Stop the deployed ELF before upload or build')

def verify_payload(directory, files):
    if not isinstance(files, dict) or not files:
        raise ValueError('Payload file hashes are required')
    for name, expected in files.items():
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts or '\\' in name
                or relative.as_posix() != name or name.startswith('.pyxcp-')):
            raise ValueError('Invalid payload file path')
        path = safe_path(str(directory / relative))
        if not path.is_file():
            raise ValueError('Payload file is missing: ' + name)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1048576), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise RuntimeError('Payload SHA256 mismatch: ' + name)

def check_deployed_payload(elf):
    directory = elf.parent
    if safe_path(str(directory / '.pyxcp-payload.pending')).exists():
        raise RuntimeError('Payload upload did not complete verification; redeploy before starting')
    receipt = safe_path(str(directory / '.pyxcp-payload.json'))
    if receipt.exists():
        deployment = json.loads(receipt.read_text())
        if deployment.get('elf_name') != elf.name:
            raise RuntimeError('ELF does not belong to the verified payload')
        verify_payload(directory, deployment['files'])

action = request['action']
if action == 'home':
    answer = {'home': str(home), 'python': sys.version.split()[0]}
elif action == 'directory':
    directory = safe_path(request['path'], directory=True, create=request.get('create', False))
    if request.get('require_stopped'):
        ensure_not_running(directory)
    answer = {'remote_directory': str(directory)}
elif action == 'elf':
    answer = fingerprint(safe_path(request['path']))
elif action in ('payload_begin', 'payload_verify'):
    directory = safe_path(request['path'], directory=True, create=action == 'payload_begin')
    ensure_not_running(directory)
    pending = safe_path(str(directory / '.pyxcp-payload.pending'))
    receipt = safe_path(str(directory / '.pyxcp-payload.json'))
    if action == 'payload_begin':
        pending.write_text('Upload requires complete hash verification before start.\n')
        pending.chmod(0o600)
    else:
        if not pending.is_file():
            raise RuntimeError('Missing pending deployment marker')
        verify_payload(directory, request['files'])
        elf = safe_path(str(directory / request['elf_name']))
        if elf.parent != directory or elf.name not in request['files']:
            raise ValueError('ELF is not covered by the payload')
        fingerprint(elf)
        elf.chmod(elf.stat().st_mode | stat.S_IXUSR)
        temporary = receipt.with_name(receipt.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'elf_name': elf.name, 'files': request['files']}))
            temporary.chmod(0o600)
            os.replace(str(temporary), str(receipt))
            pending.unlink()
        finally:
            if temporary.exists():
                temporary.unlink()
    answer = {'remote_directory': str(directory), 'verified': action == 'payload_verify'}
elif action in ('start', 'stop', 'status', 'log'):
    elf = safe_path(request['path'])
    log = safe_path(str(elf) + '.pyxcp-host.log')
    stored = owned_state(elf)
    if action == 'start' and stored is None:
        check_deployed_payload(elf)
        fingerprint(elf)
        elf.chmod(elf.stat().st_mode | stat.S_IXUSR)
        with log.open('ab') as output:
            environment = dict(os.environ)
            runtime_environment = request.get('runtime_environment', {})
            if any(key not in ('X280_RT_REQUIRE_KERNEL', 'X280_RT_PRIORITY', 'X280_RT_CPU')
                   or not isinstance(value, str) or not value.isdigit()
                   for key, value in runtime_environment.items()):
                raise ValueError('Invalid RT runtime environment')
            environment.update(runtime_environment)
            child = subprocess.Popen([str(elf)] + request.get('arguments', []),
                cwd=str(elf.parent), stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, env=environment)
        time.sleep(0.12)
        stored = process_identity(child.pid)
        if stored is None or child.poll() is not None:
            raise RuntimeError('ELF exited immediately; inspect the runtime log')
        stored['token'] = uuid.uuid4().hex
        marker = state_path(elf)
        temporary = marker.with_name(marker.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(stored))
            temporary.chmod(0o600)
            os.replace(str(temporary), str(marker))
        except BaseException:
            child.terminate()
            child.wait(timeout=3)
            raise
    elif action == 'stop' and stored is not None:
        # Re-check before every signal; never kill a reused PID or another executable.
        for sig, seconds in ((signal.SIGTERM, 3.0), (signal.SIGKILL, 1.0)):
            current = owned_state(elf)
            if current is None:
                break
            if hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'):
                try:
                    descriptor = os.pidfd_open(current['pid'])
                except ProcessLookupError:
                    break
                try:
                    if owned_state(elf) != current:
                        break
                    signal.pidfd_send_signal(descriptor, sig)
                finally:
                    os.close(descriptor)
            else:
                os.kill(current['pid'], sig)
            deadline = time.monotonic() + seconds
            while owned_state(elf) is not None and time.monotonic() < deadline:
                time.sleep(0.05)
        stored = owned_state(elf)
        if stored is not None:
            raise RuntimeError('Owned ELF did not stop')
    if action == 'log':
        if log.is_file():
            with log.open('rb') as source:
                source.seek(max(0, log.stat().st_size - 65536))
                text = source.read(65536).decode('utf-8', errors='replace')
            answer = {'text': '\n'.join(text.splitlines()[-200:])}
        else:
            answer = {'text': ''}
    else:
        answer = {'running': stored is not None, 'pid': stored['pid'] if stored else None,
                  'state': 'running' if stored else 'stopped', 'elf_path': str(elf),
                  'log_path': str(log)}
else:
    raise ValueError('Unknown remote operation')
print(json.dumps(answer))
'''


# Keep SSH stdin open: EOF means cancellation/disconnection and terminates the build group.
_BUILD_HELPER = r'''
import json, os, selectors, signal, subprocess, sys, time
request = json.loads(sys.argv[1])
child = subprocess.Popen(['/bin/sh', '-c', request['command']],
    cwd=request['directory'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
selector = selectors.DefaultSelector()
selector.register(child.stdout, selectors.EVENT_READ, 'output')
selector.register(sys.stdin.buffer, selectors.EVENT_READ, 'input')
deadline = time.monotonic() + request['timeout']
failure = None
try:
    while child.poll() is None or selector.get_map().get(child.stdout.fileno()):
        if time.monotonic() >= deadline:
            failure = 'Remote build timed out'
            break
        for key, _ in selector.select(0.1):
            data = os.read(key.fd, 16384)
            if key.data == 'input':
                if not data:
                    failure = 'Remote build cancelled'
                    break
            elif data:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            else:
                selector.unregister(key.fileobj)
        if failure:
            break
finally:
    if failure or child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
    selector.close()
if failure:
    print(failure, file=sys.stderr)
    sys.exit(124)
sys.exit(child.wait())
'''


class _RememberHostKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, filename: Path, log: Callable[[str], None]) -> None:
        self.filename = filename
        self.log = log

    def missing_host_key(self, client: Any, hostname: str, key: Any) -> None:
        fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        self.log('First SSH host key: {} {} SHA256:{}'.format(hostname, key.get_name(), fingerprint))
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        client.get_host_keys().add(hostname, key.get_name(), key)
        client.save_host_keys(str(self.filename))


class SSHDeployment:
    """One SSH connection with serial operations and independently callable cancellation."""

    def __init__(self, log_callback: Optional[Callable[[str], None]] = None) -> None:
        self._log_callback = log_callback
        self._client = None
        self._operation_lock = threading.RLock()
        self._active_lock = threading.Lock()
        self._active = None
        self._cancelled = threading.Event()
        self._remote_elf = ''
        self._identity = None
        self._host = ''
        self._username = ''
        self._port = 22
        self._pid = None
        self._home = ''

    @property
    def connected(self) -> bool:
        client = self._client
        transport = client.get_transport() if client is not None else None
        return bool(transport is not None and transport.is_active())

    @property
    def host(self) -> str:
        return self._host

    @property
    def pid(self) -> Optional[int]:
        return self._pid

    def _log(self, message: str) -> None:
        if self._log_callback is not None:
            self._log_callback(message)

    @staticmethod
    def _timeout(value: float) -> float:
        result = float(value)
        if not math.isfinite(result) or result <= 0:
            raise ValueError('Timeout must be a finite positive number')
        return result

    def connect(self, host: str, username: str, password: str = '', port: int = 22,
                key_filename: str = '') -> Dict[str, Any]:
        host, username = host.strip(), username.strip()
        if not host or not username or any(c in host + username for c in '\r\n\x00'):
            raise ValueError('SSH host and username are required')
        if not 1 <= int(port) <= 65535:
            raise ValueError('SSH port must be between 1 and 65535')
        if key_filename:
            raise ValueError('SSH private-key authentication is not supported; use a password')
        if not password:
            raise ValueError('SSH password is required')
        with self._operation_lock:
            self.close()
            self._cancelled.clear()
            client = paramiko.SSHClient()
            known_hosts = Path.home() / '.ssh' / 'known_hosts'
            client.load_system_host_keys()
            if known_hosts.is_file():
                client.load_host_keys(str(known_hosts))
            client.set_missing_host_key_policy(_RememberHostKey(known_hosts, self._log))
            try:
                client.connect(hostname=host, port=int(port), username=username,
                               password=password or None,
                               timeout=8.0, auth_timeout=8.0, banner_timeout=8.0,
                               look_for_keys=False, allow_agent=False)
                if self._cancelled.is_set():
                    raise InterruptedError('SSH connection cancelled')
                self._client = client
                result = self._request('home')
                identity = (host, int(port), username)
                if self._identity != identity:
                    self._remote_elf = ''
                    self._pid = None
                self._identity = identity
                self._host, self._username, self._port = host, username, int(port)
                self._home = result['home']
                result.update(host=host, username=username, port=int(port))
                self._log('SSH connected to {}:{}'.format(host, port))
                return result
            except BaseException:
                self._client = None
                client.close()
                raise

    def cancel(self) -> None:
        self._cancelled.set()
        with self._active_lock:
            active = self._active
        if active is not None:
            try:
                if hasattr(active, 'shutdown_write'):
                    active.shutdown_write()
                active.close()
            except (OSError, EOFError):
                pass

    def close(self) -> None:
        self.cancel()
        client, self._client = self._client, None
        if client is not None:
            client.close()

    def _begin(self) -> None:
        if not self.connected:
            raise ConnectionError('Connect SSH first')
        self._cancelled.clear()

    def _check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise InterruptedError('SSH operation cancelled')

    def _execute(self, command: str, timeout: float = 30.0, stream: bool = False) -> str:
        timeout = self._timeout(timeout)
        self._check_cancelled()
        if not self.connected:
            raise ConnectionError('Connect SSH first')
        channel = self._client.get_transport().open_session(timeout=min(timeout, 8.0))
        with self._active_lock:
            self._active = channel
        stdout, stderr = bytearray(), bytearray()
        decoders = [codecs.getincrementaldecoder('utf-8')('replace') for _ in range(2)]
        started = time.monotonic()
        try:
            channel.exec_command(command)
            while True:
                self._check_cancelled()
                if time.monotonic() - started > timeout:
                    raise TimeoutError('SSH command timed out after {} seconds'.format(timeout))
                received = False
                # Bound each drain pass so a busy stdout cannot starve stderr/cancellation.
                for ready, receive, target, decoder in ((channel.recv_ready, channel.recv, stdout, decoders[0]),
                                                (channel.recv_stderr_ready, channel.recv_stderr, stderr, decoders[1])):
                    for _ in range(8):
                        if not ready():
                            break
                        block = receive(32768)
                        if not block:
                            break
                        received = True
                        target.extend(block)
                        if len(target) > _OUTPUT_LIMIT:
                            del target[:-_OUTPUT_LIMIT]
                        if stream:
                            text = decoder.decode(block)
                            if text:
                                self._log(text)
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    code = channel.recv_exit_status()
                    break
                if not received:
                    self._cancelled.wait(0.02)
            output = stdout.decode('utf-8', errors='replace')
            error = stderr.decode('utf-8', errors='replace').strip()
            if code != 0:
                raise RuntimeError('Remote command exited {}: {}'.format(code, error or output[-4000:]))
            return output
        finally:
            try:
                channel.shutdown_write()
            except (OSError, EOFError):
                pass
            channel.close()
            with self._active_lock:
                if self._active is channel:
                    self._active = None

    def _request(self, action: str, **values: Any) -> Dict[str, Any]:
        payload = dict(values, action=action)
        command = 'python3 -c {} {}'.format(shlex.quote(_REMOTE_HELPER), shlex.quote(json.dumps(payload)))
        return json.loads(self._execute(command))

    @staticmethod
    def _validate_remote(path: str) -> str:
        path = path.strip()
        if not path or path in ('/', '.', '~', '~/') or '\\' in path:
            raise ValueError('Use a dedicated remote project path')
        if any(c in path for c in '\r\n\x00') or '..' in PurePosixPath(path).parts:
            raise ValueError('Remote path contains invalid characters or parent traversal')
        return path

    def upload(self, local_dir: Path, remote_dir: str) -> int:
        with self._operation_lock:
            self._begin()
            return self._upload(local_dir, remote_dir)

    def deploy_payload(self, local_dir: Path, remote_dir: str) -> Dict[str, Any]:
        payload = validate_payload(local_dir)
        remote_dir = self._validate_remote(remote_dir)
        with self._operation_lock:
            self._begin()
            target = self._request('payload_begin', path=remote_dir)['remote_directory']
            count = self._upload(Path(payload['directory']), target)
            self._check_cancelled()
            if validate_payload(local_dir)['files'] != payload['files']:
                raise RuntimeError('Local payload changed during upload; deploy it again')
            result = self._request('payload_verify', path=target, files=payload['files'],
                                   elf_name=payload['elf_name'])
            if result.get('verified') is not True:
                raise RuntimeError('Target did not confirm payload verification')
            result.update(file_count=count, elf_path=str(PurePosixPath(target, payload['elf_name'])),
                          a2l_path=payload['a2l'], files=payload['files'])
            self._log('Payload uploaded and SHA256 verified: ' + payload['elf_name'])
            return result

    def _upload(self, local_dir: Path, remote_dir: str) -> int:
        local_dir = Path(local_dir).expanduser()
        if local_dir.is_symlink():
            raise ValueError('Source directory cannot be a symlink')
        source = local_dir.resolve()
        if not source.is_dir() or source == Path(source.anchor) or source == Path.home().absolute():
            raise ValueError('Choose an existing dedicated source directory')
        remote_dir = self._validate_remote(remote_dir)
        files = []
        directories = []
        for base, names, filenames in os.walk(str(source), followlinks=False):
            self._check_cancelled()
            for name in list(names):
                entry = Path(base, name)
                if name in _EXCLUDED:
                    names.remove(name)
                elif entry.is_symlink():
                    raise ValueError('Source contains a symlink: {}'.format(entry.relative_to(source)))
                else:
                    directories.append(entry.relative_to(source).as_posix())
            for name in filenames:
                entry = Path(base, name)
                if entry.is_symlink() or not entry.is_file():
                    raise ValueError('Source contains a non-regular file: {}'.format(entry.relative_to(source)))
                if name.endswith(('.pyxcp-host.json', '.pyxcp-host.log')):
                    continue
                if Path(base) == source and name in ('.build.lock', 'build_result.json'):
                    continue
                files.append((entry, entry.relative_to(source).as_posix()))
        if not files:
            raise ValueError('Source directory contains no uploadable files')
        with self._operation_lock:
            self._check_cancelled()
            target = self._request('directory', path=remote_dir, create=True, require_stopped=True)['remote_directory']
            sftp = self._client.open_sftp()
            sftp.get_channel().settimeout(15.0)
            with self._active_lock:
                self._active = sftp
            try:
                for relative in directories:
                    self._check_cancelled()
                    remote = str(PurePosixPath(target, relative))
                    try:
                        attributes = sftp.lstat(remote)
                    except FileNotFoundError:
                        sftp.mkdir(remote)
                    else:
                        if not stat.S_ISDIR(attributes.st_mode):
                            raise ValueError('Remote source path is not a regular directory: {}'.format(relative))
                for entry, relative in files:
                    self._check_cancelled()
                    destination = str(PurePosixPath(target, relative))
                    try:
                        attributes = sftp.lstat(destination)
                    except FileNotFoundError:
                        pass
                    else:
                        if not stat.S_ISREG(attributes.st_mode):
                            raise ValueError('Remote destination is not a regular file: {}'.format(relative))
                    temporary = destination + '.pyxcp-upload-' + uuid.uuid4().hex
                    try:
                        sftp.put(str(entry), temporary, callback=lambda *_: self._check_cancelled())
                        sftp.chmod(temporary, entry.stat().st_mode & 0o777)
                        sftp.posix_rename(temporary, destination)
                    finally:
                        try:
                            sftp.remove(temporary)
                        except OSError:
                            pass
                    self._log('Uploaded {}'.format(relative))
            finally:
                sftp.close()
                with self._active_lock:
                    if self._active is sftp:
                        self._active = None
            return len(files)

    def build(self, remote_dir: str, command: str, timeout: float = 300.0) -> str:
        remote_dir = self._validate_remote(remote_dir)
        if not command.strip() or '\x00' in command:
            raise ValueError('Build command is required')
        timeout = self._timeout(timeout)
        with self._operation_lock:
            self._begin()
            directory = self._request('directory', path=remote_dir, require_stopped=True)['remote_directory']
            payload = json.dumps({'directory': directory, 'command': command, 'timeout': timeout})
            invocation = 'python3 -c {} {}'.format(shlex.quote(_BUILD_HELPER), shlex.quote(payload))
            self._log('Build started in {}'.format(directory))
            output = self._execute(invocation, timeout=timeout + 5.0, stream=True)
            self._log('Build completed')
            return output

    def download_elf(self, remote_elf: str, local_path: Path) -> Path:
        remote_elf = self._validate_remote(remote_elf)
        destination = Path(local_path).expanduser().absolute()
        if destination.is_symlink() or destination.is_dir():
            raise ValueError('Choose a regular local ELF output file')
        with self._operation_lock:
            self._begin()
            metadata = self._request('elf', path=remote_elf)
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, filename = tempfile.mkstemp(prefix='.' + destination.name + '.', suffix='.tmp', dir=str(destination.parent))
            os.close(descriptor)
            temporary = Path(filename)
            sftp = self._client.open_sftp()
            sftp.get_channel().settimeout(15.0)
            with self._active_lock:
                self._active = sftp
            try:
                sftp.get(metadata['elf_path'], str(temporary), callback=lambda *_: self._check_cancelled())
                self._check_cancelled()
                digest = hashlib.sha256()
                with temporary.open('rb') as source:
                    if source.read(4) != b'\x7fELF':
                        raise ValueError('Downloaded file is not an ELF executable')
                    source.seek(0)
                    for block in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(block)
                if temporary.stat().st_size != metadata['size'] or digest.hexdigest() != metadata['sha256']:
                    raise RuntimeError('ELF changed during download or SHA256 verification failed')
                os.replace(str(temporary), str(destination))
            finally:
                sftp.close()
                with self._active_lock:
                    if self._active is sftp:
                        self._active = None
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            self._log('ELF downloaded; SHA256 {}'.format(metadata['sha256']))
            return destination

    def start(self, remote_elf: str, arguments: str = '', runtime_environment=None) -> int:
        remote_elf = self._validate_remote(remote_elf)
        arguments_list = shlex.split(arguments, posix=True)
        if any('\x00' in item for item in arguments_list):
            raise ValueError('Arguments contain a null byte')
        with self._operation_lock:
            self._begin()
            if self._remote_elf:
                previous = self._request('status', path=self._remote_elf)
                candidate = self._request('elf', path=remote_elf)['elf_path']
                if previous['running'] and candidate != self._remote_elf:
                    raise RuntimeError('Stop the current owned ELF before starting another')
            candidate = self._request('elf', path=remote_elf)['elf_path']
            # Remember the path before launching so failed/short-lived starts remain inspectable.
            self._remote_elf = candidate
            values = dict(path=candidate, arguments=arguments_list)
            if runtime_environment is not None:
                values['runtime_environment'] = dict(runtime_environment)
            result = self._request('start', **values)
            self._remote_elf = result['elf_path']
            self._pid = int(result['pid'])
            self._log('ELF started with PID {}'.format(self._pid))
            return self._pid

    def status(self, remote_elf: Optional[str] = None) -> Dict[str, Any]:
        with self._operation_lock:
            self._begin()
            if remote_elf is not None:
                candidate = self._request('status', path=self._validate_remote(remote_elf))
                if self._remote_elf and candidate['elf_path'] != self._remote_elf:
                    previous = self._request('status', path=self._remote_elf)
                    if previous['running']:
                        raise RuntimeError('Stop the current owned ELF before selecting another')
                self._remote_elf = candidate['elf_path']
                self._pid = candidate['pid']
                return candidate
            if not self._remote_elf:
                return {'running': False, 'pid': None, 'state': 'stopped', 'elf_path': '', 'log_path': ''}
            result = self._request('status', path=self._remote_elf)
            self._pid = result['pid']
            return result

    def stop(self) -> bool:
        with self._operation_lock:
            self._begin()
            if not self._remote_elf:
                return False
            previous = self._request('status', path=self._remote_elf)
            result = self._request('stop', path=self._remote_elf)
            self._pid = result['pid']
            return bool(previous['running'] and not result['running'])

    def read_log(self) -> str:
        with self._operation_lock:
            self._begin()
            if not self._remote_elf:
                return ''
            return self._request('log', path=self._remote_elf)['text']

    def delete_model(self, remote_elf: str, root: str = 'MATLAB_ws') -> Dict[str, Any]:
        """Delete a stopped model's immediate parent directory and matching autostart."""
        from .model_deletion import request_delete
        remote_elf = self._validate_remote(remote_elf)
        root = self._validate_remote(root)
        with self._operation_lock:
            self._begin()
            result = request_delete(self, remote_elf, root)
            if self._remote_elf == result['elf_path']:
                self._remote_elf = ''
                self._pid = None
            self._log('Model directory deleted: ' + result['directory'])
            return result

    def autostart_status(self) -> Dict[str, Any]:
        from .model_autostart import request_autostart
        return request_autostart(self, 'status')

    def set_autostart(self, remote_elf: Optional[str], arguments: str = '') -> Dict[str, Any]:
        from .model_autostart import request_autostart
        arguments_list = shlex.split(arguments, posix=True)
        if any('\x00' in item for item in arguments_list):
            raise ValueError('Arguments contain a null byte')
        with self._operation_lock:
            self._begin()
            candidate = ''
            if remote_elf:
                candidate = self._request('elf', path=self._validate_remote(remote_elf))['elf_path']
            return request_autostart(self, 'configure', elf_path=candidate, arguments=arguments_list)
