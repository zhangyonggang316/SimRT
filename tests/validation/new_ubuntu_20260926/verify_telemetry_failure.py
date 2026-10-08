"""Target-side diagnostic using an existing Windows-cross-compiled harness."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


SOURCE = Path('/home/zh/MATLAB_ws/telemetry_diagnostic_20260926/rt_runtime_harness.elf')
EXPECTED_SHA256 = '991dc8dba8f851b52d0ab50fbe0e1190b7c3d5e6ba5af17a22c76c86c41ec1fe'


def run_case(root, label):
    directory = root / label
    directory.mkdir()
    executable = directory / 'runtime_failure_check.elf'
    shutil.copy2(SOURCE, executable)
    executable.chmod(0o755)
    status = Path(str(executable) + '.simrt-status.json')
    if label == 'readonly_directory':
        directory.chmod(0o555)
    else:
        status.mkdir()
    process = None
    try:
        process = subprocess.Popen([str(executable), '--normal-load', '--cycles', '4000'],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, env=dict(os.environ, SIMRT_RT_REQUIRE_KERNEL='0'))
        time.sleep(1.1)
        assert process.poll() is None, 'Harness exited before scheduler observation'
        policies = []
        for task in sorted(Path('/proc/{}/task'.format(process.pid)).iterdir()):
            tid = int(task.name)
            policies.append(dict(tid=tid, policy=os.sched_getscheduler(tid),
                                 priority=os.sched_getparam(tid).sched_priority,
                                 affinity=sorted(os.sched_getaffinity(tid))))
        output, _ = process.communicate(timeout=12)
        assert process.returncode == 0, output
        events = [json.loads(row) for row in output.splitlines() if row.startswith('{')]
        summary = next(event for event in events if event.get('event') == 'simrt_rt_summary')
        assert summary['model_step_calls'] == summary['model_step_completed_calls'] == 4000
        assert output.count('SimRT RT live status unavailable:') == 1
        assert not status.is_file()
        assert not list(directory.glob('*.tmp.*'))
        realtime = [task for task in policies if task['policy'] == os.SCHED_FIFO]
        background = [task for task in policies if task['policy'] == os.SCHED_OTHER]
        assert len(realtime) == 1 and realtime[0]['priority'] == summary['priority'], policies
        assert 1 <= summary['priority'] <= 49 and summary['memory_locked'] is True
        assert len(background) == 2 and all(task['priority'] == 0 for task in background), policies
        model_cpus = set(realtime[0]['affinity'])
        assert len(model_cpus) == 1
        writer = [task for task in background if task['tid'] != process.pid]
        assert len(writer) == 1 and not model_cpus.intersection(writer[0]['affinity']), policies
        return dict(name=label, passed=True, policies=policies, summary=summary, output=output,
                    elapsed_seconds=summary['elapsed_ns'] / 1e9)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
        directory.chmod(0o755)


def main():
    assert os.getuid() != 0, 'This test requires the ordinary target user'
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED_SHA256
    root = Path(tempfile.mkdtemp(prefix='telemetry_failure_', dir='/home/zh/MATLAB_ws'))
    cases = [run_case(root, label) for label in ('readonly_directory', 'rename_to_directory')]
    report = dict(passed=True, target_compilation=False, diagnostic_only=True,
                  strict_realtime_acceptance=False, kernel=os.uname().release,
                  source_sha256=EXPECTED_SHA256, directory=str(root), cases=cases)
    (root / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
