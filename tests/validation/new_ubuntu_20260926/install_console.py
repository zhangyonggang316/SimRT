"""Install the local tty1 profile hook and the user-approved automatic login."""

import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import subprocess

if os.geteuid() != 0 or platform.node() != 'ark2120':
    raise RuntimeError('Expected root on ark2120')
user = pwd.getpwnam('zh')
home = Path(user.pw_dir)
console = home / '.local/lib/simrt-console'
for name in ('start_console.sh', 'simrt_console.py'):
    if not (console / name).is_file() or (console / name).is_symlink():
        raise RuntimeError('Missing uploaded console file: ' + name)
subprocess.run(['sh', '-n', str(console / 'start_console.sh')], check=True)
subprocess.run(['python3', '-m', 'py_compile', str(console / 'simrt_console.py')], check=True)
backup = Path('/var/lib/simrt/console-before-20260926')
backup.mkdir(parents=True, exist_ok=True)
profile = home / '.profile'
if profile.is_symlink():
    raise RuntimeError('Refusing symlink profile')
text = profile.read_text()
marker = '# BEGIN SIMRT LOCAL CONSOLE'
hook = '''
# BEGIN SIMRT LOCAL CONSOLE
if [ -z "${SSH_CONNECTION:-}${SSH_TTY:-}${TMUX:-}" ] && [ "$(tty 2>/dev/null)" = /dev/tty1 ]; then
    "$HOME/.local/lib/simrt-console/start_console.sh"
fi
# END SIMRT LOCAL CONSOLE
'''
if marker not in text:
    if not (backup / 'profile').exists():
        (backup / 'profile').write_text(text)
    profile.write_text(text.rstrip() + '\n' + hook)
    os.chown(profile, user.pw_uid, user.pw_gid)
elif hook.strip() not in text:
    raise RuntimeError('Existing SimRT hook differs')
dropin = Path('/etc/systemd/system/getty@tty1.service.d/90-simrt-console.conf')
content = '''# Managed by SimRT local console deployment
[Service]
ExecStartPre=-/usr/bin/setfont -C /dev/tty1 /usr/share/consolefonts/Uni2-Terminus32x16.psf.gz
ExecStart=
ExecStart=-/sbin/agetty --autologin zh --noclear %I $TERM
'''
if dropin.is_symlink() or (dropin.exists() and dropin.read_text() != content):
    raise RuntimeError('Refusing to replace unrelated getty configuration')
dropin.parent.mkdir(parents=True, exist_ok=True)
dropin.write_text(content)
dropin.chmod(0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
print(json.dumps({'profile': str(profile), 'backup': str(backup), 'getty_dropin': str(dropin),
                  'console_sha256': {name: hashlib.sha256((console / name).read_bytes()).hexdigest()
                                     for name in ('start_console.sh', 'simrt_console.py')},
                  'login_user': 'zh', 'rebooted': False, 'getty_restarted': False}, indent=2))
