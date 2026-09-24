# Native Signal Core

This C++17 DLL is the Qt application's required raw-data engine. It owns each
signal's bounded ring, rolling minimum/maximum statistics, linear cursor lookup,
and chronological min/max plot envelopes. It does not generate model samples or
control Ubuntu scheduling. Raw snapshots are never decimated.

The C ABI in `xcp_core.h` uses fixed-width handles and caller-owned output memory.
The adapter in `qt_host/native.py` rejects a missing/incompatible DLL. Both layers
are thread safe; adapter operations are serialized so multi-signal exports are
consistent with append batches. Histories accept finite values and nondecreasing,
finite, nonnegative timestamps. Equal timestamps are allowed, with the latest
value selected at an exact cursor time. Out-of-range cursors do not extrapolate.

Default capacity is 10,000 points per signal; supported capacity is 1..10,000,000.
Memory grows on demand to that bound. Plot budgets >= 4 preserve the first/last
raw sample and each interior bucket's actual minimum and maximum in time order.
Statistics describe retained samples, not discarded history.

## Rebuild

The pinned portable compiler is LLVM-MinGW 20250709 (Clang 20.1.8), UCRT x86_64.
Upstream: https://github.com/mstorsjo/llvm-mingw/releases/tag/20250709

Archive: `llvm-mingw-20250709-ucrt-x86_64.zip`

SHA256 (verified against the upstream GitHub release asset digest):
`82babcd6aae4dc3606e8e0471d816989c384b4bf86a139f184a8b4a1b2c2758d`

Extract to `tools/qt_toolchain/` without adding anything to the system PATH.
From the workspace root:

```powershell
& ./qt_xcp_host/build_native.ps1
& ./.venv/Scripts/python.exe -m unittest discover -s qt_xcp_host/tests -p test_native_core.py -v
```

The resulting `qt_host/native_bin/xcp_core.dll` statically links the C++ runtime;
only standard Windows system DLLs are needed. End users do not need a compiler.
