"""Read additional isolation and tracing prerequisites without changing the target."""
import getpass
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

SCRIPT = r'''
import json,os,subprocess
from pathlib import Path
def read(name):
    try: return Path(name).read_text().strip()
    except OSError as error: return str(error)
def command(args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=30)
    return dict(code=p.returncode,stdout=p.stdout,stderr=p.stderr)
config=read('/boot/config-'+os.uname().release)
keys=('CONFIG_NO_HZ','CONFIG_RCU_NOCB','CONFIG_PREEMPT','CONFIG_HZ','CONFIG_CPU_ISOLATION','CONFIG_OSNOISE','CONFIG_TIMERLAT','CONFIG_HWLAT','CONFIG_CGROUP','CONFIG_CPUSETS')
paths=['/sys/fs/cgroup/cgroup.controllers','/sys/fs/cgroup/cgroup.subtree_control','/sys/fs/cgroup/cpuset.cpus.effective','/sys/fs/cgroup/cpuset.cpus.isolated',
       '/sys/kernel/tracing/available_tracers','/sys/kernel/tracing/current_tracer','/proc/sys/kernel/nmi_watchdog','/proc/sys/kernel/watchdog_cpumask',
       '/proc/sys/kernel/timer_migration','/sys/devices/system/cpu/smt/control','/run/simrt-rt-tuning.json']
msrs={}
for cpu in range(4):
    try:
        with open('/dev/cpu/%d/msr'%cpu,'rb',buffering=0) as f:
            f.seek(0x34); msrs[str(cpu)]=int.from_bytes(f.read(8),'little')
    except OSError as error: msrs[str(cpu)]=str(error)
print(json.dumps(dict(config=[line for line in config.splitlines() if line.startswith(keys)],
    files={p:read(p) for p in paths},smi_count=msrs,
    available_tools=command(['sh','-c','command -v rtla; command -v cyclictest; command -v perf']),
    services=command(['systemctl','list-timers','--all','--no-pager']),
    systemd=command(['systemctl','--version']))))
'''

service = SSHDeployment()
password = getpass.getpass('SSH password: ')
try:
    service.connect('192.168.193.195', 'zh', password=password)
    result = json.loads(service._execute("sudo -S -p '' -- python3 -c " + shlex.quote(SCRIPT),
        input_data=(password+'\n').encode(), timeout=90))
    with Path(__file__).with_name('prerequisites.json').open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))
finally:
    service.close()
