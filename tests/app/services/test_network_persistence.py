import base64
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import yaml

from pyxcp_host.services.network_configuration import _NETWORK_LIBRARY


class NetplanPersistenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.helper = {'__name__': 'network_test'}
        with patch.dict(sys.modules, fcntl=types.SimpleNamespace(flock=Mock(), LOCK_EX=2)):
            exec(compile(_NETWORK_LIBRARY, '<network>', 'exec'), self.helper)
        self.helper['Path'] = lambda value: self.root / value.lstrip('/')
        self.helper['shutil'] = types.SimpleNamespace(which=lambda _: '/usr/sbin/netplan')
        self.helper['run'] = Mock()
        self.path = self.root / 'etc/netplan/90-test.yaml'
        self.path.parent.mkdir(parents=True)
        self.original = {'network': {'version': 2, 'renderer': 'networkd', 'wifis': {
            'wlan0': {'dhcp4': True, 'dhcp6': True, 'addresses': ['2001:db8::2/64'],
                      'access-points': {'fixture': {'password': 'synthetic'}},
                      'nameservers': {'addresses': ['192.0.2.53']}},
            'wlan1': {'dhcp4': True}}, 'ethernets': {
            'enp1s0': {'dhcp4': True, 'dhcp6': True, 'accept-ra': True, 'optional': False,
                       'addresses': ['192.168.7.2/24', '2001:db8::7/64']},
            'enp3s0': {'dhcp4': False, 'addresses': ['192.168.8.1/24'], 'optional': True},
            'enp4s0': {'dhcp4': False, 'addresses': ['192.168.9.1/24']}}}}
        self.path.write_text(yaml.safe_dump(self.original), encoding='utf-8')

    def plan(self, interface='wlan0'):
        return self.helper['netplan_plan'](interface, '192.0.2.8/24', '192.0.2.1', 101)

    def test_only_selected_ipv4_changes_and_wifi_ipv6_dns_are_preserved(self):
        records = self.plan()
        self.assertEqual(len(records), 1)
        value = yaml.safe_load(records[0]['updated'])['network']['wifis']
        self.assertEqual(value['wlan1'], self.original['network']['wifis']['wlan1'])
        node = value['wlan0']
        self.assertEqual(node['addresses'], ['2001:db8::2/64', '192.0.2.8/24'])
        self.assertFalse(node['dhcp4'])
        self.assertTrue(node['dhcp6'])
        self.assertNotIn('ignore-carrier', node)
        self.assertEqual(node['access-points'], self.original['network']['wifis']['wlan0']['access-points'])
        self.assertEqual(node['nameservers'], {'addresses': ['192.0.2.53']})
        self.assertEqual(node['routes'], [dict(to='default', via='192.0.2.1', metric=101)])
        self.assertEqual(base64.b64decode(records[0]['original']), self.path.read_bytes())

    def test_selected_ethernet_is_configured_without_carrier(self):
        records = self.plan('enp1s0')
        network = yaml.safe_load(records[0]['updated'])['network']
        node = network['ethernets']['enp1s0']
        self.assertIs(node.get('ignore-carrier'), True)
        self.assertEqual(node['addresses'], ['2001:db8::7/64', '192.0.2.8/24'])
        self.assertFalse(node['dhcp4'])
        self.assertTrue(node['dhcp6'])
        self.assertTrue(node['accept-ra'])
        self.assertFalse(node['optional'])
        self.assertEqual(network['wifis'], self.original['network']['wifis'])
        for interface in ('enp3s0', 'enp4s0'):
            self.assertEqual(network['ethernets'][interface], self.original['network']['ethernets'][interface])

    def test_only_last_ethernet_fragment_overrides_carrier_requirement(self):
        self.original['network']['ethernets']['enp1s0']['ignore-carrier'] = False
        self.path.write_text(yaml.safe_dump(self.original), encoding='utf-8')
        extra = self.path.with_name('95-static.yaml')
        extra.write_text(yaml.safe_dump({'network': {'version': 2, 'ethernets': {'enp1s0': {
            'ignore-carrier': False, 'addresses': ['192.0.2.10/24']}}}}), encoding='utf-8')
        records = self.plan('enp1s0')
        self.assertEqual([Path(record['path']).name for record in records], ['90-test.yaml', '95-static.yaml'])
        nodes = [yaml.safe_load(record['updated'])['network']['ethernets']['enp1s0'] for record in records]
        self.assertIs(nodes[0]['ignore-carrier'], False)
        self.assertIs(nodes[1].get('ignore-carrier'), True)
        self.assertEqual(nodes[0]['addresses'], ['2001:db8::7/64'])
        self.assertEqual(nodes[1]['addresses'], ['192.0.2.8/24'])

    def test_old_ipv4_addresses_are_removed_from_all_merging_fragments(self):
        extra = self.path.with_name('95-static.yaml')
        extra.write_text(yaml.safe_dump({'network': {'version': 2, 'wifis': {'wlan0': {
            'addresses': ['192.0.2.10/24'], 'gateway4': '192.0.2.9',
            'routes': [{'to': '10.0.0.0/8', 'via': '192.0.2.9'}]}}}}), encoding='utf-8')
        nodes = [yaml.safe_load(record['updated'])['network']['wifis']['wlan0'] for record in self.plan()]
        self.assertNotIn('192.0.2.10/24', [value for node in nodes for value in node['addresses']])
        self.assertEqual(sum('192.0.2.8/24' in node['addresses'] for node in nodes), 1)
        self.assertTrue(all('gateway4' not in node for node in nodes))
        self.assertIn({'to': '10.0.0.0/8', 'via': '192.0.2.9'}, nodes[-1]['routes'])

    def test_unsupported_or_ambiguous_config_is_rejected_before_changes(self):
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'dedicated'):
            self.helper['netplan_plan']('missing0', '192.0.2.8/24', '')
        self.assertEqual(self.path.read_bytes(), original)
        self.original['network']['renderer'] = 'NetworkManager'
        self.path.write_text(yaml.safe_dump(self.original), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'networkd'):
            self.plan()

    def prepare_persist(self, interface='wlan0'):
        saved = {'netplan_files': self.plan(interface)}
        self.helper['Path'] = Path
        self.helper['atomic_config'] = lambda path, content, mode: path.write_bytes(content)
        return saved

    def test_global_renderer_in_separate_fragment_is_respected(self):
        self.original['network'].pop('renderer')
        self.path.write_text(yaml.safe_dump(self.original), encoding='utf-8')
        self.path.with_name('99-renderer.yaml').write_text(
            'network:\n  version: 2\n  renderer: NetworkManager\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'networkd'):
            self.plan()

    def test_wildcard_interface_match_cannot_change_other_ports(self):
        self.original['network']['wifis']['wlan0']['match'] = {'name': 'wlan*'}
        self.path.write_text(yaml.safe_dump(self.original), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'dedicated'):
            self.plan()

    def test_confirm_persists_then_generates_without_reapplying_live_network(self):
        saved = self.prepare_persist()
        self.helper['persist_netplan'](saved)
        self.assertTrue(saved['netplan_written'])
        self.assertFalse(yaml.safe_load(self.path.read_text())['network']['wifis']['wlan0']['dhcp4'])
        self.helper['run'].assert_called_once_with(['netplan', 'generate'])

    def test_generation_failure_restores_original_config_bytes(self):
        saved = self.prepare_persist()
        original = self.path.read_bytes()
        self.helper['run'].side_effect = [RuntimeError('invalid config'), None]
        with self.assertRaisesRegex(RuntimeError, 'invalid config'):
            self.helper['persist_netplan'](saved)
        self.assertEqual(self.path.read_bytes(), original)

    def test_external_edit_is_not_overwritten_and_does_not_arm_file_rollback(self):
        saved = self.prepare_persist()
        self.path.write_text('external edit', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.helper['persist_netplan'](saved)
        self.assertNotIn('netplan_written', saved)
        self.assertEqual(self.path.read_text(), 'external edit')

    def test_rollback_restores_persistent_and_live_state(self):
        saved = self.prepare_persist()
        original = self.path.read_bytes()
        self.helper['persist_netplan'](saved)
        saved.update(interface='wlan0', up=True, addresses=[], routes=[])
        self.helper['restore'](saved)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn(unittest.mock.call(['ip', '-4', 'address', 'flush', 'dev', 'wlan0', 'scope', 'global']),
                      self.helper['run'].call_args_list)

    def test_rollback_removes_added_ethernet_carrier_setting_and_restores_down_state(self):
        saved = self.prepare_persist('enp1s0')
        original = self.path.read_bytes()
        self.helper['persist_netplan'](saved)
        node = yaml.safe_load(self.path.read_text())['network']['ethernets']['enp1s0']
        self.assertIs(node.get('ignore-carrier'), True)
        saved.update(interface='enp1s0', up=False, addresses=[], routes=[])
        self.helper['restore'](saved)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.helper['run'].call_args_list.count(unittest.mock.call(['netplan', 'generate'])), 2)
        self.helper['run'].assert_called_with(['ip', 'link', 'set', 'dev', 'enp1s0', 'down'])

    def test_failed_netplan_generation_still_restores_live_address_route_and_link(self):
        saved = self.prepare_persist()
        original = self.path.read_bytes()
        self.helper['persist_netplan'](saved)
        saved.update(interface='wlan0', up=True,
                     addresses=[dict(local='192.0.2.2', prefixlen=24)],
                     routes=[dict(dst='default', gateway='192.0.2.1')])

        def run(command):
            if command[0] == 'netplan':
                raise RuntimeError('netplan generation failed')

        self.helper['run'] = Mock(side_effect=run)
        with self.assertRaisesRegex(RuntimeError, 'netplan generation failed'):
            self.helper['restore'](saved)
        self.assertEqual(self.path.read_bytes(), original)
        self.helper['run'].assert_has_calls([
            unittest.mock.call(['ip', '-4', 'address', 'add', '192.0.2.2/24', 'dev', 'wlan0']),
            unittest.mock.call(['ip', '-4', 'route', 'flush', 'table', 'main', 'dev', 'wlan0']),
            unittest.mock.call(['ip', '-4', 'route', 'replace', 'default', 'via', '192.0.2.1', 'dev', 'wlan0']),
            unittest.mock.call(['ip', 'link', 'set', 'dev', 'wlan0', 'up']),
        ])

    def test_failed_live_command_does_not_skip_remaining_recovery(self):
        saved = dict(interface='wlan0', up=False,
                     addresses=[dict(local='192.0.2.2', prefixlen=24)], routes=[])
        self.helper['run'].side_effect = [RuntimeError('flush failed'), None, None, None]
        with self.assertRaisesRegex(RuntimeError, 'flush failed'):
            self.helper['restore'](saved)
        self.helper['run'].assert_any_call(['ip', '-4', 'address', 'add', '192.0.2.2/24', 'dev', 'wlan0'])
        self.helper['run'].assert_called_with(['ip', 'link', 'set', 'dev', 'wlan0', 'down'])
