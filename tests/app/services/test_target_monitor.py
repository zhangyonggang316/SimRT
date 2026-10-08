from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.target_monitor import TargetMonitor, _TARGET_HELPER


def helper_namespace():
    namespace = {'__name__': 'monitor_test'}
    exec(compile(_TARGET_HELPER, '<target monitor>', 'exec'), namespace)
    return namespace


class TargetMonitorTransportTests(unittest.TestCase):
    def service(self, result):
        deployment = SSHDeployment()
        deployment._begin = Mock()
        deployment._execute = Mock(return_value=json.dumps(result))
        return TargetMonitor(deployment), deployment

    def test_snapshot_reuses_connection_and_starts_serial_operation(self):
        monitor, deployment = self.service({'cpu_percent': 21.0})
        deployment._operation_lock = Mock(wraps=threading.RLock())
        deployment._operation_lock.__enter__ = Mock()
        deployment._operation_lock.__exit__ = Mock()
        self.assertEqual(monitor.snapshot(), {'cpu_percent': 21.0})
        deployment._operation_lock.__enter__.assert_called_once()
        deployment._begin.assert_called_once()
        self.assertEqual(deployment._execute.call_args.kwargs['timeout'], 15.0)

    def test_models_paths_are_json_data_not_shell_commands(self):
        monitor, deployment = self.service([])
        root = "MATLAB_ws/a 'quoted'; $(literal)"
        self.assertEqual(monitor.list_models(root), [])
        command = shlex.split(deployment._execute.call_args.args[0])
        self.assertEqual(command[:2], ['python3', '-c'])
        self.assertEqual(command[2], _TARGET_HELPER)
        self.assertEqual(json.loads(command[3]), {'action': 'models', 'root': root})

    def test_default_matches_legacy_matlab_directory(self):
        monitor, deployment = self.service([])
        monitor.list_models()
        command = shlex.split(deployment._execute.call_args.args[0])
        self.assertEqual(json.loads(command[3])['root'], 'MATLAB_ws')

    def test_scan_diagnostics_are_kept_without_changing_list_api(self):
        monitor, _ = self.service({'models': [], 'scan': {'truncated': True, 'reason': 'model limit'}})
        self.assertEqual(monitor.list_models(), [])
        self.assertTrue(monitor.last_scan['truncated'])

    def test_broad_and_traversing_roots_rejected_before_remote_call(self):
        monitor, deployment = self.service([])
        for root in ('', '/', '.', '~', '~/../other', 'project/../other', 'x\ny'):
            with self.subTest(root=root), self.assertRaises(ValueError):
                monitor.list_models(root)
        deployment._execute.assert_not_called()

    def test_disconnected_and_cancelled_failures_propagate(self):
        monitor, deployment = self.service({})
        deployment._begin.side_effect = ConnectionError('Connect SSH first')
        with self.assertRaises(ConnectionError):
            monitor.snapshot()
        deployment._execute.assert_not_called()
        deployment._begin.side_effect = None
        deployment._execute.side_effect = InterruptedError('Cancelled')
        with self.assertRaises(InterruptedError):
            monitor.snapshot()

    def test_unexpected_remote_result_type_rejected(self):
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            self.service([])[0].snapshot()
        with self.assertRaisesRegex(ValueError, 'model list'):
            self.service({})[0].list_models()


