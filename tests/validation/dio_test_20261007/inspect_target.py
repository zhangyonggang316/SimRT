"""Read the ARK GPIO inventory without requesting or writing GPIO lines."""
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
sys.path.insert(0, str(ROOT / 'tools'))
from qt_host.credential_store import CredentialStore
from pyxcp_host.services.ssh_deployment import SSHDeployment
from inspect_ark_resources import AUDIT


def main():
    login = CredentialStore().load()
    preset = json.loads((ROOT / 'Demo_XCP_Qt/demo.json').read_text(encoding='utf-8'))
    if not login or login['host'] != preset['host'] or login['username'] != preset['username']:
        raise RuntimeError('Saved APP credentials do not match the selected ARK')
    service = SSHDeployment()
    try:
        service.connect(**login)
        report = json.loads(service._execute('python3 -c ' + shlex.quote(AUDIT), timeout=120))
        destination = Path(__file__).with_name('target_inventory.json')
        destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({key: report[key] for key in
                         ('hostname', 'kernel', 'gpio_nodes', 'gpio_devices',
                          'library_cache', 'vendor_paths')}, indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
