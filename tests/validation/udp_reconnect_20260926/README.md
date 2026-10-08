# XCP UDP reconnect correction, 2026-09-26

Root's real-model soak connected, acquired DAQ and calibrated successfully, then
timed out when a fresh client connected from another UDP source port. R2024b's
`rtiostream_tcpip.c` calls `connect()` on the UDP server socket after its first
`recvfrom()`. Protocol DISCONNECT changes XCP state but leaves this kernel peer
filter in place.

The repository-owned `simrt_rtiostream_udp.c` includes the unchanged vendor driver,
renames its send implementation and wraps the final positive DISCONNECT response.
When XCP is disconnected, it binds a replacement listener before sending that
response, then closes the old connected socket and resets its datagram buffers.
Active sessions retain the vendor's source-port filter. `simrt_xcp_status.c` bridges
the protocol state API separately because generated `rtwtypes.h` and vendor
`tmwtypes.h` contain incompatible complex type declarations.

`onAfterCodeGen.m` compiles the adapter and bridge, not the vendor source a second
time. packNGo includes the original vendor source as an include dependency. Final
artifact tests/validation verifies identical vendor source hashes and both linked adapter
symbols. No file under the MATLAB installation was modified.

## Local evidence

- `baseline_regression.json`: the actual vendor driver succeeds once, then fails
  the second client's CONNECT after all three UDP attempts.
- `fixed_regression.json`: 100 unique source ports successfully complete CONNECT,
  two positive-response commands, DISCONNECT; a third-party source port cannot
  take over each active session. 99 connects used one packet, one used two.
- `udp_reconnect_harness.c` uses the actual driver and Ethernet framing, with only
  XCP command processing/state stubbed. This transport test does not substitute
  for the parent agent's real generated-model DAQ/calibration soak.
- `artifact_validation.json`: APP archive/A2L loaders, all 18 scalar addresses,
  three-file ZIP, Linux ELF EXEC, linked adapter, endpoint UDP 17725 at
  192.168.219.195, 1 ms step period all verified.
- `build_main.log` retains the initial type-conflict failure; the final corrected
  build succeeded in `build_main_fixed.log`.

## Reproduction on Windows

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tests/validation/udp_reconnect_20260926/build_harnesses.ps1
.venv/Scripts/python.exe tests/toolchain/test_udp_reconnect.py tests/validation/udp_reconnect_20260926/udp_vendor_baseline.exe --expect-pinned-peer
.venv/Scripts/python.exe tests/toolchain/test_udp_reconnect.py tests/validation/udp_reconnect_20260926/udp_fixed.exe --cycles 100
.venv/Scripts/python.exe tests/validation/udp_reconnect_20260926/verify_main.py
```

The build script also cross-compiles `udp_vendor_baseline.elf` and `udp_fixed.elf`
locally using the portable Linux GCC 7.5 toolchain, with warnings as errors. Root
can upload them and `test_udp_reconnect.py` for Linux loopback verification:

```sh
python3 test_udp_reconnect.py ./udp_vendor_baseline.elf --expect-pinned-peer
python3 test_udp_reconnect.py ./udp_fixed.elf --cycles 100
```

These tests reserve a temporary loopback UDP port and do not use target port 17725.
This agent has performed no remote operations. No reboot is required.

## Deliverable

`demos/Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single_local/20260926_084450_781.zip`

- ZIP SHA256: `2bd4f5d732f9afc67686d0101fd3dc761e31191f07273c69fe55e89910428764`
- ELF SHA256: `c6156eea180454fbd5fca43b0f61781ac9a6ed17776f4147f2277da7ab731ea1`
- Fixed Linux harness SHA256: `f3cbe3039c1d61404841d6f822c333829e97fd72e2d14bf4da119c2754e66087`
- Baseline Linux harness SHA256: `fa9099871c7ddd6a158b3432d10fe10ffd419e580f5b1b5526b37b341d702087`

This correction handles explicit successful DISCONNECT followed by a new client.
Recovery from a client disappearing without DISCONNECT is outside this change.
