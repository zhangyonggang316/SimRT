import types
import unittest

from x280_xcp.a2l import A2LScalar
from x280_xcp.client import (
    CalibrationRestoreError,
    CalibrationVerificationError,
    ClientState,
    TcpTransportSettings,
    TransportSettings,
    UdpTransportSettings,
    XcpClient,
    XcpClientError,
    XcpTcpClient,
    XcpUdpClient,
    build_pyxcp_config,
)


class FakeTransport:
    def __init__(self):
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1


class FakeMaster:
    def __init__(self, transport_name, config, memory=None):
        self.transport_name = transport_name
        self.config = config
        self.transport = FakeTransport()
        self.slaveProperties = types.SimpleNamespace(
            bytesPerElement=1,
            maxCto=8,
            maxDto=256,
            supportsCalpag=True,
            supportsDaq=True,
        )
        self.memory = memory if memory is not None else bytearray(256)
        self.mta = 0
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.close_calls = 0
        self.download_sizes = []

    def connect(self):
        self.connect_calls += 1
        return types.SimpleNamespace(maxCto=8)

    def disconnect(self):
        self.disconnect_calls += 1

    def close(self):
        self.close_calls += 1

    def setMta(self, address, address_extension=0):
        self.mta = address

    def upload(self, length):
        payload = bytes(self.memory[self.mta : self.mta + length])
        self.mta += length
        return payload

    def download(self, payload):
        self.download_sizes.append(len(payload))
        self.memory[self.mta : self.mta + len(payload)] = payload
        self.mta += len(payload)


class CorruptFirstDownloadMaster(FakeMaster):
    def download(self, payload):
        if not self.download_sizes:
            corrupted = bytes([payload[0] ^ 0xFF]) + payload[1:]
            super().download(corrupted)
        else:
            super().download(payload)


class CorruptRestoreMaster(FakeMaster):
    def download(self, payload):
        if len(self.download_sizes) == 1:
            corrupted = bytes([payload[0] ^ 0xFF]) + payload[1:]
            super().download(corrupted)
        else:
            super().download(payload)


class ConnectFailureMaster(FakeMaster):
    def connect(self):
        self.connect_calls += 1
        raise RuntimeError("CONNECT failed")


class MasterFactory:
    def __init__(self, master_type=FakeMaster, memory=None):
        self.master_type = master_type
        self.memory = memory
        self.instance = None
        self.calls = 0

    def __call__(self, transport_name, config):
        self.calls += 1
        self.instance = self.master_type(transport_name, config, self.memory)
        return self.instance


