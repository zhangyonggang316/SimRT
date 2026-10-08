# CAN and CAN FD tests/validation on the new Ubuntu target

Both copied models now pass real loopback, XCP disconnect continuity, StopTime cleanup, and supervised process exit on `zh@192.168.219.195`. All runs used explicit generic-kernel baseline mode. No reboot, target compilation, firmware update, priority-limit change, or default SDK replacement was performed.

## Final delivery

Models are under `can_models/`. Both CANSetup blocks in each model use `/home/zh/.local/lib/tscan-thread-fix-20260926`. This is the isolated local SDK derivation documented in `sdk_crash_resolution.md`, not an official vendor update. The original model sources and `/home/zh/.local/lib/tscan` remain separate.

| Model | Final archive under can_models | ZIP SHA256 |
| --- | --- | --- |
| CAN | `simrt_can_loopback_local/20260926_090607_973.zip` | `f260df383f0302589a4e919bef0c343ec519692b476a4ee9fc515c36989cfb18` |
| CAN FD | `simrt_canfd_loopback_local/20260926_090654_550.zip` | `7d44c7d4a319932918fd5a97af86965f684fde33f65ebb78cd51cb56dc1aafe5` |

Both ZIPs contain exactly ELF, A2L, and manifest, targeting 192.168.219.195. `build_can_candidates.m` reproduces local MATLAB R2024b builds of the saved copies; build reports and timestamped logs are retained. The final ELF hashes and full tests/validation details are in `can_delivery_manifest.json`.

## Hardware results

| Check | CAN | CAN FD |
| --- | --- | --- |
| Payload | Changing little-endian double, 8 bytes | All 64 bytes, increasing/decreasing patterns, BRS, 500/2000 kbit/s |
| Matched channel 1 / channel 2 samples | 6274 / 6270 after warmup | 6545 / 6548 |
| Payload or ID mismatch | 0 / 0 | 0 / 0 |
| Total DAQ samples | 6806 | 6583 |
| DAQ transport/timestamp gaps | 2 | 1 |
| Completed model steps | 13001 / 13001 | 13001 / 13001 |
| Final telemetry | STOPPED | STOPPED |
| Separate supervised exit code | 0 | 0 |

Evidence: `can_candidate_final.json`, `canfd_candidate_final.json`, corresponding compressed raw samples, and `can_process_exit_checks.json`. The initial SDK initialization required normal XCP connect retries. Final tests used port 17726 to leave the root agent's main-model soak on 17725 undisturbed.

The verified running processes loaded the exact candidate libraries: main API SHA256 `11a0749548d586b25b198ea29b46a6bb15f6c42e51b3cc34ee2e9426bf3dd03b`; corrected TSH SHA256 `e289da8f4a1b0703129213b34d84ff93e483e66d7f7f7154db00e9e2f4af3f8b`. SDK/I/O threads were SCHED_OTHER priority 0; model threads were SCHED_FIFO priority 40 on CPU 3. Memory locking was active. Kernel was `7.0.0-30-generic`.

These are functionality and cleanup results, not zero-loss, endurance, or strict realtime acceptance. Driver status -6 is documented nonblocking trylock busy and was observed; no other driver errors occurred. Both runs recorded one deadline miss in the final cycle, which includes approximately 1.05 seconds of SDK termination. Model-step execution maxima were 634920 ns (CAN) and 246552 ns (CAN FD); these generic-kernel observations do not establish a worst-case bound.

## Shutdown defect and correction

The first copied models exchanged correct data but crashed during cleanup. The initial verifier only checked process disappearance and incorrectly marked the lifecycle successful; preserve `can_candidate_loopback_v2.json` and `canfd_candidate_loopback.json` as superseded evidence with this caveat. Empty runtime logs and RUNNING final telemetry triggered further investigation.

GDB proved `libTSCANApiOnLinux.so` registered a pthread-key destructor at `0x7ffff722db90`, then the driver unloaded its code before the model thread exited. The thread subsequently jumped to that same unmapped address. Evidence: `can_shutdown_gdb.json`, `can_shutdown_tls.json`, `can_kernel_postcheck.json`.

The narrow production correction is `RTLD_NODELETE` on SDK `dlopen` in `simrt_tc1013_can.c`. Disconnect, finalize, worker join, and balanced loader-handle close still run; library code remains mapped until process exit so deferred thread destructors remain valid. This retains SDK code/data for the process lifetime; restart the executable when changing SDK builds.

The Linux regression uses a mock SDK that deliberately retains a pthread-key destructor after finalization. The pre-fix negative control returns SIGSEGV (-11); the corrected driver completes eight configure/release/thread-exit cycles with all eight destructors called. This test is locally cross-compiled and uses no real SDK or USB. Evidence: `tls_lifetime_result.json`; sources and build command: `tests/drivers/tc1013/{test_tls_sdk.c,test_tls_lifetime.c,build_tls_lifetime.ps1}`. Existing offline driver tests and Linux strict link also pass in `can_offline_nodelete/`.

The verifier now requires same-PID STOPPED telemetry and equal positive completed/started model-step counts. Its six local tests include rejecting the stale RUNNING state seen in the actual crash and preserving manifest metadata when overriding the isolated runtime port.

## Reproduction

From the workspace root, with no other model using port 17726:

```powershell
.\.venv\Scripts\python.exe tests/validation/new_ubuntu_20260926/run_can_candidate.py tests/validation/new_ubuntu_20260926/can_models/simrt_can_loopback_local/20260926_090607_973.zip --host 192.168.219.195 --user zh --length 8 --seconds 6 --port 17726 --baseline --output tests/validation/new_ubuntu_20260926/can_repeat.json
.\.venv\Scripts\python.exe tests/validation/new_ubuntu_20260926/run_can_candidate.py tests/validation/new_ubuntu_20260926/can_models/simrt_canfd_loopback_local/20260926_090654_550.zip --host 192.168.219.195 --user zh --length 64 --seconds 6 --port 17726 --baseline --output tests/validation/new_ubuntu_20260926/canfd_repeat.json
```

The runner uses the reusable `tests/tools/scripts/verify_can_target.py`, prompts for the password, and pins the authorized target SSH key through `target_session.py`. `can_cleanup_postcheck.json` verifies both original SDK hashes, both candidate hashes, no owned CAN/test process left running, and port 17726 free.
