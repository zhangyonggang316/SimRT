"""Real Ethernet sockets with deterministic mock DTOs, not timing benchmarks."""

from __future__ import annotations

import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pyxcp_host.models import Endpoint
from pyxcp_host.services import A2LCatalogService, XcpSession


class DaqSlave:
    def __init__(self, protocol, supports_event_info=True):
        self.protocol = protocol
        self.supports_event_info = supports_event_info
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM if protocol == "TCP" else socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.settimeout(.002)
        if protocol == "TCP":
            self.socket.listen(1)
        self.port = self.socket.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.error = None
        self.running = False
        self.peer = None
        self.connection = None
        self.counter = 0
        self.ticks = 0
        self.sent_samples = 0
        self.memory = bytearray(256)
        self.memory[0x20:0x24] = struct.pack("<f", 1.5)
        self.mta = 0
        self.command_ids = []

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop.set()
        self.thread.join(2)
        if self.connection:
            self.connection.close()
        self.socket.close()
        if exc_type is None and self.error:
            raise self.error

    def send(self, payload):
        frame = struct.pack("<HH", len(payload), self.counter) + payload
        self.counter = (self.counter + 1) & 0xFFFF
        if self.protocol == "TCP":
            self.connection.sendall(frame)
        else:
            self.socket.sendto(frame, self.peer)

    def serve(self):
        buffer = b""
        next_sample = time.monotonic()
        try:
            if self.protocol == "TCP":
                while not self.stop.is_set():
                    try:
                        self.connection, self.peer = self.socket.accept()
                        self.connection.settimeout(.002)
                        break
                    except socket.timeout:
                        continue
            while not self.stop.is_set():
                try:
                    if self.protocol == "TCP":
                        part = self.connection.recv(4096)
                        if not part:
                            return
                        buffer += part
                    else:
                        buffer, self.peer = self.socket.recvfrom(4096)
                    while len(buffer) >= 4:
                        length, counter = struct.unpack_from("<HH", buffer)
                        if len(buffer) < 4 + length:
                            break
                        packet = buffer[4:4 + length]
                        buffer = buffer[4 + length:]
                        self.send(self.command(packet))
                except socket.timeout:
                    pass
                if self.running and time.monotonic() >= next_sample:
                    self.ticks += 1000
                    self.sent_samples += 1
                    # Model output responds to calibration while the DTO stream runs.
                    self.send(b"\x00" + struct.pack("<I", self.ticks) + self.memory[0x20:0x24])
                    next_sample = time.monotonic() + .001
        except OSError as exc:
            if not self.stop.is_set():
                self.error = exc
        except BaseException as exc:
            self.error = exc

    def command(self, packet):
        command = packet[0]
        self.command_ids.append(command)
        if command == 0xFF:
            return bytes((0xFF, 0x05, 0, 255, 255, 0, 1, 1))
        if command == 0xFD:
            return bytes((0xFF, 0, 0, 0, 0, 0))
        if command == 0xD7:
            if not self.supports_event_info:
                return b"\xfe\x20"
            return bytes((0xFF, 4, 255, 0, 1, 6, 0))
        if command == 0xDA:
            return bytes((0xFF, 0x13, 0, 0, 1, 0, 0, 0))
        if command == 0xD9:
            return bytes((0xFF, 1, 248, 1, 248, 0x3C, 1, 0))
        if command == 0xDE:
            return b"\xff\x00"
        if command == 0xDD:
            self.running = packet[1] == 1
        elif command == 0xFE:
            self.running = False
        elif command == 0xF6:
            self.mta = struct.unpack_from("<I", packet, 4)[0]
        elif command == 0xF5:
            payload = bytes(self.memory[self.mta:self.mta + packet[1]])
            self.mta += packet[1]
            return b"\xff" + payload
        elif command == 0xF0:
            self.memory[self.mta:self.mta + packet[1]] = packet[2:2 + packet[1]]
            self.mta += packet[1]
        elif command not in {0xD6, 0xD5, 0xD4, 0xD3, 0xE2, 0xE1, 0xE0}:
            raise ValueError("Unexpected XCP command: {:02x}".format(command))
        return b"\xff"


class DaqTransportTest(unittest.TestCase):
    def test_real_tcp_and_udp_daq_continue_during_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "socket_daq.a2l"
            path.write_text('''/begin PROJECT D "" /begin MODULE D ""
              /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
              /begin RECORD_LAYOUT R FNC_VALUES 1 FLOAT32_IEEE COLUMN_DIR DIRECT /end RECORD_LAYOUT
              /begin MEASUREMENT Output "" FLOAT32_IEEE NO_COMPU_METHOD 0 0 -100 100 ECU_ADDRESS 0x10 /end MEASUREMENT
              /begin CHARACTERISTIC Gain "" VALUE 0x20 R 0 NO_COMPU_METHOD -100 100 /end CHARACTERISTIC
              /begin IF_DATA XCP /begin DAQ
                /begin EVENT "1ms" "1ms" 0 DAQ 255 1 6 0 /end EVENT
              /end DAQ /end IF_DATA
              /end MODULE /end PROJECT''', encoding="ascii")
            for protocol, supports_info in (("TCP", True), ("UDP", True), ("UDP", False)):
                with self.subTest(protocol=protocol, supports_info=supports_info), DaqSlave(protocol, supports_info) as slave:
                    catalog = A2LCatalogService()
                    catalog.load(path)
                    session = XcpSession(catalog)
                    session.connect(Endpoint(protocol, "127.0.0.1", slave.port, 1))
                    try:
                        metadata = session.start_daq(["Output"])
                        self.assertEqual(metadata["period_seconds"], .001)
                        self.assertEqual(metadata["period_source"], "slave" if supports_info else "A2L EVENT")
                        before = self.collect_until(session, lambda rows: len(rows) >= 5)
                        self.assertTrue(all(row.values["Output"] == 1.5 for row in before))
                        session.write_calibrations({"Gain": 2.75})
                        after = self.collect_until(session, lambda rows: any(row.values["Output"] == 2.75 for row in rows))
                        self.assertTrue(session.daq_active)
                        session.restore_calibrations()
                        restored = self.collect_until(session, lambda rows: any(row.values["Output"] == 1.5 for row in rows))
                        session.stop_daq()
                        self.assertFalse(slave.running)
                        self.assertGreater(len(before + after + restored), 6)
                        timestamps = [row.timestamp_seconds for row in before + after + restored]
                        self.assertTrue(all(left < right for left, right in zip(timestamps, timestamps[1:])))
                        self.assertEqual(session.diagnostics()["daq"]["invalid_frames"], 0)
                        self.assertEqual(session.diagnostics()["daq"]["transport_counter_gaps"], 0)
                        self.assertIn(0xE1, slave.command_ids)
                        # Fresh DAQ allocation sends only START and final STOP.
                        self.assertEqual(slave.command_ids.count(0xDD), 2)
                    finally:
                        session.disconnect()
                    self.assertEqual(struct.unpack("<f", slave.memory[0x20:0x24])[0], 1.5)

    @staticmethod
    def collect_until(session, predicate):
        rows = []
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rows.extend(session.drain_daq())
            if predicate(rows):
                return rows
            time.sleep(.005)
        raise AssertionError("Expected DTOs were not received within two seconds.")


if __name__ == "__main__":
    unittest.main()
