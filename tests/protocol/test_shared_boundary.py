"""Shared services must import without the APP, GUI stack or MATLAB toolchain."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHECK = r'''
import importlib
import importlib.abc
import json
from pathlib import Path
import pkgutil
import sys

root = Path(sys.argv[1]).resolve()
for entry in sys.path:
    path = Path(entry).resolve()
    assert path != root
    assert not path.is_relative_to(root / 'app')
    assert not path.is_relative_to(root / 'toolchain')

forbidden = {'PySide6', 'PySide2', 'PyQt5', 'PyQt6', 'tkinter', 'matplotlib', 'qt_host', 'simrt_linux_target'}
class HeadlessOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in forbidden:
            raise AssertionError('Shared services imported a GUI/toolchain dependency: ' + fullname)
sys.meta_path.insert(0, HeadlessOnly())
import pyxcp_host
import simrt_xcp
modules = []
for package in (pyxcp_host, simrt_xcp):
    assert Path(package.__file__).resolve().is_relative_to(root / 'shared/python')
    for item in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
        if item.name.endswith('.__main__'):
            continue
        importlib.import_module(item.name)
        modules.append(item.name)
assert not forbidden.intersection(name.split('.')[0] for name in sys.modules)
print(json.dumps({'modules': modules, 'headless': True}))
'''


class SharedBoundaryTests(unittest.TestCase):
    def test_services_and_protocol_import_without_app_or_toolchain(self):
        environment = dict(os.environ, PYTHONPATH=str(ROOT / 'shared/python'), PYTHONIOENCODING='utf-8')
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', CHECK, str(ROOT)], cwd=directory,
                                    env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['headless'])
        self.assertIn('pyxcp_host.services.ssh_deployment', report['modules'])
        self.assertIn('simrt_xcp.client', report['modules'])
