"""Read-only ARK board, serial and digital-I/O inventory over SSH."""

import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment

sys.excepthook = sys.__excepthook__

AUDIT = r'''
import gzip, json, os, platform, re, shutil, stat, subprocess, time
from pathlib import Path

def command(argv, timeout=10, stdout_limit=48000):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=timeout)
        return dict(code=result.returncode, stdout=result.stdout[-stdout_limit:], stderr=result.stderr[-2000:])
    except (OSError, subprocess.TimeoutExpired) as error:
        return dict(error=str(error))

def read(path, limit=64000):
    try:
        with Path(path).open('r', errors='replace') as stream:
            return stream.read(limit).strip()
    except OSError:
        return None

def metadata(path):
    path = Path(path)
    result = dict(path=str(path), resolved=str(path.resolve()))
    try:
        info = path.stat()
        result.update(mode=stat.filemode(info.st_mode), uid=info.st_uid, gid=info.st_gid)
        if stat.S_ISCHR(info.st_mode):
            result.update(major=os.major(info.st_rdev), minor=os.minor(info.st_rdev))
    except OSError as error:
        result['error'] = str(error)
    return result

def device_record(path, attributes):
    result = metadata(path)
    result['attributes'] = {name: read(Path(path) / name) for name in attributes}
    for name in ('device', 'device/driver', 'device/driver/module', 'driver', 'driver/module'):
        candidate = Path(path) / name
        if candidate.exists():
            result[name] = str(candidate.resolve())
    return result

def library_paths():
    found, checked, truncated = [], 0, False
    deadline = time.monotonic() + 12
    roots = ['/opt', '/usr/local', '/usr/lib', '/usr/include', '/home/zh',
             '/lib/modules/' + platform.release()]
    for root in roots:
        for base, directories, files in os.walk(root, followlinks=False):
            directories[:] = [name for name in directories if name not in
                ('.git', '.cache', 'node_modules', '.npm', '.venv', '__pycache__')]
            checked += len(directories) + len(files)
            for name in directories + files:
                if any(token in name.lower() for token in ('susi', 'imanager', 'advantech', 'eapi')):
                    found.append(str(Path(base) / name))
            if checked >= 100000 or time.monotonic() > deadline:
                truncated = True
                break
        if truncated:
            break
    return dict(paths=sorted(set(found)), examined_entries=checked, truncated=truncated)

def kernel_config():
    path = Path('/proc/config.gz')
    try:
        if path.is_file():
            with gzip.open(str(path), 'rt') as stream:
                content = stream.read(1024 * 1024)
        else:
            path = Path('/boot/config-' + platform.release())
            content = read(path, 1024 * 1024) or ''
        selected = [line for line in content.splitlines() if re.search(
            r'CONFIG_(GPIO|PINCTRL|MFD|I2C|SERIAL_8250|LPC_ICH|HW_RANDOM|HWMON|SENSORS_IT87|WATCHDOG|PREEMPT)', line)]
        return dict(path=str(path), entries=selected)
    except OSError as error:
        return dict(path=str(path), error=str(error))

gpio = []
for base in ('/sys/class/gpio', '/sys/bus/gpio/devices'):
    for path in sorted(Path(base).glob('gpiochip*')):
        gpio.append(device_record(path, ('label', 'base', 'ngpio', 'dev', 'uevent')))
serial = []
for path in sorted(Path('/sys/class/tty').glob('tty*')):
    if re.fullmatch(r'tty(S|USB|ACM)\d+', path.name):
        record = device_record(path, ('dev', 'device/uevent', 'device/modalias', 'device/id'))
        record['node'] = metadata('/dev/' + path.name)
        serial.append(record)
platform_devices = []
for path in sorted(Path('/sys/bus/platform/devices').iterdir()):
    if any(word in path.name.lower() for word in ('gpio', 'imanager', 'adv', 'serial', 'lpc', 'i801', 'sch')):
        platform_devices.append(device_record(path, ('modalias', 'uevent', 'name')))
kernel = command(['dmesg', '--color=never'], stdout_limit=512000)
if kernel.get('stdout'):
    kernel['stdout'] = '\n'.join(line for line in kernel['stdout'].splitlines()
        if 'Modules linked in:' not in line and
        re.search(r'gpio|imanager|advantech|ttyS|serial|i2c|smbus|super.?io|lpc|DMI:', line, re.I))
libraries = command(['ldconfig', '-p'])
if libraries.get('stdout'):
    libraries['stdout'] = '\n'.join(line for line in libraries['stdout'].splitlines()
        if re.search(r'susi|imanager|advantech|gpiod|eapi', line, re.I))
result = dict(
    collection_scope='read-only metadata; no GPIO direction/value requests, raw I/O, driver loading or configuration changes',
    hostname=platform.node(), kernel=platform.release(), architecture=platform.machine(),
    os_release=read('/etc/os-release'), effective_uid=os.geteuid(),
    dmi={name: read('/sys/class/dmi/id/' + name) for name in (
        'sys_vendor', 'product_name', 'product_version', 'board_vendor', 'board_name',
        'board_version', 'bios_vendor', 'bios_version', 'bios_date')},
    cpu=command(['lscpu']), pci=command(['lspci', '-nnk']),
    serial_driver=read('/proc/tty/driver/serial'), serial_devices=serial,
    serial_by_id=[metadata(path) for path in sorted(Path('/dev/serial/by-id').glob('*'))],
    serial_by_path=[metadata(path) for path in sorted(Path('/dev/serial/by-path').glob('*'))],
    gpio_devices=gpio, gpio_nodes=[metadata(path) for path in sorted(Path('/dev').glob('gpiochip*'))],
    gpio_detect=command(['gpiodetect']), gpio_info=command(['gpioinfo']),
    platform_devices=platform_devices,
    loaded_modules=command(['lsmod']), kernel_config=kernel_config(),
    module_metadata={name: command(['modinfo', name]) for name in (
        'imanager', 'gpio_imanager', 'gpio-imanager', 'gpio_ich', 'gpio_sch', 'gpio_it87', 'gpio_f7188x')},
    library_cache=libraries, vendor_paths=library_paths(), hardware_messages=kernel,
    kernel_command_line=read('/proc/cmdline'),
    ioport_claims=read('/proc/ioports'),
)
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--user', default='zh')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--sudo', action='store_true', help='Read protected hardware metadata through sudo')
    parser.add_argument('--password-stdin', action='store_true')
    args = parser.parse_args()
    password = (sys.stdin.readline().rstrip('\r\n') if args.password_stdin else
                os.environ.get('SIMRT_SSH_PASSWORD') or getpass.getpass('SSH password: '))
    if not password or any(character in password for character in '\r\n\x00'):
        raise ValueError('A valid SSH password is required')
    service = SSHDeployment()
    try:
        service.connect(args.host, args.user, password=password)
        command = 'python3 -c ' + shlex.quote(AUDIT)
        if args.sudo:
            command = 'sudo -S -p ' + shlex.quote('') + ' -- ' + command
        result = json.loads(service._execute(command, timeout=120,
            input_data=(password + '\n').encode('utf-8') if args.sudo else None))
        result.update(target_address=args.host, username=args.user,
                      collected_utc=datetime.now(timezone.utc).isoformat())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=True)
        print(json.dumps(dict(report=str(args.output.resolve()), dmi=result['dmi'], kernel=result['kernel'],
            gpio_nodes=result['gpio_nodes'], serial_driver=result['serial_driver'],
            vendor_paths=result['vendor_paths'], library_cache=result['library_cache']), indent=2))
    except Exception as error:
        message = str(error).replace(password, '[redacted]')
        raise RuntimeError(message) from None
    finally:
        service.close()
        password = None


if __name__ == '__main__':
    main()
