"""Measure actual 1 ms model-entry jitter with explicit wake-ahead settings."""
import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

RUN = r'''
import json,os,subprocess,sys,time
from pathlib import Path
r=json.loads(sys.argv[1])
def cpu_list(text):
    result=set()
    for part in text.strip().split(','):
        a,_,b=part.partition('-'); result.update(range(int(a),int(b or a)+1))
    return result
online=cpu_list(Path('/sys/devices/system/cpu/online').read_text())
cpu=max(online)
siblings=cpu_list(Path('/sys/devices/system/cpu/cpu%d/topology/thread_siblings_list'%cpu).read_text())
housekeeping=online-siblings
if not housekeeping: raise RuntimeError('Separate physical core required')
os.sched_setaffinity(0,housekeeping)
env=dict(os.environ,SIMRT_RT_CPU=str(cpu),SIMRT_RT_SPIN_US=str(r['spin']),SIMRT_RT_LOW_LATENCY='1')
workers=[]
try:
    if r['stress']:
        for worker_cpu in sorted(housekeeping):
            workers.append(subprocess.Popen(['python3','-c','import os; os.sched_setaffinity(0,{%d}); exec("while True: pass")'%worker_cpu]))
    start=time.monotonic()
    p=subprocess.run([r['binary']]+r.get('arguments',['--normal-load','--cycles',str(r['seconds']*1000)]),env=env,
        capture_output=True,text=True,timeout=r['seconds']+30,preexec_fn=lambda:os.sched_setaffinity(0,online))
    print(json.dumps(dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr,
        elapsed=time.monotonic()-start,cpu=cpu,housekeeping=sorted(housekeeping),
        stress=r['stress'],temperatures={str(p):p.read_text().strip() for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')})))
finally:
    for p in workers:
        p.terminate()
    for p in workers:
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired: p.kill(); p.wait()
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--diagnostics', type=Path)
    parser.add_argument('--affinity-tests', type=Path)
    parser.add_argument('--previous-model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--spins', type=int, nargs='+', default=[50, 100, 250, 500])
    parser.add_argument('--stress', action='store_true')
    args = parser.parse_args()
    if args.output.exists() or args.seconds < 1 or any(spin < 0 or spin > 500 for spin in args.spins):
        parser.error('Use a new output path and valid duration/spin settings')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    service = SSHDeployment()
    password = getpass.getpass('SSH password: ')
    report = dict(started=datetime.now(timezone.utc).isoformat(),tolerance_us=50,cases=[])
    previous = None
    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        service.connect('192.168.193.195', 'zh', password=password)
        report['autostart'] = service.autostart_status()
        previous = service.status(args.previous_model)
        report['previous'] = previous
        remote = '/home/zh/MATLAB_ws/jitter_50us_' + uuid.uuid4().hex[:8] + '.elf'
        with service._client.open_sftp() as sftp:
            sftp.put(str(args.binary), remote)
            sftp.chmod(remote, 0o755)
            with sftp.open(remote, 'rb') as stream:
                report['binary_sha256'] = hashlib.sha256(stream.read()).hexdigest()
        if report['binary_sha256'] != hashlib.sha256(args.binary.read_bytes()).hexdigest():
            raise RuntimeError('Upload hash mismatch')
        if args.diagnostics:
            with service._client.open_sftp() as sftp:
                sftp.put(str(args.diagnostics), remote + '.diagnostics')
                sftp.chmod(remote + '.diagnostics', 0o755)
                with sftp.open(remote + '.diagnostics', 'rb') as stream:
                    actual = hashlib.sha256(stream.read()).hexdigest()
            if actual != hashlib.sha256(args.diagnostics.read_bytes()).hexdigest():
                raise RuntimeError('Diagnostics upload hash mismatch')
            report['diagnostics_sha256'] = actual
        if args.affinity_tests:
            with service._client.open_sftp() as sftp:
                sftp.put(str(args.affinity_tests), remote + '.affinity')
                sftp.chmod(remote + '.affinity', 0o755)
                with sftp.open(remote + '.affinity', 'rb') as stream:
                    actual = hashlib.sha256(stream.read()).hexdigest()
            if actual != hashlib.sha256(args.affinity_tests.read_bytes()).hexdigest():
                raise RuntimeError('Affinity test upload hash mismatch')
            report['affinity_tests_sha256'] = actual
        if previous['running']:
            service.stop()
        save()
        report['regression'] = []
        checks = [('math', remote, ['--math'], 0), ('overload', remote, ['--cycles','200'], 0),
                  ('invalid_period',remote,['--bad-period'],1), ('invalid_subrates',remote,['--bad-subrates'],1),
                  ('period_10ms',remote,['--normal-load','--period-ms','10','--cycles','20'],0),
                  ('period_100ms',remote,['--normal-load','--period-ms','100','--cycles','20'],0)]
        if args.diagnostics:
            checks.insert(0, ('deterministic', remote + '.diagnostics', [], 0))
        if args.affinity_tests:
            checks.insert(0, ('affinity', remote + '.affinity', [], 0))
        for name, binary, arguments, code in checks:
            request = dict(binary=binary, arguments=arguments, spin=50, seconds=10, stress=False)
            result = json.loads(service._execute("sudo -S -p '' -- python3 -c " + shlex.quote(RUN) + ' ' + shlex.quote(json.dumps(request)),
                input_data=(password+'\n').encode(), timeout=70))
            report['regression'].append(dict(name=name, expected_code=code, result=result))
            save()
            if result['returncode'] != code:
                raise RuntimeError('Runtime regression failed: ' + name)
        for spin in args.spins:
            request = dict(binary=remote,spin=spin,seconds=args.seconds,stress=args.stress)
            response = json.loads(service._execute("sudo -S -p '' -- python3 -c " + shlex.quote(RUN) + ' ' + shlex.quote(json.dumps(request)),
                input_data=(password+'\n').encode(), timeout=args.seconds+60))
            record = dict(request=request,result=response)
            for line in response['stdout'].splitlines():
                if line.startswith('{'):
                    record['metrics'] = json.loads(line)
            metrics = record.get('metrics', {})
            record['passed'] = (response['returncode'] == 0 and metrics.get('spin_us') == spin
                and metrics.get('model_step_interval_min_ns', 0) >= 950000
                and 0 < metrics.get('model_step_interval_max_ns', 0) <= 1050000
                and metrics.get('deadline_misses') == 0 and metrics.get('skipped_releases') == 0
                and metrics.get('model_step_interval_early_count') == 0
                and metrics.get('model_step_interval_late_count') == 0)
            report['cases'].append(record)
            save()
            print(json.dumps(record), flush=True)
    finally:
        try:
            if previous and previous['running']:
                service.start(args.previous_model)
                report['restored'] = service.status()
        finally:
            save()
            service.close()


if __name__ == '__main__':
    main()
