import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

from pyxcp_host.services.network_configuration import (
    NetworkConfiguration, _NETWORK_HELPER, _NETWORK_LIBRARY, _ROLLBACK_HELPER, validate_ipv4,
)
from pyxcp_host.services.ssh_deployment import SSHDeployment
from test_ssh_deployment import FakeChannel, FakeClient


class NetworkValidationTests(unittest.TestCase):
    def test_mask_and_prefix_produce_same_normalized_settings(self):
        expected = dict(interface='enp1s0', address='192.0.2.3', prefix=24, gateway='192.0.2.1')
        for mask in ('24', '255.255.255.0'):
            self.assertEqual(validate_ipv4('enp1s0', '192.0.2.3', mask, '192.0.2.1'), expected)

    def test_unsafe_interfaces_and_invalid_ip_settings_are_rejected(self):
        for interface in ('lo', '-all', 'eth0;id', 'eth0\n', '$(id)', '../eth0', 'x' * 16):
            with self.subTest(interface=interface), self.assertRaises(ValueError):
                validate_ipv4(interface, '192.0.2.3', '24')
        for address, mask, gateway in (
            ('192.0.2.256', '24', ''), ('::1', '24', ''), ('0.0.0.0', '24', ''),
            ('127.0.0.2', '24', ''), ('239.1.1.1', '24', ''), ('192.0.2.0', '24', ''),
            ('192.0.2.255', '24', ''), ('192.0.2.3', '0', ''), ('192.0.2.3', '33', ''),
            ('192.0.2.3', '255.0.255.0', ''), ('192.0.2.3', '0.0.0.255', ''),
            ('192.0.2.3', '24', '198.51.100.1'), ('192.0.2.3', '24', '192.0.2.3'),
            ('192.0.2.3', '24', '192.0.2.0'), ('192.0.2.3', '24', '$(id)'),
        ):
            with self.subTest(address=address, mask=mask, gateway=gateway), self.assertRaises(ValueError):
                validate_ipv4('eth0', address, mask, gateway)

    def test_point_to_point_and_host_prefixes_are_supported(self):
        self.assertEqual(validate_ipv4('eth0', '192.0.2.0', '31', '192.0.2.1')['prefix'], 31)
        self.assertEqual(validate_ipv4('eth0', '192.0.2.4', '32')['prefix'], 32)


class NetworkTransportTests(unittest.TestCase):
    def setUp(self):
        self.deployment = SSHDeployment()
        self.deployment._begin = Mock()
        self.deployment._execute = Mock()
        self.service = NetworkConfiguration(self.deployment)

    def test_password_is_only_channel_input_and_success_requires_second_command(self):
        self.deployment._execute.side_effect = ['{"interfaces":[],"server_address":"192.0.2.8"}', json.dumps(dict(token='a' * 32,
            address='192.0.2.3/24', interface='eth0', persistent=False)), '{"confirmed":true,"persistent":true}']
        secret = 'private $literal\' password'
        self.assertTrue(self.service.configure('eth0', '192.0.2.3', '24', password=secret)['confirmed'])
        self.assertEqual(self.deployment._execute.call_count, 3)
        for call in self.deployment._execute.call_args_list[1:]:
            command = call.args[0]
            self.assertNotIn(secret, command)
            self.assertEqual(call.kwargs['input_data'], (secret + '\n').encode())
            words = shlex.split(command)
            self.assertEqual(words[:7], ['sudo', '-S', '-p', '', '--', 'python3', '-c'])
            self.assertEqual(words[7], _NETWORK_HELPER)
            self.assertIsInstance(json.loads(words[8]), dict)

    def test_privilege_failure_and_confirmation_loss_never_report_success(self):
        for failure in (RuntimeError('sudo: a password is required'), TimeoutError('SSH lost')):
            self.deployment._execute.side_effect = failure
            with self.assertRaisesRegex(RuntimeError, 'unconfirmed.*'):
                self.service.configure('eth0', '192.0.2.3', '24')
        self.deployment._execute.side_effect = ['{"interfaces":[]}', json.dumps(dict(token='a' * 32, address='192.0.2.3/24')), '{}']
        with self.assertRaisesRegex(RuntimeError, 'did not confirm'):
            self.service.configure('eth0', '192.0.2.3', '24')

    def test_password_is_redacted_from_errors(self):
        self.deployment._execute.side_effect = RuntimeError('sudo failure secret-password')
        with self.assertRaises(RuntimeError) as failure:
            self.service.configure('eth0', '192.0.2.3', '24', password='secret-password')
        self.assertNotIn('secret-password', str(failure.exception))

    def test_invalid_values_never_reach_ssh(self):
        with self.assertRaises(ValueError):
            self.service.configure('eth0;id', '192.0.2.3', '24')
        self.deployment._execute.assert_not_called()
        self.deployment._execute.return_value = '{"interfaces":[]}'
        with self.assertRaisesRegex(RuntimeError, 'control character'):
            self.service.configure('eth0', '192.0.2.3', '24', password='a\nb')
        self.assertEqual(self.deployment._execute.call_count, 1)

    def test_inventory_requires_no_privileges(self):
        self.deployment._execute.return_value = '{"interfaces":[]}'
        self.assertEqual(self.service.interfaces(), dict(interfaces=[]))
        self.assertEqual(shlex.split(self.deployment._execute.call_args.args[0])[:2], ['python3', '-c'])

    def test_ssh_sends_password_without_logging_or_command_interpolation(self):
        channel = FakeChannel([b'{}'])
        channel.sendall = Mock()
        logger = Mock()
        deployment = SSHDeployment(logger)
        deployment._client = FakeClient(channel)
        self.assertEqual(deployment._execute('sudo-command', input_data=b'secret\n'), '{}')
        channel.sendall.assert_called_once_with(b'secret\n')
        self.assertEqual(channel.commands, ['sudo-command'])
        logger.assert_not_called()


