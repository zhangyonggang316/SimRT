# SimRT pyXCP TCP/UDP Master

This directory contains a Python 3.9-compatible XCP Master for the SimRT target.
The Python package and command-line module remain named `simrt_xcp`.
It uses the workspace-pinned `pyxcp==0.22.32` and creates its ETH transport
configuration in memory. The project defaults are UDP port `5555` and
TCP port `17725`; select TCP with `--protocol tcp`. Rebuild older-port models
and use their matching ELF/A2L/manifest ZIPs rather than editing old metadata.

Run from this directory with the workspace environment:

```powershell
& '..\..\.venv\Scripts\python.exe' -m simrt_xcp --host 192.168.0.106 probe
& '..\..\.venv\Scripts\python.exe' -m simrt_xcp --protocol tcp --host 192.168.0.106 probe
& '..\..\.venv\Scripts\python.exe' -m simrt_xcp list --a2l '<matching.a2l>'
& '..\..\.venv\Scripts\python.exe' -m simrt_xcp --host 192.168.0.106 read-measurement --a2l '<matching.a2l>' MeasuredOutput
& '..\..\.venv\Scripts\python.exe' -m simrt_xcp --host 192.168.0.106 read-characteristic --a2l '<matching.a2l>' CalGain
& '..\..\.venv\Scripts\python.exe' -m simrt_xcp --host 192.168.0.106 calibration-smoke --a2l '<matching.a2l>' CalGain 1.25
```

`calibration-smoke` uses one connection and one pyXCP `Master` for the whole
operation. It retains the original bytes, writes the temporary value, verifies it
byte-for-byte, and restores and verifies the original bytes inside a `finally`
block. A restoration failure is reported as an error. Use only the A2L file
packaged with the ELF that is currently running on the SimRT.

## Programmatic API

Use a fresh `XcpClient` for each session. One client object creates at most one
pyXCP `Master`; after disconnect or a failed connection it is permanently closed.

```python
from simrt_xcp import TransportSettings, XcpClient, parse_a2l

database = parse_a2l("simrt_calibration_demo.a2l")
settings = TransportSettings("192.168.0.106", protocol="UDP", port=5555)

with XcpClient(settings) as client:
    output = client.read_measurement(database.get("MeasuredOutput", "MEASUREMENT"))
    gain = client.read_characteristic(database.get("CalGain", "CHARACTERISTIC"))
    result = client.calibration_smoke_test(
        database.get("CalGain", "CHARACTERISTIC"), 1.25
    )
```

The legacy `UdpTransportSettings` and `XcpUdpClient` names remain supported.
`TcpTransportSettings` and `XcpTcpClient` provide transport-specific convenience
types. `write-characteristic` verifies an enduring write but does not restore it;
prefer `calibration-smoke` for acceptance testing. Likewise, raw `write-memory`
performs read-back verification but does not restore data.

Run the offline suite (it never opens a real network connection):

```powershell
& '..\..\.venv\Scripts\python.exe' -m unittest discover -s '..\..\tests\protocol' -v
```
