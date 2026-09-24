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
file/symbol list matches this version. Actual loading and hardware validation
are recorded separately under `validation/tc1013_can_20260919/`.
