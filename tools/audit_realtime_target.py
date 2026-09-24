"""Read-only SSH audit for PREEMPT_RT deployment prerequisites."""

import argparse
import getpass
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qt_xcp_host"))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__


AUDIT = r'''
import json, os, platform, resource, shutil, subprocess
from pathlib import Path

def command(argv):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=20)
        return {'exit_code': result.returncode, 'output': result.stdout[-16000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error': str(exc)}

kernel = platform.release()
config = Path('/boot/config-' + kernel)
lines = config.read_text().splitlines() if config.exists() else []
result = {
    'kernel': kernel, 'architecture': platform.machine(),
    'os_release': Path('/etc/os-release').read_text(),
    'cmdline': Path('/proc/cmdline').read_text(),
    'realtime_flag': Path('/sys/kernel/realtime').read_text().strip() if Path('/sys/kernel/realtime').exists() else None,
    'kernel_config': [line for line in lines if any(key in line for key in ('CONFIG_PREEMPT', 'CONFIG_HZ=', 'CONFIG_HIGH_RES_TIMERS'))],
    'cpu_count': os.cpu_count(), 'cpu_allowed': sorted(os.sched_getaffinity(0)),
    'rlimit_rtprio': resource.getrlimit(resource.RLIMIT_RTPRIO),
    'rlimit_memlock': resource.getrlimit(resource.RLIMIT_MEMLOCK),
    'disk': {p: shutil.disk_usage(p)._asdict() for p in ('/', '/boot', str(Path.home()))},
    'memory': Path('/proc/meminfo').read_text(),
    'secure_boot': command(['mokutil', '--sb-state']),
    'rt_packages': command(['apt-cache', 'policy', 'ubuntu-realtime', 'linux-image-realtime', 'linux-realtime', 'rt-tests']),
    'installed_kernels': command(['dpkg-query', '-W', '-f=${Package} ${Version} ${Status}\n', 'linux-image-*']),
    'rt_kernel_files': command(['dpkg-query', '-L', 'linux-image-intel-rt']),
    'boot_files': command(['ls', '-l', '/boot']),
    'grub_entries': command(['sudo', '-n', 'grep', '-E', '^[[:space:]]*(menuentry|submenu)', '/boot/grub/grub.cfg']),
    'grub_defaults': command(['cat', '/etc/default/grub']),
    'existing_rt_config': command(['sh', '-c', 'grep -H -E "CONFIG_PREEMPT_RT=|CONFIG_HZ=|CONFIG_HIGH_RES_TIMERS=" /boot/config-*rt*']),
    'pro_status': command(['pro', 'status', '--format', 'json']),
    'linger': command(['loginctl', 'show-user', str(os.getuid()), '-p', 'Linger']),
    'user_manager': command(['systemctl', '--user', 'is-system-running']),
    'rt_bandwidth_us': Path('/proc/sys/kernel/sched_rt_runtime_us').read_text().strip(),
    'sudo_noninteractive': command(['sudo', '-n', 'true']),
}
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='192.168.219.86')
    parser.add_argument('--user', default='zh')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    service = SSHDeployment()
    password = getpass.getpass('SSH password: ')
    try:
        service.connect(args.host, args.user, password=password)
        password = None
        result = json.loads(service._execute('python3 -c ' + shlex.quote(AUDIT), timeout=90))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        for key in ('kernel', 'os_release', 'realtime_flag', 'kernel_config', 'rlimit_rtprio',
                    'rlimit_memlock', 'secure_boot', 'rt_packages', 'linger', 'sudo_noninteractive'):
            print(key + ': ' + json.dumps(result[key]))
        print('Audit saved to ' + str(args.output))
    finally:
        service.close()


if __name__ == '__main__':
    main()
