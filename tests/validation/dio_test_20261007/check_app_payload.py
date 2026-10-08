"""Load the new DIO ZIP through the APP's real offline import services."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.payload_archive import PayloadArchive
from pyxcp_host.services.a2l_catalog import A2LCatalogService

folder = Path(__file__).parent
build = json.loads((folder / 'matlab_validation.json').read_text(encoding='utf-8'))['build']
archive = PayloadArchive()
try:
    payload = archive.load(build['archive'])
    catalog = A2LCatalogService().load(Path(payload['a2l']))
    assert payload['model'] == 'simrt_dio_loopback'
    assert payload['protocol'] == 'UDP' and payload['port'] == 5555
    calibrations = {item.name: item.data_type for item in catalog.calibrations}
    measurements = {item.name: item.data_type for item in catalog.measurements}
    for name in ('DIO_Enable', 'DIO_Automatic', 'DIO_ManualMask', 'DIO_CheckLoopback'):
        assert any(key.endswith(name) for key in calibrations), name
    assert len(calibrations) == 4, 'Only the four documented controls should be tunable'
    for name in ('DIO_CommandMask', 'DIO_InputMask', 'DIO_Ready', 'DIO_Valid',
                 'DIO_Matched', 'DIO_MismatchSamples', 'DIO_OutputSetupStatus',
                 'DIO_InputSetupStatus', 'DIO_ReadStatus', 'DIO_WriteStatus'):
        assert any(key.endswith(name) for key in measurements), name
    report = dict(passed=True, archive=build['archive'], protocol=payload['protocol'],
                  port=payload['port'], calibrations=calibrations, measurements=measurements)
    (folder / 'app_payload.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
finally:
    archive.close()
