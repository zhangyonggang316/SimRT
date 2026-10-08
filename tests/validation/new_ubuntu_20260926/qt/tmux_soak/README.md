# Isolated tmux console soak

Requested duration: 7200 seconds. The actual completion result is recorded in
`tmux_validation.json`; while it lacks `actual_seconds`, the run is still in
progress and `passed: false` is not a final failure result.

The validator runs on the pinned SSH target `192.168.219.195` as ordinary user
`zh`. It creates a unique `simrt-validation-*` tmux server and never operates the
production `simrt-console` server. It does not use sudo, reboot the machine, or
start a model. Launch identity and timestamps are in `launch.json`.

Every cycle resizes the independent terminal, keeps a six-row Bash pane focused,
sends ESC and a harmless printf command, then verifies the command's standalone
output. Sizes cycle through 80 x 25, 120 x 40, 160 x 50 and 80 x 25. Both panes
must remain alive, the dashboard must redraw with its header and log section,
and the dashboard PID must remain unchanged.

`latest_dashboard.txt` and `latest_shell.txt` are refreshed while monitoring.
On completion, numbered captures, the runner log and the final report are
downloaded from the target. Captures contain real target resource information;
model timing remains unavailable whenever no confirmed model is running.

This is an on-target isolated tmux input/resize test. It is not a physical
keyboard/monitor, tty1 automatic-login, reboot, XCP, CAN, or 1 ms scheduling
acceptance test. No such result should be inferred from this report.
