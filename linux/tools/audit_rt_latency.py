"""Read target scheduling, CPU topology, IRQ placement and model telemetry."""
import argparse
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import shlex
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook=sys.__excepthook__

AUDIT=r'''
import json,os,subprocess,time
from pathlib import Path
def read(path):
    try: return Path(path).read_text(errors='replace').strip()
    except OSError: return None
def command(args):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=15)
        return dict(code=p.returncode,stdout=p.stdout[-24000:],stderr=p.stderr[-2000:])
    except (OSError,subprocess.TimeoutExpired) as e: return dict(error=str(e))
cpus=[]
for p in sorted(Path('/sys/devices/system/cpu').glob('cpu[0-9]*')):
    values={n:read(p/n) for n in ('online','topology/core_id','topology/physical_package_id',
        'topology/thread_siblings_list','cpufreq/scaling_governor','cpufreq/scaling_cur_freq')}
    values['idle']=[dict(state=q.name,**{n:read(q/n) for n in ('name','latency','disable','usage','time')})
                    for q in sorted((p/'cpuidle').glob('state*'))]
    cpus.append(dict(cpu=p.name,values=values))
processes=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit(): continue
    try:
        exe=os.readlink(p/'exe')
        if not exe.endswith('.elf'): continue
        threads=[]
        for t in (p/'task').iterdir():
            tid=int(t.name)
            threads.append(dict(tid=tid,name=read(t/'comm'),policy=os.sched_getscheduler(tid),
                priority=os.sched_getparam(tid).sched_priority,affinity=sorted(os.sched_getaffinity(tid)),
                schedstat=read(t/'schedstat'),status=read(t/'status')))
        processes.append(dict(pid=int(p.name),exe=exe,arguments=read(p/'cmdline').replace('\0',' '),
            threads=threads,status=read(p/'status'),limits=read(p/'limits'),
            telemetry=read(exe+'.simrt-status.json'),marker=read(exe+'.pyxcp-host.json')))
    except (OSError,ValueError): pass
irqs=[]
for p in sorted(Path('/proc/irq').iterdir()):
    if p.name.isdigit():
        irqs.append(dict(irq=p.name,affinity=read(p/'smp_affinity_list'),
                         effective=read(p/'effective_affinity_list')))
print(json.dumps(dict(kernel=os.uname().release,boot_id=read('/proc/sys/kernel/random/boot_id'),
    uptime=read('/proc/uptime'),cpus=cpus,processes=processes,irqs=irqs,
    interrupts=read('/proc/interrupts'),softirqs=read('/proc/softirqs'),
    cmdline=read('/proc/cmdline'),isolated=read('/sys/devices/system/cpu/isolated'),
    nohz_full=read('/sys/devices/system/cpu/nohz_full'),
    clocksource=read('/sys/devices/system/clocksource/clocksource0/current_clocksource'),
    cpuidle_driver=read('/sys/devices/system/cpu/cpuidle/current_driver'),
    rt_period=read('/proc/sys/kernel/sched_rt_period_us'),rt_runtime=read('/proc/sys/kernel/sched_rt_runtime_us'),
    irqbalance=command(['systemctl','show','irqbalance','-p','ActiveState','-p','UnitFileState']),
    all_threads=command(['ps','-eLo','pid,tid,cls,rtprio,psr,pcpu,comm','--sort=-pcpu']),
    power=command(['ls','-l','/dev/cpu_dma_latency']),
    systemd_affinity=command(['systemctl','show','system.slice','user.slice','-p','AllowedCPUs','-p','EffectiveCPUs']),
    kernel_messages=command(['dmesg','--level=err,warn','--color=never']))))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='192.168.193.195')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Preserve the existing audit; use a new output path')
    password=getpass.getpass('SSH password: ')
    service=SSHDeployment()
    try:
        service.connect(args.host,'zh',password=password)
        data=json.loads(service._execute("sudo -S -p '' -- python3 -c "+shlex.quote(AUDIT),
            input_data=(password+'\n').encode(),timeout=90))
        data.update(host=args.host,collected_utc=datetime.now(timezone.utc).isoformat())
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as f: json.dump(data,f,indent=2)
        print(json.dumps(dict(report=str(args.output),cpus=data['cpus'],processes=[
            dict(pid=p['pid'],exe=p['exe'],telemetry=p['telemetry'],threads=[
                {k:t[k] for k in ('tid','name','policy','priority','affinity')} for t in p['threads']])
            for p in data['processes']]),indent=2))
    finally:
        service.close()
        password=None

if __name__=='__main__': main()
