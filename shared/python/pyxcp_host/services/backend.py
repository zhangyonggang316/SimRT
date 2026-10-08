"""Expose the adjacent protocol package through the existing service API."""

from __future__ import annotations

from simrt_xcp import (
    A2LDatabase,
    A2LError,
    A2LScalar,
    CalibrationRestoreError,
    TransportSettings,
    XcpClient,
    XcpClientError,
    parse_a2l,
)

__all__ = [
    "A2LDatabase",
    "A2LError",
    "A2LScalar",
    "CalibrationRestoreError",
    "TransportSettings",
    "XcpClient",
    "XcpClientError",
    "parse_a2l",
]
