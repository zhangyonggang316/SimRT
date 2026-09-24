"""Offline build-driver tests; compiler/process results are explicit fixtures."""

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


TARGET = Path(__file__).resolve().parents[1]
LOADER = importlib.util.spec_from_file_location('build_model_tested', TARGET / 'tools' / 'build_model.py')
BUILD = importlib.util.module_from_spec(LOADER)
LOADER.loader.exec_module(BUILD)


def elf_bytes(elf_type=2, machine=62):
    header = bytearray(64)
    header[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', header, 16, elf_type, machine, 1)
    struct.pack_into('<H', header, 52, 64)
    return bytes(header)


class BuildModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'src').mkdir()
        self.spec = dict(model='model', sources=['model.c', 'x280_rt_runtime.c', 'x280_rt_main.c'],
                         defines=['-DMT=0', '-DNUMST=1', '-DMODEL=model'],
                         target='x86-64 Linux', xcp_transport='UDP', xcp_port=17725,
                         runtime=dict(name='x280_single_task_rt', period_ns=1000000,
                                      tasking='single', main='x280_rt_main.c', xcp_background=True))
        for name in self.spec['sources']:
            (self.root / 'src' / name).write_text('/* ' + name + ' */', encoding='utf-8')
        (self.root / 'src' / 'x280_rt_main.c').write_text(
            'int main(void) {myRTOSInit(0.001, 0); model_step(); extmodeBackgroundRun();}', encoding='utf-8')
        (self.root / 'src' / 'model.h').write_text('/* model declarations */', encoding='utf-8')
        self.write_spec()
        self.commands = []
        self.toolchain_version = 'test GCC 1'
        self.failure = None
        self.link_output = elf_bytes()
        self.after_link = None

    def write_spec(self):
        (self.root / 'build_spec.json').write_text(json.dumps(self.spec), encoding='utf-8')

    def identity(self, name, environment=None):
        return dict(path='/usr/bin/' + name if environment is None else name, version=self.toolchain_version,
                    target='x86_64-linux-gnu', sha256=self.toolchain_version)

    def execute(self, command, **kwargs):
        self.commands.append(command)
        if self.failure == ('compile' if '-c' in command else 'link'):
            raise subprocess.CalledProcessError(1, command)
        output = Path(command[command.index('-o') + 1])
        if '-c' in command:
            source = Path(command[command.index('-c') + 1])
            output.write_bytes(b'object:' + source.read_bytes())
        else:
            output.write_bytes(self.link_output)
            if self.after_link:
                self.after_link()
        return subprocess.CompletedProcess(command, 0)

    def invoke(self, *args, system='Linux'):
        output = io.StringIO()
        with patch.object(BUILD.platform, 'system', return_value=system), \
                patch.object(BUILD.platform, 'machine', return_value='x86_64'), \
                patch.object(BUILD, 'compiler_identity', side_effect=self.identity), \
                patch.object(BUILD.subprocess, 'run', side_effect=self.execute), redirect_stdout(output):
            code = BUILD.main(list(args), self.root)
        result = json.loads(output.getvalue().splitlines()[-1])
        return code, result

    def test_check_is_offline_and_never_claims_an_elf(self):
        with patch.object(BUILD.platform, 'system', return_value='Windows'), \
                patch.object(BUILD.subprocess, 'run') as execute, redirect_stdout(io.StringIO()):
            self.assertEqual(BUILD.main(['--check'], self.root), 0)
        execute.assert_not_called()
        result = json.loads((self.root / 'build_result.json').read_text())
        self.assertEqual(result['status'], 'checked')
        self.assertEqual(result['source_count'], 3)
        self.assertEqual(len(result['sources_hash']), 64)
        self.assertIsNone(result['elf_sha256'])
        self.assertFalse(result['published'])
        self.assertFalse((self.root / '.build_cache').exists())

    def test_first_build_then_reuses_verified_objects_and_relinks(self):
        code, first = self.invoke()
        self.assertEqual(code, 0, first)
        self.assertEqual((first['compiled_count'], first['reused_count']), (3, 0))
        self.assertEqual(first['elf_sha256'], BUILD.digest(self.root / 'model.elf'))
        self.assertTrue(first['published'])
        self.commands.clear()
        code, second = self.invoke()
        self.assertEqual(code, 0, second)
        self.assertEqual((second['compiled_count'], second['reused_count']), (0, 3))
        self.assertEqual(len(self.commands), 1)
        self.assertNotIn('-c', self.commands[0])

    def test_source_change_rebuilds_only_that_translation_unit(self):
        self.invoke()
        (self.root / 'src' / 'model.c').write_text('/* edited source */')
        code, result = self.invoke()
        self.assertEqual(code, 0, result)
        self.assertEqual((result['compiled_count'], result['reused_count']), (1, 2))

    def test_any_bundled_header_change_invalidates_all_objects(self):
        self.invoke()
        (self.root / 'src' / 'model.h').write_text('/* edited declarations */')
        self.assertEqual(self.invoke()[1]['compiled_count'], 3)
        (self.root / 'src' / 'extra.hpp').write_text('/* newly added header */')
        self.assertEqual(self.invoke()[1]['compiled_count'], 3)

    def test_define_and_compiler_version_changes_invalidate_all_objects(self):
        self.invoke()
        self.spec['defines'].append('-DCHANGED=1')
        self.write_spec()
        self.assertEqual(self.invoke()[1]['compiled_count'], 3)
        self.toolchain_version = 'test GCC 2'
        self.assertEqual(self.invoke()[1]['compiled_count'], 3)

    def test_flag_changes_invalidate_objects(self):
        self.invoke()
        original = BUILD.compile_flags
        with patch.object(BUILD, 'compile_flags', side_effect=lambda rt, cxx: original(rt, cxx) + ['-Wextra']):
            self.assertEqual(self.invoke()[1]['compiled_count'], 3)

    def test_rebuild_ignores_cache_without_deleting_unrelated_files(self):
        self.invoke()
        marker = self.root / '.build_cache' / 'keep.txt'
        marker.write_text('user data')
        code, result = self.invoke('--rebuild', '--jobs', '1')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['compiled_count'], 3)
        self.assertEqual(marker.read_text(), 'user data')

    def test_tampered_object_and_malformed_record_are_recompiled(self):
        self.invoke()
        next((self.root / '.build_cache').glob('*.o')).write_bytes(b'tampered')
        self.assertEqual(self.invoke()[1]['compiled_count'], 1)
        next((self.root / '.build_cache').glob('*.json')).write_text('[]')
        self.assertEqual(self.invoke()[1]['compiled_count'], 1)

    def test_realtime_flags_and_link_wrappers_are_preserved(self):
        code, result = self.invoke()
        self.assertEqual(code, 0, result)
        for command in self.commands:
            for flag in ('-g', '-O2', '-fno-pie', '-gdwarf-4', '-pthread'):
                self.assertIn(flag, command)
            self.assertNotIn('-O0', command)
        for command in self.commands[:-1]:
            self.assertIn('-std=c11', command)
        for flag in ('-no-pie', '-Wl,--wrap=sem_wait', '-Wl,--wrap=sem_post', '-lm', '-lrt', '-ldl', '-lstdc++'):
            self.assertIn(flag, self.commands[-1])

    def test_nonrealtime_keeps_original_optimization_and_no_wrappers(self):
        self.spec.pop('runtime')
        self.write_spec()
        self.assertEqual(self.invoke()[0], 0)
        for command in self.commands:
            self.assertIn('-O0', command)
            self.assertNotIn('-O2', command)
            self.assertNotIn('-Wl,--wrap=sem_wait', command)

    def test_cpp_compiles_with_gpp_but_c_runtime_stays_c11(self):
        self.spec['sources'].append('helper.cpp')
        (self.root / 'src' / 'helper.cpp').write_text('// C++ source')
        self.write_spec()
        code, result = self.invoke()
        self.assertEqual(code, 0, result)
        cpp = next(command for command in self.commands if any(arg.endswith('helper.cpp') for arg in command))
        self.assertEqual(cpp[0], '/usr/bin/g++')
        self.assertNotIn('-std=c11', cpp)
        self.assertEqual(self.commands[-1][0], '/usr/bin/g++')

    def test_compile_and_link_failures_preserve_old_elf_but_report_failure(self):
        artifact = self.root / 'model.elf'
        artifact.write_bytes(b'old delivery')
        for stage in ('compile', 'link'):
            with self.subTest(stage=stage):
                self.failure = stage
                code, result = self.invoke('--rebuild')
                self.assertEqual(code, 1)
                self.assertEqual(result['status'], 'failed')
                self.assertFalse(result['published'])
                self.assertIsNone(result['elf_sha256'])
                self.assertIsNone(result['elf'])
                self.assertEqual(artifact.read_bytes(), b'old delivery')
                self.assertFalse(list(self.root.glob('*.elf.tmp')))

    def test_rejects_pie_wrong_architecture_and_truncated_elf(self):
        for content in (elf_bytes(elf_type=3), elf_bytes(machine=183), b'\x7fELF'):
            self.link_output = content
            code, result = self.invoke()
            self.assertEqual(code, 1)
            self.assertIn('non-PIE', result['error'])
            self.assertFalse((self.root / 'model.elf').exists())

    def test_source_changes_during_build_prevent_publication(self):
        self.after_link = lambda: (self.root / 'src' / 'model.h').write_text('changed during build')
        code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn('changed during compilation', result['error'])
        self.assertFalse((self.root / 'model.elf').exists())

    def test_source_changed_while_compiling_is_not_cached_under_old_hash(self):
        original = self.execute

        def mutate(command, **kwargs):
            result = original(command, **kwargs)
            if '-c' in command and command[command.index('-c') + 1].endswith('model.c'):
                (self.root / 'src' / 'model.c').write_text('changed during compilation')
            return result

        with patch.object(self, 'execute', side_effect=mutate):
            code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn('object was not cached', result['error'])
        self.assertFalse((self.root / 'model.elf').exists())
        (self.root / 'src' / 'model.c').write_text('/* model.c */')
        self.assertEqual(self.invoke()[1]['compiled_count'], 1)

    def test_running_report_invalidates_prior_success_before_compilation(self):
        self.invoke()
        original = self.execute
        reports = []

        def inspect(command, **kwargs):
            reports.append(json.loads((self.root / 'build_result.json').read_text()))
            return original(command, **kwargs)

        with patch.object(self, 'execute', side_effect=inspect):
            self.assertEqual(self.invoke('--rebuild')[0], 0)
        self.assertTrue(reports)
        self.assertTrue(all(value['status'] == 'running' and value['elf_sha256'] is None for value in reports))

    def test_invalid_names_missing_sources_duplicates_and_definitions(self):
        original = json.loads(json.dumps(self.spec))
        changes = [('model', '../bad'), ('model', 'model.elf'), ('sources', ['../model.c']),
                   ('sources', ['sub\\model.c']), ('sources', ['missing.c']),
                   ('sources', ['model.c', 'model.c']), ('sources', []),
                   ('defines', ['-include/etc/passwd']), ('defines', ['-DMT=0', '-DMT=1']),
                   ('defines', ['-DMODEL=model\n']), ('xcp_port', True), ('xcp_port', 65536)]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.spec = dict(original, **{key: value})
                self.write_spec()
                code, result = self.invoke('--check')
                self.assertEqual(code, 1, result)
        self.assertFalse(self.commands)

    def test_runtime_contract_rejects_mismatch_period_main_or_multitasking(self):
        original = json.loads(json.dumps(self.spec))
        for runtime in ({'period_ns': 10000000}, {'period_ns': True}, {'main': 'ert_main.c'},
                        {'tasking': 'multi'}, {'xcp_background': 'true'}, {'optimization': 'O0'}):
            with self.subTest(runtime=runtime):
                self.spec = dict(original, runtime=dict(original['runtime'], **runtime))
                self.write_spec()
                self.assertEqual(self.invoke('--check')[0], 1)
        self.spec = original
        self.spec['defines'][0] = '-DMT=1'
        self.write_spec()
        self.assertEqual(self.invoke('--check')[0], 1)

    def test_all_supported_runtime_periods_are_checked_against_main(self):
        for seconds, ns in (('0.001', 1000000), ('0.01', 10000000), ('0.1', 100000000)):
            self.spec['runtime']['period_ns'] = ns
            self.write_spec()
            (self.root / 'src' / 'x280_rt_main.c').write_text(
                'int main(void) {myRTOSInit(' + seconds + ', 0); model_step(); extmodeBackgroundRun();}')
            self.assertEqual(self.invoke('--check')[0], 0)

    def test_flat_bundle_rejects_nested_directories(self):
        (self.root / 'src' / 'nested').mkdir()
        code, result = self.invoke('--check')
        self.assertEqual(code, 1)
        self.assertIn('regular file', result['error'])

    def test_source_symlink_is_rejected(self):
        source = self.root / 'src' / 'model.c'
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda path: path == source or original(path)):
            code, result = self.invoke('--check')
        self.assertEqual(code, 1)
        self.assertIn('Symbolic links', result['error'])

    def test_same_bundle_lock_prevents_collision_without_overwriting_report(self):
        self.invoke('--check')
        before = (self.root / 'build_result.json').read_bytes()
        with BUILD.bundle_lock(self.root):
            code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn('Another build/check', result['error'])
        self.assertFalse(result['report_written'])
        self.assertEqual((self.root / 'build_result.json').read_bytes(), before)
        self.assertEqual(self.invoke('--check')[0], 0)

    def test_job_boundaries_are_rejected_before_build(self):
        for jobs in ('0', '9', '-1', 'two'):
            with self.subTest(jobs=jobs), redirect_stdout(io.StringIO()), \
                    patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit) as error:
                BUILD.main(['--jobs', jobs], self.root)
            self.assertEqual(error.exception.code, 2)

    def test_default_compile_parallelism_is_bounded_at_two(self):
        counts = dict(active=0, maximum=0)
        guard = threading.Lock()
        original = self.execute

        def timed(command, **kwargs):
            if '-c' not in command:
                return original(command, **kwargs)
            with guard:
                counts['active'] += 1
                counts['maximum'] = max(counts['maximum'], counts['active'])
            time.sleep(0.03)
            try:
                return original(command, **kwargs)
            finally:
                with guard:
                    counts['active'] -= 1

        with patch.object(self, 'execute', side_effect=timed):
            code, result = self.invoke()
        self.assertEqual(code, 0, result)
        self.assertEqual(counts['maximum'], 2)

    def test_windows_missing_toolchain_fails_without_calling_compiler(self):
        with patch.object(BUILD.platform, 'system', return_value='Windows'), \
                patch.object(BUILD, 'locate_toolchain', side_effect=RuntimeError('Missing toolchain; use --check')), \
                patch.object(BUILD.subprocess, 'run') as execute, redirect_stdout(io.StringIO()):
            self.assertEqual(BUILD.main([], self.root), 1)
        execute.assert_not_called()
        self.assertIn('--check', json.loads((self.root / 'build_result.json').read_text())['error'])

    def test_wrong_compiler_target_is_rejected(self):
        compiler = self.root / 'fake-gcc'
        compiler.write_bytes(b'compiler fixture')
        with patch.object(BUILD.shutil, 'which', return_value=str(compiler)), \
                patch.object(BUILD.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 0, stdout='GCC fixture'),
                    subprocess.CompletedProcess([], 0, stdout='aarch64-linux-gnu')]):
            with self.assertRaisesRegex(RuntimeError, 'x86-64 Linux'):
                BUILD.compiler_identity('gcc')

    def portable_fixture(self):
        package = self.root / 'portable fixture'
        binary = package / 'toolchain' / 'bin'
        binary.mkdir(parents=True)
        (binary / 'linux-gcc.exe').write_bytes(b'GCC fixture')
        sysroot = package / 'toolchain' / 'x86_64-linux'
        sysroot.mkdir()
        (sysroot / 'stdio.h').write_text('/* sysroot fixture */')
        return package, sysroot

    def test_windows_compiler_uses_explicit_sysroot_and_pinned_flags(self):
        package, sysroot = self.portable_fixture()
        code, result = self.invoke('--toolchain-root', str(package), system='Windows')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['toolchain']['mode'], 'windows-cross')
        self.assertEqual(result['toolchain']['sysroot'], str(sysroot))
        self.assertEqual(len(result['toolchain']['sysroot_sha256']), 64)
        for command in self.commands:
            self.assertEqual(command[0], str(package / 'toolchain' / 'bin' / 'linux-gcc.exe'))
            self.assertIn('--sysroot=' + sysroot.as_posix(), command)
            self.assertIn('-O2', command)
            self.assertIn('-gdwarf-4', command)
        self.assertIn('-no-pie', result['link_command'])
        self.assertEqual(len(result['compile_commands']), 3)
        self.assertTrue(all(item['command'] and len(item['sha256']) == 64 for item in result['compile_commands']))

    def test_changed_sysroot_and_compiler_support_invalidate_cached_objects(self):
        package, sysroot = self.portable_fixture()
        self.assertEqual(self.invoke('--toolchain-root', str(package), system='Windows')[1]['compiled_count'], 3)
        self.assertEqual(self.invoke('--toolchain-root', str(package), system='Windows')[1]['reused_count'], 3)
        (sysroot / 'stdio.h').write_text('/* changed sysroot */')
        self.assertEqual(self.invoke('--toolchain-root', str(package), system='Windows')[1]['compiled_count'], 3)
        (package / 'toolchain' / 'cc1.exe').write_bytes(b'new compiler support')
        self.assertEqual(self.invoke('--toolchain-root', str(package), system='Windows')[1]['compiled_count'], 3)

    def test_portable_environment_drops_host_gcc_search_paths(self):
        with patch.dict(BUILD.os.environ, {'Path': 'unrelated toolchain', 'GCC_EXEC_PREFIX': '/other',
                'cpath': '/other/include', 'LIBRARY_PATH': '/other/lib', 'SystemRoot': 'C:/Windows'}, clear=True):
            before = dict(BUILD.os.environ)
            environment = BUILD.portable_environment(Path('portable fixture'))
            self.assertEqual(dict(BUILD.os.environ), before)
        self.assertFalse(set(key.upper() for key in environment) & set(BUILD.GCC_ENVIRONMENT))
        self.assertNotIn('unrelated toolchain', environment['PATH'])
        self.assertIn('System32', environment['PATH'])

    def test_elf_dependencies_extract_dynamic_libraries_without_executing_target(self):
        content = bytearray(512)
        content[:64] = elf_bytes()
        struct.pack_into('<Q', content, 32, 64)
        struct.pack_into('<HH', content, 54, 56, 3)
        struct.pack_into('<IIQQQQQQ', content, 64, 1, 5, 0, 0x400000, 0, 512, 512, 4096)
        interpreter = b'/lib64/ld-linux-x86-64.so.2\0'
        struct.pack_into('<IIQQQQQQ', content, 120, 3, 4, 256, 0x400100, 0, len(interpreter), len(interpreter), 1)
        struct.pack_into('<IIQQQQQQ', content, 176, 2, 6, 320, 0x400140, 0, 64, 64, 8)
        content[256:256 + len(interpreter)] = interpreter
        for index, (tag, value) in enumerate(((1, 1), (5, 0x400190), (10, 11), (0, 0))):
            struct.pack_into('<qQ', content, 320 + index * 16, tag, value)
        content[400:411] = b'\0libc.so.6\0'
        artifact = self.root / 'dependencies.elf'
        artifact.write_bytes(content)
        with patch.object(BUILD.subprocess, 'run') as execute:
            self.assertEqual(BUILD.elf_dependencies(artifact), dict(
                interpreter='/lib64/ld-linux-x86-64.so.2', needed_libraries=['libc.so.6']))
        execute.assert_not_called()
        struct.pack_into('<Q', content, 400 - 64 + 8, 0x900000)
        artifact.write_bytes(content)
        with self.assertRaisesRegex(ValueError, 'string table'):
            BUILD.elf_dependencies(artifact)


if __name__ == '__main__':
    unittest.main()
