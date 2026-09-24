from __future__ import annotations

import struct
import tempfile
import types
import unittest
from pathlib import Path

from pyxcp_host.models import Endpoint, HostState
from pyxcp_host.services import A2LCatalogService, XcpSession
from pyxcp_host.services.backend import CalibrationRestoreError
from pyxcp_host.viewmodel import HostViewModel


A2L_TEXT = r'''
/begin PROJECT Demo ""
  /begin MODULE Demo ""
    /begin MOD_COMMON ""
      BYTE_ORDER MSB_LAST
    /end MOD_COMMON
    /begin RECORD_LAYOUT Record_FLOAT32_IEEE
      FNC_VALUES 1 FLOAT32_IEEE COLUMN_DIR DIRECT
    /end RECORD_LAYOUT
    /begin CHARACTERISTIC CalGain "" VALUE 0x20 Record_FLOAT32_IEEE 0 NO_COMPU_METHOD -100 100
    /end CHARACTERISTIC
    /begin CHARACTERISTIC CalOffset "" VALUE 0x24 Record_FLOAT32_IEEE 0 NO_COMPU_METHOD -100 100
    /end CHARACTERISTIC
    /begin MEASUREMENT MeasuredOutput "" FLOAT32_IEEE NO_COMPU_METHOD 0 0 -100 100
      ECU_ADDRESS 0x10
    /end MEASUREMENT
    /begin XCP_ON_TCP_IP
      0x0100 0x15B3 ADDRESS "127.0.0.1"
    /end XCP_ON_TCP_IP
    /begin XCP_ON_UDP_IP
      0x0100 0x453D ADDRESS "127.0.0.1"
    /end XCP_ON_UDP_IP
  /end MODULE
/end PROJECT
'''


class FakeClient:
    def __init__(
        self,
        settings,
        memory,
        fail_connect=False,
        fail_restore=False,
        byte_order="INTEL",
    ):
        self.settings = settings
        self.memory = memory
        self.fail_connect = fail_connect
        self.fail_restore = fail_restore
        self.connected = False
        self.master = types.SimpleNamespace(
            slaveProperties=types.SimpleNamespace(
                byteOrder=types.SimpleNamespace(name=byte_order),
                bytesPerElement=1,
                maxCto=255,
                maxDto=508,
                supportsCalpag=True,
                supportsDaq=False,
            )
        )

    def connect(self):
        if self.fail_connect:
            raise RuntimeError("simulated CONNECT failure")
        self.connected = True
        return types.SimpleNamespace()

    def disconnect(self):
        self.connected = False

    def read_memory(self, address, size, address_extension=0):
        return bytes(self.memory[address : address + size])

    def write_memory(self, address, payload, address_extension=0):
        if self.fail_restore and address == 0x20 and payload == struct.pack("<f", 1.5):
            return
        self.memory[address : address + len(payload)] = payload

    def read_measurement(self, scalar):
        return scalar.decode(self.read_memory(scalar.address, scalar.size))

    def read_characteristic(self, scalar):
        return scalar.decode(self.read_memory(scalar.address, scalar.size))

    def write_characteristic(self, scalar, value, verify=True):
        expected = scalar.encode(value)
        self.write_memory(scalar.address, expected, scalar.address_extension)
        actual = self.read_memory(scalar.address, scalar.size, scalar.address_extension)
        if verify and actual != expected:
            raise RuntimeError("simulated readback mismatch")
        return scalar.decode(actual)


class ClientFactory:
    def __init__(
        self,
        memory,
        fail_connect=False,
        fail_restore=False,
        byte_order="INTEL",
    ):
        self.memory = memory
        self.fail_connect = fail_connect
        self.fail_restore = fail_restore
        self.byte_order = byte_order
        self.instances = []

    def __call__(self, settings):
        client = FakeClient(
            settings,
            self.memory,
            fail_connect=self.fail_connect,
            fail_restore=self.fail_restore,
            byte_order=self.byte_order,
        )
        self.instances.append(client)
        return client


class HostCoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.a2l_path = Path(self.temporary.name) / "demo.a2l"
        self.a2l_path.write_text(A2L_TEXT, encoding="utf-8")
        self.memory = bytearray(256)
        self.memory[0x10:0x14] = struct.pack("<f", 12.25)
        self.memory[0x20:0x24] = struct.pack("<f", 1.5)
        self.memory[0x24:0x28] = struct.pack("<f", -0.25)

    def create_viewmodel(self, factory=None):
        catalog = A2LCatalogService()
        factory = factory or ClientFactory(self.memory)
        session = XcpSession(catalog, factory)
        return HostViewModel(catalog_service=catalog, session=session), factory

    def test_catalog_exposes_scalar_metadata_and_both_transports(self):
        catalog = A2LCatalogService().load(self.a2l_path)

        self.assertEqual([item.name for item in catalog.measurements], ["MeasuredOutput"])
        self.assertEqual(
            [item.name for item in catalog.calibrations], ["CalGain", "CalOffset"]
        )
        self.assertEqual(catalog.declared_transports, ("TCP", "UDP"))
        self.assertEqual(catalog.declared_ports, {"TCP": 5555, "UDP": 17725})
        self.assertEqual(catalog.byte_order, "little")

    def test_endpoint_normalizes_protocol_and_validates_port(self):
        endpoint = Endpoint("tcp", " 127.0.0.1 ", 5555, 1.25)
        self.assertEqual(endpoint.protocol, "TCP")
        self.assertEqual(endpoint.summary, "ETH/TCP 127.0.0.1:5555")
        with self.assertRaises(ValueError):
            Endpoint("UDP", "127.0.0.1", 65536)

    def test_tcp_connect_poll_and_diagnostics(self):
        vm, factory = self.create_viewmodel()
        vm.load_a2l(self.a2l_path)
        info = vm.connect("TCP", "127.0.0.1", 5555, 1.0)

        self.assertEqual(vm.state, HostState.CONNECTED)
        self.assertEqual(factory.instances[0].settings.protocol, "TCP")
        self.assertEqual(vm.poll_measurements(["MeasuredOutput"]), {"MeasuredOutput": 12.25})
        self.assertEqual(info.max_dto, 508)
        self.assertEqual(vm.diagnostics["transport"], "ETH/TCP")

    def test_udp_connect_uses_udp_configuration(self):
        vm, factory = self.create_viewmodel()
        vm.load_a2l(self.a2l_path)
        vm.connect("udp", "192.0.2.10", 17725, 2.5)

        settings = factory.instances[0].settings
        self.assertEqual((settings.protocol, settings.host, settings.port), ("UDP", "192.0.2.10", 17725))

    def test_connect_rejects_slave_byte_order_mismatch(self):
        factory = ClientFactory(self.memory, byte_order="MOTOROLA")
        vm, _ = self.create_viewmodel(factory)
        vm.load_a2l(self.a2l_path)

        with self.assertRaisesRegex(Exception, "字节序"):
            vm.connect("TCP", "127.0.0.1", 5555)

        self.assertFalse(vm.connected)
        self.assertFalse(factory.instances[0].connected)

    def test_read_all_calibrations_and_log_sink(self):
        vm, _ = self.create_viewmodel()
        emitted = []
        vm.set_log_sink(emitted.append)
        vm.load_a2l(self.a2l_path)
        vm.connect("TCP", "127.0.0.1", 5555)

        values = vm.read_calibrations()

        self.assertEqual(set(values), {"CalGain", "CalOffset"})
        self.assertAlmostEqual(values["CalGain"], 1.5)
        self.assertAlmostEqual(values["CalOffset"], -0.25)
        self.assertTrue(any("已读取 2 个标定量" in line for line in emitted))

    def test_calibration_write_is_verified_and_disconnect_restores_original(self):
        vm, _ = self.create_viewmodel()
        vm.load_a2l(self.a2l_path)
        vm.connect("TCP", "127.0.0.1", 5555)

        actual = vm.write_calibrations({"CalGain": "2.75"})
        self.assertAlmostEqual(actual["CalGain"], 2.75)
        self.assertAlmostEqual(struct.unpack("<f", self.memory[0x20:0x24])[0], 2.75)
        self.assertEqual(vm.diagnostics["pending_calibrations"], 1)

        vm.disconnect()
        self.assertAlmostEqual(struct.unpack("<f", self.memory[0x20:0x24])[0], 1.5)
        self.assertEqual(vm.state, HostState.LOADED)

    def test_selected_calibrations_can_be_restored_without_disconnect(self):
        vm, _ = self.create_viewmodel()
        vm.load_a2l(self.a2l_path)
        vm.connect("UDP", "127.0.0.1", 17725)
        vm.write_calibrations({"CalGain": 3.0, "CalOffset": 4.0})

        restored = vm.restore_calibrations(["CalGain"])

        self.assertAlmostEqual(restored["CalGain"], 1.5)
        self.assertEqual(vm.diagnostics["pending_calibrations"], 1)
        self.assertAlmostEqual(struct.unpack("<f", self.memory[0x24:0x28])[0], 4.0)

    def test_connect_failure_leaves_retryable_error_state(self):
        factory = ClientFactory(self.memory, fail_connect=True)
        vm, _ = self.create_viewmodel(factory)
        vm.load_a2l(self.a2l_path)

        with self.assertRaisesRegex(RuntimeError, "CONNECT failure"):
            vm.connect("TCP", "127.0.0.1", 5555)

        self.assertEqual(vm.state, HostState.ERROR)
        self.assertFalse(vm.connected)
        self.assertIn("XCP 连接失败", vm.last_error)

    def test_restore_failure_keeps_session_connected_and_recoverable(self):
        factory = ClientFactory(self.memory, fail_restore=True)
        vm, _ = self.create_viewmodel(factory)
        vm.load_a2l(self.a2l_path)
        vm.connect("TCP", "127.0.0.1", 5555)
        vm.write_calibrations({"CalGain": 2.0})

        with self.assertRaises(CalibrationRestoreError):
            vm.disconnect()

        self.assertTrue(vm.connected)
        self.assertEqual(vm.state, HostState.CONNECTED)
        self.assertEqual(vm.diagnostics["pending_calibrations"], 1)
        factory.instances[0].fail_restore = False
        vm.disconnect()
        self.assertFalse(vm.connected)
        self.assertAlmostEqual(struct.unpack("<f", self.memory[0x20:0x24])[0], 1.5)

    def test_overlapping_calibration_alias_is_rejected_before_write(self):
        alias_block = r'''
    /begin CHARACTERISTIC CalAlias "" VALUE 0x20 Record_FLOAT32_IEEE 0 NO_COMPU_METHOD -100 100
    /end CHARACTERISTIC
'''
        alias_path = Path(self.temporary.name) / "alias.a2l"
        alias_path.write_text(
            A2L_TEXT.replace("    /begin MEASUREMENT", alias_block + "    /begin MEASUREMENT"),
            encoding="utf-8",
        )
        vm, _ = self.create_viewmodel()
        vm.load_a2l(alias_path)
        vm.connect("TCP", "127.0.0.1", 5555)
        vm.write_calibrations({"CalGain": 2.0})

        with self.assertRaisesRegex(ValueError, "地址范围重叠"):
            vm.write_calibrations({"CalAlias": 3.0})

        self.assertAlmostEqual(struct.unpack("<f", self.memory[0x20:0x24])[0], 2.0)
        vm.disconnect()
        self.assertAlmostEqual(struct.unpack("<f", self.memory[0x20:0x24])[0], 1.5)


if __name__ == "__main__":
    unittest.main()
