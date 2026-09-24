"""Compile generated realtime bundles locally and publish ELF build evidence.

Use --folder for a generation_report.json directory, or --bundle with --output.
--host is A2L target metadata only. This tool never connects to or runs a target.
"""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / 'x280_linux_target' / 'tools' / 'build_model.py'


def builder_api():
    specification = importlib.util.spec_from_file_location('_local_bundle_builder', BUILDER)
    if specification is None or specification.loader is None:
        raise RuntimeError('Canonical build_model.py is unavailable')
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def model_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', value):
        raise ValueError('Invalid model identifier: ' + repr(value))
    return value


def regular_path(path):
    for part in [path] + list(path.parents):
        if part.is_symlink():
            raise ValueError('Symbolic links are not allowed: ' + str(part))


def validate_selection(args):
    if not args.host.strip() or any(char in args.host for char in '\0\r\n'):
        raise ValueError('--host must be a nonempty single-line target address')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('--timeout must be a positive finite number')
    expected = None
    if args.bundle:
        if args.output is None:
            raise ValueError('--bundle requires a dedicated --output directory')
        bundles, output = [args.bundle.absolute()], args.output.absolute()
    else:
        folder = args.folder.absolute()
        regular_path(folder)
        generation = folder / 'generation_report.json'
        regular_path(generation)
        items = json.loads(generation.read_text(encoding='utf-8-sig'))
        if not isinstance(items, list) or not items:
            raise ValueError('generation_report.json must be a nonempty model list')
        expected = [model_name(item.get('model')) if isinstance(item, dict) else model_name(None) for item in items]
        bundles = [folder / (name + '_rt_bundle') for name in expected]
        output = (args.output or folder).absolute()
    regular_path(output)
    if output.exists() and not output.is_dir():
        raise ValueError('--output must be a directory')
    if output.resolve() in (Path(output.anchor).resolve(), Path.home().resolve()):
        raise ValueError('--output must be a dedicated build directory')
    for name in ('build_report.json', 'built', 'build_sources', 'build_logs'):
        if (output / name).exists() or (output / name).is_symlink():
            raise FileExistsError('Preserve existing build output: ' + str(output / name))
    validator, records, names = builder_api(), [], set()
    for index, bundle in enumerate(bundles):
        regular_path(bundle)
        bundle = bundle.resolve()
        if output.resolve() == bundle or bundle in output.resolve().parents:
            raise ValueError('Build output must not be inside a source bundle')
        spec, hashes, fingerprint = validator.validate_bundle(bundle)
        model = model_name(spec['model'])
        if not isinstance(spec.get('runtime'), dict):
            raise ValueError('Only realtime bundles with an explicit runtime contract are accepted')
        if model.casefold() in names:
            raise ValueError('Selected model names must be unique: ' + model)
        names.add(model.casefold())
        if expected is not None and expected[index] != model:
            raise ValueError('generation_report model does not match bundle: ' + model)
        records.append(dict(model=model, bundle=str(bundle), status='pending', success=False,
            period_seconds=spec['runtime']['period_ns'] / 1e9, payload=model + '_payload',
            local_elf=str(output / 'built' / (model + '.elf')), elf_sha256=None,
            source_sha256=fingerprint, source_files_sha256=hashes,
            spec_sha256=validator.digest(bundle / 'build_spec.json'),
            build_script_sha256=validator.digest(BUILDER),
            build_directory=str(output / 'build_sources' / model),
            build_log=str(output / 'build_logs' / (model + '.log')),
            xcp_transport=spec.get('xcp_transport'), xcp_port=spec.get('xcp_port'),
            command=None, build_result=None, started_at=None, finished_at=None, error=None))
    return output.resolve(), records


def write_report(path, report, exclusive=False):
    descriptor, temporary = tempfile.mkstemp(prefix='.build_report.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute_build(command, directory, stream, timeout):
    options = dict(cwd=directory, stdout=stream, stderr=subprocess.STDOUT)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    process = subprocess.Popen(command, **options)
    try:
        code = process.wait(timeout=timeout)
        if code:
            raise subprocess.CalledProcessError(code, command)
    except BaseException:
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=stream, stderr=subprocess.STDOUT, check=False)
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise


