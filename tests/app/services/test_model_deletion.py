import ast
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from pyxcp_host.services.model_deletion import _DELETE_HELPER
from pyxcp_host.services.ssh_deployment import SSHDeployment


class ModelDeletionTransportTests(unittest.TestCase):
    def service(self, result):
        service = SSHDeployment()
        service._begin = Mock()
        service._execute = Mock(return_value=json.dumps(result))
        return service

    def test_exact_paths_are_json_data_and_deleted_identity_is_cleared(self):
        elf = "/home/test/MATLAB_ws/model 'a'; $(literal)/model.elf"
        result = dict(deleted=True, elf_path=elf, directory=elf.rsplit('/', 1)[0], autostart_cleared=True)
        service = self.service(result)
        service._remote_elf, service._pid = elf, 42
        self.assertEqual(service.delete_model(elf), result)
        words = shlex.split(service._execute.call_args.args[0])
        self.assertEqual(words[:2], ['python3', '-c'])
        self.assertEqual(words[2], _DELETE_HELPER)
        self.assertEqual(json.loads(words[3]), dict(path=elf, root='MATLAB_ws'))
        self.assertEqual(service._remote_elf, '')
        self.assertIsNone(service.pid)

    def test_other_selected_model_is_preserved(self):
        service = self.service(dict(deleted=True, elf_path='/home/test/models/a/a.elf',
                                    directory='/home/test/models/a', autostart_cleared=False))
        service._remote_elf, service._pid = '/home/test/models/b/b.elf', 99
        service.delete_model('/home/test/models/a/a.elf', root='models')
        self.assertEqual(service._remote_elf, '/home/test/models/b/b.elf')
        self.assertEqual(service.pid, 99)

    def test_failure_preserves_selected_identity(self):
        service = self.service({})
        service._remote_elf = '/home/test/models/a/a.elf'
        service._execute.side_effect = RuntimeError('Stop the model')
        with self.assertRaisesRegex(RuntimeError, 'Stop the model'):
            service.delete_model(service._remote_elf)
        self.assertEqual(service._remote_elf, '/home/test/models/a/a.elf')

    def test_invalid_remote_result_is_rejected(self):
        for result in ({}, {'deleted': False}, []):
            with self.subTest(result=result), self.assertRaises(ValueError):
                self.service(result).delete_model('models/a.elf')

    def test_broad_and_traversing_paths_fail_before_remote_execution(self):
        service = self.service({})
        for path, root in (('/', 'models'), ('models/a.elf', '.'), ('../a.elf', 'models'),
                           ('models/a.elf', '/home/test/../other')):
            with self.subTest(path=path, root=root), self.assertRaises(ValueError):
                service.delete_model(path, root)
        service._execute.assert_not_called()


class ModelDeletionHelperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name).resolve()
        self.directory = self.home / 'MATLAB_ws' / "model 'quoted'"
        self.directory.mkdir(parents=True)
        self.elf = self.directory / 'model.elf'
        self.elf.write_bytes(b'\x7fELFmodel')
        self.elf.with_suffix('.a2l').write_text('A2L')
        self.elf.with_suffix('.json').write_text('{}')
        self.sibling = self.directory.with_name('other')
        self.sibling.mkdir()
        (self.sibling / 'model.elf').write_bytes(b'\x7fELFother')
        self.namespace = {'__name__': 'deletion_tests'}
        self.fcntl = types.SimpleNamespace(flock=Mock(), LOCK_EX=2, LOCK_NB=4)
        pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_name='test'))
        module = ast.parse(_DELETE_HELPER)
        # Windows lacks Linux directory descriptors; keep filesystem mutations real
        # while adapting only the /proc/self/fd lookup and directory syscalls.
        if os.name == 'nt':
            for node in ast.walk(module):
                if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                        and target.id == 'pinned_parent' for target in node.targets):
                    node.value = ast.parse('test_handles[parent_fd]', mode='eval').body
            ast.fix_missing_locations(module)
        with patch.object(Path, 'home', return_value=self.home), \
                patch.dict(sys.modules, pwd=pwd, fcntl=self.fcntl):
            exec(compile(module, '<delete helper>', 'exec'), self.namespace)
        self.handles = {}
        self.namespace['test_handles'] = self.handles
        remote_os = types.SimpleNamespace(**vars(os))
        remote_os.getuid = lambda: 1000
        remote_os.O_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
        remote_os.O_NONBLOCK = getattr(os, 'O_NONBLOCK', 0)
        remote_os.O_DIRECTORY = getattr(os, 'O_DIRECTORY', 0x10000000)
        if os.name == 'nt':
            def open_path(value, flags, *args):
                if flags & remote_os.O_DIRECTORY:
                    descriptor = 100000 + len(self.handles)
                    self.handles[descriptor] = Path(value)
                    return descriptor
                return os.open(value, flags | os.O_BINARY, *args)

            def rename(source, destination, src_dir_fd=None, dst_dir_fd=None):
                if src_dir_fd is not None:
                    source = self.handles[src_dir_fd] / source
                if dst_dir_fd is not None:
                    destination = self.handles[dst_dir_fd] / destination
                os.rename(source, destination)

            remote_os.open = open_path
            remote_os.rename = rename
            remote_os.close = lambda descriptor: None if descriptor in self.handles else os.close(descriptor)
        self.namespace['os'] = remote_os
        self.namespace['ensure_stopped'] = Mock()
        self.namespace['shutil'] = types.SimpleNamespace(rmtree=Mock(side_effect=shutil.rmtree))
        self.namespace['shutil'].rmtree.avoids_symlink_attacks = True
        self.enabled = False
        self.fail_operation = ''
        self.calls = []
        self.namespace['run'] = self.fake_run

    def tearDown(self):
        self.temporary.cleanup()

    def fake_run(self, arguments, required=True):
        self.calls.append(arguments)
        if arguments[0] == 'loginctl':
            return types.SimpleNamespace(returncode=0, stdout='yes\n')
        operation = arguments[4]
        if operation == self.fail_operation:
            self.fail_operation = ''
            raise RuntimeError('Failed ' + operation)
        if operation == 'is-enabled':
            return types.SimpleNamespace(returncode=0 if self.enabled else 1,
                                         stdout='enabled\n' if self.enabled else 'disabled\n')
        if operation == 'enable':
            self.enabled = True
        elif operation == 'disable':
            self.enabled = False
        return types.SimpleNamespace(returncode=0, stdout='')

    def configure(self, elf=None, enabled=True):
        config = self.namespace['config']
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps(dict(owner='pyxcp-host-v1', elf_path=str(elf or self.elf))))
        unit = self.namespace['unit']
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(self.namespace['MARKER'] + '[Unit]\n')
        self.enabled = enabled

    def delete(self, elf=None, root='MATLAB_ws'):
        return self.namespace['delete_model'](dict(path=(elf or self.elf).as_posix(), root=root))

    def test_deletes_exact_parent_with_metadata_and_keeps_sibling(self):
        nested = self.directory / 'logs'
        nested.mkdir()
        (nested / 'run.log').write_text('log')
        result = self.delete()
        self.assertEqual(result, dict(deleted=True, elf_path=str(self.elf),
                                      directory=str(self.directory), autostart_cleared=False))
        self.assertFalse(self.directory.exists())
        self.assertTrue((self.sibling / 'model.elf').is_file())
        self.assertTrue(self.directory.parent.is_dir())
        self.assertEqual(list(self.directory.parent.iterdir()), [self.sibling])

    def test_scan_root_can_be_selected_model_directory(self):
        self.delete(root=self.directory.as_posix())
        self.assertFalse(self.directory.exists())
        self.assertTrue(self.sibling.is_dir())

    def test_other_elf_at_any_depth_rejects_shared_directory(self):
        other = self.directory / 'nested' / 'other.elf'
        other.parent.mkdir()
        other.write_bytes(b'\x7fELFother')
        with self.assertRaisesRegex(ValueError, 'another ELF'):
            self.delete()
        self.assertTrue(other.exists())
        self.assertTrue(self.elf.exists())

    def test_missing_or_non_elf_selection_rejected(self):
        for content in (None, b'not ELF'):
            if content is None:
                self.elf.unlink()
            else:
                self.elf.write_bytes(content)
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.delete()
        self.assertTrue(self.directory.exists())

    def test_outside_scan_root_home_and_hidden_directory_rejected(self):
        with self.assertRaisesRegex(ValueError, 'scan root'):
            self.delete(root=self.sibling.as_posix())
        for candidate in (self.home.as_posix(), self.home.parent.as_posix(), '.ssh/a.elf', 'a/../b'):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.namespace['model_path'](candidate)
        self.assertTrue(self.elf.exists())

    def test_symlink_parent_or_selected_file_rejected(self):
        original = Path.is_symlink
        for candidate in (self.elf, self.directory):
            with self.subTest(candidate=candidate), patch.object(Path, 'is_symlink',
                    lambda path: path == candidate or original(path)):
                with self.assertRaisesRegex(ValueError, 'symlinks'):
                    self.delete()
        self.assertTrue(self.elf.exists())

    def test_symlink_inside_directory_rejected_without_removal(self):
        entry = Mock()
        entry.is_symlink.return_value = True
        scan = Mock()
        scan.__enter__ = Mock(return_value=iter([entry]))
        scan.__exit__ = Mock(return_value=False)
        self.namespace['os'].scandir = Mock(return_value=scan)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.delete()
        self.assertTrue(self.elf.exists())

    def test_running_model_rejected_before_autostart_mutation(self):
        self.configure()
        self.namespace['ensure_stopped'].side_effect = RuntimeError('Stop the model')
        with self.assertRaisesRegex(RuntimeError, 'Stop the model'):
            self.delete()
        self.assertTrue(self.elf.exists())
        self.assertTrue(self.enabled)
        self.assertEqual(self.calls, [])

    def test_late_start_after_rename_restores_directory_and_autostart(self):
        self.configure()
        self.namespace['ensure_stopped'].side_effect = [None, None, RuntimeError('Stop the model')]
        with self.assertRaisesRegex(RuntimeError, 'Stop the model'):
            self.delete()
        self.assertTrue(self.elf.exists())
        self.assertTrue(self.enabled)
        self.assertTrue(self.namespace['config'].exists())
        self.assertFalse(list(self.directory.parent.glob('.pyxcp-delete-*')))

    def test_directory_swap_before_rename_preserves_both_directories(self):
        replacement = self.directory.with_name('replacement')
        replacement.mkdir()
        original_clear = self.namespace['clear_autostart']

        def swap(elf):
            result = original_clear(elf)
            self.directory.rename(self.directory.with_name('original'))
            replacement.rename(self.directory)
            return result

        self.namespace['clear_autostart'] = swap
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            self.delete()
        self.assertTrue(self.directory.is_dir())
        self.assertTrue((self.directory.with_name('original') / self.elf.name).exists())

    def test_enabled_and_disabled_stale_autostart_are_removed(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.directory.mkdir(exist_ok=True)
                self.elf.write_bytes(b'\x7fELFmodel')
                self.configure(enabled=enabled)
                result = self.delete()
                self.assertTrue(result['autostart_cleared'])
                self.assertFalse(self.enabled)
                self.assertFalse(self.namespace['config'].exists())
                self.assertFalse(self.namespace['unit'].exists())
                self.assertFalse(self.directory.exists())

    def test_unrelated_autostart_remains_byte_identical(self):
        self.configure(elf=self.sibling / 'model.elf')
        original = self.namespace['config'].read_bytes()
        result = self.delete()
        self.assertFalse(result['autostart_cleared'])
        self.assertEqual(self.namespace['config'].read_bytes(), original)
        self.assertTrue(self.enabled)
        self.assertEqual(self.calls, [])

    def test_disable_and_reload_failures_preserve_model_and_autostart(self):
        for operation in ('disable', 'daemon-reload'):
            self.configure()
            original = self.namespace['config'].read_bytes()
            self.fail_operation = operation
            with self.subTest(operation=operation), self.assertRaisesRegex(RuntimeError, 'Failed'):
                self.delete()
            self.assertTrue(self.elf.exists())
            self.assertEqual(self.namespace['config'].read_bytes(), original)
            self.assertTrue(self.enabled)

    def test_autostart_process_lock_refuses_deletion(self):
        self.configure()
        self.fcntl.flock.side_effect = BlockingIOError('running')
        with self.assertRaisesRegex(RuntimeError, 'Stop the autostart model'):
            self.delete()
        self.assertTrue(self.elf.exists())
        self.assertTrue(self.enabled)

    def test_unowned_matching_autostart_configuration_rejected(self):
        self.configure()
        self.namespace['config'].write_text(json.dumps(dict(elf_path=str(self.elf), owner='other')))
        with self.assertRaisesRegex(RuntimeError, 'not owned'):
            self.delete()
        self.assertTrue(self.elf.exists())

    def test_partial_removal_failure_never_reenables_autostart(self):
        self.configure()
        self.namespace['shutil'].rmtree.side_effect = PermissionError('cannot remove')
        with self.assertRaisesRegex(PermissionError, 'cannot remove'):
            self.delete()
        self.assertTrue(self.directory.exists())
        self.assertFalse(self.enabled)
        self.assertFalse(self.namespace['config'].exists())


class ModelDeletionProcessTests(unittest.TestCase):
    def setUp(self):
        self.namespace = {'__name__': 'deletion_tests'}
        with patch.dict(sys.modules, pwd=types.SimpleNamespace(), fcntl=types.SimpleNamespace()):
            exec(compile(_DELETE_HELPER, '<delete helper>', 'exec'), self.namespace)
        self.os = types.SimpleNamespace(**vars(os))
        self.os.getuid = lambda: 1000
        self.namespace['os'] = self.os

    def processes(self, executable, state='S', permission=False, uid=1000):
        process = Mock()
        process.stat.return_value = types.SimpleNamespace(st_uid=uid)
        process.__truediv__ = Mock(side_effect=lambda name: Mock(read_text=Mock(
            return_value='42 (model with spaces) ' + state)) if name == 'stat' else '/proc/42/exe')
        self.namespace['Path'] = Mock(side_effect=lambda value: process if value == '/proc/42' else Path(value))
        entry = types.SimpleNamespace(name='42', path='/proc/42')
        scan = Mock()
        scan.__enter__ = Mock(return_value=iter([entry]))
        scan.__exit__ = Mock(return_value=False)
        self.os.scandir = Mock(return_value=scan)
        self.os.readlink = Mock(side_effect=PermissionError() if permission else None, return_value=executable)

    def test_owned_and_unowned_running_executable_are_both_rejected(self):
        for suffix in ('', ' (deleted)'):
            self.processes('/home/test/models/a/model.elf' + suffix)
            with self.subTest(suffix=suffix), self.assertRaisesRegex(RuntimeError, 'Stop the model'):
                self.namespace['ensure_stopped'](Path('/home/test/models/a'))

    def test_other_directory_zombies_and_other_users_are_ignored(self):
        for executable, state, uid in (('/home/test/models/abc/model.elf', 'S', 1000),
                ('/home/test/models/a/model.elf', 'Z', 1000),
                ('/home/test/models/a/model.elf', 'S', 1001)):
            self.processes(executable, state=state, uid=uid)
            self.namespace['ensure_stopped'](Path('/home/test/models/a'))

    def test_unreadable_same_user_process_fails_closed(self):
        self.processes('/home/test/models/a/model.elf', permission=True)
        with self.assertRaisesRegex(RuntimeError, 'Could not verify'):
            self.namespace['ensure_stopped'](Path('/home/test/models/a'))


if __name__ == '__main__':
    unittest.main()
