"""Check module ownership without a GUI, MATLAB installation or target machine."""

import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ModuleBoundaryTests(unittest.TestCase):
    def test_shared_services_import_without_gui_or_toolchain(self):
        script = r'''
import importlib.abc
import sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'qt_host', 'PySide6', 'matplotlib', 'matlab'}:
            raise AssertionError('Forbidden service dependency: ' + fullname)
sys.meta_path.insert(0, Boundary())
from pyxcp_host.services.ssh_deployment import SSHDeployment
from pyxcp_host.services.network_configuration import NetworkConfiguration
from pyxcp_host.services.model_payload import validate_payload
import simrt_xcp.a2l
assert 'qt_host' not in sys.modules
'''
        environment = dict(os.environ, PYTHONPATH=str(ROOT / 'shared' / 'python'))
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT / 'shared',
                                env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_source_does_not_import_product_or_tests(self):
        forbidden = {'qt_host', 'PySide6', 'matplotlib', 'matlab', 'tests'}
        for source in (ROOT / 'shared' / 'python').rglob('*.py'):
            tree = ast.parse(source.read_text(encoding='utf-8-sig'), filename=str(source))
            for item in ast.walk(tree):
                names = []
                if isinstance(item, ast.Import):
                    names = [alias.name for alias in item.names]
                elif isinstance(item, ast.ImportFrom) and not item.level:
                    names = [item.module or '']
                for name in names:
                    self.assertNotIn(name.split('.')[0], forbidden, str(source))

    def test_linux_maintenance_entrypoints_are_independent(self):
        environment = dict(os.environ)
        environment.pop('PYTHONPATH', None)
        for script in sorted((ROOT / 'linux' / 'tools').glob('*.py')):
            with self.subTest(script=script.name):
                text = script.read_text(encoding='utf-8-sig')
                self.assertNotIn('app/qt_xcp_host', text)
                result = subprocess.run([sys.executable, str(script), '--help'],
                                        cwd=ROOT / 'linux', env=environment,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
