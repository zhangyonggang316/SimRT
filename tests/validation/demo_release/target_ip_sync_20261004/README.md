# Target IP Synchronization

The entered Ubuntu host now takes precedence over the ZIP manifest and A2L
addresses. When the input is empty, the existing ZIP-then-A2L fallback remains.
Protocol and port tests/validation still comes from the model files. Model artifacts
and their checksums are not rewritten.

The top endpoint, diagnostic target, and actual XCP connection use the resolved
address. The host field is read-only during XCP operations and active sessions.
Disconnecting resolves the address again before the next connection.

## Verification

- Qt suite: 143 passed, including seven added regressions.
- Service suite: 190 passed, no skips.
- TCP and UDP loopback regressions use an A2L containing an old address and
  connect to the newly entered address, then exercise DAQ and calibration.
- PyInstaller build completed; the EXE started with a responsive SimRT window.
- Native desktop automation was unavailable, so packaged-window typing was not
  manually automated. Input, header, diagnostics, and connection parameters were
  checked by the Qt tests.
- No connection to or changes on the physical Ubuntu target were performed.

The relocated virtual environment's `pyvenv.cfg` now references
`D:\05SimRT\.python\3.9.10`. Tests use a canonical long TEMP/TMP path to avoid
unrelated Windows short-path versus long-path assertions in the demo tests.

## Delivery

The updated application is `app/distribution/SimRT.exe`, launched through the
existing `demos/Demo_XCP_Qt/START_DEMO.cmd`. Its SHA256 is
`db64130e3c1bf8d029976adc3fd27e5efea4f0833285138e2dcd4a537720e817`.

The previous application directory is preserved under `replaced_app_files/`.
`test_report.json`, the suite logs, and `package_report.json` record verification
and the unchanged model artifact hashes.

## Reproduce

Run from the workspace root:

```powershell
$env:TEMP = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Temp'
$env:TMP = $env:TEMP
& ./.venv/Scripts/python.exe ./app/qt_xcp_host/validate_tests.py --output ./tests/validation/target_ip_sync_rerun
```
