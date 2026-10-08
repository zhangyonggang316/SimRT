# Vendor Linux SDK provenance

Source: https://github.com/TOSUN-Shanghai/libTSCANDemos

Pinned commit: `6690a4f1bc9056dd8b3d0bfc28f909db64df5e6d`.

Downloaded on 2026-09-19 from the vendor's public repository:

| Local file | Repository path | SHA256 |
| --- | --- | --- |
| `linux/libTSCANApiOnLinux.so` | `lib/linux/libTSCANApiOnLinux.so` | `11a0749548d586b25b198ea29b46a6bb15f6c42e51b3cc34ee2e9426bf3dd03b` |
| `linux/libTSH.so` | `lib/linux/libTSH.so` | `8308ec91016870da114ba476d496900cdf73fe2aaa038e0aa00cf56a44bd6758` |
| `linux/TSCANDef.hpp` | `include/linux/TSCANDef.hpp` | `3f3589399f5a7dc0ebfb650cab777a091a2a18d2cba6f405e665fcddad7daa8f` |

The upstream MIT license is retained as `LICENSE`. Binaries are unmodified.
Both libraries are ELF64 x86-64. This delivery contains two shared libraries;
the older PDF's `blf.so` is not included. The main library exports CAN and CAN FD
configuration/FIFO APIs, but does not export `tscan_get_can_channel_count`.
The runtime must check optional SDK features rather than assume the older PDF's
file/symbol list matches this version. Actual loading and hardware tests/validation
are recorded separately under `tests/validation/tc1013_can_20260919/`.


## Local compatibility correction, 2026-09-26

This directory is an opt-in derived SDK, not an unmodified vendor release.
GDB identified libTSH AddHIDDevice, HIDControl.cpp:458, calling
pthread_setschedparam with a null native handle after detaching the read thread.
The preceding creation of the write thread is successful. One instruction's
stack-relative operand is corrected from the detached read-thread object
(rbp-0x68) to the live write-thread object (rbp-0x60).

The original MIT license is retained. The project vendor directory and default
target SDK remain unchanged. No CAN protocol, message, bitrate, or firmware
operation is modified. This is a local compatibility fix, not vendor approval.

Correction receipt:

```json
{
  "original_sha256": "8308ec91016870da114ba476d496900cdf73fe2aaa038e0aa00cf56a44bd6758",
  "patched_sha256": "e289da8f4a1b0703129213b34d84ff93e483e66d7f7f7154db00e9e2f4af3f8b",
  "file": "libTSH.so",
  "file_offset": "0xd185",
  "original_instruction": "488d4598",
  "patched_instruction": "488d45a0",
  "effect": "Use live write-thread object at rbp-0x60 instead of detached read-thread object at rbp-0x68",
  "evidence": "sdk_gdb_backtrace.json; sdk_gdb_skip_invalid_sched.json",
  "vendor_files_modified": false,
  "production_selection_changed": false
}
```
