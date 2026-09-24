"""Verify the generated nested-model ZIP through the APP's public loader."""

import json
from pathlib import Path
import sys


EVIDENCE = Path(__file__).resolve().parent
PROJECT = EVIDENCE.parents[1]
sys.path[:0] = [str(PROJECT / 'qt_xcp_host'), str(PROJECT / 'x280_linux_target' / 'python')]

from pyxcp_host.services.a2l_catalog import A2LCatalogService
from pyxcp_host.services.payload_archive import PayloadArchive


def main():
    matlab = json.loads((EVIDENCE / 'nested_hierarchy_matlab.json').read_text(encoding='utf-8'))
    loader = PayloadArchive()
    try:
        payload = loader.load(Path(matlab['archive']))
        info = A2LCatalogService().load(payload['a2l'])
        measurement = next(item for item in info.measurements if item.name == matlab['measurement'])
        calibration = next(item for item in info.calibrations if item.name == matlab['calibration'])
        expected = tuple(matlab['expected_path'])
        assert measurement.model_path == calibration.model_path == expected
        assert info.declared_transports == ('UDP',)
        assert info.declared_ports == {'UDP': 17725}
        assert info.declared_hosts == {'UDP': '192.168.219.86'}
        files = sorted(path.name for path in Path(payload['directory']).iterdir())
        assert files == ['x280_hierarchy_test.a2l', 'x280_hierarchy_test.elf',
                         'x280_hierarchy_test.xcp-manifest.json']
        assert not Path(matlab['archive']).with_suffix('').exists()
        report = dict(passed=True, archive=matlab['archive'], files=files,
                      measurements=len(info.measurements), calibrations=len(info.calibrations),
                      measurement=dict(name=measurement.name, model_path=measurement.model_path),
                      calibration=dict(name=calibration.name, model_path=calibration.model_path),
                      transport=info.declared_transports, ports=info.declared_ports,
                      hosts=info.declared_hosts)
        (EVIDENCE / 'nested_hierarchy_python.json').write_text(
            json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
    finally:
        loader.close()


if __name__ == '__main__':
    main()
