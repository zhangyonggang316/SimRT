"""Build a local-disk initramfs, retaining the original image for recovery."""
import getpass
import json
from pathlib import Path
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

PREPARE = r'''
import datetime, hashlib, json, os, shlex, shutil, subprocess
from pathlib import Path
def run(args, timeout=30):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(' '.join(args[:4]) + ': ' + result.stderr[-5000:])
    return result.stdout
kernel = os.uname().release
assert kernel == '7.0.0-34-realtime'
assert run(['findmnt', '-n', '-o', 'SOURCE', '/']).strip() == '/dev/mapper/ubuntu--vg-ubuntu--lv'
assert run(['pvs', '--noheadings', '-o', 'pv_name']).strip() == '/dev/sda3'
if Path('/etc/crypttab').is_file():
    assert not any(shlex.split(line, comments=True) for line in Path('/etc/crypttab').read_text().splitlines())
old = Path('/boot/initrd.img-' + kernel)
candidate = Path('/boot/initrd.img-' + kernel + '.simrt-fast')
assert not candidate.is_symlink() and not old.is_symlink()
assert shutil.disk_usage('/boot').free > old.stat().st_size * 3
omit = 'dyn-netconf systemd-networkd kernel-network-modules net-lib'
if not candidate.exists():
    run(['nice', '-n', '19', 'ionice', '-c', '3', 'dracut', '--force', '--hostonly',
         '--hostonly-mode', 'sloppy', '--hostonly-cmdline', '--omit', omit, str(candidate), kernel], timeout=600)
modules = run(['lsinitrd', '-m', str(candidate)])
for required in ('lvm', 'rootfs-block', 'kernel-modules', 'systemd-initrd'):
    assert required in modules.splitlines(), required
for excluded in omit.split():
    assert excluded not in modules.splitlines(), excluded
assert 1000000 < candidate.stat().st_size < old.stat().st_size
listing = run(['lsinitrd', str(candidate)], timeout=60)
kernel_config = dict(line.split('=', 1) for line in Path('/boot/config-' + kernel).read_text().splitlines() if line.startswith('CONFIG_') and '=' in line)
drivers = {'ahci.ko': 'CONFIG_SATA_AHCI', 'dm-mod.ko': 'CONFIG_BLK_DEV_DM', 'ext4.ko': 'CONFIG_EXT4_FS'}
for filename, setting in drivers.items():
    assert kernel_config.get(setting) == 'y' or kernel_config.get(setting) == 'm' and filename in listing, setting
stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
backup = old.with_name(old.name + '.before-simrt-' + stamp)
shutil.copy2(old, backup)
old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
assert hashlib.sha256(backup.read_bytes()).hexdigest() == old_hash
candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
os.chmod(candidate, old.stat().st_mode & 0o777)
os.replace(candidate, old)
configuration = Path('/etc/dracut.conf.d/90-simrt-local-boot.conf')
assert not configuration.exists()
configuration.write_text('hostonly="yes"\nhostonly_mode="sloppy"\nhostonly_cmdline="yes"\nomit_dracutmodules+=" ' + omit + ' "\n')
run(['sync'])
print(json.dumps(dict(passed=True, image=str(old), backup=str(backup), original_bytes=backup.stat().st_size,
    new_bytes=old.stat().st_size, original_sha256=old_hash, new_sha256=candidate_hash,
    modules=modules, storage_drivers={setting: kernel_config[setting] for setting in drivers.values()},
    configuration=str(configuration), reboot_test=False)))
'''

if __name__ == '__main__':
    password = getpass.getpass('SSH/admin password: ')
    service = SSHDeployment()
    try:
        service.connect('192.168.193.195', 'zh', password=password)
        result = json.loads(service._execute('sudo -S -p ' + shlex.quote('') + ' -- python3 -c ' + shlex.quote(PREPARE),
            timeout=720, input_data=(password + '\n').encode()))
        (Path(__file__).parent / 'fast_initrd.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        service.close()
