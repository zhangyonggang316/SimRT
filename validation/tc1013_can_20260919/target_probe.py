"""Read-only TC1013 prerequisite audit; credentials come from the environment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qt_xcp_host"))
from pyxcp_host.services.ssh_deployment import SSHDeployment

sys.excepthook = sys.__excepthook__

REMOTE_PROBE = r'''
import fnmatch, json, os, platform, stat, subprocess, time
from pathlib import Path

def text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None

def command(argv, timeout=8):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {'exit_code': result.returncode, 'stdout': result.stdout[-24000:],
                'stderr': result.stderr[-4000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': str(exc)}

devices = []
for entry in sorted(Path('/sys/bus/usb/devices').glob('*')):
    vendor, product = text(entry / 'idVendor'), text(entry / 'idProduct')
    if not vendor or not product:
        continue
    device = {'sysfs': str(entry), 'vendor_id': vendor, 'product_id': product,
              'manufacturer': text(entry / 'manufacturer'), 'product': text(entry / 'product'),
              'serial': text(entry / 'serial')}
    bus, number = text(entry / 'busnum'), text(entry / 'devnum')
    if bus and number:
        node = Path('/dev/bus/usb/{:03d}/{:03d}'.format(int(bus), int(number)))
        try:
            info = node.stat()
            device.update(node=str(node), mode=stat.filemode(info.st_mode), uid=info.st_uid,
                          gid=info.st_gid, readable=os.access(node, os.R_OK),
                          writable=os.access(node, os.W_OK))
        except OSError as exc:
            device['node_error'] = str(exc)
    devices.append(device)

processes = []
for entry in Path('/proc').glob('[0-9]*'):
    try:
        exe = os.readlink(entry / 'exe')
        if not (exe.lower().endswith('.elf') or any(
                value in exe.lower() for value in ('x280', 'tscan', 'tc1013', 'tsmaster'))):
            continue
        processes.append({'pid': int(entry.name), 'exe': exe,
                          'uid': entry.stat().st_uid, 'status': text(entry / 'comm')})
    except OSError:
        pass

sdk_libraries, search_errors, skipped = [], [], []
deadline = time.monotonic() + 12
directories = 0
for root in (str(Path.home()), '/opt', '/usr/local'):
    for directory, children, filenames in os.walk(root, followlinks=False,
                                                 onerror=lambda exc: search_errors.append(str(exc))):
        directories += 1
        if time.monotonic() > deadline or directories > 30000:
            skipped.append('Search bound reached in ' + root)
            break
        depth = len(Path(directory).relative_to(root).parts)
        children[:] = [name for name in children if name not in
                       ('.cache', '.git', '.npm', 'node_modules', 'proc', 'sys')]
        if depth >= 9:
            children[:] = []
        for name in filenames:
            lower = name.lower()
            if any(fnmatch.fnmatch(lower, pattern) for pattern in
                   ('*tscan*.so*', 'libtsh.so*', 'blf.so*', 'libblf.so*')):
                path = Path(directory) / name
                try:
                    sdk_libraries.append({'path': str(path), 'size': path.stat().st_size,
                                          'file': command(['file', str(path)])})
                except OSError as exc:
                    search_errors.append(str(exc))

result = {
    'kernel': platform.release(), 'architecture': platform.machine(),
    'os_release': text('/etc/os-release'), 'realtime_flag': text('/sys/kernel/realtime'),
    'identity': command(['id']), 'usb': devices, 'lsusb': command(['lsusb']),
    'running_related_processes': processes, 'sdk_libraries': sdk_libraries,
    'searched_directories': directories, 'search_bounds': skipped,
    'search_errors': search_errors[:30],
    'dynamic_libraries': command(['sh', '-c', "ldconfig -p 2>/dev/null | grep -Ei 'libusb|tscan|tsh|blf'"]),
    'default_driver_directory_exists': Path('/home/zh/.local/lib/tscan').is_dir(),
    'python': command(['python3', '--version']),
}
print(json.dumps(result))
'''


def credentials_from_environment() -> tuple[str, str, str]:
    password = os.environ.get("SIMRT_SSH_PASSWORD")
    if not password:
        raise ValueError("Set SIMRT_SSH_PASSWORD before running hardware validation")
    host = os.environ.get("SIMRT_SSH_HOST", "192.168.219.86").strip()
    username = os.environ.get("SIMRT_SSH_USERNAME", "zh").strip()
    if not host or not username:
        raise ValueError("SIMRT_SSH_HOST and SIMRT_SSH_USERNAME must not be empty")
    return host, username, password


def local_sdk_inventory(root: Path) -> dict:
    libraries, archives = [], []
    if not root.is_dir():
        return {"directory": str(root), "error": "Directory does not exist"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".so" in path.name.lower() or path.suffix.lower() in (".dll", ".a"):
            libraries.append({"path": str(path.relative_to(root)), "size": path.stat().st_size})
        elif path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    matches = [entry.filename for entry in archive.infolist()
                               if ".so" in Path(entry.filename).name.lower()]
                    archives.append({"path": str(path.relative_to(root)), "linux_shared_libraries": matches})
            except (OSError, zipfile.BadZipFile) as exc:
                archives.append({"path": str(path.relative_to(root)), "error": str(exc)})
    return {"directory": str(root), "libraries": libraries, "archives": archives}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-dir", type=Path, default=Path("C:/DataSave/06同星二次开发库"))
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("target_probe.json"))
    args = parser.parse_args()
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "read_only": True, "local_sdk": local_sdk_inventory(args.sdk_dir)}
    service = SSHDeployment()
    password = None
    try:
        host, username, password = credentials_from_environment()
        result["endpoint"] = {"host": host, "username": username, "port": 22}
        service.connect(host, username, password=password)
        result["target"] = json.loads(service._execute(
            "python3 -c " + shlex.quote(REMOTE_PROBE), timeout=60))
        result["ssh_connected"] = True
    except Exception as exc:
        result["ssh_connected"] = service.connected
        # Authentication exceptions never echo credentials; avoid traceback/local dumps.
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        service.close()
        password = None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if "target" in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
