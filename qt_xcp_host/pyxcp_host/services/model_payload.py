"""Validate a matching, deployable ELF/A2L payload before any network operation."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def validate_payload(directory):
    root = Path(directory).expanduser().absolute()
    if any(path.is_symlink() for path in [root] + list(root.parents)) or not root.is_dir():
        raise ValueError('Payload must be a regular directory without symbolic links')
    manifests = list(root.glob('*.xcp-manifest.json'))
    if len(manifests) != 1:
        raise ValueError('Select one payload containing ELF, A2L and one xcp-manifest.json')
    manifest_path = manifests[0]
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('Payload manifest must be a regular file')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    if not isinstance(manifest, dict) or manifest.get('SchemaVersion') != 2:
        raise ValueError('Unsupported payload manifest version')
    if manifest.get('XCPTransport') not in ('TCP', 'UDP') or type(manifest.get('XCPPort')) is not int or not 1 <= manifest['XCPPort'] <= 65535:
        raise ValueError('Invalid payload XCP endpoint')
    files = {}

    def check(name, expected, basename=False):
        if (not isinstance(name, str) or not name or '\\' in name or ':' in name
                or any(ord(char) < 32 for char in name)):
            raise ValueError('Invalid payload filename')
        relative = PurePosixPath(name)
        if (relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name
                or basename and len(relative.parts) != 1 or name.startswith('.pyxcp-')):
            raise ValueError('Payload paths must stay within the payload directory')
        path = root.joinpath(*relative.parts)
        if any(part.is_symlink() for part in [path] + list(path.parents)) or not path.is_file():
            raise ValueError('Missing or non-regular payload file: ' + name)
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('Invalid SHA256 for ' + name)
        if name in files or file_hash(path) != expected:
            raise ValueError('Duplicate file or payload SHA256 mismatch: ' + name)
        files[name] = expected
        return path

    elf = check(manifest.get('ELFFile'), manifest.get('ELFSHA256'), True)
    a2l = check(manifest.get('A2LFile'), manifest.get('A2LSHA256'), True)
    with elf.open('rb') as stream:
        header = stream.read(64)
    if (len(header) < 64 or header[:7] != b'\x7fELF\x02\x01\x01'
            or struct.unpack_from('<HHI', header, 16) != (2, 62, 1)):
        raise ValueError('Payload requires a fixed-address x86-64 Linux ELF64')
    runtime = manifest.get('RuntimeFiles', {})
    if not isinstance(runtime, dict):
        raise ValueError('RuntimeFiles must map relative filenames to SHA256')
    for name, expected in runtime.items():
        check(name, expected)
    if manifest_path.name in files:
        raise ValueError('Manifest cannot reference itself as an artifact')
    files[manifest_path.name] = file_hash(manifest_path)
    present = set()
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError('Payload contains a non-regular entry')
        if path.is_file():
            present.add(path.relative_to(root).as_posix())
    if present != set(files):
        raise ValueError('Payload contains files not covered by its manifest: ' + ', '.join(sorted(present - set(files))))
    return dict(directory=str(root), elf=str(elf), a2l=str(a2l), manifest=str(manifest_path),
                elf_name=elf.name, files=files, model=manifest.get('ModelName', elf.stem),
                host=manifest.get('TargetAddress', ''), protocol=manifest['XCPTransport'], port=manifest['XCPPort'])