class XcpClientTest(unittest.TestCase):
    def test_programmatic_configuration_supports_eth_udp(self):
        settings = UdpTransportSettings(
            "192.0.2.10", port=17725, timeout=1.5, bind_address="0.0.0.0", bind_port=0
        )
        config = build_pyxcp_config(settings)

        self.assertEqual(config.transport.layer, "ETH")
        self.assertEqual(config.transport.eth.protocol, "UDP")
        self.assertEqual(config.transport.eth.host, "192.0.2.10")
        self.assertEqual(config.transport.eth.port, 17725)
        self.assertEqual(config.transport.timeout, 1.5)

    def test_programmatic_configuration_supports_eth_tcp(self):
        settings = TcpTransportSettings("192.0.2.11", timeout=3.0)
        config = build_pyxcp_config(settings)

        self.assertEqual(config.transport.layer, "ETH")
        self.assertEqual(config.transport.eth.protocol, "TCP")
        self.assertEqual(config.transport.eth.host, "192.0.2.11")
        self.assertEqual(config.transport.eth.port, 5555)
        self.assertTrue(config.transport.eth.tcp_nodelay)

    def test_transport_protocol_is_normalized_and_validated(self):
        self.assertEqual(TransportSettings("127.0.0.1", protocol="tcp").protocol, "TCP")
        with self.assertRaises(ValueError):
            TransportSettings("127.0.0.1", protocol="SCTP")

    def test_legacy_udp_and_tcp_clients_reject_wrong_transport(self):
        with self.assertRaises(ValueError):
            XcpUdpClient(TcpTransportSettings("127.0.0.1"))
        with self.assertRaises(ValueError):
            XcpTcpClient(UdpTransportSettings("127.0.0.1"))

    def test_connect_and_disconnect_cover_transport_and_protocol(self):
        factory = MasterFactory()
        client = XcpUdpClient(UdpTransportSettings("127.0.0.1"), factory)

        client.connect()
        self.assertTrue(client.connected)
        self.assertEqual(client.state, ClientState.CONNECTED)
        self.assertEqual(factory.instance.transport.connect_calls, 1)
        self.assertEqual(factory.instance.connect_calls, 1)

        client.connect()
        self.assertEqual(factory.calls, 1)

        client.disconnect()
        self.assertFalse(client.connected)
        self.assertEqual(client.state, ClientState.CLOSED)
        self.assertEqual(factory.instance.disconnect_calls, 1)
        self.assertEqual(factory.instance.close_calls, 1)

        with self.assertRaises(XcpClientError):
            client.connect()
        self.assertEqual(factory.calls, 1)

    def test_failed_connect_closes_master_and_client_is_not_reusable(self):
        factory = MasterFactory(ConnectFailureMaster)
        client = XcpClient(TransportSettings("127.0.0.1", protocol="TCP"), factory)

        with self.assertRaisesRegex(RuntimeError, "CONNECT failed"):
            client.connect()

        self.assertEqual(client.state, ClientState.CLOSED)
        self.assertEqual(factory.instance.close_calls, 1)
        with self.assertRaises(XcpClientError):
            client.connect()
        self.assertEqual(factory.calls, 1)

    def test_raw_memory_read_and_write_are_chunked_to_max_cto(self):
        memory = bytearray(range(64))
        factory = MasterFactory(memory=memory)
        with XcpUdpClient(UdpTransportSettings("127.0.0.1"), factory) as client:
            self.assertEqual(client.read_memory(3, 13), bytes(range(3, 16)))
            client.write_memory(20, b"abcdefghijklmn")
            self.assertEqual(client.read_memory(20, 14), b"abcdefghijklmn")

        self.assertEqual(factory.instance.download_sizes, [6, 6, 2])

    def test_measurement_write_is_refused(self):
        factory = MasterFactory()
        measurement = A2LScalar("Output", "MEASUREMENT", 4, "UBYTE")
        with XcpUdpClient(UdpTransportSettings("127.0.0.1"), factory) as client:
            with self.assertRaises(XcpClientError):
                client.write_scalar(measurement, 4)

    def test_explicit_measurement_and_characteristic_read_apis_enforce_kind(self):
        memory = bytearray(64)
        memory[4] = 7
        memory[8] = 9
        factory = MasterFactory(memory=memory)
        measurement = A2LScalar("Output", "MEASUREMENT", 4, "UBYTE")
        characteristic = A2LScalar("Gain", "CHARACTERISTIC", 8, "UBYTE")

        with XcpClient(TransportSettings("127.0.0.1", protocol="TCP"), factory) as client:
            self.assertEqual(client.read_measurement(measurement), 7)
            self.assertEqual(client.read_characteristic(characteristic), 9)
            with self.assertRaises(XcpClientError):
                client.read_measurement(characteristic)
            with self.assertRaises(XcpClientError):
                client.read_characteristic(measurement)

    def test_characteristic_write_is_verified(self):
        memory = bytearray(64)
        factory = MasterFactory(memory=memory)
        characteristic = A2LScalar("Gain", "CHARACTERISTIC", 8, "UWORD")

        with XcpClient(TransportSettings("127.0.0.1"), factory) as client:
            readback = client.write_characteristic(characteristic, "0x4321")

        self.assertEqual(readback, 0x4321)
        self.assertEqual(memory[8:10], b"\x21\x43")

    def test_characteristic_write_reports_verification_failure(self):
        memory = bytearray(64)
        factory = MasterFactory(CorruptFirstDownloadMaster, memory)
        characteristic = A2LScalar("Gain", "CHARACTERISTIC", 8, "UWORD")

        with XcpClient(TransportSettings("127.0.0.1"), factory) as client:
            with self.assertRaises(CalibrationVerificationError):
                client.write_characteristic(characteristic, "0x4321")

    def test_memory_operations_require_an_active_single_master_session(self):
        client = XcpClient(TransportSettings("127.0.0.1"), MasterFactory())

        with self.assertRaises(XcpClientError):
            client.read_memory(0, 0)
        with self.assertRaises(XcpClientError):
            client.write_memory(0, b"")

    def test_memory_operation_cannot_cross_32_bit_address_boundary(self):
        factory = MasterFactory()
        with XcpUdpClient(UdpTransportSettings("127.0.0.1"), factory) as client:
            with self.assertRaises(ValueError):
                client.read_memory(0xFFFFFFFE, 3)
            with self.assertRaises(ValueError):
                client.write_memory(0xFFFFFFFF, b"xx")

    def test_calibration_smoke_restores_original_value(self):
        memory = bytearray(64)
        memory[8:10] = b"\x34\x12"
        factory = MasterFactory(memory=memory)
        scalar = A2LScalar("CalGain", "CHARACTERISTIC", 8, "UWORD")

        with XcpUdpClient(UdpTransportSettings("127.0.0.1"), factory) as client:
            result = client.calibration_smoke_test(scalar, "0x4321")

        self.assertEqual(result.original_value, 0x1234)
        self.assertEqual(result.readback_value, 0x4321)
        self.assertEqual(result.restored_value, 0x1234)
        self.assertEqual(memory[8:10], b"\x34\x12")

    def test_calibration_smoke_restores_after_verification_failure(self):
        memory = bytearray(64)
        memory[8:10] = b"\x34\x12"
        factory = MasterFactory(CorruptFirstDownloadMaster, memory)
        scalar = A2LScalar("CalGain", "CHARACTERISTIC", 8, "UWORD")

        with XcpUdpClient(UdpTransportSettings("127.0.0.1"), factory) as client:
            with self.assertRaises(CalibrationVerificationError):
                client.calibration_smoke_test(scalar, "0x4321")

        self.assertEqual(memory[8:10], b"\x34\x12")

    def test_calibration_smoke_reports_restore_verification_failure(self):
        memory = bytearray(64)
        memory[8:10] = b"\x34\x12"
        factory = MasterFactory(CorruptRestoreMaster, memory)
        scalar = A2LScalar("CalGain", "CHARACTERISTIC", 8, "UWORD")

        with XcpClient(TransportSettings("127.0.0.1"), factory) as client:
            with self.assertRaises(CalibrationRestoreError):
                client.calibration_smoke_test(scalar, "0x4321")


if __name__ == "__main__":
    unittest.main()
