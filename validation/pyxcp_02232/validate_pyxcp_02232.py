"""Offline compatibility checks for pyXCP 0.22.32 on Python 3.9.10.

The loopback slave implements only the XCP commands needed by these checks.
It never contacts the X280 or reads deployment credentials.
"""

from __future__ import annotations

import importlib.metadata
import socket
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from traitlets.config import Config

from pyxcp.config import General, Transport
from pyxcp.cpp_ext.cpp_ext import DaqList
from pyxcp.daq_stim.optimize import make_continuous_blocks
from pyxcp.daq_stim.optimize.binpacking import first_fit_decreasing
from pyxcp.master import Master
from pyxcp.transport.eth import Eth

_WORKSPACE = Path(__file__).resolve().parents[2]
for _source_path in (
    _WORKSPACE / "python_xcp_host",
    _WORKSPACE / "x280_linux_target" / "python",
):
    if str(_source_path) not in sys.path:
        sys.path.insert(0, str(_source_path))

from pyxcp_host.services import A2LCatalogService, XcpSession
from pyxcp_host.viewmodel import HostViewModel


_HEADER = struct.Struct("<HH")
_CONNECT = 0xFF
_DISCONNECT = 0xFE
_SET_MTA = 0xF6
_UPLOAD = 0xF5
_DOWNLOAD = 0xF0

_HOST_A2L = r'''
/begin PROJECT Loopback ""
  /begin MODULE Loopback ""
    /begin MOD_COMMON ""
      BYTE_ORDER MSB_LAST
    /end MOD_COMMON
    /begin RECORD_LAYOUT Record_FLOAT32_IEEE
      FNC_VALUES 1 FLOAT32_IEEE COLUMN_DIR DIRECT
    /end RECORD_LAYOUT
    /begin CHARACTERISTIC CalGain "" VALUE 0x1004 Record_FLOAT32_IEEE 0 NO_COMPU_METHOD -100 100
    /end CHARACTERISTIC
    /begin MEASUREMENT MeasuredOutput "" FLOAT32_IEEE NO_COMPU_METHOD 0 0 -100 100
      ECU_ADDRESS 0x1000
    /end MEASUREMENT
  /end MODULE
/end PROJECT
'''


def _pyxcp_config(protocol: str, port: int) -> SimpleNamespace:
    config = Config()
    config.Transport.layer = "ETH"
    config.Transport.timeout = 0.5
    config.Transport.alignment = 1
    config.Eth.host = "127.0.0.1"
    config.Eth.port = port
    config.Eth.protocol = protocol
    config.Eth.ipv6 = False
    config.Eth.bind_to_address = None
    config.Eth.bind_to_port = None
    return SimpleNamespace(
        general=General(config=config),
        transport=Transport(config=config),
    )


class LoopbackXcpSlave:
    """Minimal XCP-on-Ethernet slave for real TCP or UDP socket checks."""

    def __init__(self, protocol: str) -> None:
        self.protocol = protocol
        socket_type = socket.SOCK_DGRAM if protocol == "UDP" else socket.SOCK_STREAM
        self.socket = socket.socket(socket.AF_INET, socket_type)
        self.socket.settimeout(0.2)
        self.socket.bind(("127.0.0.1", 0))
        if protocol == "TCP":
            self.socket.listen(1)
        self.port = self.socket.getsockname()[1]
        self.memory = bytearray(0x2000)
        self.mta = 0
        self.error: Optional[BaseException] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> "LoopbackXcpSlave":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop.set()
        self.socket.close()
        self._thread.join(timeout=2.0)
        if exc_type is None and self.error is not None:
            raise self.error

    def _serve(self) -> None:
        try:
            if self.protocol == "UDP":
                self._serve_udp()
            else:
                self._serve_tcp()
        except EOFError:
            # A TCP master closing its transport is the normal end of a session.
            return
        except OSError as exc:
            if not self._stop.is_set():
                self.error = exc
        except BaseException as exc:  # Surface failures in the test thread.
            self.error = exc

    def _serve_udp(self) -> None:
        while not self._stop.is_set():
            try:
                frame, peer = self.socket.recvfrom(4096)
            except socket.timeout:
                continue
            response = self._handle_frame(frame)
            self.socket.sendto(response, peer)

    def _serve_tcp(self) -> None:
        connection = None
        while connection is None and not self._stop.is_set():
            try:
                connection, _ = self.socket.accept()
            except socket.timeout:
                continue
        if connection is None:
            return
        with connection:
            connection.settimeout(0.2)
            while not self._stop.is_set():
                try:
                    header = self._recv_exact(connection, _HEADER.size)
                except socket.timeout:
                    continue
                length, counter = _HEADER.unpack(header)
                packet = self._recv_exact(connection, length)
                response_packet = self._handle_packet(packet)
                connection.sendall(_HEADER.pack(len(response_packet), counter) + response_packet)

    @staticmethod
    def _recv_exact(connection: socket.socket, size: int) -> bytes:
        result = bytearray()
        while len(result) < size:
            chunk = connection.recv(size - len(result))
            if not chunk:
                raise EOFError("peer closed the loopback connection")
            result.extend(chunk)
        return bytes(result)

    def _handle_frame(self, frame: bytes) -> bytes:
        if len(frame) < _HEADER.size:
            raise ValueError("short XCP-on-Ethernet frame")
        length, counter = _HEADER.unpack_from(frame)
        packet = frame[_HEADER.size : _HEADER.size + length]
        if len(packet) != length:
            raise ValueError("truncated XCP-on-Ethernet packet")
        response_packet = self._handle_packet(packet)
        return _HEADER.pack(len(response_packet), counter) + response_packet

    def _handle_packet(self, packet: bytes) -> bytes:
        command = packet[0]
        if command == _CONNECT:
            # CAL/PAG, DAQ, STIM, PGM; Intel byte order; BYTE addressing;
            # MAX_CTO 255; MAX_DTO 508; XCP protocol/transport version 1.0.
            return bytes((0xFF, 0x1D, 0x00, 0xFF, 0xFC, 0x01, 0x01, 0x01))
        if command == _DISCONNECT:
            return b"\xFF"
        if command == _SET_MTA:
            if len(packet) != 8:
                raise ValueError("invalid SET_MTA packet")
            self.mta = struct.unpack_from("<I", packet, 4)[0]
            return b"\xFF"
        if command == _UPLOAD:
            size = packet[1]
            payload = bytes(self.memory[self.mta : self.mta + size])
            self.mta += size
            return b"\xFF" + payload
        if command == _DOWNLOAD:
            size = packet[1]
            payload = packet[2 : 2 + size]
            if len(payload) != size:
                raise ValueError("truncated DOWNLOAD packet")
            self.memory[self.mta : self.mta + size] = payload
            self.mta += size
            return b"\xFF"
        raise ValueError(f"unsupported loopback XCP command 0x{command:02X}")


