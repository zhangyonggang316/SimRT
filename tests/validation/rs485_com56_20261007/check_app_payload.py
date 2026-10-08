"""Validate the bench ZIP with the APP's production offline import services."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qt_xcp_host"))
from pyxcp_host.services.payload_archive import PayloadArchive
from pyxcp_host.services.a2l_catalog import A2LCatalogService

folder = Path(__file__).parent
build = json.loads((folder / "matlab_validation.json").read_text(encoding="utf-8"))["build"]
archive = PayloadArchive()
try:
    payload = archive.load(build["archive"])
    catalog = A2LCatalogService().load(Path(payload["a2l"]))
    assert payload["model"] == "simrt_serial_com56"
    assert payload["protocol"] == "UDP" and payload["port"] == 5555
    calibrations = {item.name: item.data_type for item in catalog.calibrations}
    measurements = {item.name: item.data_type for item in catalog.measurements}
    assert any(name.endswith("Serial_Enable") for name in calibrations)
    expected = ["Serial_Ready", "Serial_Healthy"]
    for port in (5, 6):
        expected.extend(f"COM{port}_{suffix}" for suffix in (
            "TxFrames", "TxFailures", "RxFrames", "CrcErrors", "SequenceGaps", "Duplicates",
            "ForeignFrames", "LastSequence", "RxAgeMs", "FormatErrors", "SetupStatus", "ReadStatus", "WriteStatus"))
    for name in expected:
        assert any(key.endswith(name) for key in measurements), name
    report = dict(passed=True, archive=build["archive"], protocol=payload["protocol"], port=payload["port"],
                  calibrations=calibrations, measurements=measurements)
    (folder / "app_payload.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
finally:
    archive.close()
