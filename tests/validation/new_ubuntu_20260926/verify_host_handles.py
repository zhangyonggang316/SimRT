"""Compare native pyxcp object reclamation without connecting to any device."""

import argparse
import gc
import json
from pathlib import Path
import sys
import weakref

from soak_model import host_resources
from pyxcp.master import Master
from pyxcp.transport.base import NoOpPolicy
from simrt_xcp.client import _create_master, build_pyxcp_config, TransportSettings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output report')
    references = []

    def exercise(count, keep_refs):
        for _ in range(count):
            config = build_pyxcp_config(TransportSettings('127.0.0.1'))
            master = Master('eth', config=config, policy=NoOpPolicy()) if args.baseline else _create_master('eth', config)
            if keep_refs:
                references.append(weakref.ref(master))
            master.close()
            del master
        gc.collect()

    exercise(5, False)
    samples = [host_resources()]
    for batch in range(5):
        exercise(10, True)
        samples.append(host_resources())
        print(json.dumps(dict(batch=batch, handles=samples[-1]['HandleCount'],
                              retained=sum(reference() is not None for reference in references))), flush=True)
    growth = samples[-1]['HandleCount'] - samples[0]['HandleCount']
    retained = sum(reference() is not None for reference in references)
    passed = retained == 50 and growth >= 250 if args.baseline else retained == 0 and abs(growth) <= 4
    report = dict(passed=passed, baseline_bug_reproduction=args.baseline,
                  created_closed_masters=50, retained_after_gc=retained,
                  handle_growth=growth, samples=samples, target_network_used=False,
                  python=sys.version)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
