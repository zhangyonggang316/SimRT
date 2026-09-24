from __future__ import annotations

import copy
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from pyxcp import types
from pyxcp.transport.base import NoOpPolicy
from x280_xcp.a2l import A2LDaqEvent, A2LScalar
from x280_xcp.client import XcpClient

from pyxcp_host.models import Endpoint
from pyxcp_host.services import A2LCatalogService, XcpSession
from pyxcp_host.services.daq_acquisition import DaqAcquisition, event_period_seconds
from pyxcp_host.viewmodel import HostViewModel


DAQ_INFO = {
    "processor": {
        "minDaq": 0, "maxDaq": 0,
        "keyByte": {"identificationField": "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD"},
        "properties": {
            "configType": "DYNAMIC", "timestampSupported": True,
            "prescalerSupported": True, "pidOffSupported": False,
            "overloadMsb": False,
        },
    },
    "resolution": {
        "granularityOdtEntrySizeDaq": 1, "maxOdtEntrySizeDaq": 248,
        "timestampTicks": 1,
        "timestampMode": {"unit": "DAQ_TIMESTAMP_UNIT_1US", "fixed": True, "size": "S4"},
    },
}


class FakeMaster:
    def __init__(self, byte_order="INTEL", max_dto=255, info=None):
        self.slaveProperties = SimpleNamespace(
            supportsDaq=True, supportsCalpag=True, bytesPerElement=1,
            byteOrder=getattr(types.ByteOrder, byte_order), maxDto=max_dto, maxCto=255,
        )
        self.transport = SimpleNamespace(policy=NoOpPolicy(), policy_lock=threading.Lock())
        self.stim = SimpleNamespace(set_policy_feeder=lambda feeder: None)
        self.info = copy.deepcopy(info or DAQ_INFO)
        self.commands = []
        self.fail_start = False
        self.fail_stop = False
        self.event = {
            "eventChannelTimeCycle": 1, "eventChannelTimeUnit": "EVENT_CHANNEL_TIME_UNIT_1MS",
            "daqEventProperties": {"daq": True},
        }

    def getDaqInfo(self, include_event_lists=False):
        return self.info

    def getDaqEventInfo(self, number):
        self.commands.append(("event", number))
        return self.event

    def cond_unlock(self, resource):
        self.commands.append(("unlock", resource))

    def freeDaq(self):
        self.commands.append(("free",))

    def allocDaq(self, count):
        self.commands.append(("allocate", count))

    def allocOdt(self, number, count):
        self.commands.append(("odt", number, count))

    def allocOdtEntry(self, number, odt, count):
        self.commands.append(("entries", number, odt, count))

    def setDaqPtr(self, number, odt, entry):
        self.commands.append(("pointer", number, odt, entry))

    def writeDaq(self, bit, size, extension, address):
        self.commands.append(("write", bit, size, extension, address))

    def setDaqListMode(self, **kwargs):
        self.commands.append(("mode", kwargs))

    def startStopDaqList(self, mode, number):
        self.commands.append(("select", mode, number))
        return SimpleNamespace(firstPid=0)

    def startStopSynch(self, mode):
        self.commands.append(("sync", mode))
        if mode == 1 and self.fail_start:
            raise RuntimeError("start failed")
        if mode == 0 and self.fail_stop:
            raise RuntimeError("stop failed")


class FakeClient:
    exchange_acquisition_policy = XcpClient.exchange_acquisition_policy
    _validate_address_span = XcpClient._validate_address_span

    def __init__(self, master=None):
        self.master = master or FakeMaster()
        self.connected = True
        self.memory = bytearray(256)
        self.memory[0x20:0x24] = struct.pack("<f", 1.5)
        self.read_started = threading.Event()
        self.allow_read = threading.Event()
        self.allow_read.set()

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def read_memory(self, address, size, extension=0):
        self.read_started.set()
        self.allow_read.wait(2)
        return bytes(self.memory[address:address + size])

    def write_memory(self, address, payload, extension=0):
        self.memory[address:address + len(payload)] = payload

    def read_characteristic(self, scalar):
        return scalar.decode(self.read_memory(scalar.address, scalar.size))

    def write_characteristic(self, scalar, value, verify=True):
        payload = scalar.encode(value)
        self.write_memory(scalar.address, payload)
        return scalar.decode(self.read_memory(scalar.address, scalar.size))


