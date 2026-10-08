# CAN review coordination

local_build 16:46 CST: Main corrected build passed; MATLAB RELEASED to CAN now. Type conflict fixed with separate simrt_xcp_status.c bridge. CAN can resume both copied-model builds using current integration sources. Main ZIP ready for root; target UDP port still reserved for your tests until you release it.

2026-09-26: CAN reviewer has read agent_tasks.md. Need shared MATLAB session for copied CAN/CAN FD models, both DriverDirectory values set to `/home/zh/.local/lib/tscan-thread-fix-20260926`, then local builds. Please record MATLAB availability here or in local_build status before CAN calls MATLAB. CAN has not started MATLAB work yet.

Root task grants target UDP port 17725 for CAN verification once archives are ready; no reboot, remote compilation, priority changes, or default vendor replacement.

16:32 CST: local_build grants CAN MATLAB access until its main rebuild readiness signal (estimated 10-15 minutes). CAN is now using MATLAB. Library settings show no configured custom library and satisfied prerequisites.

16:41 CST: CAN build reached native compilation and picked up new `src/simrt_rtiostream_udp.c` from local_build. Build fails because wrapper includes MathWorks `rtiostream_tcpip.c` (tmwtypes.h) before `xcp.h` (generated rtwtypes.h); compiler reports conflicting complex types starting creal32_T. MCP returned the complete error but intercepted diary output, leaving `can_candidate_build.log` empty. `build_can_candidates.m` now captures future logs with evalc. CAN makes no change to the integration owner's source. Both model copies are correctly patched and saved in `can_models/`.

16:46 CST: Read local_build_status.md. MATLAB is now released to local_build for its corrected main build. CAN is waiting for its explicit release; target port is still untouched. The CAN verifier now records actual loaded SDK paths and SHA256 via /proc/PID/maps; its five local tests pass.

16:47 CST: local_build main build passed and explicitly released MATLAB. CAN is resuming both builds now, using the corrected adapter.

16:50 CST: Both copied models built successfully. MATLAB RELEASED. CAN ZIP `can_models/simrt_can_loopback_local/20260926_084809_855.zip`; FD ZIP `can_models/simrt_canfd_loopback_local/20260926_084915_795.zip`. Starting target loopback now. First evidence wrapper attempt stopped before upload because its cancellation flag was not cleared; wrapper fixed, original failed evidence retained.

16:58 CST: Both functional loops produced thousands of exact payload matches, but POSTCHECK FOUND A REAL SHUTDOWN SEGFAULT at StopTime in both models. Kernel evidence `can_kernel_postcheck.json`, final telemetry `can_final_runtime_status.json` remains RUNNING and stdout logs empty. Existing verifier passed on process disappearance, so its `passed:true` is insufficient for clean lifecycle and will be tightened. Investigating driver dlclose/SDK detached thread teardown now. Port 17725 currently free, MATLAB idle. Root may start main soak now if needed; CAN will avoid another UDP model run until coordination, and can diagnose shutdown with no XCP client if assigned a different port. Current functional evidence must be described with shutdown failure caveat.

17:01 CST: Confirmed existing transport accepts `-port` override. Shutdown debugger uses port 17726 and no XCP client; port 17725 RELEASED for root soak. All further CAN diagnostic invocations use 17726 until root grants the main port again.

TLS diagnosis update: GDB proves shutdown crash is a pthread-key destructor at 0x7ffff722db90 registered from libTSCANApiOnLinux.so, then invoked after dlclose unmaps that library (can_shutdown_tls.json). Added RTLD_NODELETE to CAN SDK dlopen; normal disconnect/finalize/dlclose still balance resources but code stays mapped until process exit. Offline driver tests and Linux cross-link pass. Building dedicated Linux mock SDK/TLS lifecycle regression, including pre-fix negative control. Verifier now requires final STOPPED telemetry and supports explicit --port 17726. MATLAB is being acquired for updated CAN/FD builds; local_build has already released it and reports no further MATLAB work.

Updated: TLS negative control SIGSEGV and corrected 8-cycle exit=0 regression passed (`tls_lifetime_result.json`), with no real SDK or USB usage. Corrected CAN ZIP `can_models/simrt_can_loopback_local/20260926_090607_973.zip` and FD ZIP `can_models/simrt_canfd_loopback_local/20260926_090654_550.zip` built; MATLAB RELEASED. Running final CAN/FD on port 17726 only; port 17725 remains released to root.

FINAL: CAN and CAN FD full verification PASSED, including STOPPED telemetry and separately supervised exit=0. Final evidence `can_candidate_final.json`, `canfd_candidate_final.json`, `can_process_exit_checks.json`; aggregate `can_delivery_manifest.json`; report `can_final_report.md`. CAN channels matched 6274/6270 dynamic samples; FD matched 6545/6548 complete 64-byte samples, all mismatches=0. DAQ gaps 2/1 retained as limitations. Generic kernel, FIFO40 model/OTHER0 SDK; not RT acceptance. All owned processes stopped and port17726 free; original default SDK hashes unchanged (`can_cleanup_postcheck.json`). MATLAB and all CAN ports released. IMPORTANT: earlier v2/initial FD passed flags are superseded because they missed cleanup SIGSEGV; only *_final reports include the corrected loader and clean-exit guard.

Root, 08:30 UTC: MATLAB is available for your copied-model builds now. local_build is assigned UDP source investigation and should wait until you record MATLAB release here. Root will leave port 17725 free for your initial CAN/CAN FD functional tests; record release here after they finish so the main soak can start.
