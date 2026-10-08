"""Validate current deployment ZIPs through the application's real loaders."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.a2l_catalog import A2LCatalogService
from pyxcp_host.services.model_payload import file_hash
from pyxcp_host.services.payload_archive import PayloadArchive


def main():
    reports = []
    nm = ROOT / 'portable-linux-toolchain/portable-linux-toolchain/toolchain/bin/linux-nm.exe'
    readelf = nm.with_name('linux-readelf.exe')
    for label in ('main', 'can', 'canfd'):
        receipt = OUTPUT / (label + '_telemetry_build.json')
        record = json.loads(receipt.read_text(encoding='utf-8-sig'))
        archive = Path(record['archive'])
        assert record['success'] and record['remote_operations_performed'] is False
        assert record['period_seconds'] == 0.001
        assert file_hash(archive) == record['archive_sha256']
        assert not archive.with_suffix('').exists()
        assert not (archive.parent.parent / (record['model'] + '.elf')).exists()
        with closing(PayloadArchive()) as loader:
            payload = loader.load(archive)
            extracted = Path(payload['directory'])
            assert payload['host'] == '192.168.219.195'
            assert payload['protocol'] == 'UDP' and payload['port'] == 17725
            assert payload['model'] == record['model']
            assert file_hash(payload['elf']) == record['elf_sha256']
            catalog = A2LCatalogService().load(Path(payload['a2l']))
            assert catalog.declared_hosts['UDP'] == payload['host']
            assert catalog.declared_ports['UDP'] == payload['port']
            assert catalog.measurements and catalog.calibrations
            symbols_output = subprocess.check_output(
                [str(nm), '--defined-only', '--print-size', '--format=posix', payload['elf']], text=True)
            symbols = {}
            for line in symbols_output.splitlines():
                fields = line.split()
                if len(fields) == 4 and fields[1] in 'BbDdRr':
                    symbols[fields[0]] = (int(fields[2], 16), int(fields[3], 16))
            checked = []
            for scalar in (*catalog.measurements, *catalog.calibrations):
                assert any(address <= scalar.address and scalar.address + scalar.size <= address + size
                           for address, size in symbols.values()), scalar
                if scalar.name in symbols:
                    assert symbols[scalar.name][0] == scalar.address, scalar
                    checked.append(scalar.name)
            inspection = subprocess.check_output([str(readelf), '-h', '-l', '-d', '-V', payload['elf']], text=True)
            (OUTPUT / (label + '_elf_inspection.txt')).write_text(inspection)
            with zipfile.ZipFile(archive) as bundle:
                files = [entry.filename for entry in bundle.infolist() if not entry.is_dir()]
            assert len(files) == 3
            reports.append(dict(model=record['model'], archive=str(archive), archive_sha256=file_hash(archive),
                                elf_sha256=file_hash(payload['elf']), files=files,
                                measurements=len(catalog.measurements), calibrations=len(catalog.calibrations),
                                scalar_addresses_within_elf_symbols=True, exact_named_symbols_checked=checked,
                                host=payload['host'], protocol=payload['protocol'], port=payload['port'],
                                runtime_sha256=record['runtime_sha256']))
        assert not extracted.exists()
    report = dict(passed=True, remote_operations_performed=False, models=reports)
    (OUTPUT / 'artifact_validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