class NetworkHelperTests(unittest.TestCase):
    def setUp(self):
        self.helper = {'__name__': 'network_tests'}
        with patch.dict(sys.modules, fcntl=types.SimpleNamespace(flock=Mock(), LOCK_EX=2)):
            exec(compile(_NETWORK_LIBRARY, '<network>', 'exec'), self.helper)
        self.calls = []
        self.helper['run'] = lambda args: self.calls.append(args)

    def test_remote_sources_compile(self):
        compile(_NETWORK_HELPER, '<network-helper>', 'exec')
        compile(_ROLLBACK_HELPER, '<rollback>', 'exec')

    def test_inventory_retains_unaddressed_interfaces_and_all_addresses(self):
        self.helper['ip'] = Mock(side_effect=[[], [
            dict(ifname='eth0', operstate='DOWN', addr_info=[]),
            dict(ifname='wlan0', operstate='UP', addr_info=[
                dict(local='192.0.2.3', prefixlen=24, family='inet'),
                dict(local='fe80::12', prefixlen=64, family='inet6')]),
            dict(ifname='lo', addr_info=[dict(local='127.0.0.1', prefixlen=8, family='inet')]),
        ]])
        with patch.dict(os.environ, SSH_CONNECTION='192.0.2.5 54321 192.0.2.3 22'):
            result = self.helper['inventory']()
        self.assertEqual(len(result['interfaces']), 3)
        self.assertEqual(result['interfaces'][0]['addresses'], [])
        self.assertEqual(len(result['interfaces'][1]['addresses']), 2)
        self.assertTrue(result['interfaces'][1]['management'])

    def test_rollback_restores_selected_interface_addresses_routes_and_link(self):
        self.helper['restore'](dict(interface='eth0', up=False,
            addresses=[dict(local='192.0.2.8', prefixlen=24, broadcast='192.0.2.255')],
            routes=[dict(dst='default', gateway='192.0.2.1', metric=50)]))
        self.assertIn(['ip', '-4', 'address', 'add', '192.0.2.8/24', 'dev', 'eth0', 'broadcast', '192.0.2.255'], self.calls)
        self.assertEqual(self.calls[-1], ['ip', 'link', 'set', 'dev', 'eth0', 'down'])
        for args in self.calls:
            self.assertIn('eth0', args)
            self.assertIsInstance(args, list)

    def test_expired_confirmation_does_not_cancel_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'state.json').write_text(json.dumps(dict(interface='eth0', deadline=time.monotonic() - 1)))
            self.helper['transaction_dir'] = Mock(return_value=directory)
            with self.assertRaisesRegex(RuntimeError, 'expired'):
                self.helper['confirm'](dict(token='a' * 32, address='192.0.2.3/24'))
            self.assertFalse((directory / 'confirmed').exists())

    def test_expired_transaction_rolls_back_without_ssh(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            state = dict(interface='eth0', deadline=time.monotonic() - 1)
            (directory / 'state.json').write_text(json.dumps(state))
            self.helper['transaction_dir'] = Mock(return_value=directory)
            self.helper['restore'] = Mock()
            self.helper['rollback']('a' * 32)
            self.helper['restore'].assert_called_once_with(state)
            self.assertFalse(directory.exists())

    def test_remote_interface_and_advanced_routes_are_rejected_before_mutation(self):
        with self.assertRaisesRegex(ValueError, 'interface'):
            self.helper['configure'](dict(interface='eth0;id'))
        with self.assertRaisesRegex(ValueError, 'advanced routes'):
            self.helper['route_args'](dict(dst='default', nexthops=[]), 'eth0')
        self.assertEqual(self.calls, [])

    def test_configuration_starts_detached_rollback_and_changes_only_selected_port(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen') as child:
            self.helper['Path'] = lambda value: Path(directory) if value == '/run' else Path(value)
            self.helper['ip'] = Mock(side_effect=[
                [dict(flags=['UP'], addr_info=[dict(local='192.0.2.8', prefixlen=24, scope='global', family='inet')])],
                [dict(dev='wlan0', dst='default', metric=100)], [],
                [dict(addr_info=[dict(local='192.0.2.9', prefixlen=24)])],
            ])
            result = self.helper['configure'](dict(interface='eth0', address='192.0.2.9', prefix=24,
                gateway='192.0.2.1', management_address='192.0.2.8', rollback_source=_ROLLBACK_HELPER))
            self.assertFalse(result['persistent'])
            self.assertTrue(child.call_args.kwargs['start_new_session'])
            self.assertTrue((Path(directory) / ('pyxcp-network-' + result['token']) / 'state.json').is_file())
            self.assertIn(['ip', '-4', 'route', 'add', 'default', 'via', '192.0.2.1', 'dev', 'eth0', 'metric', '101'], self.calls)
            self.assertTrue(all('eth0' in args for args in self.calls))
            self.assertEqual(result['retained_management_addresses'], ['192.0.2.8/24'])
            self.assertFalse(any('del' in args for args in self.calls))

    def test_configuration_failure_restores_immediately(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen'):
            self.helper['Path'] = lambda value: Path(directory) if value == '/run' else Path(value)
            self.helper['ip'] = Mock(side_effect=[[dict(flags=[], addr_info=[])], [], []])
            self.helper['run'] = Mock(side_effect=RuntimeError('ip failed'))
            self.helper['restore'] = Mock()
            with self.assertRaisesRegex(RuntimeError, 'ip failed'):
                self.helper['configure'](dict(interface='eth0', address='192.0.2.9', prefix=24,
                    gateway='', rollback_source=_ROLLBACK_HELPER))
            self.helper['restore'].assert_called_once()
            transaction = next(Path(directory).iterdir())
            self.assertTrue((transaction / 'confirmed').exists())

    def test_first_ipv4_configuration_retains_unaddressed_and_ipv6_only_interfaces(self):
        ipv6 = dict(local='2001:db8::2', prefixlen=64, scope='global', family='inet6')
        for flags, old_addresses in (([], []), (['UP', 'NO-CARRIER'], []), (['UP'], [ipv6])):
            with self.subTest(flags=flags, addresses=old_addresses), tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen'):
                self.calls.clear()
                self.helper['Path'] = lambda value: Path(directory) if value == '/run' else Path(value)
                current = dict(ifname='eth0', flags=flags, address='02:00:00:00:00:01', addr_info=old_addresses)

                def query(*args):
                    if args == ('address', 'show', 'dev', 'eth0'):
                        return [current]
                    if args == ('-4', 'address', 'show', 'dev', 'eth0'):
                        if any('replace' in command for command in self.calls):
                            return [dict(addr_info=[dict(local='192.0.2.9', prefixlen=24, family='inet')])]
                        return []
                    return []

                self.helper['ip'] = Mock(side_effect=query)
                self.helper['netplan_plan'] = Mock(return_value=[])
                result = self.helper['configure'](dict(interface='eth0', address='192.0.2.9', prefix=24,
                    gateway='', persistent=True, rollback_source=_ROLLBACK_HELPER))
                saved = json.loads((Path(directory) / ('pyxcp-network-' + result['token']) / 'state.json').read_text())
                self.assertEqual(saved['addresses'], [])
                self.assertEqual(saved['up'], 'UP' in flags)
                self.assertEqual(self.helper['netplan_plan'].call_args.args[-1], current['address'])
                self.assertIn(['ip', '-4', 'address', 'replace', '192.0.2.9/24', 'broadcast', '+', 'dev', 'eth0'], self.calls)
                self.helper['restore'](saved)
                self.assertEqual(self.calls[-1], ['ip', 'link', 'set', 'dev', 'eth0', 'up' if 'UP' in flags else 'down'])
                self.assertFalse(any('2001:db8::2' in ' '.join(command) for command in self.calls))

    def test_missing_interface_is_rejected_before_any_network_changes(self):
        self.helper['ip'] = Mock(return_value=[])
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            self.helper['configure'](dict(interface='eth0', address='192.0.2.9', prefix=24, gateway=''))
        self.assertEqual(self.calls, [])

    def test_primary_address_is_removed_before_adding_replacement_in_same_subnet(self):
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.Popen'):
            self.helper['Path'] = lambda value: Path(directory) if value == '/run' else Path(value)
            self.helper['ip'] = Mock(side_effect=[
                [dict(flags=['UP'], addr_info=[dict(local='192.0.2.8', prefixlen=24, scope='global', family='inet')])], [], [],
                [dict(addr_info=[dict(local='192.0.2.9', prefixlen=24)])],
            ])
            self.helper['configure'](dict(interface='eth0', address='192.0.2.9', prefix=24,
                gateway='', rollback_source=_ROLLBACK_HELPER))
            deleted = next(index for index, args in enumerate(self.calls) if 'del' in args)
            replaced = next(index for index, args in enumerate(self.calls) if 'replace' in args)
            self.assertLess(deleted, replaced)


if __name__ == '__main__':
    unittest.main()
