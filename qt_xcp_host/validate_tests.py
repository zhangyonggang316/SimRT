"""Run Qt and shared-service suites in isolated interpreters and record results."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

PROJECT = Path(__file__).resolve().parent
WORKSPACE = PROJECT.parent


def run_suite(name, output):
    start = PROJECT / 'tests' if name == 'qt' else PROJECT / 'service_tests'
    sys.path[:0] = [str(PROJECT), str(WORKSPACE / 'x280_linux_target/python')]
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    started = time.monotonic()
    suite = unittest.defaultTestLoader.discover(str(start))
    with (output / (name + '_tests.log')).open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    record = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  skipped=len(result.skipped), passed=result.wasSuccessful(), seconds=time.monotonic() - started)
    (output / (name + '_tests.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(name, record)
    return 0 if result.wasSuccessful() and not result.skipped else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--suite', choices=('qt', 'baseline'))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.suite:
        return run_suite(args.suite, output)
    environment = dict(os.environ, PYTHONIOENCODING='utf-8', QT_QPA_PLATFORM='offscreen')
    results = []
    for name in ('qt', 'baseline'):
        results.append(subprocess.run([sys.executable, str(Path(__file__).resolve()), '--suite', name, '--output', str(output)],
                                     cwd=WORKSPACE, env=environment).returncode)
    files = {}
    for directory in ('qt_host', 'pyxcp_host', 'native', 'tests', 'service_tests'):
        for path in sorted((PROJECT / directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                files[path.relative_to(PROJECT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(PROJECT.glob('*.py')):
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(created_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'), python=sys.version,
                  qt=json.loads((output / 'qt_tests.json').read_text(encoding='utf-8')),
                  baseline=json.loads((output / 'baseline_tests.json').read_text(encoding='utf-8')),
                  passed=not any(results), ubuntu_hardware_test=False, source_sha256=files)
    (output / 'test_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return int(any(results))


if __name__ == '__main__':
    raise SystemExit(main())
