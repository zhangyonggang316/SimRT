"""Resolve the shared pyXCP backend in source and packaged layouts."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_backend_path() -> None:
    try:
        import x280_xcp  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    workspace = Path(__file__).resolve().parents[3]
    backend = workspace / "x280_linux_target" / "python"
    if backend.is_dir():
        sys.path.insert(0, str(backend))


_ensure_backend_path()

from x280_xcp import (  # noqa: E402
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
