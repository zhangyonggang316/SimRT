"""Install reversible IRQ placement and grant the model user CPU latency QoS access."""
import argparse
import getpass
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

INSTALL = r'''
import grp,json,os,pwd,subprocess,sys
from pathlib import Path
r=json.loads(sys.argv[1]); account=pwd.getpwnam(r['user']); group=grp.getgrgid(account.pw_gid).gr_name
files={
'/usr/local/lib/simrt/simrt_rt_tuning.py':r['script'],
'/etc/systemd/system/simrt-rt-tuning.service':''' + repr('''# Managed by SimRT realtime tuning
[Unit]
Description=SimRT model core IRQ placement
After=systemd-modules-load.service systemd-udev-trigger.service
Before=user@1000.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /usr/local/lib/simrt/simrt_rt_tuning.py apply
ExecStop=/usr/bin/python3 /usr/local/lib/simrt/simrt_rt_tuning.py restore

[Install]
WantedBy=multi-user.target
''') + r'''.replace('user@1000', 'user@'+str(account.pw_uid)),
'/etc/udev/rules.d/90-simrt-cpu-latency.rules':'# Managed by SimRT realtime tuning\nKERNEL=="cpu_dma_latency", GROUP="'+group+'", MODE="0660"\n'}
for name,content in files.items():
    path=Path(name)
    if path.is_symlink(): raise ValueError('Refuse symlink: '+name)
    if path.exists() and path.read_text()!=content:
        raise ValueError('Preserve existing different configuration: '+name)
for name,content in files.items():
    path=Path(name); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(content); path.chmod(0o644)
device=Path('/dev/cpu_dma_latency')
before=dict(uid=device.stat().st_uid,gid=device.stat().st_gid,mode=device.stat().st_mode & 0o777)
os.chown(device,0,account.pw_gid); device.chmod(0o660)
outputs={}
for args in (['udevadm','control','--reload-rules'],['systemctl','daemon-reload'],
             ['systemctl','enable','--now','simrt-rt-tuning.service'],
             ['systemctl','status','--no-pager','simrt-rt-tuning.service']):
    p=subprocess.run(args,capture_output=True,text=True,timeout=30)
    outputs[' '.join(args)]=dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
    if p.returncode: raise RuntimeError(p.stderr or p.stdout)
print(json.dumps(dict(files=files,device_before=before,commands=outputs,
    applied=json.loads(Path('/run/simrt-rt-tuning.json').read_text()))))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',default='192.168.193.195')
    parser.add_argument('--user',default='zh')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Preserve the existing installation receipt')
    password=getpass.getpass('SSH password: '); service=SSHDeployment()
    try:
        service.connect(args.host,args.user,password=password)
        request=dict(user=args.user,script=(ROOT/'linux/runtime/simrt_rt_tuning.py').read_text())
        result=json.loads(service._execute("sudo -S -p '' -- python3 -c "+shlex.quote(INSTALL)+' '+shlex.quote(json.dumps(request)),
            input_data=(password+'\n').encode(),timeout=120))
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print('Installed; receipt: '+str(args.output))
    finally: service.close()

if __name__=='__main__': main()
