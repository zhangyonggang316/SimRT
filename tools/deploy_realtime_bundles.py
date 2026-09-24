"""Validate, remotely compile, and retrieve RT bundles without running models.

Use --folder for generation_report.json or --bundle with a dedicated --output.
--check-only is offline, does not prompt for credentials, and writes no files.
"""

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import sys
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / 'x280_linux_target' / 'tools' / 'build_model.py'


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def builder_api():
    """Load the repository validator, never execute a supplied bundle script."""
    spec = importlib.util.spec_from_file_location('_rt_bundle_validator', BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError('Canonical build_model.py validator is unavailable')
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def create_service(log):
    sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
    from pyxcp_host.services.ssh_deployment import SSHDeployment
    return SSHDeployment(log)


def model_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', value):
        raise ValueError('Invalid model identifier: ' + repr(value))
    return value


def remote_root(value):
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or value in ('.', '~') or '..' in path.parts
            or any(char in value for char in '\\\x00\r\n:') or value.startswith('~')):
        raise ValueError('--remote-root must be a dedicated relative path below the SSH home')
    return path.as_posix()


def validate_selection(args):
    """Validate every input and destination before password prompt/network/writes."""
    for value in (args.host, args.user):
        if not value.strip() or any(char in value for char in '\x00\r\n'):
            raise ValueError('SSH host and username must be nonempty single-line values')
    if not 1 <= args.port <= 65535 or not math.isfinite(args.timeout) or args.timeout <= 0:
        raise ValueError('Invalid SSH port or compilation timeout')
    args.remote_root = remote_root(args.remote_root)
    expected = None
    if args.bundle:
        if args.output is None:
            raise ValueError('--bundle requires a dedicated --output directory')
        bundles = [args.bundle.absolute()]
        output = args.output.absolute()
    else:
        folder = args.folder.absolute()
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError('--folder must be a regular generation directory')
        generation = folder / 'generation_report.json'
        if generation.is_symlink():
            raise ValueError('generation_report.json cannot be a symbolic link')
        if generation.is_file():
            items = json.loads(generation.read_text(encoding='utf-8-sig'))
            if not isinstance(items, list) or not items:
                raise ValueError('generation_report.json must be a nonempty model list')
            expected = [model_name(item.get('model')) if isinstance(item, dict) else model_name(None)
                        for item in items]
            bundles = [folder / (name + '_rt_bundle') for name in expected]
        else:
            bundles = [folder / name for name in ('single_rt_bundle', 'multirate_rt_bundle')]
        output = (args.output or folder).absolute()
    for path in [output] + list(output.parents):
        if path.is_symlink():
            raise ValueError('Output path cannot contain symbolic links')
    if output.exists() and not output.is_dir():
        raise ValueError('--output must be a directory')
    if output.resolve() in (Path(output.anchor).resolve(), Path.home().resolve()):
        raise ValueError('--output must be a dedicated build directory')
    for name in ('build_report.json', 'downloaded', 'build_logs'):
        if (output / name).exists() or (output / name).is_symlink():
            raise FileExistsError('Preserve existing build output: ' + str(output / name))
    validator = builder_api()
    records, names = [], set()
    for index, bundle in enumerate(bundles):
        for path in [bundle] + list(bundle.parents):
            if path.is_symlink():
                raise ValueError('Bundle path cannot contain symbolic links')
        bundle = bundle.resolve()
        if output.resolve() == bundle or bundle in output.resolve().parents:
            raise ValueError('Build output must not be inside an uploaded bundle')
        spec, hashes, source_hash = validator.validate_bundle(bundle)
        model = model_name(spec['model'])
        if not isinstance(spec.get('runtime'), dict):
            raise ValueError('Only realtime bundles with an explicit runtime contract are accepted')
        if model.casefold() in names:
            raise ValueError('Selected model names must be unique: ' + model)
        names.add(model.casefold())
        if expected is not None and expected[index] != model:
            raise ValueError('generation_report model does not match bundle: ' + model)
        script = bundle / 'build_model.py'
        if script.is_symlink() or not script.is_file() or digest(script) != digest(BUILDER):
            raise ValueError('Bundle build_model.py is outdated; re-export using the current toolbox: ' + str(bundle))
        # SSH upload includes auxiliary files too; reject unsafe entries before connecting.
        for path in bundle.rglob('*'):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('Bundle contains a non-regular entry: ' + str(path))
        records.append(dict(model=model, bundle=str(bundle), status='pending', success=False,
            remote_directory='', period_seconds=spec['runtime']['period_ns'] / 1e9,
            payload=model + '_payload', local_elf=str(output / 'downloaded' / (model + '.elf')),
            download=None, elf_sha256=None, source_sha256=source_hash,
            spec_sha256=digest(bundle / 'build_spec.json'), build_script_sha256=digest(script),
            source_files_sha256=hashes, build_log=str(output / 'build_logs' / (model + '.log')),
            xcp_transport=spec.get('xcp_transport'), xcp_port=spec.get('xcp_port'),
            started_at=None, finished_at=None, error=None))
    return output.resolve(), records


