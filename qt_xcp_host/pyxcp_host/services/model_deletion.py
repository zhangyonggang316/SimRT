"""Remove one stopped model deployment through a bounded remote operation."""

import json
import shlex

from .model_autostart import _AUTOSTART_LIBRARY


_DELETE_HELPER = _AUTOSTART_LIBRARY + r'''
import fcntl, shutil, time

MAX_ENTRIES = 20000
MAX_SECONDS = 8.0

def model_path(value):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in '\x00\r\n\\'):
        raise ValueError('Invalid model path')
    given = Path(value.strip()).expanduser()
    if '..' in given.parts:
        raise ValueError('Parent traversal is not allowed')
    candidate = given if given.is_absolute() else home / given
    for part in [candidate] + list(candidate.parents):
        if part.is_symlink():
            raise ValueError('Model deletion does not follow symlinks')
        if part == home:
            break
    candidate = candidate.resolve()
    if candidate == home or home not in candidate.parents:
        raise ValueError('Model must be below the SSH home')
    if candidate.relative_to(home).parts[0].startswith('.'):
        raise ValueError('Hidden home directories are not model deployments')
    return candidate

def validate_tree(directory, elf):
    deadline = time.monotonic() + MAX_SECONDS
    pending = [directory]
    count = 0
    while pending:
        current = pending.pop()
        if current.is_symlink():
            raise ValueError('Model deletion does not follow symlinks')
        with os.scandir(str(current)) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES or time.monotonic() > deadline:
                    raise RuntimeError('Model directory is too large to validate for deletion')
                if entry.is_symlink():
                    raise ValueError('Model directory contains a symlink')
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif not entry.is_file(follow_symlinks=False):
                    raise ValueError('Model directory contains a non-regular file')
                elif entry.name.lower().endswith('.elf') and Path(entry.path) != elf:
                    raise ValueError('Model directory contains another ELF; refusing to delete shared files')

def ensure_stopped(directory, proc=Path('/proc')):
    deadline = time.monotonic() + MAX_SECONDS
    count = 0
    with os.scandir(str(proc)) as entries:
        for entry in entries:
            count += 1
            if count > MAX_ENTRIES or time.monotonic() > deadline:
                raise RuntimeError('Could not finish checking model processes')
            if not entry.name.isdigit():
                continue
            process = Path(entry.path)
            try:
                if process.stat().st_uid != os.getuid():
                    continue
                fields = (process / 'stat').read_text().rsplit(')', 1)[1].split()
                if fields[0] == 'Z':
                    continue
                executable = os.readlink(str(process / 'exe'))
                if executable.endswith(' (deleted)'):
                    executable = executable[:-10]
                if directory in Path(executable).parents:
                    raise RuntimeError('Stop the model before deleting its directory')
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (PermissionError, ValueError, IndexError) as error:
                raise RuntimeError('Could not verify that model processes are stopped') from error

def clear_autostart(elf):
    safe_file(config)
    if not config.exists():
        return None
    stored = json.loads(config.read_text())
    if not isinstance(stored, dict):
        raise ValueError('Invalid model autostart configuration')
    if stored.get('elf_path') != str(elf):
        return None
    owned_files()
    lock = safe_file(base / 'model.lock')
    descriptor = os.open(str(lock), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Stop the autostart model before deleting its directory') from error
        previous = status()
        saved = {path: path.read_bytes() if path.exists() else None for path in (unit, config)}
        try:
            if unit.exists():
                systemctl('disable', UNIT)
                if systemctl('is-enabled', UNIT, required=False).returncode == 0:
                    raise RuntimeError('Could not disable model autostart')
            config.unlink()
            if unit.exists():
                unit.unlink()
                systemctl('daemon-reload')
        except BaseException:
            rollback = descriptor, previous, saved
            descriptor = None
            restore_autostart(rollback)
            raise
        return descriptor, previous, saved
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise

def restore_autostart(saved):
    if saved is None:
        return
    descriptor, previous, contents = saved
    try:
        for path, data in contents.items():
            if data is not None:
                atomic_write(path, data)
        systemctl('daemon-reload', required=False)
        if previous['enabled']:
            systemctl('enable', UNIT, required=False)
    finally:
        os.close(descriptor)

def delete_model(request):
    elf = model_path(request['path'])
    root = model_path(request.get('root', 'MATLAB_ws'))
    directory = elf.parent
    if directory == home or not (directory == root or root in directory.parents):
        raise ValueError('Model directory is outside the selected scan root')
    if not root.is_dir() or not directory.is_dir() or not elf.is_file():
        raise ValueError('Selected model no longer exists')
    descriptor = os.open(str(elf), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read(4) != b'\x7fELF':
            raise ValueError('Selected file is not an ELF executable')
    validate_tree(directory, elf)
    ensure_stopped(directory)
    identity = directory.stat()
    saved_autostart = clear_autostart(elf)
    parent_fd = None
    moved = False
    removing = False
    temporary = directory.with_name('.pyxcp-delete-' + uuid.uuid4().hex)
    try:
        # Pin the parent and re-check before rename. Starts using the original path
        # can no longer succeed after rename; inspect processes again before removal.
        parent_fd = os.open(str(directory.parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        pinned_parent = Path('/proc/self/fd') / str(parent_fd)
        current = model_path(directory.as_posix()).stat()
        if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise RuntimeError('Model directory changed during deletion')
        ensure_stopped(directory)
        validate_tree(directory, elf)
        os.rename(directory.name, temporary.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        moved = True
        moved_path = pinned_parent / temporary.name
        current = moved_path.lstat()
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
            raise RuntimeError('Model directory changed during deletion')
        ensure_stopped(temporary)
        ensure_stopped(directory)
        validate_tree(moved_path, moved_path / elf.name)
        if not shutil.rmtree.avoids_symlink_attacks:
            raise RuntimeError('Target Python does not support safe directory deletion')
        removing = True
        shutil.rmtree(str(moved_path))
        moved = False
    except BaseException:
        if moved:
            # Restore the visible path on failure, including partial removal errors.
            if not directory.exists() and not directory.is_symlink():
                os.rename(temporary.name, directory.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        if not removing:
            rollback = saved_autostart
            saved_autostart = None
            restore_autostart(rollback)
        raise
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        if saved_autostart is not None:
            os.close(saved_autostart[0])
    return dict(deleted=True, elf_path=str(elf), directory=str(directory),
                autostart_cleared=saved_autostart is not None)

if __name__ == '__main__':
    print(json.dumps(delete_model(json.loads(sys.argv[1]))))
'''


def request_delete(deployment, remote_elf, root):
    payload = dict(path=remote_elf, root=root)
    command = 'python3 -c {} {}'.format(shlex.quote(_DELETE_HELPER), shlex.quote(json.dumps(payload)))
    result = json.loads(deployment._execute(command, timeout=60.0))
    if (not isinstance(result, dict) or result.get('deleted') is not True
            or not isinstance(result.get('elf_path'), str)
            or not isinstance(result.get('directory'), str)
            or not isinstance(result.get('autostart_cleared'), bool)):
        raise ValueError('Invalid model deletion result returned by target')
    return result
