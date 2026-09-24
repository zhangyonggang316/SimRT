import argparse
import ast
import importlib.util
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pyxcp
from pyxcp.scripts.xcp_examples import copy_files_from_package


class InstalledPyXcpExamplesTest(unittest.TestCase):
    def test_unmodified_official_skeleton_executes_over_tcp_and_udp(self):
        workspace = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            'pyxcp_loopback_validation',
            workspace / 'validation' / 'pyxcp_02232' / 'validate_pyxcp_02232.py',
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class ExampleSlave(module.LoopbackXcpSlave):
            def __init__(self, protocol):
                super().__init__(protocol)
                self.commands = []

            def _handle_packet(self, packet):
                self.commands.append(packet[0])
                if packet[0] == 0xFA:  # GET_ID, inline identifier.
                    identifier = b'pyXCP official example loopback'
                    return b'\xff\x01\x00\x00' + struct.pack('<I', len(identifier)) + identifier
                if packet[0] == 0xFD:  # GET_STATUS, resources are unprotected.
                    return b'\xff\x00\x00\x00\x00\x00'
                return super()._handle_packet(packet)

        example = Path(pyxcp.__file__).resolve().parent / 'examples' / 'xcp_skel.py'
        for protocol in ('TCP', 'UDP'):
            with self.subTest(protocol=protocol), tempfile.TemporaryDirectory() as temporary, ExampleSlave(protocol) as slave:
                config = Path(temporary, 'pyxcp_conf.py')
                config.write_text(
                    "c = get_config()\n"
                    "c.Transport.layer = 'ETH'\n"
                    "c.Transport.timeout = 2.0\n"
                    "c.Eth.host = '127.0.0.1'\n"
                    "c.Eth.port = {}\n".format(slave.port) +
                    "c.Eth.protocol = {!r}\n".format(protocol), encoding='utf-8',
                )
                result = subprocess.run(
                    [sys.executable, str(example), '-c', str(config)],
                    cwd=temporary, capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(slave.commands, [0xFF, 0xFA, 0xFD, 0xFE])

    def test_official_example_copier_and_python_examples(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            copy_files_from_package(
                "pyxcp",
                "examples",
                argparse.Namespace(output_directory=output, force=False),
            )
            copied = sorted(output.glob("*.py"))
            self.assertGreaterEqual(len(copied), 6)
            self.assertTrue((output / "xcphello.py").is_file())
            self.assertTrue((output / "run_daq.py").is_file())
            for file_path in copied:
                ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))

    def test_installed_eth_example_matches_supported_transport_shape(self):
        example = Path(pyxcp.__file__).resolve().parent / "examples" / "conf_eth.toml"
        text = example.read_text(encoding="utf-8")
        self.assertIn('TRANSPORT = "ETH"', text)
        self.assertIn('PROTOCOL = "UDP"', text)
        self.assertIn("PORT = 5555", text)


if __name__ == "__main__":
    unittest.main()
