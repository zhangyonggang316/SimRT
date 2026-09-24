from __future__ import annotations

import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

import paramiko

from pyxcp_host.services.ssh_deployment import (
    SSHDeployment, _BUILD_HELPER, _OUTPUT_LIMIT, _REMOTE_HELPER, _RememberHostKey,
)


class FakeChannel:
    def __init__(self, stdout=(), stderr=(), code=0, blocked=False):
        self.stdout = list(stdout)
        self.stderr = list(stderr)
        self.code = code
        self.blocked = blocked
        self.closed = False
        self.commands = []

    def exec_command(self, command):
        self.commands.append(command)

    def recv_ready(self):
        return bool(self.stdout)

    def recv_stderr_ready(self):
        return bool(self.stderr)

    def recv(self, _size):
        return self.stdout.pop(0)

    def recv_stderr(self, _size):
        return self.stderr.pop(0)

    def exit_status_ready(self):
        return not self.blocked and not self.stdout and not self.stderr

    def recv_exit_status(self):
        return self.code

    def shutdown_write(self):
        pass

    def close(self):
        self.closed = True


class FakeSFTP:
    def __init__(self, data=b'\x7fELFtest payload'):
        self.files = {}
        self.directories = set()
        self.data = data
        self.closed = False

    def get_channel(self):
        return Mock()

    def lstat(self, path):
        if path in self.directories:
            return types.SimpleNamespace(st_mode=stat.S_IFDIR | 0o755)
        if path in self.files:
            return types.SimpleNamespace(st_mode=stat.S_IFREG | 0o644)
        raise FileNotFoundError(path)

    def mkdir(self, path):
        self.directories.add(path)

    def put(self, source, destination, callback):
        self.files[destination] = Path(source).read_bytes()
        callback(len(self.files[destination]), len(self.files[destination]))

    def get(self, source, destination, callback):
        Path(destination).write_bytes(self.data)
        callback(len(self.data), len(self.data))

    def chmod(self, _path, _mode):
        pass

    def posix_rename(self, source, destination):
        self.files[destination] = self.files.pop(source)

    def remove(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        del self.files[path]

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self, channel=None, sftp=None):
        self.channel = channel or FakeChannel()
        self.sftp = sftp or FakeSFTP()
        self.active = True

    def get_transport(self):
        return self

    def is_active(self):
        return self.active

    def open_session(self, timeout):
        return self.channel

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.active = False


