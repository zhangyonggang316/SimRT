"""Install the pinned TC1013 SDK and verify USB access without transmitting CAN."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import sys
import uuid

from target_probe import ROOT, SSHDeployment, credentials_from_environment

sys.excepthook = sys.__excepthook__
DESTINATION = "/home/zh/.local/lib/tscan"
SERIAL = "37AFCA2612ADBF35"

USB_ACCESS = r'''
import grp, json, os, stat, sys
from pathlib import Path
expected = ('5453', '0001', '37AFCA2612ADBF35')
matches = []
for path in Path('/sys/bus/usb/devices').iterdir():
    try:
        identity = tuple((path / name).read_text().strip() for name in
                         ('idVendor', 'idProduct', 'serial'))
        if identity == expected:
            bus = int((path / 'busnum').read_text())
            number = int((path / 'devnum').read_text())
            node = Path('/dev/bus/usb/{:03d}/{:03d}'.format(bus, number))
            matches.append((path, node))
    except (OSError, ValueError):
        continue
if len(matches) != 1:
    raise RuntimeError('Expected exactly one matching TOSUN USB device')
path, node = matches[0]
before = node.stat()
if not stat.S_ISCHR(before.st_mode):
    raise RuntimeError('USB path is not a character device')
record = {'sysfs': str(path), 'node': str(node), 'identity': expected,
          'before': {'uid': before.st_uid, 'gid': before.st_gid,
                     'mode': stat.filemode(before.st_mode)}, 'changed': False}
if sys.argv[1] == 'fix':
    if os.geteuid() != 0:
        raise RuntimeError('Permission repair requires sudo')
    if not before.st_mode & stat.S_IWGRP:
        raise RuntimeError('Unexpected mode; refusing a broader permission change')
    group = grp.getgrnam('plugdev').gr_gid
    os.chown(node, -1, group, follow_symlinks=False)
    record['changed'] = before.st_gid != group
after = node.stat()
record['after'] = {'uid': after.st_uid, 'gid': after.st_gid,
                   'mode': stat.filemode(after.st_mode),
                   'readable': os.access(node, os.R_OK),
                   'writable': os.access(node, os.W_OK)}
print(json.dumps(record))
'''

SDK_PROBE = r'''
import ctypes as c, json, os
root = '/home/zh/.local/lib/tscan'
result = {'can_frames_transmitted': 0, 'channel_configuration_changed': False}
c.CDLL(root + '/libTSH.so', mode=c.RTLD_GLOBAL)
sdk = c.CDLL(root + '/libTSCANApiOnLinux.so', mode=c.RTLD_LOCAL)
sdk.initialize_lib_tscan.argtypes = [c.c_bool, c.c_bool, c.c_bool]
sdk.initialize_lib_tscan.restype = None
sdk.finalize_lib_tscan.argtypes = []
sdk.finalize_lib_tscan.restype = None
sdk.tscan_scan_devices.argtypes = [c.POINTER(c.c_uint32)]
sdk.tscan_scan_devices.restype = c.c_uint32
sdk.tscan_get_device_info.argtypes = [c.c_uint32, c.POINTER(c.c_char_p),
                                    c.POINTER(c.c_char_p), c.POINTER(c.c_char_p)]
sdk.tscan_get_device_info.restype = c.c_uint32
sdk.tscan_connect.argtypes = [c.c_char_p, c.POINTER(c.c_uint64)]
sdk.tscan_connect.restype = c.c_uint32
sdk.tscan_disconnect_by_handle.argtypes = [c.c_size_t]
sdk.tscan_disconnect_by_handle.restype = c.c_uint32
handle = c.c_uint64()
initialized = False
try:
    sdk.initialize_lib_tscan(True, False, False)
    initialized = True
    count = c.c_uint32()
    result['scan_status'] = int(sdk.tscan_scan_devices(c.byref(count)))
    result['device_count'] = count.value
    result['devices'] = []
    for index in range(min(count.value, 16)):
        manufacturer, product, serial = c.c_char_p(), c.c_char_p(), c.c_char_p()
        status = sdk.tscan_get_device_info(index, c.byref(manufacturer),
                                          c.byref(product), c.byref(serial))
        values = [p.value.decode('utf-8', 'replace') if p.value else ''
                  for p in (manufacturer, product, serial)]
        result['devices'].append(dict(index=index, status=int(status),
                                      manufacturer=values[0], product=values[1], serial=values[2]))
    expected = b'37AFCA2612ADBF35'
    if any(item['serial'].upper().encode() == expected for item in result['devices']):
        result['connect_status'] = int(sdk.tscan_connect(expected, c.byref(handle)))
        result['handle_nonzero'] = bool(handle.value)
    else:
        result['connect_skipped'] = 'Expected serial was not returned by SDK scan'
finally:
    if handle.value:
        result['disconnect_status'] = int(sdk.tscan_disconnect_by_handle(handle.value))
    if initialized:
        sdk.finalize_lib_tscan()
        result['finalized'] = True
print('X280_SDK_PROBE_JSON=' + json.dumps(result))
'''


def remote_python(service: SSHDeployment, source: str, timeout: float = 30) -> dict:
    return json.loads(service._execute("python3 -c " + shlex.quote(source), timeout=timeout))


def permission_probe(service: SSHDeployment, password: str) -> dict:
    before = json.loads(service._execute("python3 -c " + shlex.quote(USB_ACCESS) + " inspect"))
    result = {"before": before}
    if not before["after"]["writable"]:
        command = "sudo -S -p '' -- python3 -c " + shlex.quote(USB_ACCESS) + " fix"
        stdin, stdout, stderr = service._client.exec_command(command, timeout=15)
        stdin.write(password + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
        output = stdout.read().decode("utf-8", "replace")
        error = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if code != 0:
            raise RuntimeError("Device permission repair failed: " + error.strip())
        result["repair"] = json.loads(output)
    result["verified_as_ssh_user"] = json.loads(service._execute(
        "python3 -c " + shlex.quote(USB_ACCESS) + " inspect"))
    if not result["verified_as_ssh_user"]["after"]["writable"]:
        raise RuntimeError("The SSH user still cannot write the verified USB device")
    return result


def install(service: SSHDeployment) -> dict:
    vendor = ROOT / "x280_linux_target/drivers/tc1013/vendor"
    prepared = Path(__file__).with_name("sdk_upload")
    files = {name: vendor / "linux" / name for name in
             ("libTSCANApiOnLinux.so", "libTSH.so")}
    files.update({"LICENSE": vendor / "LICENSE", "SOURCE.md": vendor / "SOURCE.md",
                  "tc1013-sdk-manifest.json": prepared / "tc1013-sdk-manifest.json"})
    hashes = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    stage = DESTINATION + ".stage-" + uuid.uuid4().hex
    service._execute("python3 -c " + shlex.quote(
        "from pathlib import Path; p=Path(" + repr(stage) + "); "
        "p.parent.mkdir(parents=True, exist_ok=True); p.mkdir(mode=0o755)"))
    with service._client.open_sftp() as sftp:
        for name, path in files.items():
            sftp.put(str(path), stage + "/" + name)
            sftp.chmod(stage + "/" + name, 0o644)
    source = """
