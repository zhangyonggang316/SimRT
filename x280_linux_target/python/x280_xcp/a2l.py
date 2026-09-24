"""Minimal ASAP2 parser for scalar XCP memory access.

This intentionally parses only the information needed by the X280 smoke test:
scalar CHARACTERISTIC and MEASUREMENT names, addresses, address extensions, and
primitive storage types. It is not intended to replace a complete ASAP2 parser.
"""

from __future__ import annotations

import math
import io
import re
import shlex
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Tuple, Union


class A2LError(ValueError):
    """Raised when required scalar information cannot be read from an A2L file."""


_TYPE_FORMATS: Mapping[str, Tuple[str, int]] = {
    "SBYTE": ("b", 1),
    "UBYTE": ("B", 1),
    "SWORD": ("h", 2),
    "UWORD": ("H", 2),
    "SLONG": ("i", 4),
    "ULONG": ("I", 4),
    "A_INT64": ("q", 8),
    "A_UINT64": ("Q", 8),
    "FLOAT32_IEEE": ("f", 4),
    "FLOAT64_IEEE": ("d", 8),
}

_BLOCK_RE = re.compile(
    r"/begin\s+(RECORD_LAYOUT|CHARACTERISTIC|MEASUREMENT)\b(.*?)/end\s+\1\b",
    flags=re.IGNORECASE | re.DOTALL,
)
_COMMENT_RE = re.compile(r"/\*.*?\*/", flags=re.DOTALL)
_BYTE_ORDER_RE = re.compile(r"\bBYTE_ORDER\s+(MSB_FIRST|MSB_LAST)\b", flags=re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [token for token, _quoted in _token_strings(text)]


def _token_strings(text: str) -> list[Tuple[str, bool]]:
    stream = io.StringIO(text)
    lexer = shlex.shlex(stream, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    result = []
    while True:
        start = stream.tell()
        token = lexer.get_token()
        if token is None:
            return result
        spelling = text[start:stream.tell()].lstrip()
        result.append((token, spelling.startswith(('"', "'"))))


def _parse_integer(value: str, context: str) -> int:
    try:
        parsed = int(value, 0)
    except ValueError as exc:
        raise A2LError(f"Invalid {context}: {value!r}") from exc
    if not 0 <= parsed <= 0xFFFFFFFF:
        raise A2LError(f"{context} is outside the XCP 32-bit address range: {value!r}")
    return parsed


def _keyword_value(tokens: list[str], keyword: str) -> Optional[str]:
    keyword = keyword.upper()
    for index, token in enumerate(tokens[:-1]):
        if token.upper() == keyword:
            return tokens[index + 1]
    return None


def _is_scalar(tokens: list[str], characteristic_type: Optional[str] = None) -> bool:
    if characteristic_type is not None and characteristic_type.upper() != "VALUE":
        return False
    if any(token.upper() == "ARRAY_SIZE" for token in tokens):
        return False
    matrix_index = next(
        (index for index, token in enumerate(tokens) if token.upper() == "MATRIX_DIM"),
        None,
    )
    if matrix_index is None:
        return True
    dimensions = []
    for token in tokens[matrix_index + 1 :]:
        try:
            dimensions.append(int(token, 0))
        except ValueError:
            break
    return bool(dimensions) and all(dimension == 1 for dimension in dimensions)


@dataclass(frozen=True)
class A2LScalar:
    """A directly addressable primitive scalar described by ASAP2."""

    name: str
    kind: str
    address: int
    data_type: str
    byte_order: str = "little"
    address_extension: int = 0

    def __post_init__(self) -> None:
        normalized_kind = self.kind.upper()
        normalized_type = self.data_type.upper()
        if normalized_kind not in {"CHARACTERISTIC", "MEASUREMENT"}:
            raise A2LError(f"Unsupported ASAP2 object kind: {self.kind!r}")
        if normalized_type not in _TYPE_FORMATS:
            raise A2LError(f"Unsupported ASAP2 scalar type: {self.data_type!r}")
        if self.byte_order not in {"little", "big"}:
            raise A2LError(f"Unsupported byte order: {self.byte_order!r}")
        if not 0 <= self.address <= 0xFFFFFFFF:
            raise A2LError("XCP address must fit in 32 bits")
        if not 0 <= self.address_extension <= 0xFF:
            raise A2LError("XCP address extension must fit in 8 bits")
        object.__setattr__(self, "kind", normalized_kind)
        object.__setattr__(self, "data_type", normalized_type)

    @property
    def size(self) -> int:
        return _TYPE_FORMATS[self.data_type][1]

    @property
    def is_float(self) -> bool:
        return self.data_type.startswith("FLOAT")

    @property
    def struct_format(self) -> str:
        prefix = "<" if self.byte_order == "little" else ">"
        return prefix + _TYPE_FORMATS[self.data_type][0]

    def decode(self, payload: bytes) -> Union[int, float]:
        if len(payload) != self.size:
            raise A2LError(
                f"{self.name} requires {self.size} bytes, received {len(payload)}"
            )
        return struct.unpack(self.struct_format, payload)[0]

    def encode(self, value: Union[str, int, float]) -> bytes:
        try:
            converted: Union[int, float]
            if self.is_float:
                converted = float(value)
                if not math.isfinite(converted):
                    raise ValueError("floating-point value must be finite")
            elif isinstance(value, str):
                converted = int(value, 0)
            else:
                converted = int(value)
                if converted != value:
                    raise ValueError("integer scalar requires an integral value")
            return struct.pack(self.struct_format, converted)
        except (OverflowError, TypeError, ValueError, struct.error) as exc:
            raise A2LError(
                f"Value {value!r} cannot be encoded as {self.data_type} for {self.name}"
            ) from exc


@dataclass(frozen=True)
class A2LDaqEvent:
    name: str
    channel: int
    capability: str
    cycle: int
    unit: int
    max_daq_lists: int

    @property
    def period_seconds(self) -> float:
        exponent = self.unit - 9 if self.unit <= 9 else self.unit - 22
        return self.cycle * (10.0 ** exponent)


def _daq_events(text: str) -> Tuple[A2LDaqEvent, ...]:
    """Read concrete XCP/DAQ EVENT blocks, not similarly named A2ML schema tokens."""
    tokens = _token_strings(text)
    stack = []
    events = {}
    index = 0
    while index < len(tokens):
        token, quoted = tokens[index]
        if token == "/begin" and not quoted:
            if index + 1 >= len(tokens):
                raise A2LError("Truncated ASAP2 block header")
            stack.append((tokens[index + 1][0].upper(), []))
            index += 2
            continue
        if token == "/end" and not quoted:
            if index + 1 >= len(tokens) or not stack or stack[-1][0] != tokens[index + 1][0].upper():
                raise A2LError("Mismatched ASAP2 block boundary")
            kind, body = stack.pop()
            if kind == "EVENT" and stack and stack[-1][0] == "DAQ" and any(
                owner == "IF_DATA" and values and values[0].upper() == "XCP"
                for owner, values in stack
            ):
                if len(body) < 8:
                    raise A2LError("Truncated XCP DAQ EVENT metadata")
                name, short_name, channel, capability, maximum, cycle, unit, priority = body[:8]
                numeric = [_parse_integer(value, "XCP EVENT field") for value in (channel, maximum, cycle, unit, priority)]
                channel_num, max_lists, cycle_num, unit_num, priority_num = numeric
                if channel_num > 0xFFFF or any(value > 0xFF for value in numeric[1:]) or unit_num > 12:
                    raise A2LError("XCP EVENT metadata is outside its protocol field range")
                if capability.upper() not in {"DAQ", "STIM", "DAQ_STIM"}:
                    raise A2LError("Invalid XCP EVENT capability")
                if channel_num in events:
                    raise A2LError("Duplicate XCP DAQ EVENT channel {}".format(channel_num))
                events[channel_num] = A2LDaqEvent(name, channel_num, capability.upper(), cycle_num, unit_num, max_lists)
            index += 2
            continue
        if stack:
            stack[-1][1].append(token)
        index += 1
    if stack:
        raise A2LError("Unclosed ASAP2 block")
    return tuple(events.values())


class A2LDatabase:
    """Collection of scalar CHARACTERISTIC and MEASUREMENT entries."""

    def __init__(self, scalars: Iterable[A2LScalar], byte_order: str, daq_events: Iterable[A2LDaqEvent] = ()) -> None:
        by_name: Dict[str, A2LScalar] = {}
        for scalar in scalars:
            if scalar.name in by_name:
                raise A2LError(f"Duplicate scalar name in A2L: {scalar.name}")
            by_name[scalar.name] = scalar
        self._scalars = by_name
        self.byte_order = byte_order
        self.daq_events = tuple(daq_events)

    @property
    def scalars(self) -> Tuple[A2LScalar, ...]:
        return tuple(self._scalars.values())

    @property
    def characteristics(self) -> Tuple[A2LScalar, ...]:
        return tuple(item for item in self.scalars if item.kind == "CHARACTERISTIC")

    @property
    def measurements(self) -> Tuple[A2LScalar, ...]:
        return tuple(item for item in self.scalars if item.kind == "MEASUREMENT")

    def get(self, name: str, kind: Optional[str] = None) -> A2LScalar:
        try:
            scalar = self._scalars[name]
        except KeyError as exc:
            raise A2LError(f"Scalar {name!r} was not found in the A2L file") from exc
        if kind is not None and scalar.kind != kind.upper():
            raise A2LError(f"{name!r} is a {scalar.kind}, not a {kind.upper()}")
        return scalar


def _layout_types(blocks: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    layouts: Dict[str, str] = {}
    for kind, body in blocks:
        if kind.upper() != "RECORD_LAYOUT":
            continue
        tokens = _tokens(body)
        if not tokens:
            continue
        fnc_index = next(
            (index for index, token in enumerate(tokens) if token.upper() == "FNC_VALUES"),
            None,
        )
        if fnc_index is None or fnc_index + 2 >= len(tokens):
            continue
        data_type = tokens[fnc_index + 2].upper()
        if data_type in _TYPE_FORMATS:
            layouts[tokens[0]] = data_type
    return layouts


def _infer_layout_type(layout: str) -> Optional[str]:
    upper = layout.upper()
    for data_type in sorted(_TYPE_FORMATS, key=len, reverse=True):
        if upper.endswith(data_type):
            return data_type
    if upper.endswith("BOOLEAN"):
        return "UBYTE"
    return None


def parse_a2l(source: Union[str, Path]) -> A2LDatabase:
    """Parse scalar address/type metadata from an A2L file."""

    path = Path(source)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise A2LError(f"Cannot read A2L file {path}: {exc}") from exc
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("latin-1")

    uncommented = _COMMENT_RE.sub(" ", text)
    order_match = _BYTE_ORDER_RE.search(uncommented)
    byte_order = "big" if order_match and order_match.group(1).upper() == "MSB_FIRST" else "little"
    blocks = [(match.group(1), match.group(2)) for match in _BLOCK_RE.finditer(uncommented)]
    layouts = _layout_types(blocks)
    scalars = []

    for raw_kind, body in blocks:
        kind = raw_kind.upper()
        if kind == "RECORD_LAYOUT":
            continue
        tokens = _tokens(body)
        if kind == "CHARACTERISTIC":
            if len(tokens) < 5 or not _is_scalar(tokens, tokens[2]):
                continue
            name, address_text, layout = tokens[0], tokens[3], tokens[4]
            data_type = layouts.get(layout) or _infer_layout_type(layout)
        else:
            if len(tokens) < 3 or not _is_scalar(tokens):
                continue
            name, data_type = tokens[0], tokens[2].upper()
            address_text = _keyword_value(tokens, "ECU_ADDRESS")

        if address_text is None or data_type not in _TYPE_FORMATS:
            continue
        extension_text = _keyword_value(tokens, "ECU_ADDRESS_EXTENSION") or "0"
        extension = _parse_integer(extension_text, f"address extension for {name}")
        if extension > 0xFF:
            raise A2LError(f"Address extension for {name} exceeds 8 bits")
        scalars.append(
            A2LScalar(
                name=name,
                kind=kind,
                address=_parse_integer(address_text, f"address for {name}"),
                data_type=data_type,
                byte_order=byte_order,
                address_extension=extension,
            )
        )

    return A2LDatabase(scalars, byte_order, _daq_events(uncommented))
