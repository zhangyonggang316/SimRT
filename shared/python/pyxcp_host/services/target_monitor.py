"""Read-only Linux resource sampling and bounded ELF discovery over existing SSH."""

from __future__ import annotations

import json
import shlex
from typing import Any, Dict, List

from .ssh_deployment import SSHDeployment


_TARGET_HELPER = r'''
import json, math, os, platform, shutil, stat, sys, time
from pathlib import Path

MAX_MODELS = 500
MAX_ENTRIES = 20000
MAX_DEPTH = 12
MAX_SECONDS = 8.0

def read_text(path):
    try:
        return Path(path).read_text(errors='replace')
    except (OSError, UnicodeError):
        return ''

def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None

def percentage(used, total):
    if used is None or total is None or total <= 0:
        return None
    return min(100.0, max(0.0, 100.0 * used / total))

def cpu_times(text):
    answer = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts or not (parts[0] == 'cpu' or
                             parts[0].startswith('cpu') and parts[0][3:].isdigit()):
            continue
        try:
            fields = [int(item) for item in parts[1:9]]
            if len(fields) < 4 or any(value < 0 for value in fields):
                continue
            # guest/guest_nice already belong to user/nice and are not counted twice.
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            answer[parts[0]] = (sum(fields), idle)
        except ValueError:
            continue
    return answer

def cpu_usage(before, after):
    answer = {}
    for name, current in after.items():
        previous = before.get(name)
        if previous is None:
            answer[name] = None
            continue
        total = current[0] - previous[0]
        idle = current[1] - previous[1]
        answer[name] = percentage(total - idle, total) if total > 0 and 0 <= idle <= total else None
    return answer

def memory_stats(text):
    fields = {}
    for line in text.splitlines():
        name, separator, tail = line.partition(':')
        pieces = tail.split()
        if separator and pieces:
            value = number(pieces[0])
            if value is not None:
                fields[name] = int(value * 1024)
    total = fields.get('MemTotal')
    available = fields.get('MemAvailable')
    if available is None:
        fallback = ('MemFree', 'Buffers', 'Cached')
        if all(name in fields for name in fallback):
            available = sum(fields[name] for name in fallback)
            available += fields.get('SReclaimable', 0) - fields.get('Shmem', 0)
    if total is not None and available is not None:
        available = min(total, max(0, available))
        used = total - available
    else:
        used = None
    return {'memory_total': total, 'memory_available': available,
            'memory_used': used, 'memory_percent': percentage(used, total)}

def network_stats(text):
    result = {}
    for line in text.splitlines():
        name, separator, tail = line.partition(':')
        if not separator:
            continue
        parts = tail.split()
        if len(parts) < 16:
            continue
        try:
            received, sent = int(parts[0]), int(parts[8])
            if received >= 0 and sent >= 0:
                result[name.strip()] = {'received_bytes': received, 'sent_bytes': sent}
        except ValueError:
            continue
    return result

def snapshot(proc=Path('/proc'), home=None):
    home = Path.home() if home is None else Path(home)
    before = cpu_times(read_text(proc / 'stat'))
    time.sleep(0.15)
    after = cpu_times(read_text(proc / 'stat'))
    usage = cpu_usage(before, after)
    cores = sorted((name for name in after if name != 'cpu'), key=lambda name: int(name[3:]))
    uptime_fields = read_text(proc / 'uptime').split()
    uptime = number(uptime_fields[0]) if uptime_fields else None
    loads = [number(value) for value in read_text(proc / 'loadavg').split()[:3]]
    loads += [None] * (3 - len(loads))
    answer = {'host': platform.node(), 'kernel': platform.release(),
        'architecture': platform.machine(), 'uptime': uptime,
        'cpu_percent': usage.get('cpu'),
        'core_percents': [usage.get(name) for name in cores],
        'cpu_count': len(cores) or os.cpu_count(), 'load_average': loads,
        'disk_path': str(home), 'disk_total': None, 'disk_used': None,
        'disk_available': None, 'disk_percent': None,
        'network': network_stats(read_text(proc / 'net' / 'dev'))}
    answer.update(memory_stats(read_text(proc / 'meminfo')))
    try:
        disk = shutil.disk_usage(str(home))
        answer.update(disk_total=disk.total, disk_used=disk.used, disk_available=disk.free,
                      disk_percent=percentage(disk.used, disk.total))
    except OSError:
        pass
    return answer

def safe_root(value, home):
    if not isinstance(value, str) or not value.strip() or any(c in value for c in '\x00\r\n\\'):
        raise ValueError('Use a dedicated model directory below the SSH home')
    given = Path(value.strip()).expanduser()
    if '..' in given.parts:
        raise ValueError('Parent traversal is not allowed')
    path = given if given.is_absolute() else home / given
    # Reject symlinks before resolving, including intermediate directory components.
    for component in [path] + list(path.parents):
        if component.is_symlink():
            raise ValueError('Model scan does not follow symlinks')
        if component == home:
            break
    path = path.resolve()
    if path == home or home not in path.parents:
        raise ValueError('Use a dedicated model directory below the SSH home')
    if path.exists() and not path.is_dir():
        raise ValueError('Model scan root is not a directory')
    return path

def process_identity(entry, uid):
    try:
        if entry.stat().st_uid != uid:
            return None
        data = (entry / 'stat').read_text()
        fields = data[data.rfind(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return {'pid': int(entry.name), 'start_time': fields[19],
                'elf_path': os.readlink(str(entry / 'exe')), 'uid': uid}
    except (OSError, ValueError, IndexError):
        return None

def process_map(proc, uid, deadline):
    processes = {}
    try:
        with os.scandir(str(proc)) as entries:
            for index, entry in enumerate(entries):
                if index >= MAX_ENTRIES or time.monotonic() > deadline:
                    break
                if not entry.name.isdigit():
                    continue
                identity = process_identity(Path(entry.path), uid)
                if identity:
                    processes.setdefault(identity['elf_path'], []).append(identity)
    except OSError:
        pass
    return processes

def is_owned(elf, identities):
    marker = Path(str(elf) + '.pyxcp-host.json')
    try:
        if marker.is_symlink():
            return False
        descriptor = os.open(str(marker), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                             getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
                return False
            stored = json.loads(stream.read(8193))
        if not isinstance(stored, dict) or not stored.get('token'):
            return False
        return any(all(stored.get(key) == identity.get(key)
                       for key in ('pid', 'start_time', 'elf_path', 'uid'))
                   for identity in identities)
    except (OSError, ValueError, UnicodeError):
        return False

def model_files(root, deadline, diagnostics=None):
    diagnostics = {} if diagnostics is None else diagnostics
    pending = [(root, 0)]
    count = 0
    while pending:
        directory, depth = pending.pop()
        if directory.is_symlink():
            continue
        try:
            with os.scandir(str(directory)) as entries:
                for entry in entries:
                    count += 1
                    diagnostics['scanned_entries'] = count
                    if count > MAX_ENTRIES or time.monotonic() > deadline:
                        diagnostics.update(truncated=True, reason='entry/time limit')
                        return
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if depth < MAX_DEPTH:
                            pending.append((Path(entry.path), depth + 1))
                        else:
                            diagnostics.update(truncated=True, reason='depth limit')
                    elif entry.name.lower().endswith('.elf') and entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
        except OSError:
            diagnostics.update(truncated=True, reason='unreadable directory')
            continue

def list_models(value='MATLAB_ws', home=None, proc=Path('/proc'), uid=None, diagnostics=None):
    home = (Path.home() if home is None else Path(home)).resolve()
    root = safe_root(value, home)
    diagnostics = {} if diagnostics is None else diagnostics
    diagnostics.update(root=str(root), truncated=False, reason='', scanned_entries=0,
                       max_models=MAX_MODELS, max_entries=MAX_ENTRIES, max_depth=MAX_DEPTH)
    if not root.exists():
        return []
    uid = os.getuid() if uid is None else uid
    deadline = time.monotonic() + MAX_SECONDS
    processes = process_map(proc, uid, deadline)
    answer = []
    for elf in model_files(root, deadline, diagnostics):
        try:
            # Nonblocking + no-follow avoids FIFOs or symlinks swapped in during discovery.
            descriptor = os.open(str(elf), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                                 getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or stream.read(4) != b'\x7fELF':
                    continue
            if len(answer) >= MAX_MODELS:
                diagnostics.update(truncated=True, reason='model limit')
                break
            identities = processes.get(str(elf), [])
            pids = sorted(item['pid'] for item in identities)
            a2l = elf.with_suffix('.a2l')
            a2l_path = str(a2l) if a2l.is_file() and not a2l.is_symlink() else ''
            answer.append({'name': elf.stem, 'path': str(elf), 'size': info.st_size,
                'mtime': info.st_mtime, 'running': bool(pids), 'pid': pids[0] if pids else None,
                'pids': pids, 'owned': is_owned(elf, identities), 'a2l_path': a2l_path})
        except OSError:
            continue
    return sorted(answer, key=lambda item: (not item['running'], item['name'].lower(), item['path']))

if __name__ == '__main__':
    request = json.loads(sys.argv[1])
    if request['action'] == 'snapshot':
        answer = snapshot()
    elif request['action'] == 'models':
        diagnostics = {}
        models = list_models(request.get('root', 'MATLAB_ws'), diagnostics=diagnostics)
        answer = dict(models=models, scan=diagnostics)
    else:
        raise ValueError('Unknown monitor operation')
    print(json.dumps(answer, allow_nan=False))
'''


