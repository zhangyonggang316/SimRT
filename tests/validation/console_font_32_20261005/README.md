# Real-time display font enlargement

Date: 2026-10-05. Target: `192.168.193.195`.

The tty1 font was increased from Terminus 12x24 to Terminus 16x32, making
characters approximately 33% wider and taller. At 1920x1080, the terminal
changed from 160 columns by 45 rows to 120 columns by 33 rows.

The font was applied live and persisted in `/etc/default/console-setup` as
`FONTFACE="Terminus"` and `FONTSIZE="16x32"`. The boot font cache was regenerated
and `console-setup.service` was confirmed enabled. No reboot was performed.

[font_result.json](font_result.json) records the successful apply and checks:
tty1 and tmux dimensions agree, dashboard PID 1591 remained unchanged, and the
dashboard continued refreshing. [console_after.txt](console_after.txt) captures
the actual terminal with network addresses, model status, telemetry and logs.
Model PID 8741 remained running. Existing model log errors and historical
deadline counters are unrelated to this display adjustment.

These checks verify the actual terminal setting and its rendered text; they do
not constitute a physical monitor photograph or a reboot test.

The target backup at `/var/backups/simrt-console-font-20261005-064109` contains
the previous configuration, cached boot script and the previous font as
`previous.psf`. [apply_font.py](apply_font.py) records the applied procedure.
