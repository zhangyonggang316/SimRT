import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pyxcp_host.services.sdi_export import (
    export_sdi_session, find_matlab_executable, launch_sdi,
)


def samples(*pairs):
    return tuple(SimpleNamespace(elapsed_seconds=stamp, value=value) for stamp, value in pairs)


class SdiExportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="SDI tester's ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def test_capture_preserves_names_values_and_independent_time_axes(self):
        snapshot = {
            "source'); error('injected'); %\n\u8f93\u51fa": samples((0.1, 3.25), (0.7, -8)),
            'Second': samples((0.2, 1), (1.3, 0)),
        }
        script = export_sdi_session(snapshot, self.root)
        capture = json.loads((script.parent / 'capture.json').read_text(encoding='utf-8'))
        self.assertEqual(capture['format'], 'pyxcp-host-sdi')
        self.assertEqual(capture['version'], 1)
        self.assertEqual(capture['signals'], [
            {'name': next(iter(snapshot)), 'time': [0.1, 0.7], 'values': [3.25, -8.0]},
            {'name': 'Second', 'time': [0.2, 1.3], 'values': [1.0, 0.0]},
        ])
        self.assertNotIn('injected', script.read_text(encoding='ascii'))

    def test_exports_are_unique_and_preserve_previous_files(self):
        snapshot = {'Signal': samples((0, 1))}
        first = export_sdi_session(snapshot, self.root)
        previous = first.read_bytes()
        second = export_sdi_session(snapshot, self.root)
        self.assertNotEqual(first.parent, second.parent)
        self.assertEqual(first.read_bytes(), previous)

    def test_empty_series_is_omitted_when_data_exists(self):
        script = export_sdi_session({'Empty': (), 'Signal': samples((0, 1))}, self.root)
        capture = json.loads((script.parent / 'capture.json').read_text())
        self.assertEqual([item['name'] for item in capture['signals']], ['Signal'])

    def test_no_data_is_rejected_before_creating_destination(self):
        for snapshot in ({}, {'Empty': ()}):
            with self.subTest(snapshot=snapshot):
                with self.assertRaisesRegex(ValueError, 'No sampled data'):
                    export_sdi_session(snapshot, self.root / 'not created')
                self.assertFalse((self.root / 'not created').exists())

    def test_invalid_signal_or_sample_is_rejected_without_writing(self):
        for snapshot in ([], {'': samples((0, 1))}, {1: samples((0, 1))},
                         {'Signal': None}, {'Signal': ((0, 1),)},
                         {'Signal': samples((0, '1'))}, {'Signal': samples((0, True))},
                         {'Signal': samples((0, 10 ** 1000))}):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                export_sdi_session(snapshot, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_nonfinite_time_and_value_are_rejected(self):
        for invalid in (math.nan, math.inf, -math.inf):
            for pair in ((invalid, 1), (0, invalid)):
                with self.subTest(pair=pair), self.assertRaisesRegex(ValueError, 'finite'):
                    export_sdi_session({'Signal': samples(pair)}, self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_negative_reversed_and_duplicate_times_are_rejected(self):
        for points in (samples((-1, 1)), samples((1, 1), (0, 2)), samples((1, 1), (1, 2))):
            with self.subTest(points=points), self.assertRaisesRegex(ValueError, 'strictly increasing'):
                export_sdi_session({'Signal': points}, self.root)

    def test_importer_uses_native_sdi_without_eval_or_clearing_user_runs(self):
        script = export_sdi_session({'Signal': samples((0, 1))}, self.root)
        content = script.read_text(encoding='ascii')
        self.assertIn("jsondecode(fileread(fullfile(captureFolder, 'capture.json')))", content)
        self.assertIn("timeseries(sampleValues, sampleTimes", content)
        self.assertIn("Simulink.sdi.createRun(char(capture.run_name), 'namevalue'", content)
        self.assertIn('captureSignal.plotOnSubPlot(1, 1, true)', content)
        self.assertIn('Simulink.sdi.view', content)
        for unsafe in ('eval(', 'evalin(', 'Simulink.sdi.clear', 'Simulink.sdi.setSubPlotLayout',
                       'Simulink.sdi.clearPreferences', 'deleteRun', 'set_param'):
            self.assertNotIn(unsafe, content)

    def test_launch_uses_argument_list_with_matlab_quoted_path_and_no_shell(self):
        script = export_sdi_session({'Signal': samples((0, 1))}, self.root)
        executable = self.root / 'MATLAB' / 'matlab.exe'
        executable.parent.mkdir()
        executable.touch()
        with patch('pyxcp_host.services.sdi_export.subprocess.Popen') as popen:
            self.assertIs(launch_sdi(script, executable), popen.return_value)
        args, kwargs = popen.call_args
        self.assertIsInstance(args[0], list)
        self.assertEqual(args[0][:4], [str(executable.resolve()), '-desktop', '-nosplash', '-r'])
        self.assertIn("run('{}')".format(str(script).replace("'", "''")), args[0][4])
        self.assertFalse(kwargs['shell'])
        self.assertEqual(kwargs['cwd'], str(script.parent))

    def test_missing_matlab_is_actionable_and_does_not_launch(self):
        script = export_sdi_session({'Signal': samples((0, 1))}, self.root)
        with patch('pyxcp_host.services.sdi_export.find_matlab_executable', return_value=None), \
                patch('pyxcp_host.services.sdi_export.subprocess.Popen') as popen:
            with self.assertRaisesRegex(FileNotFoundError, 'exported .m'):
                launch_sdi(script)
        popen.assert_not_called()
        self.assertTrue(script.is_file())

    def test_missing_or_non_matlab_script_is_rejected(self):
        wrong = self.root / 'not-script.json'
        wrong.touch()
        with patch('pyxcp_host.services.sdi_export.subprocess.Popen') as popen:
            for path in (wrong, self.root / 'missing.m'):
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, '.m file'):
                    launch_sdi(path)
        popen.assert_not_called()

    def test_matlab_discovery_prefers_path_executable(self):
        executable = self.root / 'custom' / 'matlab.exe'
        executable.parent.mkdir()
        executable.touch()
        with patch('pyxcp_host.services.sdi_export.shutil.which', return_value=str(executable)):
            self.assertEqual(find_matlab_executable(), executable.resolve())

    def test_matlab_discovery_uses_known_r2024b_install(self):
        executable = self.root / 'MATLAB' / 'R2024b' / 'bin' / 'matlab.exe'
        executable.parent.mkdir(parents=True)
        executable.touch()
        with patch.dict('os.environ', {'ProgramFiles': str(self.root)}), \
                patch('pyxcp_host.services.sdi_export.shutil.which', return_value=None):
            self.assertEqual(find_matlab_executable(), executable.resolve())

    def test_matlab_discovery_reports_absence_without_starting_a_process(self):
        with patch.dict('os.environ', {'ProgramFiles': str(self.root)}), \
                patch('pyxcp_host.services.sdi_export.shutil.which', return_value=None), \
                patch('pyxcp_host.services.sdi_export.subprocess.Popen') as popen:
            self.assertIsNone(find_matlab_executable())
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
