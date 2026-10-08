# Local Build Verification, 2026-09-26

This directory records Windows-only environment checks, local MATLAB R2024b
code generation and Linux cross-compilation for target address 192.168.219.195.
No SSH connection, Ubuntu configuration, target compilation, or reboot was
performed by these scripts.

## Evidence

- `matlab_environment.json/log`: R2024b Update 6, required products, SimRT
  registration, current toolchain path, and offline checks passed.
- `windows_environment.json`: Python 3.9.10 x64, fixed package versions,
  `pip check`, GCC 7.5.0 / x86_64-linux, all 3967 toolchain file hashes matched.
- `main_telemetry_build.json`, `can_telemetry_build.json`,
  `canfd_telemetry_build.json`: latest build receipts, ZIP paths and hashes.
- `artifact_validation.json`: application ZIP/A2L parsing, three-file packaging,
  matching hashes and endpoint metadata, scalar addresses inside ELF data symbols.
- `*_elf_inspection.txt`: ELF64 x86-64 EXEC, interpreter and library versions.
- `build_telemetry_monotonic.log`: final builds with the live status writer using
  a monotonic condition-variable clock.
- `target_tests.log/mat`: 11 MATLAB target tests passed, including legacy CAN FD
  hardware-name migration.
- `TELEMETRY_CONTRACT.md`: exact live JSON field definitions and tests/validation scope.
- `rt_runtime_harness.elf`, `verify_live_status.py`: prepared for Linux execution
  by the target deployment task. Local cross-compilation passed with `-Werror`.

Python checks also passed: 9 realtime bundle tests, 30 build-model tests, and
10 runtime-validator tests. The new source regression verifies that both the
condition variable and timeout use CLOCK_MONOTONIC.

## Reproduction

In MATLAB, run `check_matlab.m`, then `build_telemetry_models.m` and
`test_target.m` in this directory. The build script uses the project's
`buildSimRTLocal` / `slbuild` workflow and performs no remote operations.
The main model remains under `demos/Demo_XCP_Qt/models/simrt_rt_single`.
CAN test snapshots are under `tests/validation/can926` to remain within MATLAB's
Windows path-length limits. The historical CAN FD snapshot is preserved.

From the project root in PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/validation/local_build_20260926/check_windows.ps1
& ./.venv/Scripts/python.exe tests/validation/local_build_20260926/verify_artifacts.py
```

The execution-policy option applies only to the spawned PowerShell process.

## Migration Fixes

- `configureSimRTModel` now updates the visible HardwareBoard parameter as well
  as CoderTarget metadata. A historical CAN FD SLX retained the obsolete
  `SimRT Linux (SSH)` label and could generate code but failed target verification.
- `.venv` now uses the current project's `.python/3.9.10`. Its configuration,
  activation scripts, and all 62 installed command entry points were regenerated
  using the standard venv/distlib APIs. In-use launcher binaries were preserved
  after SHA-256 confirmed exact matches with the installed Python venv launchers.
  `original_pyvenv.cfg` preserves the previous path for audit.
- MATLAB MCP startup referenced the old `01AI ToolLinux` checkout and timed out.
  The checks/builds therefore used R2024b `-batch` in the current project path.

Earlier `build_telemetry_models.log` and `build_telemetry_models_retry.log`
retain the path-length and legacy hardware-name failures. The latest receipts
and `build_telemetry_monotonic.log` identify the deliverable artifacts.
