# Console network display update

Date: 2026-10-05. Target: `192.168.193.195`.

The real-time machine console now hides loopback interfaces and addresses.
Every remaining IPv4 or IPv6 row includes its interface MAC in parentheses.
Interfaces without an IP remain visible with their MAC; missing MAC values are
shown as `(unavailable)`. Existing wrapping and network pagination are retained.

## Verification

All 24 console tests passed, including loopback filtering, IPv4/IPv6 MAC
formatting, unassigned interfaces, missing MAC data and narrow-screen wrapping:

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s linux/console -p test_console.py -v
```

[deploy.py](deploy.py) compared the staged output against the target's actual
`ip -j address show` data before installation. It then replaced only the console
Python file and restarted the dedicated dashboard pane. The live terminal
capture matched all expected IP/MAC rows and continued refreshing at 120x33.
The 16x32 font remains configured. Model PID 8741 remained running; no model
build, model restart, target reboot or network configuration change was made.

Evidence: [deployment.json](deployment.json), [staged_snapshot.txt](staged_snapshot.txt)
and [console_after.txt](console_after.txt). These are actual terminal and target
data checks, not a physical monitor photograph or reboot test.

The previous program is retained on the target at
`/home/zh/.local/lib/simrt-console/simrt_console.py.before-network-mac-20261005-145153`.
