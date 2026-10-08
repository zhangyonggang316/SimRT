"""Run the Windows-cross-compiled runtime harness on Linux; no target compilation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def run_case(harness, label, arguments, stop_after=None, diagnostic=False):
    status_path = Path(str(harness) + '.simrt-status.json')
    environment = dict(os.environ, SIMRT_RT_REQUIRE_KERNEL='0' if diagnostic else '1')
    process = subprocess.Popen([str(harness), *arguments], stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, env=environment)
    samples = []
    started = time.monotonic()
    signalled = False
    try:
        while process.poll() is None:
            if time.monotonic() - started > 15:
                raise TimeoutError(label)
            if stop_after and not signalled and time.monotonic() - started >= stop_after:
                process.terminate()
                signalled = True
            if status_path.exists():
                snapshot = json.loads(status_path.read_text())
                if snapshot['pid'] == process.pid and snapshot['state'] == 'RUNNING':
                    assert snapshot['memory_locked'] is True
                    assert diagnostic or snapshot['realtime_kernel'] is True
                    assert snapshot['period_ns'] == 1000000
                    assert snapshot['model_step_execution_current_ns'] <= snapshot['model_step_execution_max_ns']
                    assert snapshot['model_step_completed_calls'] <= snapshot['model_step_calls']
                    if not samples or snapshot['sample_monotonic_ns'] != samples[-1]['sample_monotonic_ns']:
                        if samples:
                            assert snapshot['model_step_calls'] >= samples[-1]['model_step_calls']
                            assert snapshot['elapsed_ns'] >= samples[-1]['elapsed_ns']
                        samples.append(snapshot)
            time.sleep(0.01)
        output = process.communicate(timeout=3)[0]
        assert process.returncode == 0, output
        final = json.loads(status_path.read_text())
        summaries = [json.loads(line) for line in output.splitlines()
                     if line.startswith('{') and json.loads(line).get('event') == 'simrt_rt_summary']
        assert len(summaries) == 1, output
        summary = summaries[0]
        assert final['pid'] == process.pid and final['state'] == 'STOPPED'
        assert len(samples) >= 2 and samples[-1]['model_step_calls'] > samples[0]['model_step_calls']
        for name in ('model_step_calls', 'model_step_completed_calls', 'model_step_interval_min_ns',
                     'model_step_interval_max_ns', 'model_step_interval_mean_ns',
                     'model_step_execution_max_ns', 'deadline_misses', 'skipped_releases',
                     'period_ns', 'elapsed_ns'):
            assert final[name] == summary[name], (name, final[name], summary[name])
        assert not list(status_path.parent.glob(status_path.name + '.tmp.*'))
        if stop_after:
            assert summary['stop_signal'] == 15
        if label == 'overrun':
            assert final['deadline_misses'] > 0 and final['skipped_releases'] > 0
        return dict(name=label, passed=True, samples=samples, final=final, summary=summary, output=output)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('harness', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-non-rt-diagnostic', action='store_true',
                        help='Explicitly allow functional testing on a non-RT kernel; never an RT acceptance result.')
    args = parser.parse_args()
    assert not args.output.exists(), 'Use a new output report.'
    harness = args.harness.resolve(strict=True)
    math = subprocess.run([str(harness), '--math'], check=True, capture_output=True, text=True)
    diagnostic = args.allow_non_rt_diagnostic
    cases = [run_case(harness, 'normal', ['--normal-load', '--cycles', '2600'], diagnostic=diagnostic),
             run_case(harness, 'overrun', ['--cycles', '2200'], diagnostic=diagnostic),
             run_case(harness, 'sigterm', ['--normal-load', '--long'], stop_after=2.2, diagnostic=diagnostic)]
    report = dict(passed=True, target_compilation=False, diagnostic_only=diagnostic,
                  strict_realtime_validation=not diagnostic, math=math.stdout, cases=cases)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(passed=True, diagnostic_only=diagnostic,
                          cases=[case['name'] for case in cases])))


if __name__ == '__main__':
    main()