def scalar(name="Output", address=0x10, data_type="FLOAT32_IEEE", byte_order="little"):
    return A2LScalar(name, "MEASUREMENT", address, data_type, byte_order)


def feed_sample(acquisition, ticks, values, counter=0, odts=None):
    policy = acquisition.policy
    prefix = "<" if policy._byte_order == "little" else ">"
    dtype = {"U8": "B", "I8": "b", "U16": "H", "I16": "h", "U32": "I", "I32": "i", "U64": "Q", "I64": "q", "F32": "f", "F64": "d"}
    frames = []
    for index, odt in enumerate(policy.daq_lists[0].measurements_opt):
        if policy._header_size == 1:
            frame = bytes([index + policy._first_pid])
        elif policy._header_size == 2:
            frame = bytes([index, 0])
        elif policy._header_size == 3:
            frame = bytes([index, 0, 0])
        else:
            frame = bytes([index, 0, 0, 0])
        if index == 0:
            frame += int(ticks).to_bytes(policy.ts_size, policy._byte_order)
        for entry in odt.entries:
            for component in entry.components:
                frame += struct.pack(prefix + dtype[component.data_type], values[component.name])
        frames.append(frame)
    for index in range(len(frames)) if odts is None else odts:
        with acquisition.client.master.transport.policy_lock:
            acquisition.client.master.transport.policy.feed(types.FrameCategory.DAQ, counter, 1000000, frames[index])
        counter = (counter + 1) & 0xFFFF
    return counter


