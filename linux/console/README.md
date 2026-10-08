# SimRT local display

The Python standard-library dashboard follows `docs/实时机显示界面.jpg`: black
background, white labels and cyan values. It occupies one full-screen tmux pane.
There is no command pane, OS version or Linux kernel version on the display.
SSH remains a normal administration session. The dashboard never starts or stops
models. Runtime, finite stop time, model period, execution times and intervals
are displayed in **ms**. The independent UI refresh defaults to 1000 ms.

## Network interfaces

`ip -j address show` supplies IPv4 and IPv6 addresses; loopback interfaces and
addresses are hidden. Wireless interfaces also omit link-local IPv6 (`fe80::/10`)
rows; their global IPv6 addresses remain visible. Wireless detection uses sysfs.
Down interfaces and interfaces without an address remain
visible. IPv4 includes the netmask; IPv6 includes the prefix length. Each address
appears on a separate row followed by the interface MAC in parentheses, or
`(unavailable)` when the MAC is missing. Unassigned interfaces show
`no IP address (MAC)`. Long rows wrap; overflowing rows rotate every five seconds
with a page counter.
An unavailable query is reported as unavailable, never as an empty interface list.
The clock reloads the system timezone on each refresh so an SSH time/zone update
appears without restarting the dashboard.

## Installation

Dependencies are Python 3 with curses, tmux and iproute2. Install this directory
to `/home/zh/.local/lib/simrt-console` and make `start_console.sh` executable.
The existing tty1-only hook in `~/.profile` is:

```sh
if [ -z "${SSH_CONNECTION:-}${SSH_TTY:-}${TMUX:-}" ] && [ "$(tty 2>/dev/null)" = /dev/tty1 ]; then
    "$HOME/.local/lib/simrt-console/start_console.sh"
fi
```

The launcher uses the dedicated `simrt-console` tmux server, removes the former
command pane when upgrading, and disables tmux command bindings. Ordinary keys
do not close the dashboard. Administration and recovery use SSH. The existing
autologin setup is separate; no reboot or login configuration change is required
for a live display update.

On the current 1920x1080 target, the console uses the Terminus 16x32 font
(120 columns by 33 rows), enlarged from Terminus 12x24. The persistent settings in
`/etc/default/console-setup` are `FONTFACE="Terminus"` and `FONTSIZE="16x32"`.
Run `sudo setupcon --font-only --save-only` after changing these settings to
refresh the boot font cache. The live tty1 font can be applied independently:

```sh
sudo setfont -C /dev/tty1 /usr/share/consolefonts/Uni2-Terminus32x16.psf.gz
```

The dashboard adapts to the terminal resize without restarting its process.
The applied settings and previous-font backup are recorded in
`tests/validation/console_font_32_20261005` in the workspace. The previous 12x24
adjustment remains recorded in `tests/validation/console_font_20261005`.

`linux/tools/deploy_console_update.py --host HOST --output REPORT_DIRECTORY` uploads
the three runtime files, retains a dated backup, verifies hashes, runs an isolated
resize/input check, then upgrades the dedicated live display session. It prompts
for the SSH password unless `SIMRT_SSH_PASSWORD` is supplied in the environment.

## Telemetry

Only owned, non-zombie `.elf` processes are candidates. A matching manifest
provides the model name and MATLAB release. Live runtime status must match the
PID, schema and monotonic sample, and be at most five seconds old. Completed
steps confirm RUNNING; missing, paused and stale telemetry remains explicitly
unverified. Unknown metrics are never filled with zeros. CPU, memory and disk
come from `/proc` and filesystem usage. PREEMPT_RT status comes from the kernel
flag, without exposing the kernel version. OS/kernel values remain available in
the diagnostic `--json` output only.

Runtime files are `<model>.elf.simrt-status.json`; logs use the bounded tail of
`<model>.elf.pyxcp-host.log`. Terminal controls are sanitized. No collector or
display I/O runs in the model's real-time thread.

## Verification

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s linux/console -p test_console.py -v
```

On Linux, `python3 simrt_console.py --once` renders one snapshot, while `--json`
returns structured data. `python3 validate_tmux.py --duration 120 --sample-interval 10 --output DIRECTORY`
creates its own tmux server, checks 80x25/120x40/160x50 resizing, verifies one live
full-screen dashboard, confirms ESC/q/Enter do not expose a shell, and removes
only its own test session.

Current local/target evidence is in `tests/validation/communication_20260927`.
Resize and SSH capture checks do not constitute physical monitor or reboot tests.
