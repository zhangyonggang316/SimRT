"""Validate or incrementally build a flat RTW bundle for x86-64 Linux.

Windows uses portable-linux-toolchain locally; Linux can use native GCC.
Run --check for offline validation. No third-party Python packages are needed.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time


MAX_JOBS = 8
CACHE_VERSION = 2
CXX_SUFFIXES = ('.cpp', '.cc', '.cxx')
GCC_ENVIRONMENT = ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH',
                   'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def plain_path(path, kind=None):
    if path.is_symlink():
        raise ValueError('Symbolic links are not allowed: ' + str(path))
    if kind == 'file' and not path.is_file():
        raise ValueError('Missing regular file: ' + str(path))
    if kind == 'directory' and not path.is_dir():
        raise ValueError('Missing directory: ' + str(path))


def validate_bundle(root):
    """Return validated spec, flat file hashes, and a complete input fingerprint."""
    root = Path(root).absolute()
    plain_path(root, 'directory')
    plain_path(root / 'build_spec.json', 'file')
    plain_path(root / 'src', 'directory')
    spec = json.loads((root / 'build_spec.json').read_text(encoding='utf-8'))
    if not isinstance(spec, dict) or not isinstance(spec.get('model'), str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', spec['model']):
        raise ValueError('Invalid model identifier')
    if spec.get('target', 'x86-64 Linux') != 'x86-64 Linux':
        raise ValueError('Only the x86-64 Linux target is supported')
    sources = spec.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError('Expected a nonempty source list')
    seen = set()
    for name in sources:
        if (not isinstance(name, str) or not name or any(char in name for char in '/\\:\x00')
                or Path(name).name != name or Path(name).suffix.lower() not in ('.c',) + CXX_SUFFIXES):
            raise ValueError('Invalid flat source path: ' + repr(name))
        if name.casefold() in seen:
            raise ValueError('Duplicate source: ' + name)
        seen.add(name.casefold())
        plain_path(root / 'src' / name, 'file')
    defines = spec.get('defines')
    if not isinstance(defines, list):
        raise ValueError('Expected a list of -D definitions')
    macros = {}
    for value in defines:
        match = re.fullmatch(r'-D([A-Za-z_][A-Za-z0-9_]*)(?:=([^\x00-\x1f\x7f]*))?', value) if isinstance(value, str) else None
        if not match or match[1] in macros:
            raise ValueError('Invalid or duplicate -D definition: ' + repr(value))
        macros[match[1]] = match[2]
    if 'xcp_transport' in spec and spec['xcp_transport'] != 'UDP':
        raise ValueError('Only XCP on UDP bundles are supported')
    if 'xcp_port' in spec and (type(spec['xcp_port']) is not int or not 1 <= spec['xcp_port'] <= 65535):
        raise ValueError('XCP UDP port must be an integer from 1 to 65535')
    files = {}
    names = set()
    for path in sorted((root / 'src').iterdir()):
        plain_path(path, 'file')
        if path.name.casefold() in names:
            raise ValueError('Case-insensitive duplicate bundle filename: ' + path.name)
        names.add(path.name.casefold())
        files[path.name] = digest(path)
    runtime = spec.get('runtime')
    if runtime is not None:
        if (not isinstance(runtime, dict) or runtime.get('name') != 'x280_single_task_rt'
                or type(runtime.get('period_ns')) is not int or runtime['period_ns'] not in (1000000, 10000000, 100000000)
                or runtime.get('tasking', 'single') != 'single' or runtime.get('optimization', 'O2') != 'O2'
                or 'x280_rt_runtime.c' not in sources or 'linuxinitialize.c' in sources or macros.get('MT') != '0'):
            raise ValueError('Invalid single-task 1/10/100 ms realtime bundle contract')
        background = runtime.get('xcp_background', False)
        if not isinstance(background, bool):
            raise ValueError('xcp_background must be a boolean')
        main = 'x280_rt_main.c' if background else 'ert_main.c'
        other = 'ert_main.c' if background else 'x280_rt_main.c'
        if runtime.get('main', main) != main or main not in sources or other in sources:
            raise ValueError('Realtime main does not match the XCP background contract')
        code = (root / 'src' / main).read_text(encoding='utf-8')
        calls = re.findall(r'\bmyRTOSInit\s*\(\s*([0-9.eE+-]+)\s*,\s*([0-9]+)\s*\)\s*;', code)
        if (len(calls) != 1 or Decimal(calls[0][0]) * 1000000000 != runtime['period_ns']
                or int(calls[0][1]) != 0):
            raise ValueError('Realtime main myRTOSInit period/subrates do not match build_spec.json')
        if not re.search(r'\b' + re.escape(spec['model']) + r'_step\s*\(\s*\)\s*;', code):
            raise ValueError('Realtime main is missing the model step call')
        if background and not re.search(r'\bextmodeBackgroundRun\s*\(', code):
            raise ValueError('Realtime main is missing background XCP processing')
        numst = macros.get('NUMST')
        if not numst or not numst.isdigit() or int(numst) < 1:
            raise ValueError('Realtime bundle requires a positive NUMST definition')
    plain_path(root / (spec['model'] + '.elf'))
    return spec, files, json_digest({'build_spec': spec, 'files': files})


def compile_flags(realtime, cxx=False):
    flags = ['-g', '-O2' if realtime else '-O0', '-fno-pie', '-pthread']
    if realtime:
        flags += ([] if cxx else ['-std=c11']) + ['-gdwarf-4']
    return flags


def link_flags(realtime):
    flags = ['-g', '-O2' if realtime else '-O0', '-fno-pie', '-no-pie', '-pthread']
    if realtime:
        flags += ['-gdwarf-4', '-Wl,--wrap=sem_wait', '-Wl,--wrap=sem_post']
    return flags


def compiler_identity(name, environment=None):
    executable = shutil.which(name) if environment is None else name
    if not executable:
        raise RuntimeError('Required compiler not found: ' + name)
    executable = str(Path(executable).resolve(strict=True))
    version = subprocess.run([executable, '--version'], env=environment, check=True, capture_output=True, text=True).stdout.strip()
    target = subprocess.run([executable, '-dumpmachine'], env=environment, check=True, capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r'x86_64-[A-Za-z0-9_.-]*linux[A-Za-z0-9_.-]*', target):
        raise RuntimeError('Compiler is not an x86-64 Linux toolchain: ' + target)
    return dict(path=executable, version=version, target=target, sha256=digest(executable))


def locate_toolchain(root):
    for parent in [root] + list(root.parents) + [Path(__file__).resolve().parent] + list(Path(__file__).resolve().parents):
        for candidate in (parent / 'portable-linux-toolchain' / 'portable-linux-toolchain',
                          parent / 'portable-linux-toolchain'):
            if (candidate / 'toolchain' / 'bin' / 'linux-gcc.exe').is_file():
                return candidate.resolve()
    raise RuntimeError('Windows compilation requires --toolchain-root pointing to portable-linux-toolchain; use --check for offline validation')


def portable_environment(package):
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in GCC_ENVIRONMENT + ('PATH',)}
    system = Path(environment.get('SystemRoot', environment.get('SYSTEMROOT', 'C:/Windows')))
    environment['PATH'] = ';'.join(str(path) for path in
        (package / 'toolchain' / 'bin', package / 'host-bin', system / 'System32', system))
    return environment


def select_toolchain(root, languages, toolchain_root=None):
    system = platform.system()
    if toolchain_root is None and system == 'Linux' and platform.machine().lower() in ('x86_64', 'amd64'):
        return ({name: compiler_identity(name) for name in sorted(languages)}, [], None,
                dict(mode='native-linux', root=None, sysroot=None, sysroot_sha256=None))
    if system != 'Windows':
        raise RuntimeError('Portable compilation requires Windows x64; native compilation requires x86-64 Linux')
    package = Path(toolchain_root).resolve() if toolchain_root else locate_toolchain(root)
    plain_path(package, 'directory')
    sysroot = package / 'toolchain' / 'x86_64-linux'
    plain_path(sysroot, 'directory')
    environment = portable_environment(package)
    identities = {}
    for name in sorted(languages):
        executable = package / 'toolchain' / 'bin' / ('linux-' + name + '.exe')
        plain_path(executable, 'file')
        identities[name] = compiler_identity(str(executable), environment)
    # The cache fingerprints actual support files, so changed headers/libraries
    # cannot reuse objects just because manifest.json or the driver stayed equal.
    support = {}
    for directory in (package / 'toolchain', package / 'host-bin'):
        if directory.exists():
            for path in sorted(directory.rglob('*')):
                plain_path(path)
                if path.is_file():
                    support[path.relative_to(package).as_posix()] = digest(path)
    sysroot_files = {name: value for name, value in support.items()
                     if name.startswith('toolchain/x86_64-linux/')}
    metadata = dict(mode='windows-cross', root=str(package), sysroot=str(sysroot),
        sysroot_sha256=json_digest(sysroot_files), support_sha256=json_digest(support),
        support_file_count=len(support), sysroot_file_count=len(sysroot_files),
        manifest_sha256=digest(package / 'manifest.json') if (package / 'manifest.json').is_file() else None,
        sanitized_environment=list(GCC_ENVIRONMENT), executable_search_path=environment['PATH'])
    return identities, ['--sysroot=' + sysroot.as_posix()], environment, metadata


def validate_elf(path):
    """Check the ELF64 little-endian executable header without external tools."""
    with Path(path).open('rb') as stream:
        header = stream.read(64)
    if (len(header) != 64 or header[:4] != b'\x7fELF' or header[4:7] != b'\x02\x01\x01'
            or struct.unpack_from('<HHI', header, 16) != (2, 62, 1)
            or struct.unpack_from('<H', header, 52)[0] != 64):
        raise ValueError('Output is not a valid x86-64 ELF64 non-PIE executable')


def elf_dependencies(path):
    """Read ELF program/dynamic tables without executing the target program."""
    content = Path(path).read_bytes()
    offset = struct.unpack_from('<Q', content, 32)[0]
    entry_size, count = struct.unpack_from('<HH', content, 54)
    if count and (entry_size < 56 or offset + count * entry_size > len(content)):
        raise ValueError('Invalid ELF program-header table')
    segments, dynamic, interpreter = [], None, None
    for index in range(count):
        kind, _, file_offset, address, _, size, _, _ = struct.unpack_from('<IIQQQQQQ', content, offset + index * entry_size)
        if file_offset + size > len(content):
            raise ValueError('ELF segment exceeds file size')
        if kind == 1:
            segments.append((address, file_offset, size))
        elif kind == 2:
            dynamic = (file_offset, size)
        elif kind == 3:
            interpreter = content[file_offset:file_offset + size].rstrip(b'\0').decode('ascii')
    needed, strings, string_size = [], None, None
    if dynamic:
        for index in range(dynamic[0], dynamic[0] + dynamic[1], 16):
            tag, value = struct.unpack_from('<qQ', content, index)
            if tag == 0:
                break
            if tag == 1:
                needed.append(value)
            elif tag == 5:
                strings = value
            elif tag == 10:
                string_size = value
    libraries = []
    if needed:
        matches = [(position + strings - address, size - (strings - address))
                   for address, position, size in segments if strings is not None and address <= strings < address + size]
        if len(matches) != 1 or string_size is None or string_size > matches[0][1]:
            raise ValueError('Invalid ELF dynamic string table')
        start = matches[0][0]
        for index in needed:
            end = content.find(b'\0', start + index, start + string_size)
            if index >= string_size or end < 0:
                raise ValueError('Invalid ELF library name')
            libraries.append(content[start + index:end].decode('ascii'))
    return dict(interpreter=interpreter, needed_libraries=libraries)


def write_json(path, value):
    plain_path(path)
    handle, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def bundle_lock(root):
    """OS locks release even after a killed build; the marker file is retained."""
    path = root / '.build.lock'
    plain_path(path)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if stream.tell() == 0:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            lock = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            lock = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        try:
            lock()
        except OSError as error:
            raise RuntimeError('Another build/check holds .build.lock; wait for it to finish') from error
        try:
            yield
        finally:
            stream.seek(0)
            unlock()


def build(root, spec, files, result, jobs, rebuild=False, toolchain_root=None):
    realtime = spec.get('runtime') is not None
    sources = spec['sources']
    languages = {('g++' if Path(name).suffix.lower() in CXX_SUFFIXES else 'gcc') for name in sources}
    compilers, target_flags, environment, toolchain = select_toolchain(root, languages, toolchain_root)
    result['compilers'] = compilers
    result['toolchain'] = toolchain
    result['source_files_sha256'] = files
    cache = root / '.build_cache'
    plain_path(cache)
    cache.mkdir(exist_ok=True)
    headers = {name: value for name, value in files.items() if name not in sources}
    common = dict(version=CACHE_VERSION, root=str(root), headers=headers, defines=spec['defines'], toolchain=toolchain)

    def compile_one(name):
        cxx = Path(name).suffix.lower() in CXX_SUFFIXES
        compiler = compilers['g++' if cxx else 'gcc']
        flags = target_flags + compile_flags(realtime, cxx)
        key = json_digest(dict(common, source=name, source_hash=files[name], compiler=compiler, flags=flags))
        object_path, record = cache / (key + '.o'), cache / (key + '.json')
        plain_path(object_path)
        plain_path(record)
        if not rebuild and object_path.is_file() and record.is_file():
            try:
                metadata = json.loads(record.read_text(encoding='utf-8'))
                if isinstance(metadata, dict) and metadata.get('sha256') == digest(object_path):
                    return object_path, False, metadata.get('command')
            except (ValueError, OSError):
                pass
        descriptor, temporary = tempfile.mkstemp(prefix=key + '.', suffix='.o.tmp', dir=str(cache))
        os.close(descriptor)
        try:
            command = [compiler['path']] + flags + ['-I', str(root / 'src')] + spec['defines']
            command += ['-c', str(root / 'src' / name), '-o', temporary]
            subprocess.run(command, cwd=root, env=environment, check=True)
            if not Path(temporary).stat().st_size:
                raise RuntimeError('Compiler produced an empty object for ' + name)
            if (digest(root / 'src' / name) != files[name]
                    or any(digest(root / 'src' / header) != expected for header, expected in headers.items())):
                raise RuntimeError('Bundle inputs changed during compilation; object was not cached')
            os.replace(temporary, object_path)
            write_json(record, dict(source=name, sha256=digest(object_path), command=command))
            return object_path, True, command
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    objects, failure = {}, None
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(compile_one, name): name for name in sources}
        for future in as_completed(futures):
            try:
                object_path, compiled, command = future.result()
                objects[futures[future]] = object_path
                result['compile_commands'].append(dict(source=futures[future], command=command, reused=not compiled,
                                                       object=str(object_path), sha256=digest(object_path)))
                result['compiled_count' if compiled else 'reused_count'] += 1
            except Exception as error:
                failure = failure or error
    if failure:
        raise failure
    result['compile_commands'].sort(key=lambda item: sources.index(item['source']))
    linker = compilers['g++' if 'g++' in compilers else 'gcc']['path']
    descriptor, temporary = tempfile.mkstemp(prefix='.' + spec['model'] + '.', suffix='.elf.tmp', dir=str(root))
    os.close(descriptor)
    try:
        command = [linker] + target_flags + link_flags(realtime) + [str(objects[name]) for name in sources]
        command += ['-o', temporary, '-lm', '-lrt', '-lpthread', '-ldl', '-lstdc++']
        result['link_command'] = command
        subprocess.run(command, cwd=root, env=environment, check=True)
        validate_elf(temporary)
        result['dependencies'] = elf_dependencies(temporary)
        if validate_bundle(root)[2] != result['sources_hash']:
            raise RuntimeError('Bundle inputs changed during compilation; output was not published')
        artifact_hash = digest(temporary)
        os.chmod(temporary, 0o755)
        output = root / (spec['model'] + '.elf')
        plain_path(output)
        os.replace(temporary, output)
        result.update(elf=output.name, elf_sha256=artifact_hash, published=True)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None, root=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Validate inputs only; works on Windows and Linux')
    parser.add_argument('--jobs', type=int, default=2, choices=range(1, MAX_JOBS + 1), metavar='1..8', help='Parallel compiler processes (default: 2, maximum: 8)')
    parser.add_argument('--rebuild', action='store_true', help='Ignore cached objects and recompile all sources')
    parser.add_argument('--toolchain-root', type=Path, help='Portable package directory containing toolchain/; auto-discovered on Windows')
    parser.add_argument('--bundle', type=Path, help='Bundle to build (default: directory containing this script)')
    args = parser.parse_args(argv)
    root = Path(root or args.bundle or Path(__file__).absolute().parent).absolute()
    started = time.monotonic()
    result = dict(schema_version=1, mode='check' if args.check else 'build', status='failed',
                  sources_hash=None, compilers={}, jobs=args.jobs, rebuild=args.rebuild, source_count=0,
                  compiled_count=0, reused_count=0, elf=None, elf_sha256=None, published=False,
                  elapsed_seconds=0.0, error=None)
    result.update(toolchain=None, compile_commands=[], link_command=None, dependencies=None)
    locked = False
    try:
        plain_path(root, 'directory')
        with bundle_lock(root):
            locked = True
            try:
                spec, files, sources_hash = validate_bundle(root)
                result.update(model=spec['model'], sources_hash=sources_hash, source_count=len(spec['sources']))
                if not args.check:
                    result['status'] = 'running'
                    write_json(root / 'build_result.json', result)
                    build(root, spec, files, result, args.jobs, args.rebuild, args.toolchain_root)
                result['status'] = 'checked' if args.check else 'success'
            except Exception as error:
                result['status'] = 'failed'
                result['error'] = '{}: {}'.format(type(error).__name__, error)
            result['elapsed_seconds'] = round(time.monotonic() - started, 3)
            write_json(root / 'build_result.json', result)
    except Exception as error:
        result['status'] = 'failed'
        result['error'] = '{}: {}'.format(type(error).__name__, error)
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        if not locked:
            result['report_written'] = False
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['status'] in ('checked', 'success') else 1


if __name__ == '__main__':
    sys.exit(main())
