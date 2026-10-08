#!/usr/bin/env python3
"""Keep movable IRQs and unbound workqueues off the model's physical core."""
import argparse
import json
from pathlib import Path

STATE = Path('/run/simrt-rt-tuning.json')


def cpu_list(text):
    result = set()
    for item in text.strip().split(','):
        bounds = item.split('-')
        result.update(range(int(bounds[0]), int(bounds[-1]) + 1))
    return result


def cpu_mask(cpus):
    value = sum(1 << cpu for cpu in cpus)
    parts = []
    while value:
        parts.append('%08x' % (value & 0xffffffff))
        value >>= 32
    return ','.join(reversed(parts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('apply', 'restore'))
    parser.add_argument('--cpu', type=int)
    args = parser.parse_args()
    if args.action == 'restore':
        records = json.loads(STATE.read_text()) if STATE.exists() else []
        errors = []
        for record in reversed(records):
            path = Path(record['path'])
            try:
                if path.read_text().strip() == record['after']:
                    path.write_text(record['before'])
            except OSError as error:
                errors.append(dict(path=str(path), error=str(error)))
        if errors:
            raise RuntimeError(json.dumps(errors))
        STATE.unlink(missing_ok=True)
        return
    online = cpu_list(Path('/sys/devices/system/cpu/online').read_text())
    selected = max(online) if args.cpu is None else args.cpu
    if selected not in online:
        raise ValueError('The model CPU is offline')
    siblings = cpu_list(Path('/sys/devices/system/cpu/cpu%d/topology/thread_siblings_list' % selected).read_text())
    housekeeping = online - siblings
    if not housekeeping:
        raise ValueError('A separate physical core is required')
    cpus = ','.join(str(cpu) for cpu in sorted(housekeeping))
    mask = cpu_mask(housekeeping)
    requests = {str(p): cpus for p in Path('/proc/irq').glob('[0-9]*/smp_affinity_list')}
    requests['/proc/irq/default_smp_affinity'] = mask
    requests['/sys/devices/virtual/workqueue/cpumask'] = mask
    records = json.loads(STATE.read_text()) if STATE.exists() else []
    known = {record['path'] for record in records}
    errors = []
    for name, value in requests.items():
        path = Path(name)
        before = path.read_text().strip()
        # Save the original value before mutation, so interruption is recoverable.
        record = dict(path=name, before=before, after=value)
        if name not in known:
            records.append(record)
            STATE.write_text(json.dumps(records, indent=2))
            STATE.chmod(0o600)
        try:
            path.write_text(value)
            record['after'] = path.read_text().strip()
            for saved in records:
                if saved['path'] == name:
                    saved['after'] = record['after']
            STATE.write_text(json.dumps(records, indent=2))
        except OSError as error:
            # Fixed hardware IRQs may reject affinity changes.
            errors.append(dict(path=name, error=str(error)))
    print(json.dumps(dict(cpu=selected, housekeeping=sorted(housekeeping), changes=records, fixed_irqs=errors)))


if __name__ == '__main__':
    main()
