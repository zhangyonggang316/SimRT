"""Install reversible GRUB CPU isolation; optionally reboot and restore the running model."""
import argparse
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import shlex
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

INSTALL = r'''
import json,os,shutil,subprocess,sys
from pathlib import Path
r=json.loads(sys.argv[1])
def cpus(text):
    result=set()
    for item in text.strip().split(','):
        a,_,b=item.partition('-'); result.update(range(int(a),int(b or a)+1))
    return result
online=cpus(Path('/sys/devices/system/cpu/online').read_text())
selected=max(online)
isolated=cpus(Path('/sys/devices/system/cpu/cpu%d/topology/thread_siblings_list'%selected).read_text())
housekeeping=online-isolated
if not housekeeping: raise RuntimeError('A separate physical core is required')
config=Path('/boot/config-'+os.uname().release).read_text()
for flag in ['CONFIG_NO_HZ_FULL=y','CONFIG_CPU_ISOLATION=y','CONFIG_RCU_NOCB_CPU=y','CONFIG_PREEMPT_RT=y']:
    if flag not in config.splitlines(): raise RuntimeError('Missing kernel feature: '+flag)
iso=','.join(map(str,sorted(isolated))); hk=','.join(map(str,sorted(housekeeping)))
parameters=['isolcpus=domain,managed_irq,'+iso,'nohz_full='+iso,'rcu_nocbs='+iso,'irqaffinity='+hk]
cmdline=Path('/proc/cmdline').read_text().strip()
if any(word.split('=')[0] in ('isolcpus','nohz_full','rcu_nocbs','irqaffinity') for word in cmdline.split()):
    raise RuntimeError('Existing CPU isolation parameters require review')
path=Path('/etc/default/grub.d/92-simrt-cpu-isolation.cfg')
if path.exists() or path.is_symlink(): raise RuntimeError('Preserve existing drop-in: '+str(path))
boot=Path('/boot/grub/grub.cfg')
if boot.is_symlink(): raise RuntimeError('Unexpected GRUB symlink')
backup=Path('/var/backups/simrt')/('rt-isolation-'+r['id'])
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(boot,backup/'grub.cfg')
content='# SimRT: reserve the model physical core; remove this file and run update-grub to undo.\n'
content+='GRUB_CMDLINE_LINUX_DEFAULT="${GRUB_CMDLINE_LINUX_DEFAULT} '+' '.join(parameters)+'"\n'
commands=[]
try:
    path.write_text(content); path.chmod(0o644)
    for args in [['update-grub'],['grub-script-check',str(boot)]]:
        result=subprocess.run(args,capture_output=True,text=True,timeout=120)
        commands.append(dict(command=args,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        if result.returncode: raise RuntimeError(result.stderr or result.stdout)
    entries=[line.strip() for line in boot.read_text().splitlines()
             if line.split() and line.split()[0] in ('linux','linuxefi') and os.uname().release in line]
    if not entries or not any(all(p in line.split() for p in parameters) for line in entries):
        raise RuntimeError('Current-kernel boot entry does not contain requested parameters')
except BaseException:
    path.unlink(missing_ok=True)
    shutil.copy2(backup/'grub.cfg',boot)
    raise
print(json.dumps(dict(kernel=os.uname().release,old_cmdline=cmdline,parameters=parameters,
    isolated=sorted(isolated),housekeeping=sorted(housekeeping),model_cpu=selected,
    dropin=str(path),content=content,backup=str(backup),commands=commands,entries=entries)))
'''

VERIFY = r'''
import json,os
from pathlib import Path
def read(name): return Path(name).read_text().strip()
print(json.dumps(dict(boot_id=read('/proc/sys/kernel/random/boot_id'),kernel=os.uname().release,
    cmdline=read('/proc/cmdline'),isolated=read('/sys/devices/system/cpu/isolated'),
    nohz_full=read('/sys/devices/system/cpu/nohz_full'),online=read('/sys/devices/system/cpu/online'),
    watchdog_cpus=read('/proc/sys/kernel/watchdog_cpumask'),affinity=sorted(os.sched_getaffinity(0)))))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--previous-model', required=True)
    parser.add_argument('--reboot', action='store_true')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new receipt path')
    password = getpass.getpass('SSH password: ')
    service = SSHDeployment()
    report = dict(started=datetime.now(timezone.utc).isoformat(),passed=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save(): args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    def connect(): service.connect('192.168.193.195','zh',password=password)
    def root(script, request):
        return json.loads(service._execute("sudo -S -p '' -- python3 -c "+shlex.quote(script)+' '+shlex.quote(json.dumps(request)),
            input_data=(password+'\n').encode(),timeout=180))
    try:
        connect()
        report['before'] = json.loads(service._execute('python3 -c '+shlex.quote(VERIFY)))
        report['autostart_before'] = service.autostart_status()
        report['model_before'] = service.status(args.previous_model)
        report['installation'] = root(INSTALL,dict(id=uuid.uuid4().hex[:12]))
        save()
        print('CPU isolation installed; GRUB syntax verified',flush=True)
        if args.reboot:
            if report['model_before']['running']: service.stop()
            report['reboot_requested_utc'] = datetime.now(timezone.utc).isoformat()
            save()
            try:
                service._execute("sudo -S -p '' -- systemctl reboot",input_data=(password+'\n').encode(),timeout=15)
            except (OSError,RuntimeError,EOFError):
                pass
            service.close()
            deadline = time.monotonic()+240
            while time.monotonic() < deadline:
                time.sleep(3)
                try:
                    connect()
                    after = json.loads(service._execute('python3 -c '+shlex.quote(VERIFY),timeout=20))
                    if after['boot_id'] != report['before']['boot_id']:
                        report['after'] = after
                        break
                except Exception:
                    pass
                service.close()
            if 'after' not in report: raise RuntimeError('Target did not return with a new boot ID')
            if not all(p in report['after']['cmdline'].split() for p in report['installation']['parameters']):
                raise RuntimeError('Boot did not activate the requested isolation')
            if report['model_before']['running']:
                service.start(args.previous_model)
                report['model_restored'] = service.status()
            report['autostart_after'] = service.autostart_status()
            if report['autostart_after'] != report['autostart_before']:
                raise RuntimeError('Autostart selection changed unexpectedly')
        report['passed'] = True
        print(json.dumps(report,indent=2),flush=True)
    except BaseException as error:
        report['error'] = dict(type=type(error).__name__,message=str(error))
        raise
    finally:
        save()
        service.close()


if __name__ == '__main__':
    main()
