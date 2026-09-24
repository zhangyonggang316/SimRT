import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from pyxcp_host.services.model_autostart import _AUTOSTART_HELPER, _RUNNER, UNIT_NAME
from pyxcp_host.services.ssh_deployment import SSHDeployment


class AutostartTransportTests(unittest.TestCase):
    def test_autostart_paths_and_arguments_are_json_not_shell_or_unit_text(self):
        service = SSHDeployment()
        service._begin = Mock()
        path = "/home/test/two words/a%h'; $(literal).elf"
        service._request = Mock(return_value={'elf_path': path})
        service._execute = Mock(return_value=json.dumps({'enabled': True, 'elf_path': path}))
        service.set_autostart('project/a.elf', '--name "two words" "$(literal)"')
        words = shlex.split(service._execute.call_args.args[0])
        self.assertEqual(words[:2], ['python3', '-c'])
        self.assertEqual(words[2], _AUTOSTART_HELPER)
        payload = json.loads(words[3])
        self.assertEqual(payload['elf_path'], path)
        self.assertEqual(payload['arguments'], ['--name', 'two words', '$(literal)'])
        self.assertEqual(payload['runner'], _RUNNER)
        self.assertEqual(service._execute.call_args.kwargs['timeout'], 45.0)

    def test_disable_does_not_inspect_or_stop_a_process(self):
        service = SSHDeployment()
        service._begin = Mock()
        service._request = Mock()
        service._execute = Mock(return_value='{"enabled": false}')
        self.assertFalse(service.set_autostart(None)['enabled'])
        service._request.assert_not_called()

    def test_password_login_never_uses_key_or_agent(self):
        client = Mock()
        service = SSHDeployment()
        service._request = Mock(return_value={'home': '/home/test'})
        with patch('pyxcp_host.services.ssh_deployment.paramiko.SSHClient', return_value=client), \
                patch.object(Path, 'is_file', return_value=False):
            service.connect('ubuntu', 'test', 'example')
        options = client.connect.call_args.kwargs
        self.assertFalse(options['allow_agent'])
        self.assertFalse(options['look_for_keys'])
        self.assertNotIn('key_filename', options)
        self.assertEqual(options['password'], 'example')

    def test_empty_password_and_explicit_keys_are_rejected(self):
        for password, key in (('', ''), ('example', 'key')):
            with self.subTest(password=bool(password), key=key), self.assertRaises(ValueError):
                SSHDeployment().connect('ubuntu', 'test', password, key_filename=key)

    def test_remote_scripts_compile(self):
        compile(_AUTOSTART_HELPER, '<autostart>', 'exec')
        compile(_RUNNER, '<runner>', 'exec')


class AutostartHelperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.home = Path(self.directory.name).resolve()
        self.helper = {'__name__': 'autostart_tests'}
        pwd = types.SimpleNamespace(getpwuid=lambda uid: types.SimpleNamespace(pw_name='test'))
        with patch.object(Path, 'home', return_value=self.home), patch.dict(sys.modules, pwd=pwd):
            exec(compile(_AUTOSTART_HELPER, '<autostart>', 'exec'), self.helper)
        self.enabled = False
        self.linger = True
        self.calls = []
        self.fail_enable = False
        self.helper['run'] = self.fake_run
        self.uid_patch = patch.object(os, 'getuid', return_value=1000, create=True)
        self.uid_patch.start()
        self.elf = self.home / 'models' / "two words%h'$.elf"
        self.elf.parent.mkdir()
        self.elf.write_bytes(b'\x7fELFpayload')

    def tearDown(self):
        self.uid_patch.stop()
        self.directory.cleanup()

    def fake_run(self, args, required=True):
        self.calls.append(args)
        if args[0] == 'loginctl':
            return types.SimpleNamespace(returncode=0, stdout='yes\n' if self.linger else 'no\n')
        operation = args[4]
        if operation == 'is-enabled':
            return types.SimpleNamespace(returncode=0 if self.enabled else 1,
                                         stdout='enabled\n' if self.enabled else 'disabled\n')
        if operation == 'enable':
            if self.fail_enable:
                self.fail_enable = False
                raise RuntimeError('Enable failed')
            self.enabled = True
        elif operation == 'disable':
            self.enabled = False
        return types.SimpleNamespace(returncode=0, stdout='')

    def configure(self, elf=None):
        return self.helper['configure'](dict(elf_path=str(elf or self.elf),
                                              arguments=['--arg', 'two words', '$(literal)'], runner=_RUNNER))

    def test_one_named_unit_replaces_selection_without_starting_or_stopping(self):
        first = self.configure()
        second = self.elf.with_name('other.elf')
        second.write_bytes(b'\x7fELFother')
        result = self.configure(second)
        self.assertTrue(first['enabled'])
        self.assertTrue(result['enabled'])
        self.assertEqual(result['elf_path'], str(second))
        units = list((self.home / '.config' / 'systemd' / 'user').iterdir())
        self.assertEqual([path.name for path in units], [UNIT_NAME])
        text = units[0].read_text()
        self.assertNotIn(str(second), text)
        self.assertNotIn('$(literal)', text)
        self.assertIn('Restart=no', text)
        self.assertFalse(any('start' in args or 'stop' in args or '--now' in args for args in self.calls))

    def test_missing_linger_fails_before_writing(self):
        self.linger = False
        with self.assertRaisesRegex(RuntimeError, 'sudo loginctl enable-linger test'):
            self.configure()
        self.assertFalse(self.helper['config'].exists())
        self.assertFalse(self.helper['unit'].exists())

    def test_unrelated_unit_is_never_overwritten_or_disabled(self):
        unit = self.helper['unit']
        unit.parent.mkdir(parents=True)
        original = '[Service]\nExecStart=/usr/bin/other\n'
        unit.write_text(original)
        with self.assertRaisesRegex(RuntimeError, 'unrelated service'):
            self.configure()
        self.assertEqual(unit.read_text(), original)
        self.assertFalse(self.calls)

    def test_disable_preserves_files_and_running_process(self):
        self.configure()
        self.calls.clear()
        result = self.helper['configure']({'elf_path': ''})
        self.assertFalse(result['enabled'])
        self.assertTrue(self.helper['unit'].exists())
        self.assertTrue(self.helper['config'].exists())
        self.assertFalse(any('stop' in args or '--now' in args for args in self.calls))

    def test_failed_replacement_rolls_back_previous_selection_and_enabled_state(self):
        self.configure()
        original = self.helper['config'].read_bytes()
        self.fail_enable = True
        other = self.elf.with_name('second.elf')
        other.write_bytes(b'\x7fELFother')
        with self.assertRaisesRegex(RuntimeError, 'Enable failed'):
            self.configure(other)
        self.assertEqual(self.helper['config'].read_bytes(), original)
        self.assertTrue(self.enabled)

    def test_failed_first_enable_removes_only_created_files(self):
        self.fail_enable = True
        with self.assertRaisesRegex(RuntimeError, 'Enable failed'):
            self.configure()
        self.assertFalse(self.helper['config'].exists())
        self.assertFalse(self.helper['unit'].exists())
        self.assertTrue(self.elf.exists())
        self.assertFalse(self.enabled)

    def test_outside_home_and_symlink_paths_rejected(self):
        with self.assertRaisesRegex(ValueError, 'below the SSH home'):
            self.helper['safe_file'](self.home.parent / 'outside')
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                self.helper['safe_file'](self.elf)


if __name__ == '__main__':
    unittest.main()
