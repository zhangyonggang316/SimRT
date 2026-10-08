import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'qt_xcp_host'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.network_configuration import _NETWORK_LIBRARY

CHECK = r"""
import configparser
library = json.loads(sys.argv[1])
real_path = Path
with tempfile.TemporaryDirectory(prefix='simrt-netplan-test-') as temporary:
    sandbox = real_path(temporary)
    folder = sandbox / 'etc/netplan'
    folder.mkdir(parents=True)
    config = folder / '90-test.yaml'
    original = b'network:\n  version: 2\n  renderer: networkd\n  ethernets:\n    simrt-test0:\n      dhcp4: false\n      addresses: [192.0.2.2/24]\n'
    config.write_bytes(original)
    config.chmod(0o600)
    def mapped_path(value):
        if value in ('/etc/netplan', '/lib/netplan', '/run/netplan'):
            return sandbox / value.lstrip('/')
        return real_path(value)
    Path = mapped_path
    base_run = run
    def run(args, required=True):
        if args[:2] == ['netplan', 'generate']:
            args = args + ['--root-dir', str(sandbox)]
        return base_run(args, required)
    rollback_source = library + '\nbase_run = run\nsandbox = ' + repr(str(sandbox)) + r'''
def run(args, required=True):
    if args[:2] == ['netplan', 'generate']:
        args = args + ['--root-dir', sandbox]
    return base_run(args, required)
rollback(sys.argv[1])
'''
    run(['ip', 'link', 'add', 'simrt-test0', 'type', 'dummy'])
    run(['ip', 'link', 'set', 'simrt-test0', 'up'])
    run(['ip', 'address', 'add', '192.0.2.2/24', 'dev', 'simrt-test0'])
    request = dict(interface='simrt-test0', address='192.0.2.3', prefix=24,
                   gateway='', persistent=True, rollback_source=rollback_source)
    first = configure(request)
    result = confirm(first)
    assert result['confirmed'] and result['persistent']
    generated = list((sandbox / 'run/systemd/network').glob('*.network'))
    assert len(generated) == 1
    parser = configparser.ConfigParser(strict=False)
    parser.read(generated[0])
    assert parser['Network']['Address'] == '192.0.2.3/24'
    assert 'DHCP' not in parser['Network'] or parser['Network']['DHCP'] in ('no', 'false')
    # A fresh generator process reads the saved files, as at the next boot.
    run(['netplan', 'generate'])
    assert '192.0.2.3/24' in generated[0].read_text()
    time.sleep(0.5)
    assert not (real_path('/run') / ('pyxcp-network-' + first['token'])).exists()
    saved_config = config.read_bytes()
    request['address'] = '192.0.2.4'
    second = configure(request)
    directory = transaction_dir(second['token'])
    saved = json.loads((directory / 'state.json').read_text())
    # Simulate losing confirmation after files were written, using the real timer.
    persist_netplan(saved, directory)
    assert config.read_bytes() != saved_config
    deadline = time.monotonic() + 50
    while directory.exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not directory.exists(), 'Persistent rollback failed'
    assert config.read_bytes() == saved_config
    addresses = ip('-4', 'address', 'show', 'dev', 'simrt-test0')[0]['addr_info']
    assert [entry['local'] for entry in addresses] == ['192.0.2.3']
    print(json.dumps(dict(passed=True, online_apply=True, netplan_saved=True,
                         fresh_generator_reads_saved_ip=True,
                         persistent_and_runtime_rollback=True, rollback_seconds=45,
                         namespace_only=True, physical_interface_changes=False,
                         physical_reboot=False)))
"""

password = getpass.getpass('SSH/admin password: ')
service = SSHDeployment()
try:
    service.connect('192.168.193.195', 'zh', password=password)
    command = 'sudo -S -p ' + shlex.quote('') + ' -- unshare --net -- python3 -c '
    command += shlex.quote(_NETWORK_LIBRARY + CHECK) + ' ' + shlex.quote(json.dumps(_NETWORK_LIBRARY))
    result = json.loads(service._execute(command, timeout=90, input_data=(password + '\n').encode()))
    result['helper_sha256'] = hashlib.sha256(_NETWORK_LIBRARY.encode()).hexdigest()
    Path(__file__).with_name('network_persistence_target.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
finally:
    service.close()