def publish_elf(source, destination, expected_hash, validator):
    descriptor, temporary = tempfile.mkstemp(prefix='.' + destination.name + '.', suffix='.tmp', dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, 'wb') as destination_file, source.open('rb') as source_file:
            shutil.copyfileobj(source_file, destination_file)
            destination_file.flush()
            os.fsync(destination_file.fileno())
        if validator.digest(temporary) != expected_hash:
            raise RuntimeError('Published ELF hash does not match the local build')
        os.chmod(temporary, 0o755)
        os.link(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run(args, output, records):
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'build_report.json'
    report = dict(schema_version=3, mode='local-build', host=args.host.strip(), success=False,
        status='running', started_at=timestamp(), finished_at=None, jobs=args.jobs,
        toolchain_root=str(args.toolchain_root.resolve()) if args.toolchain_root else None,
        timeout_seconds=args.timeout, remote_operations_performed=False,
        models=records, error=None)
    write_report(report_path, report, exclusive=True)
    validator, active = builder_api(), None
    try:
        for name in ('built', 'build_sources', 'build_logs'):
            (output / name).mkdir(exist_ok=False)
        for active in records:
            active.update(status='running', started_at=timestamp())
            write_report(report_path, report)
            source = Path(active['bundle'])
            if (validator.validate_bundle(source)[2] != active['source_sha256']
                    or validator.digest(BUILDER) != active['build_script_sha256']):
                raise RuntimeError('Bundle or canonical builder changed after validation')
            directory = Path(active['build_directory'])
            directory.mkdir(exist_ok=False)
            shutil.copytree(source / 'src', directory / 'src')
            shutil.copy2(source / 'build_spec.json', directory / 'build_spec.json')
            shutil.copy2(BUILDER, directory / 'build_model.py')
            if (validator.validate_bundle(directory)[2] != active['source_sha256']
                    or validator.digest(directory / 'build_model.py') != active['build_script_sha256']):
                raise RuntimeError('Copied bundle does not match validated input')
            command = [sys.executable, str(directory / 'build_model.py'), '--jobs', str(args.jobs)]
            if args.toolchain_root:
                command += ['--toolchain-root', str(args.toolchain_root.resolve())]
            if args.rebuild:
                command.append('--rebuild')
            active['command'] = command
            write_report(report_path, report)
            with Path(active['build_log']).open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(command=command, cwd=str(directory))) + '\n')
                stream.flush()
                execute_build(command, directory, stream, args.timeout)
            result = json.loads((directory / 'build_result.json').read_text(encoding='utf-8'))
            active['build_result'] = result
            if (result.get('status') != 'success' or not result.get('published')
                    or result.get('model') != active['model']
                    or result.get('sources_hash') != active['source_sha256']
                    or result.get('elf') != active['model'] + '.elf'):
                raise RuntimeError('Local build result does not match the validated bundle')
            artifact = directory / result['elf']
            validator.validate_elf(artifact)
            artifact_hash = validator.digest(artifact)
            if artifact_hash != result.get('elf_sha256'):
                raise RuntimeError('Local ELF does not match the completed build result')
            destination = Path(active['local_elf'])
            publish_elf(artifact, destination, artifact_hash, validator)
            active.update(elf_sha256=artifact_hash, success=True, status='success', finished_at=timestamp())
            write_report(report_path, report)
        report.update(success=True, status='success')
    except (Exception, KeyboardInterrupt) as error:
        message = '{}: {}'.format(type(error).__name__, error)
        report.update(success=False, status='failed', error=message)
        if active is not None and not active['success']:
            result_path = Path(active['build_directory']) / 'build_result.json'
            if result_path.is_file():
                try:
                    active['build_result'] = json.loads(result_path.read_text(encoding='utf-8'))
                except (ValueError, OSError):
                    pass
            active.update(status='failed', error=message, finished_at=timestamp())
        for record in records:
            if record['status'] == 'pending':
                record.update(status='not_attempted', error='Earlier build stage failed')
        print(message, file=sys.stderr)
    finally:
        report['finished_at'] = timestamp()
        write_report(report_path, report)
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--folder', type=Path, help='Directory containing generation_report.json')
    selection.add_argument('--bundle', type=Path, help='One exported realtime bundle')
    parser.add_argument('--output', type=Path, help='New build output directory; required with --bundle')
    parser.add_argument('--host', default='192.168.219.86', help='Target address for subsequent A2L export only')
    parser.add_argument('--toolchain-root', type=Path, help='Portable package directory containing toolchain/')
    parser.add_argument('--jobs', type=int, default=2, choices=range(1, 9), metavar='1..8')
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--rebuild', action='store_true')
    parser.add_argument('--check-only', action='store_true', help='Offline input validation; writes no files')
    args = parser.parse_args(argv)
    try:
        output, records = validate_selection(args)
        if args.check_only:
            print(json.dumps(dict(status='checked', success=True, check_only=True,
                output=str(output), host=args.host.strip(), remote_operations_performed=False, models=records), indent=2))
            return 0
        return run(args, output, records)
    except (Exception, KeyboardInterrupt) as error:
        print('{}: {}'.format(type(error).__name__, error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
