import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


TARGET = Path(__file__).resolve().parents[2] / 'toolchain' / 'simrt_linux_target'
LOADER = importlib.util.spec_from_file_location('enable_rt', TARGET / 'tools' / 'enable_realtime_bundle.py')
RT = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(RT)


class RealtimeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.source = self.folder / 'original'
        (self.source / 'src').mkdir(parents=True)
        self.main = 'void main(void) {myRTOSInit(0.001, 0); sem_wait(&baserateTaskSem); model_step();}'
        (self.source / 'src' / 'ert_main.c').write_text(self.main)
        (self.source / 'src' / 'linuxinitialize.c').write_text('/* original scheduler */')
        (self.source / 'src' / 'model.c').write_text('void model_step(void) {rtExtModeUpload(0, model_time);}')
        self.spec = dict(model='model', sources=['ert_main.c', 'linuxinitialize.c', 'model.c'],
                         defines=['-DMT=0', '-DNUMST=1', '-DMW_SCHED_OTHER'], matlab_release='2024b', target='x86-64 Linux')
        self.write_spec()
        self.output = self.folder / 'rt'

    def tearDown(self):
        self.temporary.cleanup()

    def write_spec(self):
        (self.source / 'build_spec.json').write_text(json.dumps(self.spec))

    def test_live_status_wait_uses_monotonic_condition_clock(self):
        RT.enable_realtime_bundle(self.source, self.output)
        runtime = (self.output / 'src' / 'simrt_rt_runtime.c').read_text()
        self.assertIn('pthread_condattr_setclock(&clock_attributes, CLOCK_MONOTONIC)', runtime)
        self.assertIn('pthread_cond_init(&status_wait_condition, &clock_attributes)', runtime)
        self.assertIn('clock_gettime(CLOCK_MONOTONIC, &deadline)', runtime)
        self.assertNotIn('clock_gettime(CLOCK_REALTIME, &deadline)', runtime)

    def test_generated_sources_unchanged_runtime_selected_and_archived(self):
        before = {str(path.relative_to(self.source)): RT.digest(path) for path in self.source.rglob('*') if path.is_file()}
        RT.enable_realtime_bundle(self.source, self.output)
        after = {str(path.relative_to(self.source)): RT.digest(path) for path in self.source.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual((self.output / 'src' / 'ert_main.c').read_text(), self.main)
        spec = json.loads((self.output / 'build_spec.json').read_text())
        self.assertNotIn('linuxinitialize.c', spec['sources'])
        self.assertIn('simrt_rt_runtime.c', spec['sources'])
        self.assertIn('simrt_rt_main.c', spec['sources'])
        self.assertNotIn('ert_main.c', spec['sources'])
        self.assertNotIn('-DMW_SCHED_OTHER', spec['defines'])
        self.assertEqual(spec['runtime']['period_ns'], 1000000)
        manifest = json.loads((self.output / 'realtime_manifest.json').read_text())
        self.assertEqual(manifest['original_build_spec'], self.spec)
        self.assertTrue(manifest['model_sources_unchanged'])
        self.assertTrue(manifest['generated_main_preserved_but_not_compiled'])
        main = (self.output / 'src' / 'simrt_rt_main.c').read_text()
        self.assertNotIn('@MODEL@', main)
        self.assertNotIn('@PERIOD_SECONDS@', main)
        self.assertNotIn('@NUM_SAMPLE_TIMES@', main)
        self.assertNotIn('extmodeEvent(', main)
        self.assertNotIn('rtExtModeOneStep(', main)
        self.assertIn('extmodeBackgroundRun()', main)
        self.assertIn('simrt_rt_step_begin();\n        model_step();\n        simrt_rt_step_end();', main)
        with zipfile.ZipFile(self.output / 'sources.zip') as archive:
            self.assertIn('src/simrt_rt_runtime.c', archive.namelist())
            self.assertEqual(archive.read('src/ert_main.c').decode(), self.main)

    def test_existing_output_and_nested_output_are_rejected(self):
        self.output.mkdir()
        marker = self.output / 'keep.txt'
        marker.write_text('user delivery')
        with self.assertRaises(FileExistsError):
            RT.enable_realtime_bundle(self.source, self.output)
        self.assertEqual(marker.read_text(), 'user delivery')
        with self.assertRaises(ValueError):
            RT.enable_realtime_bundle(self.source, self.source / 'nested')

    def test_wrong_period_and_subrate_threads_rejected(self):
        for main in (self.main.replace('0.001', '0.005'), self.main.replace('0.001, 0', '0.001, 1')):
            (self.source / 'src' / 'ert_main.c').write_text(main)
            with self.subTest(main=main), self.assertRaisesRegex(ValueError, 'myRTOSInit'):
                RT.enable_realtime_bundle(self.source, self.output)
            self.assertFalse(self.output.exists())

    def test_supported_periods_come_from_generated_main(self):
        for seconds, nanoseconds in (('0.001', 1000000), ('0.01', 10000000), ('0.1', 100000000)):
            with self.subTest(seconds=seconds):
                (self.source / 'src' / 'ert_main.c').write_text(self.main.replace('0.001', seconds))
                output = self.folder / ('period_' + seconds)
                RT.enable_realtime_bundle(self.source, output)
                spec = json.loads((output / 'build_spec.json').read_text())
                self.assertEqual(spec['runtime']['period_ns'], nanoseconds)
                self.assertIn('myRTOSInit(' + seconds + ', 0)', (output / 'src' / 'simrt_rt_main.c').read_text())

    def test_missing_generated_upload_is_rejected(self):
        (self.source / 'src' / 'model.c').write_text('void model_step(void) {}')
        with self.assertRaisesRegex(ValueError, 'in-step'):
            RT.enable_realtime_bundle(self.source, self.output)

    def test_bounded_daq_pool_replaces_small_generated_count(self):
        self.spec['defines'] += ['-DXCP_MEM_DAQ_RESERVED_POOL_BLOCKS_NUMBER=3']
        self.write_spec()
        RT.enable_realtime_bundle(self.source, self.output)
        spec = json.loads((self.output / 'build_spec.json').read_text())
        defines = spec['defines']
        self.assertNotIn('-DXCP_MEM_DAQ_RESERVED_POOL_BLOCKS_NUMBER=3', defines)
        self.assertIn('-DXCP_MEM_DAQ_RESERVED_POOL_BLOCKS_NUMBER=1024', defines)
        self.assertIn('-DXCP_MEM_RESERVED_POOLS_TOTAL_SIZE=1048576', defines)
        self.assertEqual(spec['runtime']['daq_reserved_blocks'], 1024)
        self.assertEqual(spec['runtime']['xcp_reserved_pool_bytes'], 1048576)

    def test_multitask_and_release_contracts_rejected(self):
        for key, value in (('defines', ['-DMT=1']), ('matlab_release', '2023b'), ('runtime', {})):
            changed = dict(self.spec)
            changed[key] = value
            (self.source / 'build_spec.json').write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(ValueError):
                RT.enable_realtime_bundle(self.source, self.output)

    def test_runtime_metadata_cannot_disagree_with_compiler_defines(self):
        loader = importlib.util.spec_from_file_location('build_rt_check', TARGET / 'tools' / 'build_model.py')
        builder = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(builder)
        RT.enable_realtime_bundle(self.source, self.output)
        builder.validate_bundle(self.output)
        path = self.output / 'build_spec.json'
        original = json.loads(path.read_text())
        for name in ('daq_reserved_blocks', 'xcp_reserved_pool_bytes'):
            changed = dict(original, runtime=dict(original['runtime']))
            changed['runtime'][name] //= 2
            path.write_text(json.dumps(changed))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'does not match compiler'):
                builder.validate_bundle(self.output)

    def test_staging_failure_does_not_leave_partial_delivery(self):
        with patch.object(RT.zipfile, 'ZipFile', side_effect=OSError('archive failed')):
            with self.assertRaisesRegex(OSError, 'archive failed'):
                RT.enable_realtime_bundle(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.folder.iterdir()), [self.source])


if __name__ == '__main__':
    unittest.main()
