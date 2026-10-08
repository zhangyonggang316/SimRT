# TC1013 local review and new-target SDK evidence

Date: 2026-09-26. Workspace: `C:/DataSave/03matlabUbuntu/03AIToolLinux`.

Follow-up: `sdk_crash_resolution.md` identifies the vendor's detached-thread bug, records an isolated one-byte corrected candidate that passed ten connect/disconnect runs, and documents the narrow C mock synchronization fix. The original/default SDK remains unchanged; the initial failures below are retained as historical observations.

## Outcome

- Prepared and verified the two pinned Linux SDK libraries locally.
- Installed the complete seven-file SDK bundle into `/home/zh/.local/lib/tscan` on the pinned SSH target `192.168.219.195` as user `zh` after explicit delegation from the root agent. No packages, kernel settings, or USB permissions were changed by this task.
- Remote SHA256, ELF validation, and `ldd` dependency resolution passed. USB `5453:0001`, serial `37AFCA2612ADBF35`, was readable/writable by `zh` with mode `0660` and group ID 46 (`plugdev`).
- SDK initialize and scan passed. Scan returned one `TOSUN HS CANFD2` with the expected serial. **`tscan_connect` crashes with SIGSEGV (subprocess return code -11), before returning a device handle.** Therefore connect/disconnect and CAN hardware tests/validation have not passed on this new machine.
- No CAN frames were transmitted and no model was started during SDK installation/probing. No reboot was performed.
- Added `tests/tools/scripts/verify_can_target.py` for explicit `--host` / `--user`, interactive `getpass`, ZIP support, source hash validation, independent result paths, and optional non-RT functional baseline. It does not read credentials or target addresses from the requirements document.

Evidence: `sdk_install.json`, `sdk_diagnostics.json`, `sdk_diagnostics_detail.json`, `sdk_kernel_log.json`, and `sdk_process_limits.json` in this directory. The kernel recorded a null-adjacent fault at address `0x628` inside `libc.so.6` during connect. This is an observed fault location, not a proven root cause. Login limits during diagnosis were realtime priority 80 and locked memory 1048576 KiB.

## Skills and scope

Read the local `building-simulink-models` and `matlab-deploy-embedded-code` skills before assessing deployment boundaries. This subtask did not read or modify Simulink models through MATLAB, perform structural model edits, or use MATLAB Coder/PIL; their model-edit and code-generation procedures were not invoked. Existing project deployment and tests/validation APIs were reused.

## SDK and dependencies

Source: `toolchain/simrt_linux_target/drivers/tc1013/vendor/SOURCE.md`, vendor repository commit `6690a4f1bc9056dd8b3d0bfc28f909db64df5e6d`. The MIT license is retained.

| Library | Size | SHA256 |
| --- | ---: | --- |
| `libTSCANApiOnLinux.so` | 7274224 | `11a0749548d586b25b198ea29b46a6bb15f6c42e51b3cc34ee2e9426bf3dd03b` |
| `libTSH.so` | 260040 | `8308ec91016870da114ba476d496900cdf73fe2aaa038e0aa00cf56a44bd6758` |

Both are ELF64 little-endian x86-64 shared libraries. `TSCANDef.hpp` hash is `3f3589399f5a7dc0ebfb650cab777a091a2a18d2cba6f405e665fcddad7daa8f`.

Direct dependencies read with the local cross-toolchain `linux-readelf.exe`:

- `libTSCANApiOnLinux.so`: `libgcc_s.so.1`, `libc.so.6`, `libdl.so.2`, `libpthread.so.0`, `libm.so.6`; RUNPATH is `$ORIGIN`.
- `libTSH.so`: `libusb-1.0.so.0`, `libpthread.so.0`, `libstdc++.so.6`, `libgcc_s.so.1`, `libc.so.6`.
- Required symbol-version maxima observed: GLIBC 2.17, GLIBCXX 3.4.22, CXXABI 1.3.8, GCC 4.2.0. Successful dependency resolution does not prove binary behavior on newer glibc.
- Normal Ubuntu runtime package set is `libusb-1.0-0 libstdc++6 libgcc-s1 libc6`; new-target `ldd` found all dependencies, including transitive `libudev.so.1`.
- No `blf.so` is required by this pinned release. The model explicitly preloads `libTSH.so` and loads `libTSCANApiOnLinux.so`. Initialization must run from the driver directory; the existing adapter saves/restores its original working directory.

Prepared upload directory: `tests/validation/new_ubuntu_20260926/sdk_upload/`.
Files: `libTSCANApiOnLinux.so`, `libTSH.so`, `LICENSE`, `SOURCE.md`, `DEPLOY_DRIVER.md`, `prepare_driver.py`, `tc1013-sdk-manifest.json`.
The actual remote upload stage retained for evidence is `/home/zh/tc1013-sdk-upload-b8456dad8107`.

Local preparation command:

