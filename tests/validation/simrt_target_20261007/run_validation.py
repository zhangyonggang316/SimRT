"""Repeat this migration's bounded model test with saved, in-memory credentials."""
import getpass
import json
from pathlib import Path
import sys

from check_target import ROOT, credentials, SSHDeployment

sys.path.insert(0, str(ROOT / 'tools'))
import validate_rt_update


def main():
    folder = Path(__file__).parent
    previous = json.loads((folder / 'before.json').read_text(encoding='utf-8'))
    assert len(previous['processes']) == 1
    process = previous['processes'][0]
    assert process['arguments'] == [process['elf']]
    login = credentials()
    service = SSHDeployment()
    try:
        service.connect(**login)
        current = service.status(process['elf'])
        assert current['running'] and current['pid'] == process['pid']
        assert service._request('elf', path=process['elf'])['sha256'] == process['sha256']
        assert service.autostart_status() == previous['autostart']
    finally:
        service.close()
    builds = json.loads((ROOT / 'validation/simrt_migration_20261007/matlab_builds.json').read_text(encoding='utf-8'))
    receipt = next(item for item in builds['builds'] if item['model'] == 'simrt_rt_single')
    receipt_path = folder / 'model_build.json'
    with receipt_path.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2)
    original = getpass.getpass
    try:
        getpass.getpass = lambda prompt: login['password']
        sys.argv = ['validate_rt_update', '--receipt', str(receipt_path),
                    '--previous-model', process['elf'], '--seconds', '120',
                    '--output', str(folder / 'model_validation.json')]
        validate_rt_update.main()
    finally:
        getpass.getpass = original
        login = None


if __name__ == '__main__':
    main()
