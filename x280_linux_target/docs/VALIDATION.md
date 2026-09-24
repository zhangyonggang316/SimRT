# Validation Record

This is a historical record. The registered hardware is now named `SimRT`;
the former name `X280 Linux (SSH)` below identifies the configuration actually
tested on 2026-09-10. Original logs and build artifacts are unchanged. For a
current installation, rerun `setupX280LinuxTarget` and follow the
[migration guide](../../docs/NEW_MACHINE_DEPLOYMENT.md#43-注册硬件与工具链).

Validated host environment on 2026-09-10:

- MATLAB `24.2.0.2923080 (R2024b) Update 6`
- `X280 Linux (SSH)` target registration: passed
- Hardware selection on a new model: passed
- Toolchain selection `GNU GCC Embedded Linux`: passed
- Production hardware `Intel->x86-64 (Linux 64)`: passed
- R2024b demo model creation and reload: passed
- MATLAB Code Analyzer for target sources: 0 issues
- Target unit tests: 9 passed, 0 failed
- `GenCodeOnly` build: passed, including TLC and XCP source generation
- Generated runtime protocol initializer: UDP, port 17725
- Default `xcp_ext_param_default_tcp.c` excluded: passed
- Generated `XCP_MAX_DTO_SIZE=508`: passed
- Generated `xcp/server_config.json` maximum DTO 508: passed
- Rewritten A2L transport: `XCP_ON_UDP_IP`, IPv4 address, port 17725,
  maximum DTO `0x01FC`
- Rewritten UDP A2L accepted by the R2024b `xcpA2L` constructor: passed
- Generated makefile contains `LIBS = $(LINUX_TARGET_LIBS_MACRO)`: passed
- Persistent registration in a fresh MATLAB process: passed
- Password absent from model `CoderTargetData`: passed
- Target `192.168.0.106:22`: reachable, OpenSSH 8.9p1 Ubuntu banner
- Python environment: Python 3.9.10, `pip check` passed
- MATLAB Engine for Python: R2024b package `24.2`, import and startup passed
- Python-to-X280 model configuration: passed without storing credentials
- Existing Python application tests: 24 passed
- Existing MATLAB application tests: 55 passed, 0 failed, 0 incomplete

This local validation record does not claim the authenticated remote build or
live calibration run. Run the following only after entering credentials
through the documented secure workflow:

```matlab
result = buildAndDeployX280( ...
    "models/x280_calibration_demo.slx", ...
    Username="YOUR_LINUX_USER");
```

Acceptance criteria for that run:

1. `slbuild` reports a successful native target build.
2. The executable starts on the X280 and listens on UDP port 17725; it does
   not listen on TCP port 17725.
3. `result.ELFFile` passes the x86-64 ELF header check.
4. The manifest ELF and A2L SHA-256 values match the packaged files.
5. `createX280XCPChannel(..., Connect=true)` connects over UDP.
6. `CalGain` can be read, changed, and restored.
7. `MeasuredOutput` changes consistently with the gain.
