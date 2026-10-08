"""Package ignored runtime/tool distributions for a matching GitHub Release."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = {
    'app-win64': ['app/distribution'],
    'linux-toolchain': ['toolchain/portable-linux-toolchain'],
    'qt-toolchain': ['toolchain/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64'],
    'development-optional': ['toolchain/development'],
}
EXCLUDED = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', 'node_modules', '.venv'}


def digest(stream):
    value = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        value.update(block)
    return value.hexdigest()


def package(component, paths, output, version):
    destination = output / f'SimRT-{component}-{version}.zip'
    entries = []
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative in paths:
            source = ROOT / relative
            if not source.is_dir():
                raise FileNotFoundError(source)
            for file in sorted(source.rglob('*')):
                parts = file.relative_to(ROOT).parts
                if any(part in EXCLUDED for part in parts) or file.suffix == '.pyc':
                    continue
                if file.is_symlink():
                    raise ValueError(f'Release assets must not contain symbolic links: {file}')
                if not file.is_file():
                    continue
                name = file.relative_to(ROOT).as_posix()
                before = file.stat()
                with file.open('rb') as stream:
                    value = digest(stream)
                archive.write(file, name)
                after = file.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError(f'File changed while packaging: {name}')
                entries.append({'path': name, 'bytes': after.st_size, 'sha256': value})
        archive.writestr(f'.simrt-release-manifests/{component}.json',
                         json.dumps({'component': component, 'version': version,
                                     'files': entries}, indent=2))
    with zipfile.ZipFile(destination) as archive:
        for item in entries:
            with archive.open(item['path']) as stream:
                if digest(stream) != item['sha256']:
                    raise RuntimeError(f'Archive verification failed: {item["path"]}')
    with destination.open('rb') as stream:
        value = digest(stream)
    record = {'asset': destination.name, 'bytes': destination.stat().st_size,
              'sha256': value, 'files': len(entries), 'roots': paths}
    print(json.dumps(record), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.version):
        parser.error('Version must be a filename-safe identifier.')
    output = ROOT / '.release' / args.version
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for component, paths in COMPONENTS.items():
        print(f'Packaging and verifying {component}...', flush=True)
        records.append(package(component, paths, output, args.version))
    (output / 'assets.json').write_text(json.dumps({'version': args.version,
        'extraction_root': 'repository root', 'assets': records}, indent=2) + '\n', encoding='utf-8')
    (output / 'SHA256SUMS.txt').write_text(''.join(
        f'{item["sha256"]}  {item["asset"]}\n' for item in records), encoding='ascii')


if __name__ == '__main__':
    main()