def write_report(path, report, exclusive=False):
    """Publish complete JSON atomically; the initial report must not replace a run."""
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


_PREFLIGHT = r'''
import json, platform, re, shutil, subprocess, sys
from pathlib import Path
request = json.loads(sys.argv[1])
if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
    raise RuntimeError('The remote target must be native x86-64 Linux')
if sys.version_info < (3, 8):
    raise RuntimeError('Python 3.8 or later is required')
compilers = {}
for name in request['compilers']:
    path = shutil.which(name)
    if not path:
        raise RuntimeError('Required compiler not found: ' + name)
    target = subprocess.check_output([path, '-dumpmachine'], text=True).strip()
    if not re.fullmatch(r'x86_64-[A-Za-z0-9_.-]*linux[A-Za-z0-9_.-]*', target):
        raise RuntimeError('Compiler is not native x86-64 Linux: ' + target)
    version = subprocess.check_output([path, '--version'], text=True).strip()
    compilers[name] = dict(path=path, target=target, version=version)
print(json.dumps(dict(hostname=platform.node(), machine=platform.machine(),
                     system=platform.system(), python=platform.python_version(), compilers=compilers)))
'''


_RESERVE_DIRECTORIES = r'''
import json, os, sys
from pathlib import Path
request = json.loads(sys.argv[1])
home = Path.home().resolve()
root = home / request['root']
if root == home or home not in root.resolve().parents:
    raise ValueError('Remote build root must stay below the SSH home')
for path in [root] + list(root.parents):
    if path.is_symlink():
        raise ValueError('Remote build path cannot contain symbolic links')
root.mkdir(parents=True, exist_ok=True)
run = root / request['run_id']
run.mkdir(exist_ok=False)
directories = {}
for model in request['models']:
    directory = run / model
    directory.mkdir(exist_ok=False)
    directories[model] = str(directory)
print(json.dumps(dict(home=str(home), run_directory=str(run), directories=directories)))
'''


_BUILD_RESULT = r'''
import json, sys
from pathlib import Path
request = json.loads(sys.argv[1])
print((Path(request['directory']) / 'build_result.json').read_text(encoding='utf-8'))
'''


def remote_json(service, script, values, timeout=30):
    command = 'python3 -c {} {}'.format(shlex.quote(script), shlex.quote(json.dumps(values)))
    return json.loads(service._execute(command, timeout=timeout))


