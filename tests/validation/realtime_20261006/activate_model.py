"""Activate the model whose timing passed; retain the failed Wi-Fi DAQ verdict."""
import getpass
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook=sys.__excepthook__

report=json.loads((Path(__file__).parent/'model_validation_pool1024.json').read_text())
model=report['model']
assert all(model['model_checks'].values()) and not model['cleanup_errors']
assert all(value for name,value in report['checks'].items() if name!='workflow')
failures=[name for name,value in model['daq_checks'].items() if not value]
assert set(failures)=={'no_transport_counter_gaps','no_timestamp_gap_samples'}
output=Path(__file__).parent/'activation.json'
assert not output.exists()
service=SSHDeployment()
try:
    service.connect('192.168.193.195','zh',password=getpass.getpass('SSH password: '))
    before=service.status(report['previous']['elf_path'])
    if before['running']: service.stop()
    try:
        service.start(model['remote_elf'])
        result=dict(running=service.status(),timing_passed=True,daq_lossless_passed=False,
                    unresolved_daq_checks=failures,source_report='model_validation_pool1024.json',
                    autostart=service.autostart_status())
        output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2))
    except BaseException:
        if service.status()['running']: service.stop()
        if before['running']: service.start(before['elf_path'])
        raise
finally: service.close()
