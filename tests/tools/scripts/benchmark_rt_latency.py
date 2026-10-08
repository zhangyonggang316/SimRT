"""Compare local cross-compiled runtimes; restore the selected model and IRQ masks."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

RUN = r'''
import json,os,subprocess,sys,time
from pathlib import Path
request=json.loads(sys.argv[1])
env=dict(os.environ,**request['environment'])
result=subprocess.run(request['arguments'],env=env,capture_output=True,text=True,timeout=request['timeout'])
print(json.dumps(dict(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr)))
'''

IRQ = r'''
import json,sys
from pathlib import Path
request=json.loads(sys.argv[1]); results=[]
for name,value in request.items():
    path=Path(name)
    if not (str(path).startswith('/proc/irq/') or str(path).startswith('/sys/devices/virtual/workqueue/')):
        raise ValueError('Unexpected tuning path')
    try:
        before=path.read_text().strip(); path.write_text(value)
        results.append(dict(path=name,before=before,after=path.read_text().strip()))
    except OSError as e: results.append(dict(path=name,error=str(e)))
print(json.dumps(results))
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--model',help='Owned running model to pause; boot selection is unchanged')
    args=parser.parse_args()
    if args.output.exists(): parser.error('Preserve existing results')
    service=SSHDeployment(); password=getpass.getpass('SSH password: ')
    report=dict(started=datetime.now(timezone.utc).isoformat(),cases=[],restored=False)
    original=None; was_running=False; irq_restore={}
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    def root(script,request,timeout=60):
        return json.loads(service._execute("sudo -S -p '' -- python3 -c "+shlex.quote(script)+' '+shlex.quote(json.dumps(request)),
            input_data=(password+'\n').encode(),timeout=timeout))
    try:
        service.connect('192.168.193.195','zh',password=password)
        original=service.autostart_status()
        report['autostart']=original.copy()
        if args.model:
            original=dict(elf_path=args.model,arguments=[])
        report['original']=original
        if not original['elf_path']: raise RuntimeError('No selected model to restore')
        state=service.status(original['elf_path']); was_running=state['running']
        report['before']=state
        remote='/home/zh/MATLAB_ws/latency_benchmark_20261006'
        service._execute('mkdir -p '+shlex.quote(remote))
        with service._client.open_sftp() as sftp:
            for name,path in [('baseline',args.baseline),('candidate',args.candidate)]:
                target=remote+'/'+name+'.elf'
                sftp.put(str(path),target); sftp.chmod(target,0o755)
                with sftp.open(target,'rb') as f: actual=hashlib.sha256(f.read()).hexdigest()
                if actual != hashlib.sha256(path.read_bytes()).hexdigest(): raise RuntimeError('Upload hash mismatch')
                report[name+'_sha256']=actual
        if was_running: service.stop()
        save()
        cases=[('baseline',{},['--normal-load','--cycles',str(args.seconds*1000)]),
               ('affinity',{'SIMRT_RT_LOW_LATENCY':'0'},['--normal-load','--cycles',str(args.seconds*1000)]),
               ('qos',{},['--normal-load','--cycles',str(args.seconds*1000)]),
               ('qos_spin',{'SIMRT_RT_SPIN_US':'50'},['--normal-load','--cycles',str(args.seconds*1000)]),
               ('irq_qos_spin',{'SIMRT_RT_SPIN_US':'50'},['--normal-load','--cycles',str(args.seconds*1000)]),
               ('math',{},['--math']),('overrun',{},['--cycles','200']),
               ('bad_period',{},['--bad-period']),('bad_subrates',{},['--bad-subrates'])]
        for name,env,arguments in cases:
            if name=='irq_qos_spin':
                audit=json.loads((args.output.parent/'before.json').read_text())
                tuning={'/proc/irq/'+q['irq']+'/smp_affinity_list':'0-1' for q in audit['irqs']}
                tuning['/proc/irq/default_smp_affinity']='3'
                tuning['/sys/devices/virtual/workqueue/cpumask']='3'
                changes=root(IRQ,tuning)
                report['irq_changes']=changes
                irq_restore={v['path']:v['before'] for v in changes if 'before' in v}
                save()
            binary=remote+('/baseline.elf' if name=='baseline' else '/candidate.elf')
            result=root(RUN,dict(arguments=[binary]+arguments,environment=env,timeout=args.seconds+30),args.seconds+45)
            record=dict(name=name,environment=env,result=result)
            for line in result['stdout'].splitlines():
                if line.startswith('{'): record['metrics']=json.loads(line)
            report['cases'].append(record); save()
            print(json.dumps(record),flush=True)
    finally:
        try:
            if irq_restore: report['irq_restored']=root(IRQ,irq_restore)
            if was_running and original:
                service.start(original['elf_path'],shlex.join(original['arguments']))
                report['after']=service.status()
            report['restored']=True
        finally:
            save(); service.close()

if __name__=='__main__': main()