class TargetMonitor:
    """Shares deployment serialization/cancellation; performs no remote mutation."""

    def __init__(self, deployment: SSHDeployment) -> None:
        self.deployment = deployment
        self.last_scan = {}

    def _request(self, action: str, **values: Any) -> Any:
        payload = json.dumps(dict(values, action=action))
        command = 'python3 -c {} {}'.format(shlex.quote(_TARGET_HELPER), shlex.quote(payload))
        with self.deployment._operation_lock:
            self.deployment._begin()
            output = self.deployment._execute(command, timeout=15.0)
        return json.loads(output)

    def snapshot(self) -> Dict[str, Any]:
        """Return bytes/seconds and 0..100 percentages; unavailable metrics are None."""
        result = self._request('snapshot')
        if not isinstance(result, dict):
            raise ValueError('Invalid resource snapshot returned by target')
        return result

    def list_models(self, root: str = 'MATLAB_ws') -> List[Dict[str, Any]]:
        """List at most 500 verified .elf files within one dedicated home subdirectory."""
        root = self.deployment._validate_remote(root)
        result = self._request('models', root=root)
        if isinstance(result, dict) and isinstance(result.get('models'), list):
            self.last_scan = result.get('scan', {})
            result = result['models']
        else:
            self.last_scan = {}
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise ValueError('Invalid model list returned by target')
        return result
