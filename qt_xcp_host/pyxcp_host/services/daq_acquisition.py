"""Model-event DAQ using pyxcp's native online decoder and a bounded UI queue."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Union

from pyxcp import types
from pyxcp.daq_stim import DAQ_ID_FIELD_SIZE, DaqList, DaqOnlinePolicy
from pyxcp.recorder import DaqOnlinePolicy as NativeDaqOnlinePolicy
from pyxcp.master.errorhandler import SystemExit as XcpCommandFailure

from .backend import XcpClientError


_DAQ_TYPES = {
    "SBYTE": "I8", "UBYTE": "U8", "SWORD": "I16", "UWORD": "U16",
    "SLONG": "I32", "ULONG": "U32", "A_INT64": "I64", "A_UINT64": "U64",
    "FLOAT32_IEEE": "F32", "FLOAT64_IEEE": "F64",
}


@dataclass(frozen=True)
class DaqSample:
    timestamp_seconds: float
    values: Dict[str, Union[int, float]]


def event_period_seconds(event: Any) -> float:
    """Return the advertised event period, rejecting asynchronous events."""
    cycle = int(event["eventChannelTimeCycle"])
    exponent = types.EVENT_CHANNEL_TIME_UNIT_TO_EXP.get(str(event["eventChannelTimeUnit"]))
    if cycle <= 0 or exponent is None or not event["daqEventProperties"]["daq"]:
        raise XcpClientError("DAQ requires a periodic, DAQ-capable model event.")
    return cycle * (10.0 ** exponent)


def resolve_event_period(master: Any, event_channel: int, a2l_events: Iterable[Any]) -> tuple:
    try:
        return event_period_seconds(master.getDaqEventInfo(event_channel)), "slave"
    except (types.XcpResponseError, XcpCommandFailure) as exc:
        code = exc.get_error_code() if isinstance(exc, types.XcpResponseError) else exc.error_code
        if code not in (types.XcpError.ERR_CMD_UNKNOWN, types.XcpError.ERR_CMD_SYNTAX):
            raise
        matches = [event for event in a2l_events if event.channel == event_channel]
        if len(matches) != 1:
            raise XcpClientError("GET_DAQ_EVENT_INFO is unsupported and the loaded A2L has no unique matching EVENT.") from exc
        event = matches[0]
        if event.capability not in {"DAQ", "DAQ_STIM"} or event.cycle <= 0 or event.max_daq_lists <= 0:
            raise XcpClientError("The matching A2L EVENT is not a periodic DAQ-capable event.") from exc
        return event.period_seconds, "A2L EVENT"


class BufferedDaqPolicy(DaqOnlinePolicy):
    """Validate DTO envelopes before handing their scalar payload to native code.

    pyxcp 0.22.32's native decoder assumes valid IDs and complete frames, and its
    online policy does not unwrap timestamps. Both are handled at this boundary.
    No callback takes the session's command lock or invokes Tk.
    """

    def __init__(self, daq_list: DaqList, period_seconds: float, capacity: int = 20000):
        if capacity < 1:
            raise ValueError("DAQ queue capacity must be positive.")
        # DaqProcessor.__init__ starts pyxcp's CLI singleton and consumes this
        # application's argv. Its only other work is these two assignments.
        self.daq_lists = [daq_list]
        self.log = logging.getLogger(__name__)
        NativeDaqOnlinePolicy.__init__(self)
        self.period_seconds = float(period_seconds)
        self._queue = deque(maxlen=capacity)
        self._queue_lock = threading.Lock()
        self._counts = {
            "received_samples": 0, "queue_dropped_samples": 0,
            "invalid_frames": 0, "incomplete_events": 0,
            "transport_counter_gaps": 0, "reordered_frames": 0,
            "timestamp_gap_samples": 0, "timestamp_wraps": 0,
            "timestamp_reorders": 0, "overload_events": 0,
        }
        self._ready = False
        self._active = False
        self._closed = False
        self._next_odt = 0
        self._reset_decoder = False
        self._counter = None
        self._last_raw_ns = None
        self._last_unwrapped_ns = None
        self._origin_ns = None
        self._wrap_offset_ns = 0

    def initialize(self):
        # Called by set_parameters, including decoder resynchronization.
        pass

    def finalize(self):
        self._closed = True
        self._active = False

    def prepare(self, info: dict) -> None:
        processor = info["processor"]
        self._header_size = DAQ_ID_FIELD_SIZE[str(processor["keyByte"]["identificationField"])]
        self._overload_msb = bool(processor["properties"].get("overloadMsb", False))
        self._byte_order = "little" if self.xcp_master.slaveProperties.byteOrder == "INTEL" else "big"
        self._first_pid = int(self.first_pids()[0])
        daq_list = self.daq_lists[0]
        self._names = tuple(header[0] for header in daq_list.headers)
        self._frame_lengths = []
        for index, odt in enumerate(daq_list.measurements_opt):
            size = self._header_size + sum(int(entry.length) for entry in odt.entries)
            if index == 0:
                size += self.ts_size
            self._frame_lengths.append(size)
        if not self._frame_lengths or len(self._frame_lengths) > 0xFC:
            raise XcpClientError("The DAQ list does not fit the available DTO identifiers.")
        if self._header_size == 1 and self._first_pid + len(self._frame_lengths) > (0x80 if self._overload_msb else 0xFC):
            raise XcpClientError("DAQ identifiers overlap reserved protocol identifiers.")
        # Native relative-list decoding indexes its vector directly, without MIN_DAQ.
        if self._header_size != 1 and int(self.min_daq) != 0:
            raise XcpClientError("pyxcp 0.22.32 cannot decode relative DAQ IDs with nonzero MIN_DAQ.")
        self._timestamp_modulus_ns = int(round((1 << (8 * self.ts_size)) * self.ts_scale_factor))
        if self._timestamp_modulus_ns <= self.period_seconds * 2e9:
            raise XcpClientError("DAQ timestamp range is too short to unwrap model events reliably.")
        self._ready = True

    def activate(self) -> None:
        self._active = True

    def _increment(self, name: str, amount: int = 1) -> None:
        with self._queue_lock:
            self._counts[name] += amount

    def feed(self, frame_type, counter, timestamp, payload):
        if self._closed or not self._ready:
            return
        incoming = frame_type in (
            types.FrameCategory.DAQ, types.FrameCategory.RESPONSE,
            types.FrameCategory.EVENT, types.FrameCategory.SERV,
        )
        if incoming:
            if self._counter is not None:
                delta = (int(counter) - self._counter) & 0xFFFF
                if delta == 0 or delta >= 0x8000:
                    self._increment("reordered_frames")
                    return
                elif delta > 1:
                    self._increment("transport_counter_gaps", delta - 1)
            self._counter = int(counter)
        if frame_type == types.FrameCategory.EVENT:
            if len(payload) > 1 and payload[1] == int(types.Event.EV_DAQ_OVERLOAD):
                self._increment("overload_events")
            return
        if frame_type != types.FrameCategory.DAQ or not self._active:
            return
        if len(payload) < self._header_size:
            self._invalid_frame()
            return
        pid = payload[0]
        if self._overload_msb and pid & 0x80:
            self._increment("overload_events")
            payload = bytes([pid & 0x7F]) + payload[1:]
            pid &= 0x7F
        if self._header_size == 1:
            odt = pid - self._first_pid
        else:
            offset = 2 if self._header_size == 4 else 1
            daq_number = int.from_bytes(payload[offset:self._header_size], self._byte_order)
            if daq_number != 0:
                self._invalid_frame()
                return
            odt = pid
        if not 0 <= odt < len(self._frame_lengths) or len(payload) < self._frame_lengths[odt]:
            self._invalid_frame()
            return
        if odt != self._next_odt:
            self._increment("incomplete_events")
            self._reset_decoder = True
            self._next_odt = 0
            if odt != 0:
                return
        if self._reset_decoder:
            self.set_parameters(self.measurement_params)
            self._reset_decoder = False
        self._next_odt = (odt + 1) % len(self._frame_lengths)
        super().feed(frame_type, counter, timestamp, payload)

    def _invalid_frame(self) -> None:
        self._increment("invalid_frames")
        self._reset_decoder = True
        self._next_odt = 0

    def on_daq_list(self, daq_list, timestamp0, timestamp1, payload):
        raw_ns = int(timestamp1)
        with self._queue_lock:
            if self._last_raw_ns is not None and raw_ns < self._last_raw_ns:
                if self._last_raw_ns - raw_ns > self._timestamp_modulus_ns // 2:
                    self._wrap_offset_ns += self._timestamp_modulus_ns
                    self._counts["timestamp_wraps"] += 1
                else:
                    self._counts["timestamp_reorders"] += 1
                    return
            unwrapped_ns = raw_ns + self._wrap_offset_ns
            if self._last_unwrapped_ns is not None:
                delta_ns = unwrapped_ns - self._last_unwrapped_ns
                if delta_ns <= 0:
                    self._counts["timestamp_reorders"] += 1
                    return
                if delta_ns > self.period_seconds * 1.5e9:
                    self._counts["timestamp_gap_samples"] += max(0, round(delta_ns / (self.period_seconds * 1e9)) - 1)
            self._last_raw_ns = raw_ns
            self._last_unwrapped_ns = unwrapped_ns
            if self._origin_ns is None:
                self._origin_ns = unwrapped_ns
            values = dict(zip(self._names, payload))
            if len(values) != len(self._names):
                self._counts["invalid_frames"] += 1
                return
            if len(self._queue) == self._queue.maxlen:
                self._counts["queue_dropped_samples"] += 1
            self._queue.append(DaqSample((unwrapped_ns - self._origin_ns) / 1e9, values))
            self._counts["received_samples"] += 1

    def drain(self, max_samples: int = 5000) -> List[DaqSample]:
        if max_samples < 1:
            raise ValueError("max_samples must be positive.")
        with self._queue_lock:
            return [self._queue.popleft() for _ in range(min(int(max_samples), len(self._queue)))]

    def diagnostics(self) -> dict:
        with self._queue_lock:
            return dict(self._counts, queued_samples=len(self._queue), queue_capacity=self._queue.maxlen)


class DaqAcquisition:
    """Control-plane DAQ lifecycle; caller serializes methods with calibration CTOs."""

    def __init__(self, client: Any, capacity: int = 20000):
        self.client = client
        self.capacity = capacity
        self.policy = None  # type: Optional[BufferedDaqPolicy]
        self._previous_policy = None
        self.active = False
        self.metadata = {}  # type: dict

    def start(self, scalars: Iterable[Any], event_channel: int = 0, a2l_events: Iterable[Any] = ()) -> dict:
        if self.active:
            raise XcpClientError("DAQ is already active. Stop it before changing the signal list.")
        selected = list(scalars)
        if not selected:
            raise ValueError("Select at least one measurement for DAQ.")
        if not 0 <= int(event_channel) <= 0xFFFF:
            raise ValueError("DAQ event channel must fit in 16 bits.")
        master = self.client.master
        if not master.slaveProperties.supportsDaq:
            raise XcpClientError("The connected slave does not support DAQ.")
        if master.slaveProperties.bytesPerElement != 1:
            raise XcpClientError("DAQ requires BYTE address granularity.")
        measurements = []
        for scalar in selected:
            if scalar.kind != "MEASUREMENT":
                raise XcpClientError("DAQ accepts MEASUREMENT objects only.")
            self.client._validate_address_span(scalar.address, scalar.size, scalar.address_extension)
            for other in selected[:len(measurements)]:
                if scalar.address_extension == other.address_extension and max(scalar.address, other.address) < min(scalar.address + scalar.size, other.address + other.size):
                    raise XcpClientError("DAQ measurements overlap in memory; select only one alias per address range.")
            measurements.append((scalar.name, scalar.address, scalar.address_extension, _DAQ_TYPES[scalar.data_type]))
        period, period_source = resolve_event_period(master, int(event_channel), a2l_events)
        info = master.getDaqInfo(include_event_lists=False)
        props = info["processor"]["properties"]
        resolution = info["resolution"]
        if str(props["configType"]) != "DYNAMIC" or not props["timestampSupported"]:
            raise XcpClientError("Model-rate DAQ requires dynamic lists and target timestamps.")
        if int(resolution["granularityOdtEntrySizeDaq"]) != 1:
            raise XcpClientError("DAQ requires byte-sized ODT entries.")
        mode = resolution["timestampMode"]
        if str(mode["size"]) not in {"S1", "S2", "S4"} or int(resolution["timestampTicks"]) <= 0:
            raise XcpClientError("The target advertised an invalid DAQ timestamp format.")
        header_size = DAQ_ID_FIELD_SIZE[str(info["processor"]["keyByte"]["identificationField"])]
        timestamp_size = {"S1": 1, "S2": 2, "S4": 4}[str(mode["size"])]
        if min(int(resolution["maxOdtEntrySizeDaq"]), int(master.slaveProperties.maxDto) - header_size) <= timestamp_size:
            raise XcpClientError("MAX_DTO is too small for timestamped measurement data.")
        if any(scalar.size > int(resolution["maxOdtEntrySizeDaq"]) for scalar in selected):
            raise XcpClientError("A measurement exceeds the target's maximum ODT entry size.")
        policy = BufferedDaqPolicy(DaqList(
            name="model_event", event_num=int(event_channel), stim=False,
            enable_timestamps=True, measurements=measurements, priority=0, prescaler=1,
        ), period, self.capacity)
        policy.xcp_master = master
        changed_target = False
        attached = False
        try:
            master.cond_unlock("DAQ")
            # setup() begins with FREE_DAQ; R2024b rejects STOP_ALL before
            # any list exists, so do not send it on this fresh acquisition.
            changed_target = True
            policy.setup()
            policy.prepare(info)
            if set(policy._names) != {scalar.name for scalar in selected}:
                raise XcpClientError("DAQ optimizer omitted a selected measurement.")
            self._previous_policy = self.client.exchange_acquisition_policy(policy)
            attached = True
            self.policy = policy
            policy.activate()
            policy.start()
        except BaseException as operation_error:
            cleanup_error = None
            if changed_target:
                try:
                    master.startStopSynch(0)
                except Exception as exc:
                    cleanup_error = exc
            if attached and cleanup_error is not None:
                # START may have reached the slave even if its response timed out.
                # Keep the consumer and ownership so Stop/Disconnect can retry.
                self.active = True
                raise XcpClientError(
                    "DAQ start failed and its stop was not confirmed; retry Stop or Disconnect."
                ) from cleanup_error
            if attached:
                self.client.exchange_acquisition_policy(self._previous_policy)
                self._previous_policy = None
            policy.finalize()
            raise operation_error
        self.active = True
        self.metadata = {
            "mode": "DAQ", "event_channel": int(event_channel),
            "period_seconds": period, "prescaler": 1,
            "period_source": period_source,
            "timestamp_source": "target", "signals": tuple(scalar.name for scalar in selected),
            "odt_count": len(policy._frame_lengths), "queue_capacity": self.capacity,
        }
        return dict(self.metadata)

    def stop(self) -> None:
        if not self.active:
            return
        self.policy.stop()
        self.client.exchange_acquisition_policy(self._previous_policy)
        self._previous_policy = None
        self.policy.finalize()
        self.active = False

    def drain(self, max_samples: int = 5000) -> List[DaqSample]:
        return self.policy.drain(max_samples) if self.policy is not None else []

    def diagnostics(self) -> dict:
        result = dict(self.metadata, active=self.active)
        if self.policy is not None:
            result.update(self.policy.diagnostics())
        return result
