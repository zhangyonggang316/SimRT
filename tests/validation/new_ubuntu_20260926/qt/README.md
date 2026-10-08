# Local Qt tests/validation - 2026-09-26

Scope: Windows host checks only. No SSH connection, Ubuntu command, MATLAB
invocation, or remote hardware test was performed by these checks. Demo settings,
application code, the delivered EXE, and the Python environment were not changed.

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| Qt and native core | 130 passed, 0 failed, 0 skipped | `qt_tests.json`, `qt_tests.log` |
| Shared services | 172 passed, 0 failed, 0 skipped | `baseline_tests.json`, `baseline_tests.log` |
| XCP backend | 27 passed | `backend_tests.log` |
| Python 3.9.10 / pyxcp 0.22.32 compatibility | 5 passed | `pyxcp_02232_tests.log` |
| Dependency consistency | Passed | `pip_check.log` |
| Qt visual fixtures | 8 screenshots passed size/button checks | `visual_report.json` |
| Delivered EXE and native DLL hashes | Both match `app/build_report.json` | `exe_integrity.json` |
| Required Qt runtime files / legacy GUI exclusion | Passed | `exe_integrity.json` |
| Frozen EXE import smoke (`--help`) | Exit code 0, no new startup error log | `exe_import_smoke.json` |

The 334 unit/compatibility checks include actual local TCP and UDP sockets, Qt
button actions, DAQ, calibration write/readback/restore, and unmodified pyxcp
official skeleton execution. These are local loopback checks, not evidence of
target networking, target model execution, realtime scheduling, or TC1013 CAN.

Visual fixtures cover model deployment, diagnostics, observation, and calibration
at 1320 x 820 and 1000 x 660 logical pixels, using the Windows Qt platform with a
1.25 device pixel ratio. No button exceeded its parent or failed the text-width
check. The 10,000-point chart RGB variance was 5887.3894, confirming a nonblank
plot. The compact observation and model-deployment screenshots were also
visually inspected. Addresses and resource values in these images are synthetic
fixture data, not current target observations. The frozen EXE smoke test does not
constitute an interactive GUI or real-target acceptance test.

## Reproduction

Run from the repository root in PowerShell:

```powershell
& ./.venv/Scripts/python.exe ./app/qt_xcp_host/validate_tests.py --output ./tests/validation/new_ubuntu_20260926/qt
& ./.venv/Scripts/python.exe ./app/qt_xcp_host/validate_visual.py --output ./tests/validation/new_ubuntu_20260926/qt
$env:PYTHONPATH = 'qt_xcp_host;shared/python'
& ./.venv/Scripts/python.exe -m unittest discover -s tests/protocol -v
& ./.venv/Scripts/python.exe tests/validation/pyxcp_02232/validate_pyxcp_02232.py
& ./.venv/Scripts/python.exe -m pip check
```

`test_report.json` also records source SHA-256 values and explicitly marks
`ubuntu_hardware_test` as false. The historical compatibility script still adds
the removed `python_xcp_host` directory to `sys.path`; the explicit `PYTHONPATH`
above resolves the current `shared/python/pyxcp_host` package. No source change was
needed for this run.

## Local console implementation checks

The later console-display task added `linux/console/`. Its collector
and renderer passed 11 focused tests (`console_tests.log`). These cover live and
stale runtime data, a fresh status file with a stalled sample, unsupported schema,
stopped telemetry, process ownership, zombies, process elapsed time, manifest
caching, CPU deltas, network masks, realtime-flag absence, bounded/sanitized logs,
and 80 x 25 / larger display constraints.

`console_fixture_80x25.png` and `console_fixture_120x40.png` are locally rendered
synthetic layout illustrations, explicitly labeled in their content and in
`console_fixture_report.json`. The 80 x 25 image was visually inspected. They do
not prove that tmux, curses, automatic tty1 login, or command input works on the
target. On-target shell syntax, pane focus, interaction and long-running checks
remain separate host-deployment verification.
