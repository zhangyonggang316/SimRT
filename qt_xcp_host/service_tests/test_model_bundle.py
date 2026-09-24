"""Local command construction checks; these do not claim a native Linux build."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = PROJECT_ROOT / 'x280_linux_target' / 'tools' / 'build_model.py'
MODULE_SPEC = importlib.util.spec_from_file_location('model_bundle_builder', BUILD_SCRIPT)
BUILDER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(BUILDER)


class ModelBundleBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='pyxcp-model-bundle-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'src').mkdir()
        (self.root / 'src' / 'model.c').write_text('int main(void) { return 0; }', encoding='ascii')
        self.spec = {'model': 'demo', 'sources': ['model.c'],
                     'defines': ['-DMODEL=demo', '-DEXT_MODE=1']}
        for target, value in (('platform.system', 'Linux'),
                              ('platform.machine', 'x86_64')):
            owner, name = target.split('.')
            patcher = patch.object(getattr(BUILDER, owner), name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        identity_patch = patch.object(BUILDER, 'compiler_identity', return_value={
            'path': '/usr/bin/gcc', 'version': 'fixture GCC',
            'target': 'x86_64-linux-gnu', 'sha256': 'fixture-only'})
        self.identity = identity_patch.start()
        self.addCleanup(identity_patch.stop)
        self.run_patch = patch.object(BUILDER.subprocess, 'run', side_effect=self.fake_compile)
        self.run = self.run_patch.start()
        self.addCleanup(self.run_patch.stop)

    def fake_compile(self, command, **kwargs):
        output = Path(command[command.index('-o') + 1])
        if '-c' in command:
            output.write_bytes(b'fixture object')
        else:
            header = bytearray(64)
            header[:7] = b'\x7fELF\x02\x01\x01'
            struct.pack_into('<HHI', header, 16, 2, 62, 1)
            struct.pack_into('<H', header, 52, 64)
            output.write_bytes(header)
        return subprocess.CompletedProcess(command, 0)

    def build(self):
        (self.root / 'build_spec.json').write_text(json.dumps(self.spec), encoding='utf-8')
        output = io.StringIO()
        with redirect_stdout(output):
            code = BUILDER.main(argv=[], root=self.root)
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(result, json.loads((self.root / 'build_result.json').read_text(encoding='utf-8')))
        return code, result

    def assert_rejected(self, message):
        code, result = self.build()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn(message, result['error'])
        self.assertFalse(result['published'])
        self.assertIsNone(result['elf'])
        self.assertIsNone(result['elf_sha256'])
        self.assertFalse((self.root / 'demo.elf').exists())
        self.identity.assert_not_called()
        self.run.assert_not_called()

    def test_native_c_command_uses_absolute_paths_and_fixed_addresses(self):
        code, result = self.build()
        self.assertEqual(code, 0, result)
        self.assertEqual(self.run.call_count, 2)
        compile_command = self.run.call_args_list[0].args[0]
        link_command = self.run.call_args_list[1].args[0]
        for call in self.run.call_args_list:
            self.assertEqual(call.args[0][0], '/usr/bin/gcc')
            self.assertIn('-fno-pie', call.args[0])
            self.assertIn('-g', call.args[0])
            self.assertEqual(call.kwargs, {'cwd': self.root, 'env': None, 'check': True})
        self.assertIn('-c', compile_command)
        self.assertIn(str(self.root / 'src' / 'model.c'), compile_command)
        self.assertIn('-DMODEL=demo', compile_command)
        self.assertIn('-no-pie', link_command)
        self.assertTrue(any(Path(arg).suffix == '.o' for arg in link_command))
        staged_elf = Path(link_command[link_command.index('-o') + 1])
        self.assertEqual(staged_elf.parent, self.root)
        self.assertNotEqual(staged_elf, self.root / 'demo.elf')
        self.assertFalse(staged_elf.exists())
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['published'])
        self.assertEqual(result['elf'], 'demo.elf')
        self.assertEqual(result['elf_sha256'], BUILDER.digest(self.root / 'demo.elf'))
        self.assertEqual((result['compiled_count'], result['reused_count']), (1, 0))
        BUILDER.validate_elf(self.root / 'demo.elf')

    def test_unsupported_host_is_rejected_before_compiler_launch(self):
        with patch.object(BUILDER.platform, 'system', return_value='Darwin'):
            self.assert_rejected('x86-64 Linux')

    def test_non_x86_architecture_is_rejected(self):
        with patch.object(BUILDER.platform, 'machine', return_value='aarch64'):
            self.assert_rejected('x86-64 Linux')

    def test_empty_sources_are_rejected(self):
        self.spec['sources'] = []
        self.assert_rejected('nonempty source list')

    def test_missing_source_is_rejected(self):
        self.spec['sources'] = ['missing.c']
        self.assert_rejected('Missing regular file')

    def test_parent_source_path_is_rejected(self):
        self.spec['sources'] = ['../model.c']
        self.assert_rejected('Invalid flat source path')

    def test_parent_output_path_is_rejected(self):
        self.spec['model'] = '../outside'
        self.assert_rejected('Invalid model identifier')

    def test_compile_failure_returns_nonzero_and_preserves_old_elf(self):
        artifact = self.root / 'demo.elf'
        artifact.write_bytes(b'previous delivery')
        self.run.side_effect = subprocess.CalledProcessError(1, ['gcc'])
        code, result = self.build()
        self.assertEqual(code, 1)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('CalledProcessError', result['error'])
        self.assertFalse(result['published'])
        self.assertIsNone(result['elf_sha256'])
        self.assertIsNone(result['elf'])
        self.assertEqual(artifact.read_bytes(), b'previous delivery')
        self.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
