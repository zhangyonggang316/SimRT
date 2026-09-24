"""UI-facing data models for the standalone XCP host."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Tuple


DEFAULT_PORTS = {"TCP": 5555, "UDP": 17725}


class HostState(str, Enum):
    EMPTY = "empty"
    LOADED = "loaded"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    CLOSED = "closed"


@dataclass(frozen=True)
class Endpoint:
    protocol: str
    host: str
    port: int
    timeout: float = 2.0

    def __post_init__(self) -> None:
        protocol = self.protocol.strip().upper()
        if protocol not in DEFAULT_PORTS:
            raise ValueError("XCP 传输协议必须是 TCP 或 UDP。")
        if not self.host.strip():
            raise ValueError("目标地址不能为空。")
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("XCP 端口必须是 1 到 65535 的整数。")
        if float(self.timeout) <= 0:
            raise ValueError("XCP 超时时间必须大于 0。")
        object.__setattr__(self, "protocol", protocol)
        object.__setattr__(self, "host", self.host.strip())
        object.__setattr__(self, "port", int(self.port))
        object.__setattr__(self, "timeout", float(self.timeout))

    @property
    def summary(self) -> str:
        return "ETH/{} {}:{}".format(self.protocol, self.host, self.port)


@dataclass(frozen=True)
class ScalarView:
    name: str
    kind: str
    address: int
    address_extension: int
    data_type: str
    size: int
    model_path: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def address_text(self) -> str:
        if self.address_extension:
            return "0x{:08X} : 0x{:02X}".format(
                self.address, self.address_extension
            )
        return "0x{:08X}".format(self.address)


@dataclass(frozen=True)
class CatalogInfo:
    path: Path
    byte_order: str
    measurements: Tuple[ScalarView, ...]
    calibrations: Tuple[ScalarView, ...]
    declared_transports: Tuple[str, ...] = field(default_factory=tuple)
    declared_ports: Dict[str, int] = field(default_factory=dict)
    declared_hosts: Dict[str, str] = field(default_factory=dict)

    @property
    def scalar_count(self) -> int:
        return len(self.measurements) + len(self.calibrations)


@dataclass(frozen=True)
class ConnectionInfo:
    endpoint: Endpoint
    byte_order: str
    address_granularity_bytes: Any = None
    max_cto: Any = None
    max_dto: Any = None
    supports_calibration: bool = False
    supports_daq: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "transport": "ETH/{}".format(self.endpoint.protocol),
            "host": self.endpoint.host,
            "port": self.endpoint.port,
            "byte_order": self.byte_order,
            "address_granularity_bytes": self.address_granularity_bytes,
            "max_cto": self.max_cto,
            "max_dto": self.max_dto,
            "supports_calibration": self.supports_calibration,
            "supports_daq": self.supports_daq,
        }
