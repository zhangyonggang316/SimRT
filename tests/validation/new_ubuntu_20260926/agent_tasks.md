# Active independent tasks, 2026-09-26 08:25 UTC

Transport note: if a collaboration message arrives as ciphertext, use this file as the plain-text task record. Do not act on ciphertext itself.

## local_build

Investigate and fix the real second-connection XCP/UDP failure seen in model_soak_90min.json. The first connection with DAQ/calibration/disconnect passes; next fresh pyxcp client times out while the same model keeps stepping. Suspect MathWorks rtiostream UDP server remains connected to the first client source port. Inspect actual code before deciding. Implement the smallest repository-owned integration correction, preserve MATLAB vendor originals, add meaningful multiple-client-port reconnect coverage, and rebuild the main ZIP locally. Keep target UDP port 17725 free until coordination with root. No remote compilation or reboot. Own UDP integration/build files; root owns console and soak test.

Root coordination at 08:30 UTC: CAN may use MATLAB immediately for copied-model builds; local_build can investigate UDP code in parallel, then acquire MATLAB after can_review_status.md records completion. Root is not using MATLAB or port 17725. Please write your progress in local_build_status.md because collaboration messages may be unreadable.

Root coordination at 08:48 UTC: main ZIP 20260926_084450_781 is ready. Root's 90-minute real model reconnect soak is queued until CAN releases target port 17725. CAN should finish the initial short CAN/CAN FD checks and record port release; additional long CAN testing can follow the main soak if needed. Root still leaves 17725 free now.

Root coordination at 08:55 UTC: both CAN v2 and CAN FD reports now pass and confirm stopped. Root is acquiring port 17725 for the 90-minute main-model soak, expected completion about 10:26 UTC. CAN can continue read-only telemetry/log retrieval and report writing; do not start another 17725 model until root release.

## can_review

Continue from isolated SDK candidate findings. Set both CANSetup DriverDirectory values in copies of CAN and CAN FD test models to /home/zh/.local/lib/tscan-thread-fix-20260926. Build locally using existing MATLAB R2024b and local scripts, then validate actual CAN and 64-byte CAN FD loopback on target through verify_can_target.py in explicit --baseline mode (generic kernel, not strict RT acceptance). Coordinate shared MATLAB builds with local_build; target port is currently free after failed main soak cleanup. Preserve original/default vendor SDK. Investigate actual failures within this scope; save all evidence and document local-derived SDK caveat. No reboot, remote compilation, priority limit increase, firmware update, or unrelated changes. Own CAN test models, verifier, and CAN evidence.

Root observation at 08:55 UTC: classic CAN v2 functional report passes, but its runtime_log is empty. Please investigate or retrieve final .simrt-status.json directly before finalizing evidence; retain actual runtime statistics without relabeling generic-kernel tests as RT acceptance.

## runtime_review

Root at 09:15 UTC: the Windows handle leak is now reproduced and fixed by root in client.py. pyxcp native Stim callbacks keep the Master cycle alive outside GC traversal. Forty upstream create/close iterations grow handles by 240 even after gc.collect(); callback detachment permits collection and stable handles. Root owns this fix and tests. Do not edit the same files; no further independent work assigned here yet.

## qt_validation

Continue the existing two-hour isolated tmux test. Preserve formal tty1 and the root three-hour health monitor. Root patched two parser exception paths in simrt_console.py; deployed formal console will restart only the top status pane. Your existing isolated long test can finish unchanged, then run a short test of the latest console. No reboot.
