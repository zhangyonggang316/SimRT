"""Pure UI state helpers for the pyXCP host application."""

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Tuple


TCP_DEFAULT_PORT = 5555
UDP_DEFAULT_PORT = 17725
SUPPORTED_PROTOCOLS = ("TCP", "UDP")


class HostState(str, Enum):
    EMPTY = "EMPTY"
    LOADED = "LOADED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ACQUIRING = "ACQUIRING"
    ERROR = "ERROR"
    CLOSING = "CLOSING"


@dataclass(frozen=True)
class ControlPolicy:
    endpoint_enabled: bool
    a2l_enabled: bool
    connect_enabled: bool
    disconnect_enabled: bool
    observation_select_enabled: bool
    observation_start_enabled: bool
    observation_stop_enabled: bool
    calibration_enabled: bool


def normalize_state(value: Any, fallback: HostState = HostState.EMPTY) -> HostState:
    if isinstance(value, HostState):
        return value
    candidate = getattr(value, "value", value)
    if candidate is None:
        return fallback
    text = str(candidate).strip().upper()
    aliases = {
        "DISCONNECTED": HostState.LOADED,
        "READY": HostState.LOADED,
        "LOADING": HostState.CONNECTING,
        "BUSY": HostState.CONNECTING,
    }
    if text in aliases:
        return aliases[text]
    try:
        return HostState(text)
    except ValueError:
        return fallback


def control_policy(state: Any, has_a2l: bool = False) -> ControlPolicy:
    current = normalize_state(state)
    idle = current in (HostState.EMPTY, HostState.LOADED, HostState.ERROR)
    connected = current in (HostState.CONNECTED, HostState.ACQUIRING)
    acquiring = current == HostState.ACQUIRING
    return ControlPolicy(
        endpoint_enabled=idle,
        a2l_enabled=idle,
        connect_enabled=idle and has_a2l,
        disconnect_enabled=connected,
        observation_select_enabled=current in (HostState.LOADED, HostState.CONNECTED),
        observation_start_enabled=current == HostState.CONNECTED,
        observation_stop_enabled=acquiring,
        calibration_enabled=connected,
    )


def default_port(protocol: str) -> int:
    normalized = str(protocol).strip().upper()
    if normalized == "TCP":
        return TCP_DEFAULT_PORT
    if normalized == "UDP":
        return UDP_DEFAULT_PORT
    raise ValueError("协议必须是 TCP 或 UDP。")


def switch_protocol_port(
    protocol: str,
    current_port: str,
    previous_suggested_port: int,
    suggested_port: Optional[int] = None,
) -> Tuple[str, int]:
    """Switch default ports while preserving a port the operator edited."""

    suggested = default_port(protocol) if suggested_port is None else int(suggested_port)
    if not 1 <= suggested <= 65535:
        raise ValueError("建议端口必须在 1 到 65535 之间。")
    try:
        is_automatic = int(str(current_port).strip()) == int(previous_suggested_port)
    except ValueError:
        is_automatic = False
    return (str(suggested) if is_automatic else str(current_port), suggested)


@dataclass(frozen=True)
class ConnectionDraft:
    protocol: str = "TCP"
    host: str = "127.0.0.1"
    port: str = str(TCP_DEFAULT_PORT)
    timeout: str = "2.0"
    a2l_path: str = ""

    def validated(self, require_existing_a2l: bool = True) -> "ConnectionSettings":
        protocol = self.protocol.strip().upper()
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("协议必须是 TCP 或 UDP。")
        host = self.host.strip()
        if not host:
            raise ValueError("请输入目标主机。")
        try:
            port = int(self.port)
        except (TypeError, ValueError):
            raise ValueError("端口必须是整数。")
        if not 1 <= port <= 65535:
            raise ValueError("端口必须在 1 到 65535 之间。")
        try:
            timeout = float(self.timeout)
        except (TypeError, ValueError):
            raise ValueError("超时必须是数字。")
        if not 0.05 <= timeout <= 120.0:
            raise ValueError("超时必须在 0.05 到 120 秒之间。")
        path_text = self.a2l_path.strip()
        if not path_text:
            raise ValueError("请选择 A2L 文件。")
        path = Path(path_text).expanduser()
        if require_existing_a2l and not path.is_file():
            raise ValueError("A2L 文件不存在：{}".format(path))
        return ConnectionSettings(protocol, host, port, timeout, path)

    def with_protocol(self, protocol: str) -> "ConnectionDraft":
        return replace(self, protocol=protocol, port=str(default_port(protocol)))


@dataclass(frozen=True)
class ConnectionSettings:
    protocol: str
    host: str
    port: int
    timeout: float
    a2l_path: Path

    @property
    def endpoint(self) -> str:
        return "{} {}:{}".format(self.protocol, self.host, self.port)


def optional_attr(value: Any, name: str, default: Optional[Any] = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
