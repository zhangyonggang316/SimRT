# SDK connection crash diagnosis and opt-in correction

Date: 2026-09-26. Target: pinned SSH host `192.168.219.195`, Ubuntu 26.04, user `zh`.

## Result

The SDK connection crash is caused by a proven invalid thread-handle reference in the pinned vendor `libTSH.so`. A separately installed, one-byte corrected candidate completes discovery, connect, disconnect, and finalization normally. Ten independent runs passed in the initial no-transmission phase. Subsequent real-model CAN/CAN FD tests and a separate SDK-unload fix are documented in [can_final_report.md](can_final_report.md). No reboot was performed.

Default SDK `/home/zh/.local/lib/tscan` and the repository vendor files remain byte-for-byte original. The candidate is isolated at:

`/home/zh/.local/lib/tscan-thread-fix-20260926`

It is selected only by the isolated copied models under `can_models/`, with both CANSetup `DriverDirectory` values set to this path and rebuilt locally. Their final loopback and process-cleanup checks pass; strict realtime and long-duration CAN acceptance remain separate. The binary correction is a local derived SDK, not a vendor-approved release.

## Proven cause

GDB stack from `sdk_gdb_backtrace.json`:

```text
pthread_setschedparam
AddHIDDevice                    HIDControl.cpp:458
ConnectHIDDevice                HIDControl.cpp:702
ConnectHIDDeviceInternal        HIDControl.cpp:479
libTSCANApiOnLinux.so
tscan_connect
```

At the fault, the first argument (`rdi`, `pthread_t`) is zero. The SDK has already created valid USB/read/write threads. The crash is not a missing-library, USB permission, ctypes declaration, or missing-device failure.

Disassembly of the reviewed, hash-pinned `libTSH.so` shows:

1. A read-thread `std::thread` object lives at `rbp-0x68`.
2. Its native handle is passed to `pthread_setschedparam` with SCHED_RR priority 99.
3. The read-thread object is detached, clearing its native handle.
4. A write-thread object is created at `rbp-0x60`.
5. The next scheduling call mistakenly obtains the native handle from `rbp-0x68` again, resulting in `pthread_setschedparam(0, SCHED_RR, priority=98)`.

The original call site loads the detached object with bytes `48 8d 45 98` at file offset `0xD185`. The corrected instruction is `48 8d 45 A0`, referring to the live write-thread object. Exactly one byte differs, at offset `0xD188`.

Before deriving a binary candidate, a GDB-only experiment intercepted the invalid call and returned ESRCH. Connect/disconnect then both returned 0 and finalization completed, with one invalid call observed. This experiment changed only the debugged process and is retained as `sdk_gdb_skip_invalid_sched.json` plus `sdk_skip_invalid_sched.gdb`.

After the one-byte correction, GDB observes two distinct, nonzero native handles in the existing scheduling calls. Normal execution, without GDB or any preload shim, succeeds. Evidence is in `sdk_thread_fix_sched.json` and `sdk_thread_fix_validation.json`.

## Candidate provenance

| File | SHA256 |
| --- | --- |
| Original `libTSH.so` | `8308ec91016870da114ba476d496900cdf73fe2aaa038e0aa00cf56a44bd6758` |
| Corrected `libTSH.so` | `e289da8f4a1b0703129213b34d84ff93e483e66d7f7f7154db00e9e2f4af3f8b` |
| Unchanged `libTSCANApiOnLinux.so` | `11a0749548d586b25b198ea29b46a6bb15f6c42e51b3cc34ee2e9426bf3dd03b` |

Local prepared candidate: `tests/validation/new_ubuntu_20260926/sdk_thread_fix/`.
Correction receipt: `sdk_thread_fix.patch.json`.
Reproducible derivation: `create_sdk_compat.py --output <new-directory>`.

The derivation tool refuses any source library whose SHA256 or instruction bytes differ from the reviewed original. It checks that exactly one byte changes, retains the MIT license, adds explicit local-modification notes to SOURCE.md, and uses the existing SDK preparation tool to generate a new SHA256 manifest. The original vendor directory is never a write target.

No bitrate, CAN protocol, payload, firmware operation, queue behavior, or API signature was changed. The candidate corrects the wrong thread-object reference only.

## Validation

- Upload SHA256 verification and SDK `--check` passed for the separate candidate directory.
- Normal SDK scan/connect/disconnect/finalize passed once before repetition.
- Ten further independent subprocesses passed the same full lifecycle, recorded in `sdk_thread_fix_repeated.json`.
- All observed SDK threads were SCHED_OTHER, priority 0, with `zh` realtime priority limit 80.
- The vendor still attempts SCHED_RR priorities 99 and 98, which exceed this account's configured limit. Do not infer that SDK threads stay SCHED_OTHER when run as root or with realtime priority >=98; this investigation did not change the vendor's priority policy.
- `sdk_postcheck.json` confirms original/default library hashes remain unchanged, candidate hash matches the receipt, and no diagnostic probe processes remain.
- GDB and four runtime dependencies were installed as authorized diagnostic tools; `sdk_install_gdb.json` records the package operation. No compiler was installed or invoked on the target.

No-transmission reproduction on the target:

```sh
python3 /home/zh/tc1013-diagnostics-20260926/sdk_connect_probe.py --driver-dir /home/zh/.local/lib/tscan-thread-fix-20260926
```

The probe logs every lifecycle stage and validates the expected TC1013 serial before connecting. It does not configure channels or call any CAN transmit API.

## Alternative SDK search

The local `C:/DataSave/06同星二次开发库` contains Windows DLLs, C/C++ demos, and a Linux PDF, but neither loose Linux shared libraries nor a Linux shared library inside its ZIP. Inventory: `sdk_alternative_inventory.json`.

The official repository's current head remains the pinned commit `6690a4f1bc9056dd8b3d0bfc28f909db64df5e6d`. Git blob hashes of both upstream Linux libraries exactly match the original local libraries. No newer official binary was available there at review time. Sources: [official repository](https://github.com/TOSUN-Shanghai/libTSCANDemos), [pinned commit](https://github.com/TOSUN-Shanghai/libTSCANDemos/commit/6690a4f1bc9056dd8b3d0bfc28f909db64df5e6d). API evidence: `sdk_upstream_review.json`.

The repository also has an unanswered Ubuntu 24.04 connection-failure report. Its reported return code differs from this SIGSEGV, so it does not prove the same cause. [Issue 6](https://github.com/TOSUN-Shanghai/libTSCANDemos/issues/6)

## C mock test race

The production worker releases its SDK mutex before publishing an asynchronous receive error to the queue. The test previously disabled one receive fault and immediately injected the next fault. A prior in-flight receive call could still publish its error after the next test started waiting, causing the assertion at `wait_for_error` to observe an unrelated error.

The mock-race fix is confined to `tests/test_can_runtime.c`: successful mock receive calls are counted under the existing mock mutex, and fault transitions wait for a clean receive after clearing the previous injection, then drain its pending status. This particular correction does not change the production runtime. The test no longer accepts the old receive error during the transmit-error injection phase. The later production SDK lifetime correction is covered separately in `can_final_report.md`.

`tests/run_offline_tests.ps1` now includes the harness hash and names the synchronized fault-transition coverage. The complete harness, expected fatal-cwd child check, Linux cross compilation, and strict no-undefined link passed. The normal harness also passed 32 consecutive runs. Evidence:

- `can_offline_fixed/runtime_offline_tests.json`
- `can_offline_fixed/repeated_runs.json`

The original failed run remains documented in `can_local_review.md`; it has not been silently relabeled as passing.
