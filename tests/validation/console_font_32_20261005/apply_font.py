"""Enlarge the existing Linux tty1 display and retain the boot configuration."""
import getpass
import json
from pathlib import Path
import shlex
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment


UPDATE = r'''
import datetime, json, os, shlex, shutil, subprocess, tempfile
from pathlib import Path

def run(args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30, check=True)
    return result.stdout.strip()

def atomic_write(path, data, mode):
    fd, temporary = tempfile.mkstemp(prefix='.simrt-font-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

config = Path('/etc/default/console-setup')
cache = Path('/etc/console-setup/cached_setup_font.sh')
font = Path('/usr/share/consolefonts/Uni2-Terminus32x16.psf.gz')
assert font.is_file()
assert run(['systemctl', 'is-enabled', 'console-setup.service']) == 'enabled'
before_size = run(['stty', '-F', '/dev/tty1', 'size'])
resolution = Path('/sys/class/graphics/fb0/virtual_size').read_text().strip()
assert resolution == '1920,1080', 'Reassess the font size for this screen'
original = config.read_bytes()
previous_cache = cache.read_bytes()
settings = {'FONTFACE': 'Terminus', 'FONTSIZE': '16x32'}
lines, found = [], set()
for line in original.decode().splitlines(keepends=True):
    tokens = shlex.split(line, comments=True)
    key = tokens[0].partition('=')[0] if len(tokens) == 1 else ''
    if key in settings:
        assert key not in found, 'Duplicate console font setting'
        found.add(key)
        line = key + '="' + settings[key] + '"\n'
    lines.append(line)
assert found == set(settings)
backup = Path('/var/backups') / ('simrt-console-font-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
shutil.copy2(config, backup / 'console-setup')
shutil.copy2(cache, backup / 'cached_setup_font.sh')
run(['setfont', '-C', '/dev/tty1', '-O', str(backup / 'previous.psf')])
assert (backup / 'previous.psf').stat().st_size > 0
try:
    atomic_write(config, ''.join(lines).encode(), config.stat().st_mode & 0o777)
    run(['setupcon', '--font-only', '--save-only'])
    cached = cache.read_text()
    assert 'Terminus32x16.psf' in cached, 'Boot font cache was not updated'
    run(['setfont', '-C', '/dev/tty1', str(font)])
    after_size = run(['stty', '-F', '/dev/tty1', 'size'])
    assert after_size == '33 120', after_size
except BaseException:
    atomic_write(config, original, (backup / 'console-setup').stat().st_mode & 0o777)
    atomic_write(cache, previous_cache, (backup / 'cached_setup_font.sh').stat().st_mode & 0o777)
    run(['setfont', '-C', '/dev/tty1', str(backup / 'previous.psf')])
    raise
print(json.dumps(dict(passed=True, before_size=before_size, after_size=after_size,
    font=str(font), font_pixels=[16, 32], framebuffer=resolution, backup=str(backup),
    config=config.read_text(), boot_font_cache=cached, reboot_performed=False)))
'''


if __name__ == '__main__':
    service = SSHDeployment()
    password = getpass.getpass('SSH/admin password: ')
    output = Path(__file__).resolve().parent
    try:
        service.connect('192.168.193.195', 'zh', password=password)
        pane_command = "tmux -L simrt-console list-panes -a -F '#{pane_pid}|#{pane_width}|#{pane_height}|#{pane_dead}'"
        before = service._execute(pane_command).strip()
        result = json.loads(service._execute('sudo -S -p ' + shlex.quote('') + ' -- python3 -c ' +
            shlex.quote(UPDATE), timeout=60, input_data=(password + '\n').encode()))
        time.sleep(2)
        after = service._execute(pane_command).strip()
        first = service._execute('tmux -L simrt-console capture-pane -p -t simrt-console:0.0')
        time.sleep(2)
        second = service._execute('tmux -L simrt-console capture-pane -p -t simrt-console:0.0')
        result.update(pane_before=before, pane_after=after, dashboard_process_unchanged=before.split('|')[0] == after.split('|')[0],
                      dashboard_refreshing=first != second,
                      sections_present=all(label in second for label in ('SimRT:', 'Network:', 'State:', '-- LOG')))
        result['passed'] = bool(result['passed'] and result['dashboard_process_unchanged'] and
                                result['dashboard_refreshing'] and result['sections_present'] and
                                after.split('|')[1:] == ['120', '33', '0'])
        (output / 'font_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        (output / 'console_after.txt').write_text(second, encoding='utf-8')
        print(json.dumps(result, indent=2))
        if not result['passed']:
            raise RuntimeError('Console validation failed; inspect the report')
    finally:
        service.close()
