"""Command-line interface for the X280 pyXCP Ethernet master."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any, Optional, Sequence

from .a2l import A2LDatabase, parse_a2l
from .client import TransportSettings, XcpClient


_DEFAULT_PORTS = {"UDP": 17725, "TCP": 5555}


def _integer(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value!r}") from exc


def _hex_bytes(value: str) -> bytes:
    compact = value.replace(" ", "").replace(":", "").replace("-", "")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("data must be hexadecimal bytes") from exc


def _add_a2l_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--a2l", required=True, help="matching ASAP2/A2L file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="X280 XCP-on-TCP/UDP master")
    parser.add_argument("--host", default="192.168.0.106", help="X280 address")
    parser.add_argument(
        "--protocol",
        choices=("udp", "tcp"),
        default="udp",
        help="XCP Ethernet transport (default: udp)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="XCP port (default: 17725 for UDP, 5555 for TCP)",
    )
    parser.add_argument("--timeout", type=float, default=2.0, help="command timeout in seconds")
    parser.add_argument("--bind-address", help="optional local IPv4/IPv6 address")
    parser.add_argument("--bind-port", type=int, help="optional local Ethernet port")
    parser.add_argument("--ipv6", action="store_true", help="use IPv6")

    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("probe", help="CONNECT, report slave properties, and DISCONNECT")

    list_parser = commands.add_parser("list", help="list supported scalar A2L entries offline")
    _add_a2l_argument(list_parser)
    list_parser.add_argument(
        "--kind",
        choices=("all", "characteristic", "measurement"),
        default="all",
    )

    read_memory = commands.add_parser("read-memory", help="read raw target bytes")
    read_memory.add_argument("address", type=_integer)
    read_memory.add_argument("size", type=_integer)
    read_memory.add_argument("--extension", type=_integer, default=0)

    write_memory = commands.add_parser("write-memory", help="write and verify raw target bytes")
    write_memory.add_argument("address", type=_integer)
    write_memory.add_argument("data", type=_hex_bytes)
    write_memory.add_argument("--extension", type=_integer, default=0)

    read_scalar = commands.add_parser("read-scalar", help="read an A2L scalar")
    _add_a2l_argument(read_scalar)
    read_scalar.add_argument("name")

    read_measurement = commands.add_parser(
        "read-measurement", help="read an A2L MEASUREMENT"
    )
    _add_a2l_argument(read_measurement)
    read_measurement.add_argument("name")

    read_characteristic = commands.add_parser(
        "read-characteristic", help="read an A2L CHARACTERISTIC"
    )
    _add_a2l_argument(read_characteristic)
    read_characteristic.add_argument("name")

    write_characteristic = commands.add_parser(
        "write-characteristic", help="write and verify an A2L CHARACTERISTIC"
    )
    _add_a2l_argument(write_characteristic)
    write_characteristic.add_argument("name")
    write_characteristic.add_argument("value", help="decimal or 0x-prefixed integer")

    calibration = commands.add_parser(
        "calibration-smoke",
        help="temporarily write one CHARACTERISTIC, verify it, and restore it",
    )
    _add_a2l_argument(calibration)
    calibration.add_argument("name")
    calibration.add_argument("value", help="temporary value; decimal or 0x-prefixed integer")
    return parser


def _settings(args: argparse.Namespace) -> TransportSettings:
    protocol = args.protocol.upper()
    return TransportSettings(
        host=args.host,
        port=args.port if args.port is not None else _DEFAULT_PORTS[protocol],
        timeout=args.timeout,
        bind_address=args.bind_address,
        bind_port=args.bind_port,
        ipv6=args.ipv6,
        protocol=protocol,
    )


def _database(args: argparse.Namespace) -> A2LDatabase:
    return parse_a2l(args.a2l)


def _slave_properties(client: XcpClient) -> dict[str, Any]:
    properties = client.master.slaveProperties
    return {
        "transport": f"ETH/{client.settings.protocol}",
        "host": client.settings.host,
        "port": client.settings.port,
        "byte_order": getattr(getattr(properties, "byteOrder", None), "name", None),
        "address_granularity_bytes": getattr(properties, "bytesPerElement", None),
        "max_cto": getattr(properties, "maxCto", None),
        "max_dto": getattr(properties, "maxDto", None),
        "supports_calibration": bool(getattr(properties, "supportsCalpag", False)),
        "supports_daq": bool(getattr(properties, "supportsDaq", False)),
    }


def main(
    argv: Optional[Sequence[str]] = None,
    client_type: type[XcpClient] = XcpClient,
) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "list":
        database = _database(args)
        scalars = database.scalars
        if args.kind == "characteristic":
            scalars = database.characteristics
        elif args.kind == "measurement":
            scalars = database.measurements
        output = [
            {
                "name": item.name,
                "kind": item.kind,
                "address": f"0x{item.address:08X}",
                "extension": item.address_extension,
                "data_type": item.data_type,
                "size": item.size,
            }
            for item in scalars
        ]
        print(json.dumps(output, indent=2, ensure_ascii=True))
        return 0

    with client_type(_settings(args)) as client:
        if args.command == "probe":
            output = _slave_properties(client)
        elif args.command == "read-memory":
            payload = client.read_memory(args.address, args.size, args.extension)
            output = {
                "address": f"0x{args.address:08X}",
                "extension": args.extension,
                "size": len(payload),
                "data": payload.hex(),
            }
        elif args.command == "write-memory":
            client.write_memory(args.address, args.data, args.extension)
            readback = client.read_memory(args.address, len(args.data), args.extension)
            if readback != args.data:
                raise RuntimeError("Raw memory write verification failed")
            output = {
                "address": f"0x{args.address:08X}",
                "extension": args.extension,
                "size": len(args.data),
                "verified": True,
            }
        elif args.command == "read-scalar":
            scalar = _database(args).get(args.name)
            output = {
                "name": scalar.name,
                "kind": scalar.kind,
                "data_type": scalar.data_type,
                "value": client.read_scalar(scalar),
            }
        elif args.command == "read-measurement":
            scalar = _database(args).get(args.name, kind="MEASUREMENT")
            output = {
                "name": scalar.name,
                "kind": scalar.kind,
                "data_type": scalar.data_type,
                "value": client.read_measurement(scalar),
            }
        elif args.command == "read-characteristic":
            scalar = _database(args).get(args.name, kind="CHARACTERISTIC")
            output = {
                "name": scalar.name,
                "kind": scalar.kind,
                "data_type": scalar.data_type,
                "value": client.read_characteristic(scalar),
            }
        elif args.command == "write-characteristic":
            scalar = _database(args).get(args.name, kind="CHARACTERISTIC")
            output = {
                "name": scalar.name,
                "kind": scalar.kind,
                "data_type": scalar.data_type,
                "value": client.write_characteristic(scalar, args.value),
                "verified": True,
            }
        elif args.command == "calibration-smoke":
            scalar = _database(args).get(args.name, kind="CHARACTERISTIC")
            output = asdict(client.calibration_smoke_test(scalar, args.value))
            output["restored"] = True
        else:  # pragma: no cover - argparse enforces known commands.
            raise AssertionError(args.command)

    print(json.dumps(output, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
