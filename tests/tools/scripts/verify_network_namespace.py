"""Verify IP apply/confirm/rollback inside a private Linux network namespace."""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.network_configuration import _NETWORK_LIBRARY, _ROLLBACK_HELPER
sys.excepthook = sys.__excepthook__

CHECK = r'''
source = json.loads(sys.argv[1])
run(['ip','link','add','simrt-test0','type','dummy'])
run(['ip','link','set','simrt-test0','up'])
run(['ip','address','add','192.0.2.2/24','dev','simrt-test0'])
request = dict(interface='simrt-test0', address='192.0.2.3', prefix=24,
               gateway='', rollback_source=source)
first = configure(request)
assert first['address'] == '192.0.2.3/24'
assert confirm(first)['confirmed']
time.sleep(0.5)
assert not (Path('/run') / ('pyxcp-network-' + first['token'])).exists()
request['address'] = '192.0.2.4'
second = configure(request)
directory = transaction_dir(second['token'])
saved = json.loads((directory/'state.json').read_text())
# The rollback subprocess captured the original deadline; use its real 45s timer.
deadline = time.monotonic() + 50
while directory.exists() and time.monotonic() < deadline:
    time.sleep(0.5)
assert not directory.exists(), 'Rollback did not complete'
addresses = ip('-4','address','show','dev','simrt-test0')[0]['addr_info']
assert [entry['local'] for entry in addresses] == ['192.0.2.3'], addresses
print(json.dumps(dict(passed=True, confirmed_address='192.0.2.3/24',
    reverted_address='192.0.2.4/24', rollback_seconds=45, namespace_only=True,
    physical_interface_changes=False)))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    password = os.environ.get('SIMRT_SSH_PASSWORD') or getpass.getpass('SSH/admin password: ')
    service = SSHDeployment()
    try:
        service.connect(args.host, 'zh', password=password)
        command = 'sudo -S -p ' + shlex.quote('') + ' -- unshare --net -- python3 -c ' + shlex.quote(_NETWORK_LIBRARY + CHECK) + ' ' + shlex.quote(json.dumps(_ROLLBACK_HELPER))
        result = service._execute(command, timeout=65, input_data=(password+'\n').encode('utf-8'))
        report = json.loads(result)
        report['helper_sha256'] = hashlib.sha256(_NETWORK_LIBRARY.encode('utf-8')).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(result)
    finally:
        service.close()


if __name__ == '__main__':
    main()
