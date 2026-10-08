"""Read-only post-boot audit, executed as zh through target_session.py."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess


def command(arguments):
    try:
        result = subprocess.run(arguments, text=True, capture_output=True, timeout=15)
        return dict(exit_code=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip())
    except (OSError, subprocess.TimeoutExpired) as error:
        return dict(exit_code=-1, stdout='', stderr=str(error))


def read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def main():
    realtime = read('/sys/kernel/realtime')
    priority = resource.getrlimit(resource.RLIMIT_RTPRIO)
    memory = resource.getrlimit(resource.RLIMIT_MEMLOCK)
    panes = command(['tmux', '-L', 'simrt-console', 'list-panes', '-t', 'simrt-console',
                     '-F', '#{pane_index} #{pane_active} #{pane_dead} #{pane_current_command}'])
    rows = [row.split() for row in panes['stdout'].splitlines()]
    getty = command(['systemctl', 'is-active', 'getty@tty1.service'])
    wait_online = command(['systemctl', 'is-enabled', 'systemd-networkd-wait-online.service'])
    linger = command(['loginctl', 'show-user', 'zh', '-p', 'Linger', '--value'])
    network = command(['ip', '-j', '-4', 'address', 'show', 'up'])
    try:
        addresses = [address['local'] for interface in json.loads(network['stdout'])
                     if interface['ifname'] != 'lo' for address in interface.get('addr_info', [])]
    except (ValueError, KeyError, TypeError):
        addresses = []
    checks = {
        'intended_machine': os.uname().nodename == 'ark2120' and os.getuid() == 1000,
        'realtime_kernel_active': realtime == '1',
        'rtprio_limit': priority[0] >= 80,
        'memlock_limit': memory[0] == resource.RLIM_INFINITY or memory[0] >= 1073741824,
        'local_getty_active': getty['stdout'] == 'active',
        'status_pane_live': any(row[:3] == ['0', '0', '0'] and row[3:] == ['python3'] for row in rows),
        'command_pane_focused': any(row[:3] == ['1', '1', '0'] for row in rows),
        'network_wait_disabled': wait_online['stdout'] == 'masked',
        'user_linger': linger['stdout'] == 'yes',
        'network_address_present': bool(addresses),
    }
    files = {}
    for name in ('simrt_console.py', 'start_console.sh'):
        path = Path('/home/zh/.local/lib/simrt-console') / name
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    report = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
                  passed=all(checks.values()), checks=checks, kernel=os.uname().release,
                  boot_id=read('/proc/sys/kernel/random/boot_id'), realtime_flag=realtime,
                  rtprio_limit=priority, memlock_limit=memory, addresses=addresses,
                  panes=panes, console_sha256=files,
                  boot_timing=command(['systemd-analyze', 'time']),
                  failed_units=command(['systemctl', '--failed', '--no-pager']),
                  uptime=read('/proc/uptime'))
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
