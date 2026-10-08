"""Read-only target-side timing qualification; never changes or restarts the model."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time


def check_sample(status, pid, now_ns):
    age = now_ns - status.get('sample_monotonic_ns', 0)
    return dict(
        same_pid=status.get('pid') == pid,
        running=status.get('state') == 'RUNNING',
        fresh=0 <= age <= 10_000_000_000,
        period=status.get('period_ns') == 1_000_000,
        minimum=status.get('model_step_interval_min_ns', 0) >= 950_000,
        maximum=0 < status.get('model_step_interval_max_ns', 0) <= 1_050_000,
        tolerance=status.get('interval_tolerance_ns') == 50_000,
        early=status.get('model_step_interval_early_count') == 0,
        late=status.get('model_step_interval_late_count') == 0,
        misses=status.get('deadline_misses') == 0,
        skips=status.get('skipped_releases') == 0,
        low_latency=status.get('cpu_dma_latency_active') is True,
        spin=status.get('spin_us') == 500,
        realtime=status.get('realtime_kernel') is True,
        locked=status.get('memory_locked') is True,
        cpu=status.get('cpu') == 3)


def process_identity(pid):
    stat = Path('/proc', str(pid), 'stat').read_text()
    return dict(elf=os.readlink('/proc/%d/exe' % pid), start_ticks=stat[stat.rfind(')') + 2:].split()[19])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=54000)
    args = parser.parse_args()
    if args.seconds < 60:
        parser.error('Qualification duration must be at least 60 seconds')
    args.output.mkdir(parents=True, exist_ok=False)
    os.sched_setaffinity(0, {0, 1})
    os.nice(10)
    identity = process_identity(args.pid)
    if identity['elf'] != str(args.elf.resolve()):
        raise RuntimeError('The selected PID does not run the expected model')
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    start = time.monotonic()
    report = dict(state='running', passed=False, started_utc=datetime.now(timezone.utc).isoformat(),
        duration_seconds=args.seconds, boot_id=boot_id, pid=args.pid, identity=identity,
        elf_sha256=hashlib.sha256(args.elf.read_bytes()).hexdigest(),
        monitor_affinity=sorted(os.sched_getaffinity(0)), sample_count=0, first_failure=None,
        scope='Cumulative model-entry intervals; independent of XCP delivery')
    with (args.output / 'samples.jsonl').open('x', encoding='utf-8') as stream:
        while True:
            sample = dict(observed_utc=datetime.now(timezone.utc).isoformat())
            try:
                sample['metrics'] = json.loads(Path(str(args.elf) + '.simrt-status.json').read_text())
                sample['checks'] = check_sample(sample['metrics'], args.pid, time.monotonic_ns())
                sample['checks']['same_process'] = process_identity(args.pid) == identity
                sample['checks']['same_boot'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot_id
                sample['threads'] = [dict(tid=int(path.name), policy=os.sched_getscheduler(int(path.name)),
                    affinity=sorted(os.sched_getaffinity(int(path.name))))
                    for path in Path('/proc', str(args.pid), 'task').iterdir()]
                sample['checks']['thread_placement'] = any(t['policy'] == os.SCHED_FIFO and t['affinity'] == [3]
                    for t in sample['threads']) and all(set(t['affinity']).issubset({0,1})
                    for t in sample['threads'] if t['policy'] == os.SCHED_OTHER)
            except (OSError, ValueError) as error:
                sample['error'] = str(error)
                sample['checks'] = dict(telemetry_available=False)
            sample['passed'] = all(sample['checks'].values())
            if not sample['passed'] and report['first_failure'] is None:
                report['first_failure'] = sample
            stream.write(json.dumps(sample) + '\n')
            stream.flush()
            report['sample_count'] += 1
            report['observed_seconds'] = time.monotonic() - start
            report['latest'] = sample
            done = report['observed_seconds'] >= args.seconds
            if report['first_failure'] is not None:
                report['state'] = 'failed'
            elif done:
                report.update(state='passed', passed=True)
            temporary = args.output / 'summary.json.tmp'
            temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
            temporary.replace(args.output / 'summary.json')
            if done:
                break
            time.sleep(min(60, args.seconds - report['observed_seconds']))


if __name__ == '__main__':
    main()
