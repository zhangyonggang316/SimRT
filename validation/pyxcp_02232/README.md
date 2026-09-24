# pyXCP 0.22.32 compatibility validation

This isolated harness validates the exact Python/XCP dependency required by the
X280 workflow without contacting the target or loading credentials.

It checks:

- CPython 3.9.10 and `pyxcp==0.22.32`;
- importability of the bundled CPython 3.9 native DAQ/recorder extensions;
- ETH/UDP configuration and the 512-byte UDP datagram limit;
- real loopback TCP and UDP XCP framing for CONNECT, SET_MTA, UPLOAD, DOWNLOAD,
  and DISCONNECT;
- the full host ViewModel/session/Master chain for TCP and UDP measurement,
  calibration write, readback, and original-byte restoration;
- DAQ list construction and ODT packing for a 508-byte MAX_DTO target.

Run from any directory:

```powershell
& 'C:\DataSave\03matlabUbuntu\01AI ToolLinux\.venv\Scripts\python.exe' `
  'C:\DataSave\03matlabUbuntu\01AI ToolLinux\validation\pyxcp_02232\validate_pyxcp_02232.py'
```

The loopback slave is intentionally minimal. A passing result proves host-side
runtime, socket framing, memory-service calls, and DAQ layout primitives. It does
not replace the final X280 endpoint test or a DAQ packet-loss soak test.

## Compatibility report

Verified on 2026-09-12:

| Item | Result |
| --- | --- |
| Interpreter | CPython 3.9.10, 64-bit |
| Distribution | `pyxcp==0.22.32` |
| Wheel | Official `cp39-cp39-win_amd64` wheel |
| Wheel SHA-256 | `ce3b42fa3aed3d4e553e7123429d07e7b1509a5481679cc8b0d56b262a8c2940` |
| Declared Python range | `>=3.8.1,<4.0.0` |
| Native modules | CPython 3.9 DAQ, STIM, and recorder modules import successfully |
| Dependency health | `pip check` reports no broken requirements |
| Standalone host tests | 22/22 pass |
| Isolated loopback checks | 5/5 pass |
| X280 Python Master unit tests | 25/25 pass |

The exact release is listed on [PyPI](https://pypi.org/project/pyxcp/0.22.32/)
with a Windows CPython 3.9 wheel. The current upstream repository requires a
newer Python version, so examples from the installed 0.22.32 wheel are the
version-locked reference for this workspace.

## Version-locked upstream examples

The installed official wheel includes these useful files under
`pyxcp/examples`:

- `conf_eth.toml` selects `TRANSPORT = "ETH"` and `PROTOCOL = "UDP"`.
- `xcphello.py` demonstrates the required order: open the transport context,
  issue XCP CONNECT, query capabilities, then issue DISCONNECT.
- `xcp_read_benchmark.py` demonstrates memory upload using `setMta()` followed
  by `fetch()`.
- `run_daq.py` demonstrates `DaqList`, `DaqToCsv`/`DaqRecorder`, DAQ resource
  unlock, `setup()`, `start()`, `stop()`, and disconnect.

For the X280, do not copy addresses or event numbers from `run_daq.py`; the
upstream file explicitly contains simulator-specific placeholders. Build DAQ
lists from the A2L generated for the same executable. A typical X280 list will
use the A2L event number and tuples such as
`("MeasuredOutput", address, extension, "F64")`.

## Required integration constraints

- XCP-on-Ethernet uses a 4-byte little-endian length/counter header.
- pyXCP 0.22.32 limits an Ethernet UDP datagram to 512 bytes. The target must
  advertise and enforce `MAX_DTO <= 508`, leaving four bytes for the header.
- Standard UDP must be used. Any private sequence-number wrapper outside the
  XCP-on-Ethernet header is incompatible with this master.
- `Master("eth", ...)` creates the protocol master, but the transport is opened
  separately. A context manager opens it automatically; direct code must call
  `master.transport.connect()` before `master.connect()`.
- Scalar reads use `setMta(address, extension)` then `upload(element_count)`.
  Scalar writes use `setMta(...)` then `download(data)`. The element count is a
  byte count only when the slave reports BYTE address granularity.
- The UDP implementation detects an immediately duplicated message counter but
  provides no retransmission or DAQ gap recovery. Final acceptance therefore
  still needs a real-target CONNECT/read/write/restore test and a timed DAQ
  loss/ordering check.
- Upstream's packaged test files require `pytest`, which is not a runtime
  dependency in this workspace. This harness uses only `unittest` and the
  installed runtime dependencies.

Official upstream references:

- [pyXCP repository](https://github.com/christoph2/pyxcp)
- [Configuration guide](https://github.com/christoph2/pyxcp/blob/master/docs/configuration.rst)
- [DAQ guidance from the maintainer](https://github.com/christoph2/pyxcp/discussions/165)
