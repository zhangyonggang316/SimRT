"""Check the newly built package through the production APP parsers, offline."""

import json
import os
from pathlib import Path
import sys


FOLDER = Path(__file__).resolve().parent
ROOT = FOLDER.parents[1]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
sys.path.insert(0, str(ROOT / 'simrt_linux_target' / 'tools'))

from build_model import digest, validate_bundle
from pyxcp_host.services.a2l_catalog import A2LCatalogService
from pyxcp_host.services.payload_archive import PayloadArchive


def main():
    validation = json.loads((FOLDER / 'matlab_validation.json').read_text(encoding='utf-8'))
    build = validation['build']
    assert validation['tests_passed'] and validation['rejected_before_generated_c']
    assert digest(build['archive']) == build['archive_sha256']
    source = str(Path(build['realtime_source']).resolve())
    # The isolated evidence directory can exceed the Windows legacy path limit.
    if os.name == 'nt':
        source = '\\\\?\\' + source
    spec, files, fingerprint = validate_bundle(source)
    archive = PayloadArchive()
    try:
        payload = archive.load(build['archive'])
        assert digest(payload['elf']) == build['elf_sha256']
        catalog = A2LCatalogService().load(Path(payload['a2l']))
        assert catalog.declared_ports['UDP'] == 5555
        assert catalog.declared_hosts['UDP'] == '192.168.193.195'
        report = dict(
            archive_valid=True, elf_hash_matches=True,
            build_spec_valid=True, source_files=len(files), source_fingerprint=fingerprint,
            daq_reserved_blocks=spec['runtime']['daq_reserved_blocks'],
            xcp_reserved_pool_bytes=spec['runtime']['xcp_reserved_pool_bytes'],
            measurements=len(catalog.measurements), calibrations=len(catalog.calibrations),
            transports=catalog.declared_transports, ports=catalog.declared_ports,
            hosts=catalog.declared_hosts, remote_operations=False,
        )
        (FOLDER / 'artifact_validation.json').write_text(
            json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        archive.close()


if __name__ == '__main__':
    main()