```powershell
.\.venv\Scripts\python.exe simrt_linux_target\drivers\tc1013\prepare_driver.py --sdk-dir simrt_linux_target\drivers\tc1013\vendor\linux --check
.\.venv\Scripts\python.exe simrt_linux_target\drivers\tc1013\prepare_driver.py --sdk-dir simrt_linux_target\drivers\tc1013\vendor\linux --output <new-output-directory>
```

`tests/validation/new_ubuntu_20260926/install_sdk.py` reproduces pinned-host installation/probing using an interactive password and never sends CAN frames. It preserves differing existing installations by refusing overwrite. It uses the existing SDK probe routines without calling their historical `main()` or credentials parser.

## Artifacts

`can_archive_inventory.json` records all seven existing classical-CAN ZIPs, hashes, manifests, and received-data types. All seven archive structures and payload hashes passed the current Qt `PayloadArchive` validator.

| Artifact | Payload profile | Result |
| --- | --- | --- |
| `demos/io/tc1013/simrt_can_loopback/simrt_can_loopback_local/20260919_012155_876.zip` | Current sine-wave `FLOAT64_IEEE` outputs | Local checks passed, `can_zip_check.json` |
| `demos/io/tc1013/simrt_can_loopback/simrt_can_loopback_local/20260918_172542_635.zip` | Historical validated `UBYTE[8]` pattern | Local checks passed, `can_verified_zip_check.json` |
| `tests/validation/tc1013_can_20260919/simrt_canfd_loopback_local/20260918_171728_241/` | `UBYTE[64]`, CAN FD | Directory/hash/A2L checks passed, `canfd_payload_check.json` |

No CAN FD deployment ZIP existed in the inspected source tree. Its matching three-file directory remains available. The new verifier supports directories and ZIPs. All historical manifests above still contain `.86`; the new verification tool explicitly uses `--host` for both SSH and XCP and records the preserved historical manifest separately. It does not rewrite a signed/matched artifact in place.

The latest classical CAN ZIP changed from a fixed byte pattern to 8-byte double sine waves. The historical `verify_model_hardware.py` rejects this shape. The new tool recognizes both profiles. For waveform data it compares each post-warmup received double bit-for-bit with a captured peer transmission in the preceding 0.5 seconds, checks IDs and statuses, requires at least 1000 matches and changing values, and fails unmatched samples. DAQ gaps may prevent establishing a match and therefore produce an inconclusive/failing functional run; they are not silently accepted as correct CAN traffic.

Local check example, without SSH or password prompt:

```powershell
.\.venv\Scripts\python.exe tools\verify_can_target.py simrt_linux_target\drivers\tc1013\models\simrt_can_loopback\simrt_can_loopback_local\20260919_012155_876.zip --host 192.168.219.195 --user zh --check --output validation\new_ubuntu_20260926\can_zip_check.json
```

Hardware verification command, **not executed by this task**. It transmits CAN and requires the SDK connect failure to be resolved first:

```powershell
.\.venv\Scripts\python.exe tools\verify_can_target.py simrt_linux_target\drivers\tc1013\models\simrt_can_loopback\simrt_can_loopback_local\20260919_012155_876.zip --host 192.168.219.195 --user zh --baseline --output validation\new_ubuntu_20260926\hardware_can_waveform.json
```

Use `--length 64` for the FD directory. Omit `--baseline` only when the active kernel is PREEMPT_RT; baseline is explicitly a functional-only check. The tool checks XCP port availability, uploads into a unique directory, uses the existing deployment service, waits for the bounded model stop time, stops only its selected model during cleanup, preserves raw DAQ samples, and verifies continued operation after XCP disconnect. It does not modify autostart.

## Tests and remaining failures

- SDK preparation: 13 tests passed using `python -m unittest discover -s tests/drivers/tc1013 -p test_prepare_driver.py -v`.
- New CAN entry point: 5 tests passed using `python -m unittest discover -s tests/tools/unit -p test_verify_can_target.py -v`, covering ZIP extraction/cleanup, wrong length rejection, explicit target override without credential reads, failed upload ownership, and delayed waveform/corruption checks.
- Existing C mock harness compiled, but this run failed at `tests/test_can_runtime.c:301`: `assert(status == 0 || status == SIMRT_CAN_BUSY)` inside `wait_for_error`, after the mock async transmit error. This is not reported as passed or as a hardware failure. No source change was made to hide the failure.
- Separately, the current C driver successfully cross-compiled and linked with `linux-gcc.exe -std=c99 -Wall -Wextra -Werror -O2 -fPIC -shared ... -ldl -pthread -Wl,--no-undefined`; output is `can_offline/simrt_tc1013_can_test_link.so`.
- Existing SDK installation, source files, prior historical evidence, and model artifacts were not overwritten. Only the new tests/validation directory and the new verifier/test files were created by this subtask.

The 2026-09-19 hardware records are evidence for the old Ubuntu 22.04 SimRT, not proof for this Ubuntu 26.04 machine. On the new target, the vendor connect crash remains the immediate CAN blocker; active PREEMPT_RT and model timing are separately owned by the root agent.