class PyXcp02232CompatibilityTest(unittest.TestCase):
    def test_workspace_runtime_and_binary_extensions(self) -> None:
        self.assertEqual(sys.version_info[:3], (3, 9, 10))
        self.assertEqual(importlib.metadata.version("pyxcp"), "0.22.32")

        import pyxcp.daq_stim.stim  # noqa: F401
        import pyxcp.recorder.rekorder  # noqa: F401

    def test_eth_udp_limits_and_configuration(self) -> None:
        self.assertEqual(Eth.HEADER_SIZE, 4)
        self.assertEqual(Eth.MAX_DATAGRAM_SIZE, 512)
        config = _pyxcp_config("UDP", 17725)
        self.assertEqual(config.transport.layer, "ETH")
        self.assertEqual(config.transport.eth.protocol, "UDP")
        self.assertEqual(config.transport.eth.port, 17725)

    def test_tcp_and_udp_connect_read_write_disconnect(self) -> None:
        for protocol in ("TCP", "UDP"):
            with self.subTest(protocol=protocol), LoopbackXcpSlave(protocol) as slave:
                slave.memory[0x1000:0x1004] = b"\x11\x22\x33\x44"
                with Master("eth", config=_pyxcp_config(protocol, slave.port)) as master:
                    response = master.connect()
                    self.assertEqual(response.maxCto, 255)
                    self.assertEqual(response.maxDto, 508)
                    self.assertEqual(master.slaveProperties.bytesPerElement, 1)

                    master.setMta(0x1000)
                    self.assertEqual(bytes(master.upload(4)), b"\x11\x22\x33\x44")

                    master.setMta(0x1000)
                    master.download(b"\xAA\xBB\xCC\xDD")
                    master.setMta(0x1000)
                    self.assertEqual(bytes(master.upload(4)), b"\xAA\xBB\xCC\xDD")
                    master.disconnect()

    def test_host_viewmodel_full_tcp_and_udp_socket_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            a2l_path = Path(temporary) / "loopback.a2l"
            a2l_path.write_text(_HOST_A2L, encoding="utf-8")
            for protocol in ("TCP", "UDP"):
                with self.subTest(protocol=protocol), LoopbackXcpSlave(protocol) as slave:
                    slave.memory[0x1000:0x1004] = struct.pack("<f", 12.25)
                    slave.memory[0x1004:0x1008] = struct.pack("<f", 1.5)
                    catalog = A2LCatalogService()
                    vm = HostViewModel(
                        catalog_service=catalog,
                        session=XcpSession(catalog),
                    )

                    vm.load_a2l(a2l_path)
                    info = vm.connect(protocol, "127.0.0.1", slave.port, 0.5)
                    self.assertEqual(info.endpoint.protocol, protocol)
                    self.assertAlmostEqual(
                        vm.poll_measurements(("MeasuredOutput",))["MeasuredOutput"],
                        12.25,
                    )
                    self.assertAlmostEqual(vm.write_calibrations({"CalGain": 2.75})["CalGain"], 2.75)
                    vm.disconnect()
                    self.assertAlmostEqual(struct.unpack("<f", slave.memory[0x1004:0x1008])[0], 1.5)

    def test_daq_native_extension_and_layout_optimizer(self) -> None:
        daq_list = DaqList(
            name="x280_500ms",
            event_num=0,
            stim=False,
            enable_timestamps=True,
            measurements=[
                ("MeasuredOutput", 0x1000, 0, "F64"),
                ("TaskTicks", 0x1008, 0, "U32"),
            ],
            priority=0,
            prescaler=1,
        )
        blocks = make_continuous_blocks(
            daq_list.measurements,
            upper_bound=507,
            upper_bound_initial=503,
        )
        odts = first_fit_decreasing(
            blocks,
            bin_size=507,
            initial_bin_size=503,
        )
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].length, 12)
        self.assertEqual(len(odts), 1)
        self.assertEqual(odts[0].residual_capacity, 491)


if __name__ == "__main__":
    unittest.main(verbosity=2)
