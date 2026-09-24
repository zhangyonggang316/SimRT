import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path

from x280_xcp.cli import main


class FakeCliClient:
    last_settings = None

    def __init__(self, settings):
        type(self).last_settings = settings
        self.settings = settings
        self.master = types.SimpleNamespace(
            slaveProperties=types.SimpleNamespace(
                bytesPerElement=1,
                maxCto=64,
                maxDto=256,
                supportsCalpag=True,
                supportsDaq=True,
            )
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read_memory(self, address, size, extension=0):
        return bytes(range(size))

    def read_measurement(self, scalar):
        return 12

    def read_characteristic(self, scalar):
        return 3

    def write_characteristic(self, scalar, value):
        return scalar.decode(scalar.encode(value))


class CliTest(unittest.TestCase):
    def test_probe_uses_x280_default_address(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(["probe"], client_type=FakeCliClient)

        self.assertEqual(exit_code, 0)
        self.assertEqual(FakeCliClient.last_settings.host, "192.168.0.106")
        self.assertEqual(FakeCliClient.last_settings.protocol, "UDP")
        self.assertEqual(FakeCliClient.last_settings.port, 17725)

    def test_probe_passes_udp_endpoint_settings(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                ["--host", "192.0.2.20", "--port", "17726", "probe"],
                client_type=FakeCliClient,
            )
        result = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["transport"], "ETH/UDP")
        self.assertEqual(FakeCliClient.last_settings.host, "192.0.2.20")
        self.assertEqual(FakeCliClient.last_settings.port, 17726)

    def test_probe_supports_tcp_and_uses_tcp_default_port(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = main(
                ["--protocol", "tcp", "--host", "192.0.2.21", "probe"],
                client_type=FakeCliClient,
            )
        result = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(result["transport"], "ETH/TCP")
        self.assertEqual(FakeCliClient.last_settings.protocol, "TCP")
        self.assertEqual(FakeCliClient.last_settings.port, 5555)

    def test_list_is_offline_and_does_not_construct_client(self):
        fixture = '''
        /begin MEASUREMENT Signal "" UBYTE Identity 0 0 0 255
          ECU_ADDRESS 0x10
        /end MEASUREMENT
        '''
        with tempfile.TemporaryDirectory() as directory:
            a2l = Path(directory) / "demo.a2l"
            a2l.write_text(fixture, encoding="latin-1")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = main(
                    ["list", "--a2l", str(a2l), "--kind", "measurement"],
                    client_type=None,
                )
        result = json.loads(output.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(result[0]["name"], "Signal")
        self.assertEqual(result[0]["address"], "0x00000010")

    def test_explicit_measurement_and_characteristic_commands_route_by_kind(self):
        fixture = '''
        /begin RECORD_LAYOUT LayoutU8
          FNC_VALUES 1 UBYTE COLUMN_DIR DIRECT
        /end RECORD_LAYOUT
        /begin CHARACTERISTIC Gain "" VALUE 0x20 LayoutU8 0 Identity 0 255
        /end CHARACTERISTIC
        /begin MEASUREMENT Signal "" UBYTE Identity 0 0 0 255
          ECU_ADDRESS 0x10
        /end MEASUREMENT
        '''
        with tempfile.TemporaryDirectory() as directory:
            a2l = Path(directory) / "demo.a2l"
            a2l.write_text(fixture, encoding="latin-1")

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(
                    ["read-measurement", "--a2l", str(a2l), "Signal"],
                    client_type=FakeCliClient,
                )
            measurement = json.loads(output.getvalue())

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main(
                    ["write-characteristic", "--a2l", str(a2l), "Gain", "7"],
                    client_type=FakeCliClient,
                )
            characteristic = json.loads(output.getvalue())

        self.assertEqual(measurement["kind"], "MEASUREMENT")
        self.assertEqual(measurement["value"], 12)
        self.assertEqual(characteristic["kind"], "CHARACTERISTIC")
        self.assertEqual(characteristic["value"], 7)
        self.assertTrue(characteristic["verified"])


if __name__ == "__main__":
    unittest.main()