import hashlib, json, os
from pathlib import Path
stage, destination = Path(%r), Path(%r)
expected = %r
actual = {name: hashlib.sha256((stage / name).read_bytes()).hexdigest() for name in expected}
if actual != expected:
    raise RuntimeError('Uploaded SDK SHA256 mismatch')
if destination.exists():
    current = {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
               for name in expected if (destination / name).is_file()}
    if current != expected:
        raise RuntimeError('Existing driver directory differs; refusing overwrite')
    for name in expected:
        (stage / name).unlink()
    stage.rmdir()
    state = 'already_matches'
else:
    os.rename(stage, destination)
    state = 'installed'
print(json.dumps({'destination': str(destination), 'state': state, 'sha256': actual}))
""" % (stage, DESTINATION, hashes)
    return remote_python(service, source)


def probe_sdk(service: SSHDeployment) -> dict:
    source = """
import json, os, subprocess, sys
environment = os.environ.copy()
environment['LD_LIBRARY_PATH'] = %r
result = {}
for name in ('libTSH.so', 'libTSCANApiOnLinux.so'):
    process = subprocess.run(['ldd', %r + '/' + name], capture_output=True, text=True,
                             timeout=10, env=environment)
    result[name] = {'exit_code': process.returncode, 'stdout': process.stdout,
                    'stderr': process.stderr}
try:
    process = subprocess.run([sys.executable, '-c', %r], capture_output=True,
                             text=True, timeout=30, env=environment,
                             cwd=environment['LD_LIBRARY_PATH'])
    result['probe'] = {'exit_code': process.returncode, 'stdout': process.stdout,
                       'stderr': process.stderr, 'cwd': environment['LD_LIBRARY_PATH']}
    for line in process.stdout.splitlines():
        if line.startswith('X280_SDK_PROBE_JSON='):
            result['api_results'] = json.loads(line.split('=', 1)[1])
except subprocess.TimeoutExpired:
    result['probe'] = {'error': 'SDK initialization/scan exceeded 30 seconds'}
print(json.dumps(result))
""" % (DESTINATION, DESTINATION, SDK_PROBE)
    return remote_python(service, source, timeout=60)


def main() -> int:
    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "can_frames_transmitted": 0}
    service = SSHDeployment()
    try:
        host, username, password = credentials_from_environment()
        service.connect(host, username, password=password)
        result["install"] = install(service)
        result["usb_permission"] = permission_probe(service, password)
        password = None
        result["sdk_validation"] = probe_sdk(service)
        api = result["sdk_validation"].get("api_results", {})
        result["passed"] = (api.get("scan_status") == 0 and api.get("connect_status") == 0
                            and api.get("disconnect_status") == 0 and api.get("finalized") is True)
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["passed"] = False
    finally:
        service.close()
    output = Path(__file__).with_name("install_vendor.json")
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