def run(args, output, records):
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'build_report.json'
    report = dict(schema_version=2, host=args.host.strip(), username=args.user.strip(), port=args.port,
        remote_root=args.remote_root, run_id='build_' + uuid.uuid4().hex, started_at=timestamp(),
        finished_at=None, status='running', success=False, check_only=False, jobs=args.jobs,
        timeout_seconds=args.timeout, models=records, error=None, preflight=None, cleanup_errors=[])
    write_report(report_path, report, exclusive=True)
    service = None
    active = None
    log_stream = None
    last_owned_log = None

    def log(message):
        print(message, flush=True)
        if log_stream is not None:
            log_stream.write(str(message) + ('\n' if not str(message).endswith('\n') else ''))
            log_stream.flush()

    try:
        (output / 'downloaded').mkdir(exist_ok=False)
        (output / 'build_logs').mkdir(exist_ok=False)
        with (output / 'build_logs' / 'connection.log').open('x', encoding='utf-8') as connection_log:
            last_owned_log = Path(connection_log.name)
            log_stream = connection_log
            service = create_service(log)
            password = getpass.getpass('SSH password (not stored): ')
            try:
                service.connect(args.host.strip(), args.user.strip(), password=password, port=args.port)
            finally:
                password = None
            compilers = {'gcc'}
            if any(Path(name).suffix.lower() in ('.cpp', '.cc', '.cxx')
                   for record in records for name in record['source_files_sha256']):
                compilers.add('g++')
            report['preflight'] = remote_json(service, _PREFLIGHT, dict(compilers=sorted(compilers)))
            allocation = remote_json(service, _RESERVE_DIRECTORIES,
                dict(root=args.remote_root, run_id=report['run_id'], models=[item['model'] for item in records]))
            report['remote_run_directory'] = allocation['run_directory']
            for record in records:
                record['remote_directory'] = allocation['directories'][record['model']]
        log_stream = None
        write_report(report_path, report)
        for active in records:
            active.update(status='running', started_at=timestamp())
            write_report(report_path, report)
            with Path(active['build_log']).open('x', encoding='utf-8') as model_log:
                last_owned_log = Path(model_log.name)
                log_stream = model_log
                # Recheck after the password prompt, before uploading potentially edited inputs.
                spec, hashes, fingerprint = builder_api().validate_bundle(Path(active['bundle']))
                if (fingerprint != active['source_sha256']
                        or digest(Path(active['bundle']) / 'build_spec.json') != active['spec_sha256']
                        or digest(Path(active['bundle']) / 'build_model.py') != active['build_script_sha256']):
                    raise RuntimeError('Bundle inputs changed after offline validation')
                active['uploaded_files'] = service.upload(Path(active['bundle']), active['remote_directory'])
                command = 'python3 build_model.py --jobs {}'.format(args.jobs)
                active['command'] = command
                service.build(active['remote_directory'], command, timeout=args.timeout)
                result = remote_json(service, _BUILD_RESULT, dict(directory=active['remote_directory']))
                active['build_result'] = result
                if (result.get('status') != 'success' or not result.get('published')
                        or result.get('model') != active['model']
                        or result.get('sources_hash') != active['source_sha256']
                        or result.get('elf') != active['model'] + '.elf'):
                    raise RuntimeError('Remote build result does not match the validated bundle')
                destination = Path(active['local_elf'])
                if destination.exists() or destination.is_symlink():
                    raise FileExistsError('Refuse to replace downloaded ELF: ' + str(destination))
                downloaded = service.download_elf(active['remote_directory'] + '/' + destination.name, destination)
                builder_api().validate_elf(destination)
                artifact_hash = digest(destination)
                if artifact_hash != result.get('elf_sha256'):
                    raise RuntimeError('Downloaded ELF does not match the completed build result')
                active.update(download=str(downloaded), elf_sha256=artifact_hash,
                    status='success', success=True, finished_at=timestamp())
            log_stream = None
            write_report(report_path, report)
        report.update(success=True, status='success')
    except (Exception, KeyboardInterrupt) as error:
        message = '{}: {}'.format(type(error).__name__, error)
        report.update(error=message, status='failed', success=False)
        if active is not None and not active['success']:
            active.update(status='failed', error=message, finished_at=timestamp())
        for record in records:
            if record['status'] == 'pending':
                record.update(status='not_attempted', error='Earlier build stage failed')
        if last_owned_log is not None:
            try:
                with last_owned_log.open('a', encoding='utf-8') as failure_log:
                    failure_log.write('\n' + message + '\n')
            except OSError as log_error:
                report['cleanup_errors'].append('build_log: ' + str(log_error))
        print(message, file=sys.stderr)
    finally:
        log_stream = None
        if service is not None:
            try:
                service.close()
            except Exception as error:
                report['cleanup_errors'].append('{}: {}'.format(type(error).__name__, error))
                report.update(status='failed', success=False)
        report['finished_at'] = timestamp()
        write_report(report_path, report)
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--folder', type=Path, help='Generated multi-model folder')
    selection.add_argument('--bundle', type=Path, help='One exported RT bundle')
    parser.add_argument('--output', type=Path, help='New build output directory (required with --bundle)')
    parser.add_argument('--host', default='192.168.219.86')
    parser.add_argument('--user', default='zh')
    parser.add_argument('--port', type=int, default=22)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--jobs', type=int, choices=range(1, 9), default=2, metavar='1..8')
    parser.add_argument('--remote-root', default='MATLAB_ws/builds')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        output, records = validate_selection(args)
        if args.check_only:
            print(json.dumps(dict(status='checked', success=True, check_only=True,
                                  output=str(output), models=records), indent=2))
            return 0
        return run(args, output, records)
    except (Exception, KeyboardInterrupt) as error:
        print('{}: {}'.format(type(error).__name__, error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