class TargetMonitorHelperTests(unittest.TestCase):
    def setUp(self):
        self.helper = helper_namespace()

    def test_cpu_delta_ignores_guest_fields_and_counts_iowait_as_idle(self):
        parse = self.helper['cpu_times']
        before = parse('cpu 10 0 10 70 10 0 0 0 100 100\ncpu0 10 0 10 70 10 0 0 0')
        after = parse('cpu 20 0 20 90 20 0 0 0 900 900\ncpu0 20 0 20 90 20 0 0 0')
        result = self.helper['cpu_usage'](before, after)
        self.assertEqual(result, {'cpu': 40.0, 'cpu0': 40.0})

    def test_cpu_reset_new_core_and_missing_data_are_unknown(self):
        calculate = self.helper['cpu_usage']
        self.assertEqual(calculate({'cpu': (10, 5)}, {'cpu': (9, 4), 'cpu0': (10, 0)}),
                         {'cpu': None, 'cpu0': None})
        self.assertEqual(self.helper['cpu_times']('cpu broken\ncpu0 1 2\nno 1 2 3 4'), {})

    def test_memory_available_and_legacy_fallback(self):
        parse = self.helper['memory_stats']
        result = parse('MemTotal: 1000 kB\nMemAvailable: 250 kB\n')
        self.assertEqual(result['memory_used'], 750 * 1024)
        self.assertEqual(result['memory_percent'], 75.0)
        fallback = parse('MemTotal: 1000 kB\nMemFree: 100 kB\nBuffers: 100 kB\nCached: 50 kB')
        self.assertEqual(fallback['memory_percent'], 75.0)
        self.assertIsNone(parse('MemTotal: invalid kB')['memory_percent'])

    def test_snapshot_missing_proc_and_disk_is_not_fabricated_zero(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch('time.sleep') as sleep, \
                patch('shutil.disk_usage', side_effect=OSError('Unavailable')):
            result = self.helper['snapshot'](Path(directory), Path(directory))
        self.assertIsNone(result['cpu_percent'])
        self.assertIsNone(result['uptime'])
        self.assertIsNone(result['memory_percent'])
        self.assertIsNone(result['disk_percent'])
        self.assertEqual(result['load_average'], [None, None, None])
        self.assertEqual(result['network'], {})
        sleep.assert_called_once_with(0.15)
        json.dumps(result, allow_nan=False)

    def test_network_byte_counters_and_malformed_line(self):
        result = self.helper['network_stats'](
            'eth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\nbad: x y\n')
        self.assertEqual(result, {'eth0': {'received_bytes': 100, 'sent_bytes': 200}})

    def test_remote_root_must_be_dedicated_home_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            for value in (home.as_posix(), home.parent.as_posix(), 'a/../b', '/', '.'):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.helper['safe_root'](value, home)
            self.assertEqual(self.helper['safe_root']('MATLAB_ws/two words', home),
                             home / 'MATLAB_ws' / 'two words')

    def test_symlink_root_rejected_without_following(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            candidate = home / 'linked'
            with patch.object(Path, 'is_symlink', side_effect=lambda: True):
                with self.assertRaisesRegex(ValueError, 'symlinks'):
                    self.helper['safe_root'](candidate.as_posix(), home)

    def test_models_require_elf_magic_keep_spaces_and_find_a2l(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            root = home / 'MATLAB_ws' / 'two words'
            root.mkdir(parents=True)
            elf = root / "model 'one'.elf"
            elf.write_bytes(b'\x7fELFpayload')
            elf.with_suffix('.a2l').write_text('/begin PROJECT /end PROJECT')
            (root / 'text.elf').write_text('Not ELF')
            (root / 'ordinary.txt').write_bytes(b'\x7fELF')
            self.helper['process_map'] = Mock(return_value={})
            result = self.helper['list_models']('MATLAB_ws', home=home, uid=123)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['path'], str(elf))
            self.assertEqual(result[0]['a2l_path'], str(elf.with_suffix('.a2l')))
            self.assertFalse(result[0]['running'])
            self.assertFalse(result[0]['owned'])
            self.assertEqual(result[0]['pids'], [])

    def test_exact_process_path_and_owned_marker_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            root = home / 'MATLAB_ws'
            root.mkdir()
            elf = root / 'model.elf'
            elf.write_bytes(b'\x7fELF')
            identity = {'pid': 42, 'start_time': '100', 'elf_path': str(elf), 'uid': 123}
            marker = Path(str(elf) + '.pyxcp-host.json')
            marker.write_text(json.dumps(dict(identity, token='owned')))
            self.helper['process_map'] = Mock(return_value={str(elf): [identity]})
            result = self.helper['list_models']('MATLAB_ws', home=home, uid=123)[0]
            self.assertTrue(result['owned'])
            self.assertEqual(result['pid'], 42)
            marker.write_text(json.dumps(dict(identity, token='owned', start_time='99')))
            result = self.helper['list_models']('MATLAB_ws', home=home, uid=123)[0]
            self.assertTrue(result['running'])
            self.assertFalse(result['owned'])
            self.helper['process_map'] = Mock(return_value={str(elf) + 'extra': [identity]})
            self.assertFalse(self.helper['list_models']('MATLAB_ws', home=home, uid=123)[0]['running'])

    def test_model_limit_and_missing_root(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            self.assertEqual(self.helper['list_models']('missing', home=home, uid=1), [])
            root = home / 'MATLAB_ws'
            root.mkdir()
            for name in ('one', 'two', 'three'):
                (root / (name + '.elf')).write_bytes(b'\x7fELF')
            self.helper['MAX_MODELS'] = 2
            self.helper['process_map'] = Mock(return_value={})
            diagnostics = {}
            self.assertEqual(len(self.helper['list_models']('MATLAB_ws', home=home, uid=1,
                                                           diagnostics=diagnostics)), 2)
            self.assertTrue(diagnostics['truncated'])
            self.assertEqual(diagnostics['reason'], 'model limit')

    def test_model_walk_honors_entry_limit_and_ignores_symlinks(self):
        entry = Mock()
        entry.name, entry.path = 'linked.elf', '/target/linked.elf'
        entry.is_symlink.return_value = True
        scan = Mock()
        scan.__enter__ = Mock(return_value=iter([entry]))
        scan.__exit__ = Mock()
        with patch('os.scandir', return_value=scan), patch.object(Path, 'is_symlink', return_value=False):
            self.assertEqual(list(self.helper['model_files'](Path('/target'), float('inf'))), [])
        entry.is_file.assert_not_called()
        entry.is_symlink.reset_mock()
        self.helper['MAX_ENTRIES'] = 0
        scan.__enter__.return_value = iter([entry])
        with patch('os.scandir', return_value=scan), patch.object(Path, 'is_symlink', return_value=False):
            self.assertEqual(list(self.helper['model_files'](Path('/target'), float('inf'))), [])
        entry.is_symlink.assert_not_called()

    def test_oversized_or_malformed_ownership_metadata_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            elf = Path(directory, 'model.elf')
            marker = Path(str(elf) + '.pyxcp-host.json')
            marker.write_text('x' * 9000)
            self.assertFalse(self.helper['is_owned'](elf, []))
            marker.write_text('{broken')
            self.assertFalse(self.helper['is_owned'](elf, []))
            marker.write_text('[]')
            self.assertFalse(self.helper['is_owned'](elf, []))

    def test_process_identity_reads_start_time_and_exact_executable(self):
        entry = Mock()
        entry.name = '42'
        entry.stat.return_value = types.SimpleNamespace(st_uid=5)
        contents = '42 (two words) S ' + ' '.join(['0'] * 18 + ['12345'])
        entry.__truediv__ = Mock(side_effect=lambda name: Mock(read_text=Mock(return_value=contents))
                                if name == 'stat' else '/proc/42/exe')
        with patch('os.readlink', return_value='/home/test/two words.elf'):
            result = self.helper['process_identity'](entry, uid=5)
        self.assertEqual(result, {'pid': 42, 'uid': 5, 'start_time': '12345',
                                  'elf_path': '/home/test/two words.elf'})

    def test_process_identity_excludes_other_users_and_zombies(self):
        entry = Mock()
        entry.name = '42'
        entry.stat.return_value = types.SimpleNamespace(st_uid=5)
        self.assertIsNone(self.helper['process_identity'](entry, uid=6))
        entry.__truediv__ = Mock(return_value=Mock(read_text=Mock(return_value='42 (two words) Z')))
        self.assertIsNone(self.helper['process_identity'](entry, uid=5))


if __name__ == '__main__':
    unittest.main()