class SSHDeploymentTests(unittest.TestCase):
    def service(self, channel=None, sftp=None):
        service = SSHDeployment()
        service._client = FakeClient(channel, sftp)
        return service

    def test_command_drains_both_streams_and_reports_remote_failure(self):
        channel = FakeChannel([b'normal output'], [b'remote failure'], code=2)
        service = self.service(channel)
        with self.assertRaisesRegex(RuntimeError, 'remote failure'):
            service._execute('build')
        self.assertFalse(channel.stdout)
        self.assertFalse(channel.stderr)
        self.assertTrue(channel.closed)

    def test_command_return_buffer_is_bounded(self):
        channel = FakeChannel([b'a' * 32768 for _ in range(70)])
        output = self.service(channel)._execute('build')
        self.assertEqual(len(output), _OUTPUT_LIMIT)

    def test_timeout_closes_channel(self):
        channel = FakeChannel(blocked=True)
        with self.assertRaises(TimeoutError):
            self.service(channel)._execute('hang', timeout=0.03)
        self.assertTrue(channel.closed)

    def test_cancel_interrupts_command_without_waiting_for_operation_lock(self):
        channel = FakeChannel(blocked=True)
        service = self.service(channel)
        errors = []

        def run():
            try:
                with service._operation_lock:
                    service._execute('hang', timeout=10)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        deadline = threading.Event()
        for _ in range(100):
            if channel.commands:
                break
            deadline.wait(0.005)
        service.cancel()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], InterruptedError)
        self.assertTrue(channel.closed)

    def test_request_quotes_script_and_json_as_data(self):
        service = self.service()
        service._execute = Mock(return_value='{"size": 4}')
        tricky = "project/a 'quoted'; $(not-a-command).elf"
        self.assertEqual(service._request('elf', path=tricky), {'size': 4})
        words = shlex.split(service._execute.call_args[0][0])
        self.assertEqual(words[:2], ['python3', '-c'])
        self.assertEqual(json.loads(words[3])['path'], tricky)
        self.assertEqual(words[2], _REMOTE_HELPER)

    def test_rejects_broad_and_traversing_remote_paths(self):
        for value in ('/', '', '.', '~', '~/../tmp', '/home/user/../other', 'foo\nbar', 'C:\\bad'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SSHDeployment._validate_remote(value)

    def test_upload_filters_dependencies_and_uses_atomic_replacement(self):
        sftp = FakeSFTP()
        service = self.service(sftp=sftp)
        service._request = Mock(return_value={'remote_directory': '/home/test/project'})
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, 'source')
            source.mkdir()
            (source / 'main.c').write_text('int main(void) { return 0; }')
            (source / 'include').mkdir()
            (source / 'include' / 'api.h').write_text('void api(void);')
            (source / '.git').mkdir()
            (source / '.git' / 'config').write_text('not uploaded')
            (source / 'build').mkdir()
            (source / 'build' / 'old.elf').write_bytes(b'\x7fELF')
            (source / '.build_cache').mkdir()
            (source / '.build_cache' / 'old.o').write_bytes(b'object')
            (source / '.build.lock').write_bytes(b'0')
            (source / 'build_result.json').write_text('{"status": "success"}')
            self.assertEqual(service.upload(source, 'project'), 2)
        self.assertEqual(set(sftp.files), {'/home/test/project/main.c', '/home/test/project/include/api.h'})
        self.assertTrue(sftp.closed)
        self.assertTrue(service._request.call_args.kwargs['require_stopped'])

    def test_upload_rejects_remote_symlink_before_writing(self):
        sftp = FakeSFTP()
        sftp.lstat = Mock(return_value=types.SimpleNamespace(st_mode=stat.S_IFLNK | 0o777))
        service = self.service(sftp=sftp)
        service._request = Mock(return_value={'remote_directory': '/home/test/project'})
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'main.c').write_text('source')
            with self.assertRaisesRegex(ValueError, 'regular file'):
                service.upload(Path(root), 'project')
        self.assertFalse(sftp.files)

    def test_download_verifies_sha256_before_replacing_existing_file(self):
        sftp = FakeSFTP(b'\x7fELFnew content')
        service = self.service(sftp=sftp)
        service._request = Mock(return_value={'elf_path': '/home/test/app.elf',
            'size': len(sftp.data), 'sha256': hashlib.sha256(sftp.data).hexdigest()})
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root, 'app.elf')
            destination.write_bytes(b'previous')
            self.assertEqual(service.download_elf('project/app.elf', destination), destination)
            self.assertEqual(destination.read_bytes(), sftp.data)
            self.assertEqual(list(Path(root).iterdir()), [destination])

    def test_download_mismatch_preserves_existing_file(self):
        service = self.service(sftp=FakeSFTP(b'\x7fELFcorrupted'))
        service._request = Mock(return_value={'elf_path': '/home/test/app.elf', 'size': 13, 'sha256': 'bad'})
        with tempfile.TemporaryDirectory() as root:
            destination = Path(root, 'app.elf')
            destination.write_bytes(b'previous')
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                service.download_elf('project/app.elf', destination)
            self.assertEqual(destination.read_bytes(), b'previous')
            self.assertEqual(list(Path(root).iterdir()), [destination])

    def test_download_rejects_non_elf_content(self):
        service = self.service(sftp=FakeSFTP(b'not an elf'))
        service._request = Mock(return_value={'elf_path': '/home/test/app.elf', 'size': 10, 'sha256': 'unused'})
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, 'not an ELF'):
                service.download_elf('project/app.elf', Path(root, 'app.elf'))

    def test_build_wraps_user_command_with_remote_timeout(self):
        service = self.service()
        service._request = Mock(return_value={'remote_directory': '/home/test/project'})
        service._execute = Mock(return_value='compiled')
        self.assertEqual(service.build('project', 'make -j2', timeout=42), 'compiled')
        words = shlex.split(service._execute.call_args[0][0])
        self.assertEqual(words[2], _BUILD_HELPER)
        self.assertEqual(json.loads(words[3]), {'directory': '/home/test/project', 'command': 'make -j2', 'timeout': 42.0})
        self.assertEqual(service._execute.call_args.kwargs['timeout'], 47)

    def test_start_parses_arguments_without_shell_expansion(self):
        service = self.service()
        service._request = Mock(return_value={'elf_path': '/home/test/app.elf', 'pid': 123, 'running': True})
        self.assertEqual(service.start('project/app.elf', '--name "two words" "$(literal)"'), 123)
        self.assertEqual(service._request.call_args.kwargs['arguments'], ['--name', 'two words', '$(literal)'])
        self.assertEqual(service.pid, 123)

    def test_different_running_elf_is_not_orphaned_by_start(self):
        service = self.service()
        service._remote_elf = '/home/test/one.elf'
        service._request = Mock(side_effect=[{'running': True}, {'elf_path': '/home/test/two.elf'}])
        with self.assertRaisesRegex(RuntimeError, 'Stop the current'):
            service.start('project/two.elf')
        self.assertEqual(service._request.call_count, 2)

    def test_close_preserves_runtime_identity_without_stopping_process(self):
        service = self.service()
        service._remote_elf, service._pid = '/home/test/app.elf', 123
        service._request = Mock()
        service.close()
        self.assertFalse(service.connected)
        self.assertEqual(service.pid, 123)
        self.assertEqual(service._remote_elf, '/home/test/app.elf')
        service._request.assert_not_called()

    def test_status_and_stop_use_only_remembered_target(self):
        service = self.service()
        service._remote_elf = '/home/test/app.elf'
        service._request = Mock(side_effect=[{'running': True, 'pid': 123}, {'running': False, 'pid': None}])
        self.assertTrue(service.stop())
        self.assertEqual(service.pid, None)
        self.assertEqual([call.kwargs['path'] for call in service._request.call_args_list], [service._remote_elf] * 2)

    def test_select_status_recovers_owned_process_after_app_restart(self):
        service = self.service()
        service._request = Mock(return_value={'elf_path': '/home/test/app.elf', 'pid': 123, 'running': True})
        self.assertEqual(service.status('project/app.elf')['pid'], 123)
        self.assertEqual(service._remote_elf, '/home/test/app.elf')

    def test_failed_start_keeps_path_for_runtime_log(self):
        service = self.service()
        service._request = Mock(side_effect=[{'elf_path': '/home/test/app.elf'}, RuntimeError('early exit')])
        with self.assertRaisesRegex(RuntimeError, 'early exit'):
            service.start('project/app.elf')
        self.assertEqual(service._remote_elf, '/home/test/app.elf')

    def test_first_host_key_is_persisted_and_fingerprint_logged(self):
        messages = []
        client = Mock()
        key = Mock()
        key.asbytes.return_value = b'public key'
        key.get_name.return_value = 'ssh-ed25519'
        with tempfile.TemporaryDirectory() as root:
            known_hosts = Path(root, '.ssh', 'known_hosts')
            _RememberHostKey(known_hosts, messages.append).missing_host_key(client, 'ubuntu', key)
            client.get_host_keys().add.assert_called_once_with('ubuntu', 'ssh-ed25519', key)
            client.save_host_keys.assert_called_once_with(str(known_hosts))
            self.assertTrue(known_hosts.parent.is_dir())
        self.assertIn('SHA256:', messages[0])

    def test_changed_host_key_failure_is_not_silenced(self):
        client = Mock()
        mismatch = paramiko.BadHostKeyException('ubuntu', Mock(), Mock())
        client.connect.side_effect = mismatch
        with patch('pyxcp_host.services.ssh_deployment.paramiko.SSHClient', return_value=client), \
                patch('pyxcp_host.services.ssh_deployment.Path.is_file', return_value=False):
            service = SSHDeployment()
            with self.assertRaises(paramiko.BadHostKeyException):
                service.connect('ubuntu', 'tester', password='secret')
            self.assertFalse(service.connected)
            client.close.assert_called_once()

    def test_remote_helpers_are_valid_python(self):
        compile(_REMOTE_HELPER, '<remote helper>', 'exec')
        compile(_BUILD_HELPER, '<build helper>', 'exec')

    def run_remote_stop(self, reused):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root).resolve()
            project = home / 'project'
            project.mkdir()
            elf = project / 'app.elf'
            elf.write_bytes(b'\x7fELF')
            identity = {'pid': 2345, 'start_time': '100', 'elf_path': str(elf), 'uid': 1000, 'token': 'owned'}
            marker = Path(str(elf) + '.pyxcp-host.json')
            marker.write_text(json.dumps(identity))
            current = dict(identity, start_time='200') if reused else dict(identity)
            module = ast.parse(_REMOTE_HELPER)
            for node in module.body:
                if isinstance(node, ast.FunctionDef) and node.name == 'process_identity':
                    node.body = ast.parse('return fake_identity()').body
            ast.fix_missing_locations(module)
            identities = [current]

            def signal_process(pid, sig):
                self.assertEqual(pid, 2345)
                identities[0] = None

            with patch('sys.argv', ['helper', json.dumps({'action': 'stop', 'path': str(elf)})]), \
                    patch.object(Path, 'home', return_value=home), \
                    patch.object(os, 'getuid', return_value=1000, create=True), \
                    patch.object(signal, 'SIGKILL', 9, create=True), \
                    patch.object(os, 'kill', side_effect=signal_process) as kill, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                exec(compile(module, '<remote helper>', 'exec'), {'fake_identity': lambda: identities[0]})
            return kill.call_count, json.loads(output.getvalue())

    def test_remote_stop_refuses_reused_pid(self):
        signals, result = self.run_remote_stop(reused=True)
        self.assertEqual(signals, 0)
        self.assertFalse(result['running'])

    @unittest.skipIf(hasattr(os, 'pidfd_open'), 'Windows fallback branch only')
    def test_remote_stop_signals_matching_owned_identity_only(self):
        signals, result = self.run_remote_stop(reused=False)
        self.assertEqual(signals, 1)
        self.assertFalse(result['running'])

    def test_invalid_timeouts_rejected(self):
        for value in (0, -1, float('inf'), float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.service().build('project', 'make', value)


if __name__ == '__main__':
    unittest.main()
