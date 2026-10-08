import json
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'qt_xcp_host'), str(root / 'simrt_linux_target/python')]
from pyxcp_host.services import A2LCatalogService
from pyxcp_host.services.model_payload import file_hash
from pyxcp_host.services.payload_archive import PayloadArchive

output = Path(__file__).resolve().parent
receipt = root / 'Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single_ert_rtw/simrt_local_build.json'
build = json.loads(receipt.read_text(encoding='utf-8'))
assert build['success'] and not build['remote_operations_performed']
assert file_hash(Path(build['archive'])) == build['archive_sha256']
loader = PayloadArchive()
try:
    payload = loader.load(build['archive'])
    catalog = A2LCatalogService().load(Path(payload['a2l']))
    assert payload['protocol'] == 'UDP' and payload['port'] == 55555
    assert catalog.declared_ports == {'UDP': 55555}
    assert catalog.declared_hosts == {'UDP': '192.168.193.195'}
    assert file_hash(payload['elf']) == build['elf_sha256']
    record = dict(passed=True, protocol=payload['protocol'], port=payload['port'],
                  a2l_ports=catalog.declared_ports, a2l_hosts=catalog.declared_hosts,
                  archive=build['archive'], archive_sha256=build['archive_sha256'],
                  elf_sha256=build['elf_sha256'])
    (output / 'artifact_check.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    shutil.copyfile(receipt, output / 'model_build.json')
    print(json.dumps(record, indent=2))
finally:
    loader.close()