class DaqAcquisitionTest(unittest.TestCase):
    def create(self, scalars=None, **kwargs):
        client = FakeClient(FakeMaster(**kwargs))
        daq = DaqAcquisition(client)
        metadata = daq.start(scalars or [scalar()])
        self.addCleanup(daq.stop)
        return daq, metadata

    def test_native_decoder_reads_model_event_with_prescaler_one(self):
        daq, metadata = self.create()
        self.assertEqual(metadata["period_seconds"], .001)
        self.assertEqual(metadata["timestamp_source"], "target")
        self.assertEqual(metadata["prescaler"], 1)
        mode = next(value for name, *rest in daq.client.master.commands if name == "mode" for value in rest)
        self.assertEqual(mode["event_channel_number"], 0)
        self.assertEqual(mode["prescaler"], 1)
        feed_sample(daq, 50000, {"Output": 12.25})
        feed_sample(daq, 51000, {"Output": -2.5}, counter=1)
        samples = daq.drain()
        self.assertEqual([row.timestamp_seconds for row in samples], [0, .001])
        self.assertEqual([row.values["Output"] for row in samples], [12.25, -2.5])

    def test_native_decoder_big_endian_all_scalar_types(self):
        specs = [("a", "SBYTE", -3), ("b", "UBYTE", 253), ("c", "SWORD", -1234), ("d", "UWORD", 65530), ("e", "SLONG", -123456), ("f", "ULONG", 4000000000), ("g", "A_INT64", -5000000000), ("h", "A_UINT64", 9000000000), ("i", "FLOAT32_IEEE", 1.5), ("j", "FLOAT64_IEEE", -12.125)]
        scalars = [scalar(name, 0x100 + index * 16, kind, "big") for index, (name, kind, value) in enumerate(specs)]
        daq, _ = self.create(scalars, byte_order="MOTOROLA")
        feed_sample(daq, 10, {name: value for name, kind, value in specs})
        self.assertEqual(daq.drain()[0].values, {name: value for name, kind, value in specs})

    def test_bounded_queue_counts_drops(self):
        daq = DaqAcquisition(FakeClient(), capacity=2)
        daq.start([scalar()])
        self.addCleanup(daq.stop)
        for index in range(4):
            feed_sample(daq, index * 1000, {"Output": index}, counter=index)
        self.assertEqual(daq.diagnostics()["queue_dropped_samples"], 2)
        self.assertEqual(daq.diagnostics()["received_samples"], 4)
        self.assertEqual(daq.drain(1)[0].values["Output"], 2)
        self.assertEqual(len(daq.drain()), 1)

    def test_timestamp_wrap_gap_and_reorder_accounting(self):
        daq, _ = self.create()
        feed_sample(daq, 0xFFFFFFFF - 499, {"Output": 1}, counter=65535)
        feed_sample(daq, 500, {"Output": 2}, counter=0)
        feed_sample(daq, 3500, {"Output": 3}, counter=1)
        feed_sample(daq, 3400, {"Output": 99}, counter=2)
        samples = daq.drain()
        self.assertEqual([sample.timestamp_seconds for sample in samples], [0, .001, .004])
        info = daq.diagnostics()
        self.assertEqual(info["timestamp_wraps"], 1)
        self.assertEqual(info["timestamp_gap_samples"], 2)
        self.assertEqual(info["timestamp_reorders"], 1)
        self.assertEqual(info["transport_counter_gaps"], 0)

    def test_incoming_cto_responses_do_not_create_false_packet_gaps(self):
        daq, _ = self.create()
        feed_sample(daq, 1000, {"Output": 1}, counter=9)
        daq.policy.feed(types.FrameCategory.CMD, 500, 0, b"\xf5")
        daq.policy.feed(types.FrameCategory.RESPONSE, 10, 0, b"\xff")
        feed_sample(daq, 2000, {"Output": 2}, counter=11)
        self.assertEqual(daq.diagnostics()["transport_counter_gaps"], 0)
        feed_sample(daq, 3000, {"Output": 3}, counter=14)
        self.assertEqual(daq.diagnostics()["transport_counter_gaps"], 2)

    def test_invalid_identifiers_and_truncated_payloads_never_reach_native_decoder(self):
        daq, _ = self.create()
        for index, frame in enumerate([b"", b"\x00\x01\x00" + bytes(12), b"\x08\x00\x00" + bytes(12), b"\x00\x00\x00\x01"]):
            daq.policy.feed(types.FrameCategory.DAQ, index, 0, frame)
        self.assertEqual(daq.diagnostics()["invalid_frames"], 4)
        feed_sample(daq, 1000, {"Output": 5}, counter=4)
        self.assertEqual(daq.drain()[0].values["Output"], 5)

    def test_missing_odt_resynchronizes_without_mixing_events(self):
        daq, metadata = self.create([scalar("a"), scalar("b", 0x20)], max_dto=11)
        self.assertEqual(metadata["odt_count"], 2)
        feed_sample(daq, 1000, {"a": 1, "b": 10}, counter=0, odts=[0])
        feed_sample(daq, 2000, {"a": 2, "b": 20}, counter=2)
        rows = daq.drain()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].values, {"a": 2, "b": 20})
        self.assertEqual(daq.diagnostics()["incomplete_events"], 1)

    def test_absolute_and_aligned_relative_ids(self):
        for identification in ["IDF_ABS_ODT_NUMBER", "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_BYTE", "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD_ALIGNED"]:
            with self.subTest(identification=identification):
                info = copy.deepcopy(DAQ_INFO)
                info["processor"]["keyByte"]["identificationField"] = identification
                daq, _ = self.create(info=info)
                feed_sample(daq, 1000, {"Output": 4.25})
                self.assertEqual(daq.drain()[0].values["Output"], 4.25)

    def test_stop_keeps_final_rows_and_restores_original_policy(self):
        client = FakeClient()
        original = client.master.transport.policy
        daq = DaqAcquisition(client)
        daq.start([scalar()])
        feed_sample(daq, 1000, {"Output": 1})
        daq.stop()
        self.assertFalse(daq.active)
        self.assertIs(client.master.transport.policy, original)
        self.assertEqual(len(daq.drain()), 1)
        daq.stop()

    def test_failed_start_restores_policy_and_stops_target(self):
        client = FakeClient()
        client.master.fail_start = True
        original = client.master.transport.policy
        daq = DaqAcquisition(client)
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            daq.start([scalar()])
        self.assertFalse(daq.active)
        self.assertIs(client.master.transport.policy, original)
        self.assertEqual(client.master.commands[-1], ("sync", 0))

    def test_failed_stop_keeps_active_decoder_for_retry(self):
        daq, _ = self.create()
        daq.client.master.fail_stop = True
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            daq.stop()
        self.assertTrue(daq.active)
        self.assertIs(daq.client.master.transport.policy, daq.policy)
        daq.client.master.fail_stop = False
        daq.stop()

    def test_unconfirmed_failed_start_retains_ownership_for_retry(self):
        client = FakeClient()
        original_start_stop = client.master.startStopSynch
        def fail_after_start(mode):
            if mode == 1:
                client.master.fail_stop = True
                raise RuntimeError("start response lost")
            return original_start_stop(mode)
        client.master.startStopSynch = fail_after_start
        daq = DaqAcquisition(client)
        with self.assertRaisesRegex(RuntimeError, "stop was not confirmed"):
            daq.start([scalar()])
        self.assertTrue(daq.active)
        self.assertIs(client.master.transport.policy, daq.policy)
        client.master.fail_stop = False
        daq.stop()
        self.assertFalse(daq.active)

    def test_nonperiodic_and_unsupported_daq_fail_without_start(self):
        client = FakeClient()
        client.master.event["eventChannelTimeCycle"] = 0
        with self.assertRaisesRegex(RuntimeError, "periodic"):
            DaqAcquisition(client).start([scalar()])
        self.assertFalse(any(command[0] == "free" for command in client.master.commands))
        client.master.slaveProperties.supportsDaq = False
        with self.assertRaisesRegex(RuntimeError, "support DAQ"):
            DaqAcquisition(client).start([scalar()])

    def test_unsupported_event_info_uses_only_matching_a2l_metadata(self):
        client = FakeClient()
        def unsupported(number):
            raise types.XcpResponseError(types.XcpError.ERR_CMD_UNKNOWN)
        client.master.getDaqEventInfo = unsupported
        daq = DaqAcquisition(client)
        metadata = daq.start([scalar()], a2l_events=[A2LDaqEvent("10ms", 0, "DAQ", 1, 7, 255)])
        self.addCleanup(daq.stop)
        self.assertEqual(metadata["period_source"], "A2L EVENT")
        self.assertEqual(metadata["period_seconds"], .01)
        daq.stop()
        with self.assertRaisesRegex(RuntimeError, "unique matching EVENT"):
            daq.start([scalar()], a2l_events=[A2LDaqEvent("other", 1, "DAQ", 1, 6, 255)])
        with self.assertRaisesRegex(RuntimeError, "periodic DAQ-capable"):
            daq.start([scalar()], a2l_events=[A2LDaqEvent("triggered", 0, "DAQ", 0, 6, 255)])

    def test_event_timeout_and_out_of_range_do_not_use_a2l_fallback(self):
        for error in (types.XcpTimeoutError("timeout"), types.XcpResponseError(types.XcpError.ERR_OUT_OF_RANGE)):
            with self.subTest(error=error):
                client = FakeClient()
                def fail(number):
                    raise error
                client.master.getDaqEventInfo = fail
                with self.assertRaises(type(error)):
                    DaqAcquisition(client).start([scalar()], a2l_events=[A2LDaqEvent("1ms", 0, "DAQ", 1, 6, 255)])
                self.assertFalse(any(command[0] == "free" for command in client.master.commands))
    def test_overlapping_aliases_rejected_before_configuration(self):
        client = FakeClient()
        with self.assertRaisesRegex(RuntimeError, "overlap"):
            DaqAcquisition(client).start([scalar("a"), scalar("alias")])
        self.assertEqual(client.master.commands, [])


class DaqSessionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "daq.a2l"
        self.path.write_text('''/begin PROJECT D "" /begin MODULE D ""
          /begin MOD_COMMON "" BYTE_ORDER MSB_LAST /end MOD_COMMON
          /begin RECORD_LAYOUT R FNC_VALUES 1 FLOAT32_IEEE COLUMN_DIR DIRECT /end RECORD_LAYOUT
          /begin MEASUREMENT Output "" FLOAT32_IEEE NO_COMPU_METHOD 0 0 -100 100 ECU_ADDRESS 0x10 /end MEASUREMENT
          /begin CHARACTERISTIC Gain "" VALUE 0x20 R 0 NO_COMPU_METHOD -100 100 /end CHARACTERISTIC
          /end MODULE /end PROJECT''', encoding="ascii")
        self.catalog = A2LCatalogService()
        self.catalog.load(self.path)
        self.client = FakeClient()
        self.session = XcpSession(self.catalog, lambda settings: self.client)
        self.session.connect(Endpoint("UDP", "127.0.0.1", 17725))
        self.addCleanup(self.session.disconnect)

    def test_calibration_write_and_restore_do_not_stop_daq(self):
        self.session.start_daq(["Output"])
        self.session.write_calibrations({"Gain": 2.75})
        feed_sample(self.session._daq, 1000, {"Output": 2.75})
        self.assertEqual(self.session.drain_daq()[0].values["Output"], 2.75)
        self.assertTrue(self.session.daq_active)
        self.session.restore_calibrations()
        self.assertTrue(self.session.daq_active)
        self.assertEqual(struct.unpack("<f", self.client.memory[0x20:0x24])[0], 1.5)

    def test_drain_and_dto_delivery_are_independent_of_calibration_lock(self):
        self.session.start_daq(["Output"])
        self.client.allow_read.clear()
        worker = threading.Thread(target=lambda: self.session.read_calibrations(["Gain"]))
        worker.start()
        self.assertTrue(self.client.read_started.wait(1))
        try:
            feed_sample(self.session._daq, 1000, {"Output": 5})
            self.assertEqual(self.session.drain_daq()[0].values["Output"], 5)
            self.assertTrue(worker.is_alive())
        finally:
            self.client.allow_read.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_disconnect_restores_calibrations_and_stops_daq(self):
        self.session.start_daq(["Output"])
        self.session.write_calibrations({"Gain": 2.5})
        self.session.disconnect()
        self.assertFalse(self.session.daq_active)
        self.assertFalse(self.session.connected)
        self.assertEqual(struct.unpack("<f", self.client.memory[0x20:0x24])[0], 1.5)

    def test_ui_diagnostics_do_not_wait_for_calibration_command(self):
        self.client.allow_read.clear()
        worker = threading.Thread(target=lambda: self.session.read_calibrations(["Gain"]))
        worker.start()
        self.assertTrue(self.client.read_started.wait(1))
        result = []
        reader = threading.Thread(target=lambda: result.append(self.session.diagnostics()))
        try:
            reader.start()
            reader.join(.5)
            self.assertFalse(reader.is_alive())
            self.assertTrue(result[0]['connected'])
            self.assertTrue(result[0]['supports_daq'])
        finally:
            self.client.allow_read.set()
            worker.join(2)
            reader.join(2)

    def test_viewmodel_contract_has_no_per_sample_logs(self):
        vm = HostViewModel(catalog_service=self.catalog, session=self.session)
        metadata = vm.start_daq(["Output"])
        self.assertEqual(metadata["period_seconds"], .001)
        count = len(vm.log_lines)
        for index in range(3):
            feed_sample(self.session._daq, index * 1000, {"Output": index}, counter=index)
        self.assertEqual(len(vm.drain_daq()), 3)
        self.assertEqual(len(vm.log_lines), count)
        self.assertEqual(vm.diagnostics["daq"]["received_samples"], 3)
        vm.stop_daq()
        self.assertFalse(vm.daq_active)


if __name__ == "__main__":
    unittest.main()
