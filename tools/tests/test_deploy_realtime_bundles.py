"""Offline tests for validation, isolated build outputs, and SSH orchestration."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import shlex
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_realtime_bundles as deployment


def bundle_at(path, model='model_one', period_ns=1000000):
    (path / 'src').mkdir(parents=True)
    (path / 'src' / 'ert_main.c').write_text(
        'void run(void) { myRTOSInit(' + str(period_ns / 1e9) + ', 0); ' + model + '_step(); }\n')
    (path / 'src' / 'x280_rt_runtime.c').write_text('void runtime(void) {}\n')
    (path / 'src' / (model + '.c')).write_text('void ' + model + '_step(void) {}\n')
    spec = dict(model=model, sources=['ert_main.c', 'x280_rt_runtime.c', model + '.c'],
        defines=['-DMODEL=' + model, '-DMT=0', '-DNUMST=1'],
        target='x86-64 Linux', xcp_transport='UDP', xcp_port=17725,
        runtime=dict(name='x280_single_task_rt', period_ns=period_ns, tasking='single', optimization='O2'))
    (path / 'build_spec.json').write_text(json.dumps(spec), encoding='utf-8')
    shutil.copyfile(deployment.BUILDER, path / 'build_model.py')
    return path


def elf_bytes():
    header = bytearray(64)
    header[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', header, 16, 2, 62, 1)
    struct.pack_into('<H', header, 52, 64)
    return bytes(header) + b'test executable, never run'


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = bundle_at(self.root / 'bundle')
        self.output = self.root / 'new_build'
        self.arguments = ['--bundle', str(self.bundle), '--output', str(self.output)]
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.addCleanup(patch.stopall)
        self.password = patch.object(deployment.getpass, 'getpass', return_value='test-secret').start()
        self.factory = patch.object(deployment, 'create_service').start()
        self.service = self.factory.return_value
        self.calls = []

        def construct(log):
            self.service.log = log
            return self.service

        self.factory.side_effect = construct
        self.service._execute.side_effect = self.remote_execute
        self.service.upload.side_effect = lambda *args: self.calls.append('upload') or 5
        self.service.build.side_effect = lambda *args, **kwargs: self.service.log('compiler output\n')

        def download(remote, local):
            local.write_bytes(elf_bytes())
            return local

        self.service.download_elf.side_effect = download

    def remote_execute(self, command, timeout):
        arguments = shlex.split(command)
        script, request = arguments[2], json.loads(arguments[3])
        if script == deployment._PREFLIGHT:
            self.calls.append('preflight')
            return json.dumps(dict(hostname='test-target', system='Linux', machine='x86_64',
                                  python='3.10.12', compilers={'gcc': {'target': 'x86_64-linux-gnu'}}))
        if script == deployment._RESERVE_DIRECTORIES:
            self.calls.append('reserve')
            run = '/home/custom/' + request['root'] + '/' + request['run_id']
            return json.dumps(dict(home='/home/custom', run_directory=run,
                                  directories={model: run + '/' + model for model in request['models']}))
        if script == deployment._BUILD_RESULT:
            self.calls.append('result')
            model = Path(request['directory']).name
            candidates = [self.bundle] + list(self.root.glob('*_rt_bundle'))
            bundle = next(path for path in candidates if path.is_dir()
                          and json.loads((path / 'build_spec.json').read_text())['model'] == model)
            fingerprint = deployment.builder_api().validate_bundle(bundle)[2]
            return json.dumps(dict(status='success', published=True, model=model,
                sources_hash=fingerprint, elf=model + '.elf',
                elf_sha256=hashlib.sha256(elf_bytes()).hexdigest()))
        self.fail('Unexpected remote action')

    def invoke(self, extra=(), arguments=None):
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return deployment.main((arguments or self.arguments) + list(extra))

    def report(self):
        return json.loads((self.output / 'build_report.json').read_text(encoding='utf-8'))

    def assert_no_connection(self):
        self.password.assert_not_called()
        self.factory.assert_not_called()

    def test_check_only_reads_valid_bundle_without_writes_or_password_or_network(self):
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(self.invoke(['--check-only']), 0, self.stderr.getvalue())
        self.assert_no_connection()
        self.assertFalse(self.output.exists())
        after = {str(path.relative_to(self.root)): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(json.loads(self.stdout.getvalue())['check_only'])

    def test_success_keeps_export_contract_and_records_exact_artifact_inputs(self):
        self.assertEqual(self.invoke(['--host', 'lab.example', '--user', 'custom', '--port', '2222',
                                     '--jobs', '3', '--timeout', '125', '--remote-root', 'build area/rt']), 0,
                         self.stderr.getvalue())
        report = self.report()
        self.assertTrue(report['success'])
        self.assertEqual((report['host'], report['username'], report['port']), ('lab.example', 'custom', 2222))
        self.assertEqual(report['preflight']['hostname'], 'test-target')
        self.assertEqual(self.calls, ['preflight', 'reserve', 'upload', 'result'])
        record = report['models'][0]
        self.assertEqual((record['status'], record['period_seconds'], record['payload']),
                         ('success', .001, 'model_one_payload'))
        self.assertTrue(record['remote_directory'].startswith('/home/custom/build area/rt/build_'))
        self.assertEqual(record['elf_sha256'], deployment.digest(Path(record['local_elf'])))
        self.assertEqual(record['spec_sha256'], deployment.digest(self.bundle / 'build_spec.json'))
        self.assertTrue(record['source_sha256'])
        self.assertTrue(record['source_files_sha256'])
        self.assertTrue(report['started_at'])
        self.assertTrue(report['finished_at'])
        self.assertIn('compiler output', Path(record['build_log']).read_text())
        self.assertNotIn('test-secret', json.dumps(report))
        self.service.connect.assert_called_once_with('lab.example', 'custom', password='test-secret', port=2222)
        self.service.build.assert_called_once_with(record['remote_directory'], 'python3 build_model.py --jobs 3', timeout=125)
        self.service.start.assert_not_called()
        self.service.stop.assert_not_called()
        self.service.set_autostart.assert_not_called()
        self.service.close.assert_called_once()

    def test_generation_report_builds_unique_models_in_order(self):
        names = ['model_one', 'model_two']
        for name in names:
            bundle_at(self.root / (name + '_rt_bundle'), name)
        (self.root / 'generation_report.json').write_text(json.dumps([dict(model=name) for name in names]))
        self.assertEqual(self.invoke(arguments=['--folder', str(self.root), '--output', str(self.output)]), 0,
                         self.stderr.getvalue())
        records = self.report()['models']
        self.assertEqual([item['model'] for item in records], names)
        self.assertEqual(len({item['remote_directory'] for item in records}), 2)
        self.assertEqual(self.service.upload.call_count, 2)

    def test_legacy_two_bundle_folder_selection_still_validates(self):
        bundle_at(self.root / 'single_rt_bundle', 'single')
        bundle_at(self.root / 'multirate_rt_bundle', 'multirate')
        self.assertEqual(self.invoke(['--check-only'], ['--folder', str(self.root)]), 0,
                         self.stderr.getvalue())
        self.assertEqual([item['model'] for item in json.loads(self.stdout.getvalue())['models']],
                         ['single', 'multirate'])

    def test_all_bundles_are_validated_before_connection(self):
        bundle_at(self.root / 'single_rt_bundle', 'single')
        invalid = bundle_at(self.root / 'multirate_rt_bundle', 'multirate')
        (invalid / 'src' / 'multirate.c').unlink()
        self.assertEqual(self.invoke(arguments=['--folder', str(self.root)]), 1)
        self.assert_no_connection()
        self.assertFalse((self.root / 'build_report.json').exists())

    def test_duplicate_models_are_rejected_case_insensitively(self):
        bundle_at(self.root / 'single_rt_bundle', 'same')
        bundle_at(self.root / 'multirate_rt_bundle', 'Same')
        self.assertEqual(self.invoke(arguments=['--folder', str(self.root)]), 1)
        self.assertIn('unique', self.stderr.getvalue())
        self.assert_no_connection()

    def test_invalid_model_in_manifest_cannot_escape_folder(self):
        (self.root / 'generation_report.json').write_text('[{"model":"../outside"}]')
        self.assertEqual(self.invoke(arguments=['--folder', str(self.root)]), 1)
        self.assertIn('identifier', self.stderr.getvalue())
        self.assert_no_connection()

    def test_manifest_model_must_match_bundle_model(self):
        bundle_at(self.root / 'expected_rt_bundle', 'different')
        (self.root / 'generation_report.json').write_text('[{"model":"expected"}]')
        self.assertEqual(self.invoke(arguments=['--folder', str(self.root)]), 1)
        self.assertIn('does not match bundle', self.stderr.getvalue())
        self.assert_no_connection()

    def test_invalid_rt_period_is_rejected_offline(self):
        path = self.bundle / 'build_spec.json'
        spec = json.loads(path.read_text())
        spec['runtime']['period_ns'] = 2000000
        path.write_text(json.dumps(spec))
        self.assertEqual(self.invoke(['--check-only']), 1)
        self.assert_no_connection()

    def test_old_build_script_is_rejected_before_upload(self):
        (self.bundle / 'build_model.py').write_text('raise RuntimeError("must not run")')
        self.assertEqual(self.invoke(), 1)
        self.assertIn('outdated', self.stderr.getvalue())
        self.assert_no_connection()

    def test_existing_outputs_are_preserved_without_connection(self):
        self.output.mkdir()
        for name in ('build_report.json', 'downloaded', 'build_logs'):
            with self.subTest(name=name):
                path = self.output / name
                path.write_text('original evidence')
                self.assertEqual(self.invoke(), 1)
                self.assertEqual(path.read_text(), 'original evidence')
                path.unlink()
        self.assert_no_connection()

    def test_output_inside_bundle_is_rejected(self):
        arguments = ['--bundle', str(self.bundle), '--output', str(self.bundle / 'build_run')]
        self.assertEqual(self.invoke(arguments=arguments), 1)
        self.assertIn('inside', self.stderr.getvalue())
        self.assert_no_connection()

    def test_invalid_remote_roots_do_not_connect(self):
        for value in ('/', '/home/other', '../elsewhere', '.', '~', 'C:\\temp', 'a\nb'):
            with self.subTest(value=value):
                self.assertEqual(self.invoke(['--remote-root', value]), 1)
        self.assert_no_connection()

    def test_invalid_port_timeout_and_jobs_do_not_connect(self):
        for values in (['--port', '0'], ['--port', '65536'], ['--timeout', 'nan'], ['--timeout', '0']):
            with self.subTest(values=values):
                self.assertEqual(self.invoke(values), 1)
        with self.assertRaises(SystemExit):
            self.invoke(['--jobs', '9'])
        self.assert_no_connection()

    def test_compiler_preflight_failure_records_failure_without_upload(self):
        self.service._execute.side_effect = RuntimeError('Required compiler not found: gcc')
        self.assertEqual(self.invoke(), 1)
        report = self.report()
        self.assertFalse(report['success'])
        self.assertEqual(report['models'][0]['status'], 'not_attempted')
        self.assertIn('Required compiler', report['error'])
        self.service.upload.assert_not_called()
        self.service.close.assert_called_once()

    def test_connection_failure_is_reported_and_closed(self):
        self.service.connect.side_effect = RuntimeError('SSH offline')
        self.assertEqual(self.invoke(), 1)
        self.assertIn('SSH offline', self.report()['error'])
        self.service.close.assert_called_once()
        self.service.upload.assert_not_called()

    def test_build_failure_is_reported_without_download_or_process_actions(self):
        self.service.build.side_effect = TimeoutError('Remote build timed out')
        self.assertEqual(self.invoke(), 1)
        record = self.report()['models'][0]
        self.assertEqual(record['status'], 'failed')
        self.assertFalse(record['success'])
        self.assertIn('timed out', record['error'])
        self.assertIn('timed out', Path(record['build_log']).read_text())
        self.service.download_elf.assert_not_called()
        self.service.start.assert_not_called()
        self.service.stop.assert_not_called()

    def test_modified_input_after_prompt_is_not_uploaded(self):
        def password(prompt):
            (self.bundle / 'src' / 'model_one.c').write_text('changed during password prompt')
            return 'test-secret'
        self.password.side_effect = password
        self.assertEqual(self.invoke(), 1)
        self.assertIn('changed after offline validation', self.report()['error'])
        self.service.upload.assert_not_called()

    def test_remote_report_input_mismatch_fails_before_download(self):
        execute = self.remote_execute
        def mismatch(command, timeout):
            result = json.loads(execute(command, timeout))
            if 'sources_hash' in result:
                result['sources_hash'] = 'wrong'
            return json.dumps(result)
        self.service._execute.side_effect = mismatch
        self.assertEqual(self.invoke(), 1)
        self.assertIn('does not match the validated bundle', self.report()['error'])
        self.service.download_elf.assert_not_called()

    def test_download_hash_mismatch_fails_the_run(self):
        def download(remote, local):
            local.write_bytes(elf_bytes() + b'changed')
            return local
        self.service.download_elf.side_effect = download
        self.assertEqual(self.invoke(), 1)
        self.assertIn('does not match the completed build result', self.report()['error'])
        self.assertFalse(self.report()['models'][0]['success'])

    def test_invalid_elf_is_not_accepted(self):
        def download(remote, local):
            local.write_bytes(b'not an ELF')
            return local
        self.service.download_elf.side_effect = download
        self.assertEqual(self.invoke(), 1)
        self.assertFalse(self.report()['success'])
        self.assertIn('ELF64', self.report()['error'])

    def test_close_error_does_not_erase_build_results(self):
        self.service.close.side_effect = RuntimeError('close failure')
        self.assertEqual(self.invoke(), 1)
        report = self.report()
        self.assertFalse(report['success'])
        self.assertTrue(report['models'][0]['success'])
        self.assertIn('close failure', report['cleanup_errors'][0])

    def test_initial_report_exclusive_and_updates_atomic(self):
        path = self.root / 'report.json'
        deployment.write_report(path, {'run': 1}, exclusive=True)
        with self.assertRaises(FileExistsError):
            deployment.write_report(path, {'run': 2}, exclusive=True)
        self.assertEqual(json.loads(path.read_text()), {'run': 1})
        deployment.write_report(path, {'run': 1, 'finished': True})
        self.assertTrue(json.loads(path.read_text())['finished'])
        self.assertFalse(list(self.root.glob('.build_report.*.tmp')))


if __name__ == '__main__':
    unittest.main()
