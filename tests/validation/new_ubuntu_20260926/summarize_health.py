"""Summarize the complete, unmodified target_session health recording."""

import argparse
from collections import defaultdict
import json
from pathlib import Path


def kib(value):
    if not value:
        return None
    amount, unit = value.split()
    if unit != 'kB':
        raise ValueError('Unexpected /proc memory unit: ' + unit)
    return int(amount)


def summarize(source, clock_ticks):
    wrapper = json.loads(source.read_text(encoding='utf-8'))
    events = [json.loads(row) for row in wrapper['stdout'].splitlines() if row.strip()]
    samples = [event for event in events if event.get('event') == 'simrt_health_sample']
    completion = [event for event in events if event.get('event') == 'simrt_health_complete']
    if not samples:
        raise ValueError('No health samples in source')
    grouped = defaultdict(list)
    for sample in samples:
        for process in sample['processes']:
            grouped[(process['pid'], process['start_ticks'])].append((sample['elapsed_seconds'], process))
    processes = []
    for (pid, started), observations in grouped.items():
        first_time, first = observations[0]
        last_time, last = observations[-1]
        duration = last_time - first_time
        memory = [kib(process['rss']) for _, process in observations if process.get('rss')]
        tail = [kib(process['rss']) for stamp, process in observations
                if stamp >= last_time - 1800 and process.get('rss')]
        processes.append(dict(pid=pid, start_ticks=started, name=first['name'],
                              observations=len(observations), observed_seconds=duration,
                              present_in_last_sample=any(p['pid'] == pid and p['start_ticks'] == started
                                                         for p in samples[-1]['processes']),
                              rss_first_kib=kib(first.get('rss')), rss_last_kib=kib(last.get('rss')),
                              rss_min_kib=min(memory) if memory else None,
                              rss_max_kib=max(memory) if memory else None,
                              last_30_minutes_rss_range_kib=[min(tail), max(tail)] if tail else None,
                              average_cpu_percent_of_one_logical_cpu=(
                                  100 * (last['cpu_ticks'] - first['cpu_ticks']) / clock_ticks / duration
                                  if duration else None),
                              max_threads=max(int(process['threads']) for _, process in observations),
                              last_runtime=last.get('runtime')))
    intervals = [after['elapsed_seconds'] - before['elapsed_seconds']
                 for before, after in zip(samples, samples[1:])]
    indices = [sample['sample'] for sample in samples]
    complete = bool(wrapper['exit_code'] == 0 and len(completion) == 1
                    and completion[0]['elapsed_seconds'] >= 10800
                    and completion[0]['samples'] == len(samples)
                    and indices == list(range(len(samples))))
    return dict(source=str(source), complete_three_hour_recording=complete,
                completion=completion, sample_count=len(samples),
                started_utc=samples[0]['timestamp_utc'], finished_utc=samples[-1]['timestamp_utc'],
                maximum_sampling_gap_seconds=max(intervals) if intervals else None,
                minimum_memory_available_kib=min(kib(s['memory_available']) for s in samples),
                minimum_swap_free_kib=min(kib(s['swap_free']) for s in samples),
                minimum_disk_free_bytes=min(s['disk_free_bytes'] for s in samples),
                maximum_one_minute_load=max(s['load'][0] for s in samples),
                clock_ticks_per_second=clock_ticks, processes=processes,
                interpretation='Process starts/stops include intentional tests and status-pane updates. '
                               'Resource sampling alone is not a realtime deadline acceptance test.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clock-ticks', type=int, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.clock_ticks <= 0:
        parser.error('Use a new output report and the actual target CLK_TCK value')
    report = summarize(args.source, args.clock_ticks)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['complete_three_hour_recording'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
