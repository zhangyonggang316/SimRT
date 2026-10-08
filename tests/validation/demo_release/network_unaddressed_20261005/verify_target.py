"""Verify first IPv4 assignment in an isolated target network namespace."""
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
with tempfile.TemporaryDirectory(prefix='simrt-first-ipv4-') as temporary:
    sandbox = real_path(temporary)
    folder = sandbox / 'etc/netplan'
    folder.mkdir(parents=True)
    config = folder / '90-test.yaml'
    original = b'network:\n  version: 2\n  renderer: networkd\n  ethernets:\n    enp1s0:\n      match:\n        macaddress: "02:00:00:00:00:01"\n      set-name: enp1s0\n      dhcp4: false\n'
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
    def create_interface():
        config.write_bytes(original)
        config.chmod(0o600)
        run(['ip', 'link', 'add', 'enp1s0', 'type', 'veth', 'peer', 'name', 'simrt-peer'])
        run(['ip', 'link', 'set', 'dev', 'enp1s0', 'address', '02:00:00:00:00:01'])

    request = dict(interface='enp1s0', address='192.168.7.1', prefix=24,
                   gateway='', persistent=True, rollback_source=rollback_source)
    scenarios = []
    for name in ('admin_down_no_address', 'no_carrier_no_address', 'ipv6_only'):
        create_interface()
        if name != 'admin_down_no_address':
            run(['ip', 'link', 'set', 'dev', 'enp1s0', 'up'])
        if name == 'ipv6_only':
            run(['ip', 'link', 'set', 'dev', 'simrt-peer', 'up'])
            run(['ip', '-6', 'address', 'add', '2001:db8::2/64', 'dev', 'enp1s0', 'nodad'])
        before = ip('address', 'show', 'dev', 'enp1s0')
        assert len(before) == 1
        assert ip('-4', 'address', 'show', 'dev', 'enp1s0') == []
        ipv6_before = ip('-6', 'address', 'show', 'dev', 'enp1s0')
        transaction = configure(request)
        result = confirm(transaction)
        assert result['confirmed'] and result['persistent']
        assert any(a['local'] == '192.168.7.1' for a in ip('-4', 'address', 'show', 'dev', 'enp1s0')[0]['addr_info'])
        assert not ip('-4', 'route', 'show', 'default', 'dev', 'enp1s0')
        if name == 'ipv6_only':
            assert any(a['local'] == '2001:db8::2' for a in ip('-6', 'address', 'show', 'dev', 'enp1s0')[0]['addr_info'])
            assert ip('-6', 'address', 'show', 'dev', 'enp1s0') == ipv6_before
        # A new generator must be able to recover the saved address after restart.
        run(['netplan', 'generate'])
        generated = list((sandbox / 'run/systemd/network').glob('*.network'))
        assert len(generated) == 1
        parser = configparser.ConfigParser(strict=False)
        parser.read(generated[0])
        assert parser['Network']['Address'] == '192.168.7.1/24'
        time.sleep(0.5)
        assert not (real_path('/run') / ('pyxcp-network-' + transaction['token'])).exists()
        scenarios.append(dict(name=name, passed=True, old_ipv4_query_empty=True,
                              initial_state=before[0]['operstate'], saved_address='192.168.7.1/24'))
        run(['ip', 'link', 'del', 'dev', 'enp1s0'])

    create_interface()
    pending = configure(request)
    directory = transaction_dir(pending['token'])
    saved = json.loads((directory / 'state.json').read_text())
    assert not saved['up'] and saved['addresses'] == []
    persist_netplan(saved, directory)
    deadline = time.monotonic() + 50
    while directory.exists() and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not directory.exists(), 'Automatic rollback failed'
    assert config.read_bytes() == original
    after = ip('address', 'show', 'dev', 'enp1s0')[0]
    assert 'UP' not in after['flags']
    assert not any(a['family'] == 'inet' for a in after.get('addr_info', []))
    print(json.dumps(dict(passed=True, scenarios=scenarios, rollback_to_down_without_ipv4=True,
                         rollback_seconds=45, namespace_only=True, physical_interface_changes=False)))
"""


if __name__ == '__main__':
    password = getpass.getpass('SSH/admin password: ')
    service = SSHDeployment()
    try:
        service.connect('192.168.193.195', 'zh', password=password)
        physical = dict(
            complete=json.loads(service._execute('ip -j address show dev enp1s0')),
            ipv4_only=json.loads(service._execute('ip -j -4 address show dev enp1s0')))
        command = 'sudo -S -p ' + shlex.quote('') + ' -- unshare --net -- python3 -c '
        command += shlex.quote(_NETWORK_LIBRARY + CHECK) + ' ' + shlex.quote(json.dumps(_NETWORK_LIBRARY))
        result = json.loads(service._execute(command, timeout=90, input_data=(password + '\n').encode()))
        result['physical_read_only_probe'] = physical
        result['helper_sha256'] = hashlib.sha256(_NETWORK_LIBRARY.encode()).hexdigest()
        Path(__file__).with_name('target_result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        service.close()
