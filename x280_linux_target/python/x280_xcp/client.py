"""pyXCP 0.22.32 ETH client and safe calibration operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import SimpleNamespace
from typing import Any, Callable, Optional, Union

from traitlets.config import Config

from pyxcp.config import General, Transport
from pyxcp.master import Master
from pyxcp.transport.base import NoOpPolicy

from .a2l import A2LScalar


class XcpClientError(RuntimeError):
    """Base error for X280 XCP client operations."""


class CalibrationVerificationError(XcpClientError):
    """Raised when a calibration value does not read back exactly."""


class CalibrationRestoreError(XcpClientError):
    """Raised when the original calibration bytes cannot be restored."""


@dataclass(frozen=True)
class TransportSettings:
    """Configuration for XCP on Ethernet over TCP or UDP."""

    host: str
    port: int = 17725
    timeout: float = 2.0
    bind_address: Optional[str] = None
    bind_port: Optional[int] = None
    ipv6: bool = False
    protocol: str = "UDP"
    tcp_nodelay: bool = True

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("XCP host must not be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("XCP port must be between 1 and 65535")
        if self.timeout <= 0:
            raise ValueError("XCP timeout must be positive")
        if self.bind_port is not None and not 0 <= self.bind_port <= 65535:
            raise ValueError("Local bind port must be between 0 and 65535")
        protocol = self.protocol.strip().upper()
        if protocol not in {"TCP", "UDP"}:
            raise ValueError("XCP Ethernet protocol must be TCP or UDP")
        object.__setattr__(self, "protocol", protocol)


@dataclass(frozen=True)
class UdpTransportSettings(TransportSettings):
    """Backward-compatible settings fixed to XCP on UDP."""

    protocol: str = field(default="UDP", init=False)


@dataclass(frozen=True)
class TcpTransportSettings(TransportSettings):
    """Convenience settings fixed to XCP on TCP."""

    port: int = 5555
    protocol: str = field(default="TCP", init=False)


@dataclass(frozen=True)
class CalibrationSmokeResult:
    name: str
    original_value: Union[int, float]
    requested_value: Union[int, float]
    readback_value: Union[int, float]
    restored_value: Union[int, float]


def build_pyxcp_config(settings: TransportSettings) -> Any:
    """Build a pyXCP configuration in memory for ETH/TCP or ETH/UDP."""

    config = Config()
    config.Transport.layer = "ETH"
    config.Transport.timeout = float(settings.timeout)
    config.Transport.alignment = 1
    config.Eth.host = settings.host
    config.Eth.port = settings.port
    config.Eth.protocol = settings.protocol
    config.Eth.ipv6 = settings.ipv6
    config.Eth.bind_to_address = settings.bind_address
    config.Eth.bind_to_port = settings.bind_port
    config.Eth.tcp_nodelay = settings.tcp_nodelay
    return SimpleNamespace(
        general=General(config=config),
        transport=Transport(config=config),
    )


class ClientState(str, Enum):
    """Lifecycle states for one client-owned pyXCP Master."""

    NEW = "new"
    OPENING = "opening"
    CONNECTED = "connected"
    CLOSED = "closed"


def _create_master(transport_name: str, config: Any) -> Any:
    # The legacy policy retains every command/response in unbounded queues.
    # DAQ installs its bounded consumer only while an acquisition is active.
    return Master(transport_name, config=config, policy=NoOpPolicy())


class XcpClient:
    """Single-use XCP master for byte-addressed memory over TCP or UDP.

    One instance owns at most one pyXCP ``Master``. Use a fresh client object for
    each new session; a client cannot reconnect after disconnect or connect failure.
    """

    def __init__(
        self,
        settings: TransportSettings,
        master_factory: Callable[..., Any] = _create_master,
    ) -> None:
        self.settings = settings
        self._master_factory = master_factory
        self._master: Optional[Any] = None
        self._state = ClientState.NEW
        self.connect_response: Optional[Any] = None

    @property
    def connected(self) -> bool:
        return self._master is not None and self._state is ClientState.CONNECTED

    @property
    def state(self) -> ClientState:
        return self._state

    @property
    def master(self) -> Any:
        if not self.connected:
            raise XcpClientError("XCP client is not connected")
        return self._master

    def connect(self) -> Any:
        if self.connected:
            return self.connect_response
        if self._state is not ClientState.NEW:
            raise XcpClientError(
                f"This single-use XCP client cannot connect from state {self._state.value!r}"
            )

        self._state = ClientState.OPENING
        master = None
        try:
            master = self._master_factory("eth", config=build_pyxcp_config(self.settings))
            self._master = master
            master.transport.connect()
            response = master.connect()
        except BaseException:
            try:
                if master is not None:
                    master.close()
            finally:
                self._master = None
                self._state = ClientState.CLOSED
            raise
        self.connect_response = response
        self._state = ClientState.CONNECTED
        return response

    def disconnect(self) -> None:
        master = self._master
        if master is None:
            if self._state is ClientState.NEW:
                self._state = ClientState.CLOSED
            return
        try:
            if self._state is ClientState.CONNECTED:
                master.disconnect()
        finally:
            try:
                master.close()
            finally:
                self._master = None
                self._state = ClientState.CLOSED
                self.connect_response = None

    def exchange_acquisition_policy(self, policy: Any) -> Any:
        """Swap the DTO consumer without racing the transport listener.

        The caller owns the returned policy and decides when to finalize it.
        Commands remain serialized by the application session; this lock is held
        only for the pointer swap, never while waiting for a command response.
        """
        master = self.master
        policy.xcp_master = master
        with master.transport.policy_lock:
            previous = master.transport.policy
            master.stim.set_policy_feeder(policy.feed)
            master.transport.policy = policy
        return previous

    def __enter__(self) -> "XcpClient":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.disconnect()

    def _require_byte_addressing(self) -> None:
        granularity = getattr(self.master.slaveProperties, "bytesPerElement", None)
        if granularity != 1:
            raise XcpClientError(
                "The X280 memory API requires XCP BYTE address granularity; "
                f"the slave reported {granularity!r}"
            )

    @staticmethod
    def _validate_address(address: int, address_extension: int) -> None:
        if not 0 <= address <= 0xFFFFFFFF:
            raise ValueError("XCP address must fit in 32 bits")
        if not 0 <= address_extension <= 0xFF:
            raise ValueError("XCP address extension must fit in 8 bits")

    @classmethod
    def _validate_address_span(cls, address: int, size: int, address_extension: int) -> None:
        cls._validate_address(address, address_extension)
        if size > 0 and size - 1 > 0xFFFFFFFF - address:
            raise ValueError("Memory operation crosses the XCP 32-bit address boundary")

    def read_memory(self, address: int, size: int, address_extension: int = 0) -> bytes:
        """Read exactly ``size`` byte-addressed bytes from the slave."""

        if size < 0:
            raise ValueError("Read size must not be negative")
        self._validate_address_span(address, size, address_extension)
        master = self.master
        if size == 0:
            return b""
        self._require_byte_addressing()

        max_chunk = min(0xFF, int(master.slaveProperties.maxCto) - 1)
        if max_chunk < 1:
            raise XcpClientError("Slave MAX_CTO is too small for UPLOAD")
        master.setMta(address, address_extension)
        result = bytearray()
        remaining = size
        while remaining:
            chunk_size = min(remaining, max_chunk)
            chunk = bytes(master.upload(chunk_size))
            if len(chunk) != chunk_size:
                raise XcpClientError(
                    f"UPLOAD returned {len(chunk)} bytes; expected {chunk_size}"
                )
            result.extend(chunk)
            remaining -= chunk_size
        return bytes(result)

    def write_memory(self, address: int, data: bytes, address_extension: int = 0) -> None:
        """Write byte-addressed data to the slave using bounded DOWNLOAD frames."""

        payload = bytes(data)
        self._validate_address_span(address, len(payload), address_extension)
        master = self.master
        if not payload:
            return
        self._require_byte_addressing()

        max_chunk = min(0xFF, int(master.slaveProperties.maxCto) - 2)
        if max_chunk < 1:
            raise XcpClientError("Slave MAX_CTO is too small for DOWNLOAD")
        master.setMta(address, address_extension)
        for offset in range(0, len(payload), max_chunk):
            master.download(payload[offset : offset + max_chunk])

    def read_scalar(self, scalar: A2LScalar) -> Union[int, float]:
        payload = self.read_memory(scalar.address, scalar.size, scalar.address_extension)
        return scalar.decode(payload)

    def read_measurement(self, measurement: A2LScalar) -> Union[int, float]:
        """Read one scalar A2L MEASUREMENT."""

        if measurement.kind != "MEASUREMENT":
            raise XcpClientError(f"{measurement.name!r} is not a MEASUREMENT")
        return self.read_scalar(measurement)

    def read_characteristic(self, characteristic: A2LScalar) -> Union[int, float]:
        """Read one scalar A2L CHARACTERISTIC."""

        if characteristic.kind != "CHARACTERISTIC":
            raise XcpClientError(f"{characteristic.name!r} is not a CHARACTERISTIC")
        return self.read_scalar(characteristic)

    def write_scalar(self, scalar: A2LScalar, value: Union[str, int, float]) -> None:
        if scalar.kind != "CHARACTERISTIC":
            raise XcpClientError(f"Refusing to write non-CHARACTERISTIC {scalar.name!r}")
        self.write_memory(scalar.address, scalar.encode(value), scalar.address_extension)

    def write_characteristic(
        self,
        characteristic: A2LScalar,
        value: Union[str, int, float],
        *,
        verify: bool = True,
    ) -> Union[int, float]:
        """Write a CHARACTERISTIC and optionally verify its exact encoded bytes."""

        if characteristic.kind != "CHARACTERISTIC":
            raise XcpClientError(f"{characteristic.name!r} is not a CHARACTERISTIC")
        requested_bytes = characteristic.encode(value)
        self.write_memory(
            characteristic.address,
            requested_bytes,
            characteristic.address_extension,
        )
        if not verify:
            return characteristic.decode(requested_bytes)
        readback_bytes = self.read_memory(
            characteristic.address,
            characteristic.size,
            characteristic.address_extension,
        )
        if readback_bytes != requested_bytes:
            raise CalibrationVerificationError(
                f"Value for {characteristic.name} did not read back exactly"
            )
        return characteristic.decode(readback_bytes)

    def calibration_smoke_test(
        self,
        characteristic: A2LScalar,
        requested_value: Union[str, int, float],
    ) -> CalibrationSmokeResult:
        """Temporarily write a scalar and restore its exact original bytes in ``finally``."""

        if characteristic.kind != "CHARACTERISTIC":
            raise XcpClientError(
                f"Calibration smoke test requires a CHARACTERISTIC, got {characteristic.kind}"
            )
        original_bytes = self.read_memory(
            characteristic.address,
            characteristic.size,
            characteristic.address_extension,
        )
        requested_bytes = characteristic.encode(requested_value)
        if requested_bytes == original_bytes:
            raise XcpClientError("Requested calibration bytes equal the current value")

        original_value = characteristic.decode(original_bytes)
        readback_bytes = b""
        restored_bytes = b""
        try:
            self.write_memory(
                characteristic.address,
                requested_bytes,
                characteristic.address_extension,
            )
            readback_bytes = self.read_memory(
                characteristic.address,
                characteristic.size,
                characteristic.address_extension,
            )
            if readback_bytes != requested_bytes:
                raise CalibrationVerificationError(
                    f"Temporary value for {characteristic.name} did not read back exactly"
                )
        finally:
            try:
                self.write_memory(
                    characteristic.address,
                    original_bytes,
                    characteristic.address_extension,
                )
                restored_bytes = self.read_memory(
                    characteristic.address,
                    characteristic.size,
                    characteristic.address_extension,
                )
            except BaseException as exc:
                raise CalibrationRestoreError(
                    f"Failed to restore original bytes for {characteristic.name}"
                ) from exc
            if restored_bytes != original_bytes:
                raise CalibrationRestoreError(
                    f"Original bytes for {characteristic.name} did not read back after restore"
                )

        return CalibrationSmokeResult(
            name=characteristic.name,
            original_value=original_value,
            requested_value=characteristic.decode(requested_bytes),
            readback_value=characteristic.decode(readback_bytes),
            restored_value=characteristic.decode(restored_bytes),
        )


class XcpUdpClient(XcpClient):
    """Backward-compatible XCP client restricted to UDP settings."""

    def __init__(
        self,
        settings: TransportSettings,
        master_factory: Callable[..., Any] = _create_master,
    ) -> None:
        if settings.protocol != "UDP":
            raise ValueError("XcpUdpClient requires UDP transport settings")
        super().__init__(settings, master_factory)


class XcpTcpClient(XcpClient):
    """Convenience XCP client restricted to TCP settings."""

    def __init__(
        self,
        settings: TransportSettings,
        master_factory: Callable[..., Any] = _create_master,
    ) -> None:
        if settings.protocol != "TCP":
            raise ValueError("XcpTcpClient requires TCP transport settings")
        super().__init__(settings, master_factory)
