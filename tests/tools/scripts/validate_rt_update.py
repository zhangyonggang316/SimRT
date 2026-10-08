"""Validate a rebuilt model over XCP, then run it only when the timing checks pass."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import getpass
import json
from pathlib import Path
import shlex
import sys
import uuid

from validate_local_workflow import PayloadArchive, SSHDeployment, select_builds
from validate_model_periods import run_model
sys.excepthook = sys.__excepthook__


def jitter_checks(metrics, expected_spin_us):
    return dict(
        interval_min=metrics.get('model_step_interval_min_ns', 0) >= 950000,
        interval_max=0 < metrics.get('model_step_interval_max_ns', 0) <= 1050000,
        tolerance=metrics.get('interval_tolerance_ns') == 50000,
        no_early_intervals=metrics.get('model_step_interval_early_count') == 0,
        no_late_intervals=metrics.get('model_step_interval_late_count') == 0,
        no_deadline_misses=metrics.get('deadline_misses') == 0,
        no_skipped_releases=metrics.get('skipped_releases') == 0,
        low_latency=metrics.get('cpu_dma_latency_active') is True,
        spin_us=metrics.get('spin_us') == expected_spin_us)


def placement_checks(metrics, threads):
    background = [t for t in threads if t.get('policy') == 'SCHED_OTHER']
    realtime = [t for t in threads if t.get('policy') == 'SCHED_FIFO']
    return dict(
        isolated_model_cpu=metrics.get('cpu') == 3 and any(
            t.get('affinity') == [3] and t.get('priority') == metrics.get('priority')
            for t in realtime),
        background_separate_core=bool(background) and all(
            bool(t.get('affinity')) and set(t['affinity']).issubset({0,1}) for t in background))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--previous-model',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=300)
    parser.add_argument('--expected-spin-us',type=int,default=500)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Preserve existing validation evidence')
    password=getpass.getpass('SSH password: ')
    service=SSHDeployment(); previous=None; started=False
    report=dict(passed=False,started=datetime.now(timezone.utc).isoformat(),model={})
    def save(): args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    def reconnect(): service.connect('192.168.193.195','zh',password=password)
    with closing(PayloadArchive()) as archives:
        build=select_builds([args.receipt],archives)[0]
        try:
            reconnect()
            report['autostart_before']=service.autostart_status()
            previous=service.status(args.previous_model)
            report['previous']=previous
            if previous['running']: service.stop()
            payload=build['payload']
            remote='MATLAB_ws/realtime_50us_'+uuid.uuid4().hex[:8]
            deployment=service.deploy_payload(payload['directory'],remote)
            report['deployment']=deployment
            report['build_receipt']=str(args.receipt)
            model=dict(model=payload['model'],period_seconds=.001,
                remote_directory=deployment['remote_directory'],payload=Path(payload['directory']).name,
                host='192.168.193.195',xcp_port=5555,build_mode='local')
            save()
            print('Model deployed; starting XCP and timing validation',flush=True)
            run_model(service,Path(payload['directory']).parent,model,0,args.seconds,report['model'],ssh_reconnect=reconnect)
            metrics=report['model'].get('runtime',{})
            threads=report['model'].get('process_during_daq',{}).get('threads',[])
            report['checks']=dict(
                workflow=report['model'].get('passed',False),
                autonomous=report['model'].get('ssh_disconnected_autonomous',False),
                **jitter_checks(metrics,args.expected_spin_us),
                **placement_checks(metrics,threads))
            report['passed']=all(report['checks'].values())
            save()
            if not report['passed']: raise RuntimeError('Validation failed; see '+str(args.output))
            service.start(report['model']['remote_elf'])
            started=True
            report['running']=service.status()
            autostart=report['autostart_before']
            if autostart['enabled'] and autostart['elf_path']==args.previous_model:
                report['autostart_after']=service.set_autostart(report['model']['remote_elf'])
            print(json.dumps(dict(passed=True,runtime=metrics,running=report['running']),indent=2))
        finally:
            try:
                if not service.connected: reconnect()
                if not started and previous and previous['running']:
                    if service.status()['running']: service.stop()
                    service.start(args.previous_model)
                    report['restored_previous']=service.status()
            finally:
                save(); service.close()


if __name__=='__main__': main()
