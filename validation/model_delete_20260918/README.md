# Remote Model Deletion, 2026-09-18

The Qt model inventory now offers Delete Model in its context menu. Confirmation
shows the selected ELF's full parent directory and defaults to Cancel. Confirming
deletes that directory and its contents and clears matching autostart configuration.
Running models must be stopped first. Success removes the row and triggers refresh,
including when automatic refresh is disabled.

Remote checks reject paths outside the selected scan root/SSH home, symlinks,
special files and directories containing another ELF. Process state is checked
again remotely. Autostart for another model is preserved. Before removal, the
directory is renamed and its identity is checked; pre-removal failures restore it.

Validation:

- Target UI: 28 tests passed, including six new deletion tests.
- Services: 159 tests passed, including 24 new deletion tests.
- Full Qt run: 95 of 96 passed initially; the remaining existing UI-05 test used a
  menu double missing setIcon/setToolTip. Its double was corrected and all 10
  UI-05 tests passed on the focused rerun.
- verify_ui.py rendered the real context menu and confirmation with Windows Qt
  fonts. Cancel was exercised without calling the deletion service.
- ui_report.json, delete_menu.png and delete_confirmation.png record those checks.
- Packaged startup loaded Qt Widgets, the native core and the selected demo without
  a new startup error. See packaged_startup.json.
- Installed executable SHA256:
  63727cd6bacf826d5973cae7d346ec3f1bed96fdf9483181985d010e5de05024.

The existing Demo_XCP_Qt/START_DEMO.cmd launches the updated application. Existing
app processes were preserved and must be reopened to use the change. Their old
executable is temporarily retained as QtXCPHost.previous.exe in this validation
directory because Windows still holds it open; it can be removed once those old
instances exit. Generated build/dist/spec files were sent to the Recycle Bin.

No real target was connected or modified, and MATLAB was not launched. Filesystem
tests deleted only temporary fixtures. Linux /proc, directory descriptors and
systemd calls were adapted or mocked on Windows; these results are not a live Linux
deletion acceptance test.
