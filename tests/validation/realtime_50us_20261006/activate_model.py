"""Activate the 50 us qualified model while preserving the failed UDP loss verdict."""
import getpass
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__

folder = Path(__file__).parent
report = json.loads((folder / 'model_validation.json').read_text(encoding='utf-8'))
model = report['model']
assert model['model_passed'] and not model.get('error') and not model['cleanup_errors']
assert all(value for name, value in report['checks'].items() if name != 'workflow')
failures = [name for name, value in model['daq_checks'].items() if not value]
assert set(failures) == {'no_transport_counter_gaps', 'no_timestamp_gap_samples'}
output = folder / 'activation.json'
assert not output.exists()
service = SSHDeployment()
try:
    service.connect('192.168.193.195', 'zh', password=getpass.getpass('SSH password: '))
    before = service.status(report['previous']['elf_path'])
    assert service.autostart_status() == report['autostart_before']
    with service._client.open_sftp() as sftp:
        import hashlib
        with sftp.open(model['remote_elf'], 'rb') as stream:
            actual_hash = hashlib.sha256(stream.read()).hexdigest()
    assert actual_hash == report['deployment']['files']['simrt_rt_single.elf']
    if before['running']:
        service.stop()
    try:
        service.start(model['remote_elf'])
        result = dict(running=service.status(), timing_50us_passed=True, daq_lossless_passed=False,
            unresolved_daq_checks=failures, source_report='model_validation.json',
            elf_sha256=actual_hash, autostart=service.autostart_status())
        output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    except BaseException:
        if service.status()['running']:
            service.stop()
        if before['running']:
            service.start(before['elf_path'])
        raise
    snapshot = service._execute('python3 ' + shlex.quote('/home/zh/.local/lib/simrt-console/simrt_console.py')
        + ' --once --width 120 --height 33')
    (folder / 'console' / 'new_model_snapshot.txt').write_text(snapshot, encoding='utf-8')
finally:
    service.close()
