"""Local build orchestration preserves source bundles and verifies publication."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
SPECIFICATION = importlib.util.spec_from_file_location('local_build_tested', ROOT / 'tools' / 'build_local_bundles.py')
LOCAL = importlib.util.module_from_spec(SPECIFICATION)
SPECIFICATION.loader.exec_module(LOCAL)


class LocalBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / 'model_rt_bundle'
        self.bundle.mkdir()
        (self.bundle / 'src').mkdir()
        self.spec = dict(model='model', sources=['model.c', 'x280_rt_runtime.c', 'x280_rt_main.c'],
            defines=['-DMT=0', '-DNUMST=1', '-DMODEL=model'], target='x86-64 Linux',
            xcp_transport='UDP', xcp_port=17725, runtime=dict(name='x280_single_task_rt',
            period_ns=1000000, tasking='single', main='x280_rt_main.c', xcp_background=True))
        for name in self.spec['sources']:
            (self.bundle / 'src' / name).write_text('/* source */')
        (self.bundle / 'src' / 'x280_rt_main.c').write_text(
            'int main(void) {myRTOSInit(0.001, 0); model_step(); extmodeBackgroundRun();}')
        (self.bundle / 'build_spec.json').write_text(json.dumps(self.spec))
        (self.bundle / 'build_model.py').write_text('raise RuntimeError("old supplied script must not execute")')
        self.output = self.root / 'output'
        self.commands = []

    def fake_build(self, command, directory, stream, timeout):
        self.commands.append(command)
        self.assertEqual((directory / 'build_model.py').read_bytes(), LOCAL.BUILDER.read_bytes())
        validator = LOCAL.builder_api()
        spec, _, fingerprint = validator.validate_bundle(directory)
        content = bytearray(64)
        content[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHI', content, 16, 2, 62, 1)
        struct.pack_into('<H', content, 52, 64)
        artifact = directory / (spec['model'] + '.elf')
        artifact.write_bytes(content)
        (directory / 'build_result.json').write_text(json.dumps(dict(status='success', published=True,
            model=spec['model'], sources_hash=fingerprint, elf=artifact.name, elf_sha256=validator.digest(artifact))))

    def invoke(self, *extra, folder=False, execute=None):
        selection = ['--folder', str(self.root)] if folder else ['--bundle', str(self.bundle)]
        with patch.object(LOCAL, 'execute_build', side_effect=execute or self.fake_build), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = LOCAL.main(selection + ['--output', str(self.output), '--host', '192.0.2.5'] + list(extra))
        report = self.output / 'build_report.json'
        return code, json.loads(report.read_text()) if report.is_file() else None

    def test_builds_copied_sources_and_publishes_matching_elf_for_a2l(self):
        before = {path.relative_to(self.bundle): path.read_bytes() for path in self.bundle.rglob('*') if path.is_file()}
        code, report = self.invoke('--toolchain-root', str(self.root / 'portable compiler'), '--jobs', '3')
        self.assertEqual(code, 0, report)
        self.assertTrue(report['success'])
        self.assertEqual(report['host'], '192.0.2.5')
        self.assertFalse(report['remote_operations_performed'])
        record = report['models'][0]
        self.assertTrue(record['success'])
        self.assertEqual(Path(record['local_elf']), self.output / 'built' / 'model.elf')
        self.assertEqual(record['elf_sha256'], LOCAL.builder_api().digest(record['local_elf']))
        self.assertIn('--toolchain-root', record['command'])
        self.assertNotIn('192.0.2.5', record['command'])
        self.assertEqual(before, {path.relative_to(self.bundle): path.read_bytes() for path in self.bundle.rglob('*') if path.is_file()})
        self.assertFalse((self.output / 'downloaded').exists())

    def test_folder_reads_generation_report_and_rejects_model_mismatch(self):
        generation = self.root / 'generation_report.json'
        generation.write_text(json.dumps([dict(model='model')]))
        self.assertEqual(self.invoke('--check-only', folder=True)[0], 0)
        self.spec['model'] = 'other'
        (self.bundle / 'build_spec.json').write_text(json.dumps(self.spec))
        self.assertEqual(self.invoke('--check-only', folder=True)[0], 1)
        self.assertFalse(self.output.exists())

    def test_check_only_never_creates_outputs_or_invokes_a_compiler(self):
        def reject(*_):
            self.fail('Check-only must not execute a build')
        code, report = self.invoke('--check-only', execute=reject)
        self.assertEqual(code, 0)
        self.assertIsNone(report)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.bundle / 'build_result.json').exists())

    def test_existing_output_is_preserved(self):
        self.invoke()
        before = (self.output / 'build_report.json').read_bytes()
        code, _ = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual((self.output / 'build_report.json').read_bytes(), before)
        self.assertEqual(len(self.commands), 1)

    def test_bad_elf_hash_blocks_publication(self):
        def corrupt(command, directory, stream, timeout):
            self.fake_build(command, directory, stream, timeout)
            with (directory / 'model.elf').open('ab') as target:
                target.write(b'changed after result')
        code, report = self.invoke(execute=corrupt)
        self.assertEqual(code, 1)
        self.assertFalse(report['success'])
        self.assertIn('ELF does not match', report['error'])
        self.assertFalse((self.output / 'built' / 'model.elf').exists())

    def test_failed_compiler_report_is_retained_without_publishing(self):
        def failure(command, directory, stream, timeout):
            (directory / 'build_result.json').write_text(json.dumps(dict(status='failed', error='fixture compiler error')))
            raise subprocess.CalledProcessError(1, command)
        code, report = self.invoke(execute=failure)
        self.assertEqual(code, 1)
        self.assertFalse(report['models'][0]['success'])
        self.assertEqual(report['models'][0]['build_result']['error'], 'fixture compiler error')
        self.assertFalse((self.output / 'built' / 'model.elf').exists())

    def test_input_change_during_copy_is_rejected_before_compilation(self):
        original = LOCAL.shutil.copytree
        def corrupt(source, destination):
            original(source, destination)
            (destination / 'model.c').write_text('/* inconsistent source */')
        with patch.object(LOCAL.shutil, 'copytree', side_effect=corrupt):
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn('Copied bundle', report['error'])
        self.assertFalse(self.commands)

    def test_interrupted_elf_copy_does_not_publish_a_partial_executable(self):
        def interrupted(source, destination):
            destination.write(source.read(7))
            raise OSError('fixture disk error')
        with patch.object(LOCAL.shutil, 'copyfileobj', side_effect=interrupted):
            code, report = self.invoke()
        self.assertEqual(code, 1)
        self.assertFalse(report['success'])
        self.assertFalse(list((self.output / 'built').iterdir()))

    def test_bundle_requires_output_and_output_cannot_be_inside_bundle(self):
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(LOCAL.main(['--bundle', str(self.bundle)]), 1)
            self.assertEqual(LOCAL.main(['--bundle', str(self.bundle), '--output', str(self.bundle / 'nested')]), 1)
        self.assertFalse((self.bundle / 'nested').exists())

    def test_timeout_terminates_windows_compiler_process_tree(self):
        process = Mock(pid=12345)
        process.wait.side_effect = [subprocess.TimeoutExpired(['builder'], 2), 1]
        process.poll.return_value = None
        with patch.object(LOCAL.os, 'name', 'nt'), patch.object(LOCAL.subprocess, 'Popen', return_value=process), \
                patch.object(LOCAL.subprocess, 'run') as terminate, \
                self.assertRaises(subprocess.TimeoutExpired):
            LOCAL.execute_build(['builder'], self.root, io.StringIO(), 2)
        self.assertEqual(terminate.call_args.args[0], ['taskkill', '/PID', '12345', '/T', '/F'])
        self.assertEqual(process.wait.call_count, 2)


if __name__ == '__main__':
    unittest.main()
