"""Validate the reconnect build through the APP's real archive and A2L loaders."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "qt_xcp_host"))
from pyxcp_host.services.a2l_catalog import A2LCatalogService
from pyxcp_host.services.model_payload import file_hash
from pyxcp_host.services.payload_archive import PayloadArchive

record = json.loads((OUTPUT / "main_build.json").read_text(encoding="utf-8-sig"))
archive = Path(record["archive"])
assert record["success"] and not record["remote_operations_performed"]
assert record["period_seconds"] == 0.001
assert file_hash(archive) == record["archive_sha256"]
bundle = Path(record["realtime_source"])
spec = json.loads((bundle / "build_spec.json").read_text())
for source in ("simrt_rtiostream_udp.c", "simrt_xcp_status.c"):
    assert source in spec["sources"]
    assert file_hash(bundle / "src" / source) == file_hash(ROOT / "simrt_linux_target/src" / source)
assert "rtiostream_tcpip.c" not in spec["sources"]
vendor = Path("C:/Program Files/MATLAB/R2024b/toolbox/coder/rtiostream/src/rtiostreamtcpip/rtiostream_tcpip.c")
assert file_hash(bundle / "src/rtiostream_tcpip.c") == file_hash(vendor)
bin_dir = ROOT / "portable-linux-toolchain/portable-linux-toolchain/toolchain/bin"
with closing(PayloadArchive()) as loader:
    payload = loader.load(archive)
    extracted = Path(payload["directory"])
    assert (payload["host"], payload["protocol"], payload["port"]) == ("192.168.219.195", "UDP", 17725)
    assert file_hash(payload["elf"]) == record["elf_sha256"]
    catalog = A2LCatalogService().load(Path(payload["a2l"]))
    assert catalog.measurements and catalog.calibrations
    symbols_text = subprocess.check_output(
        [str(bin_dir / "linux-nm.exe"), "--defined-only", "--print-size", "--format=posix", payload["elf"]], text=True)
    symbols = {}
    for line in symbols_text.splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[1] in "BbDdRr":
            symbols[fields[0]] = (int(fields[2], 16), int(fields[3], 16))
    for scalar in (*catalog.measurements, *catalog.calibrations):
        assert any(address <= scalar.address and scalar.address + scalar.size <= address + size
                   for address, size in symbols.values()), scalar
        if scalar.name in symbols:
            assert symbols[scalar.name][0] == scalar.address, scalar
    assert "simrt_vendor_rtIOStreamSend" in symbols_text
    assert "simrt_xcp_is_disconnected" in symbols_text
    inspection = subprocess.check_output(
        [str(bin_dir / "linux-readelf.exe"), "-h", "-l", "-d", "-V", payload["elf"]], text=True)
    assert "EXEC (Executable file)" in inspection
    (OUTPUT / "main_elf_inspection.txt").write_text(inspection)
    with zipfile.ZipFile(archive) as package:
        files = [entry.filename for entry in package.infolist() if not entry.is_dir()]
    assert len(files) == 3
assert not extracted.exists()
report = dict(passed=True, archive=str(archive), archive_sha256=file_hash(archive),
              elf_sha256=record["elf_sha256"], files=files,
              scalar_addresses_within_elf_symbols=True, vendor_source_unchanged=True,
              measurements=len(catalog.measurements), calibrations=len(catalog.calibrations),
              udp_reconnect_adapter_linked=True, period_ns=1000000,
              host="192.168.219.195", protocol="UDP", port=17725,
              remote_operations_performed=False)
(OUTPUT / "artifact_validation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
