"""Validated, relocatable manual demo presets. Loading never connects to a target."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Optional
import uuid

from .services.payload_archive import PayloadArchive


@dataclass(frozen=True)
class DemoSettings:
    host: str
    username: str
    a2l_path: Optional[Path]
    payload_dir: Optional[Path]
    elf_name: str
    remote_dir: str
    payload_archive: Optional[Path] = None


def _local_file(root, relative, required=True):
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError('Demo file path is missing')
    candidate = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Demo paths must stay inside the demo directory')
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError('Demo paths must stay inside the demo directory') from None
    if required and not resolved.is_file():
        raise ValueError('Demo file does not exist: ' + relative)
    return resolved


def load_demo(directory):
    root = Path(directory).resolve()
    config = json.loads(_local_file(root, 'demo.json').read_text(encoding='utf-8-sig'))
    if config.get('version') != 1:
        raise ValueError('Unsupported demo configuration version')
    host = config.get('host', '').strip()
    username = config.get('username', '').strip()
    if not host or not username:
        raise ValueError('Demo host and username are required')
    remote = 'MATLAB_ws/manual_demo_{}_{}'.format(datetime.now().strftime('%Y%m%d_%H%M%S'), uuid.uuid4().hex[:8])
    archive = config.get('archive')
    manifest_file = None
    if archive:
        archive_file = _local_file(root, archive)
    else:
        manifest_file = _local_file(root, config.get('manifest'), required=False)
        archive_file = manifest_file.parent.with_suffix('.zip')
    if archive or not manifest_file.is_file():
        archive_file = _local_file(root, str(archive_file.relative_to(root)))
        loader = PayloadArchive()
        try:
            selected = loader.load(archive_file)
            if manifest_file is not None and Path(selected['manifest']).name != manifest_file.name:
                raise ValueError('Demo ZIP does not contain the selected manifest')
            return DemoSettings(host, username, None, None, selected['elf_name'], remote, archive_file)
        finally:
            loader.close()
    manifest = json.loads(manifest_file.read_text(encoding='utf-8-sig'))
    if (manifest.get('XCPTransport') not in ('UDP', 'TCP')
            or type(manifest.get('XCPPort')) is not int
            or not 1 <= manifest['XCPPort'] <= 65535):
        raise ValueError('Demo requires a valid TCP or UDP XCP endpoint')
    payload = manifest_file.parent
    for field in ('ELFFile', 'A2LFile'):
        name = manifest.get(field)
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError('Manifest artifact names must be basenames')
    elf = _local_file(payload, manifest['ELFFile'])
    a2l = _local_file(payload, manifest['A2LFile'])
    header = elf.read_bytes()[:20]
    if (len(header) < 20 or header[:6] != b'\x7fELF\x02\x01'
            or int.from_bytes(header[16:18], 'little') != 2
            or int.from_bytes(header[18:20], 'little') != 62):
        raise ValueError('Demo requires a fixed-address x86-64 Linux ELF')
    for artifact, field in ((elf, 'ELFSHA256'), (a2l, 'A2LSHA256')):
        if hashlib.sha256(artifact.read_bytes()).hexdigest() != manifest.get(field):
            raise ValueError('Demo ELF/A2L SHA256 mismatch: ' + artifact.name)
    return DemoSettings(host, username, a2l, payload, elf.name, remote)
