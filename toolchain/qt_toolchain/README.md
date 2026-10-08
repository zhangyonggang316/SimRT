# Windows APP native compiler

The APP native DLL uses LLVM-MinGW `20250709-ucrt-x86_64` (Clang 20.1.8).
The compiler binaries and original archive are distributed in the matching
GitHub Release, not Git history. Extract the asset into the repository root
to restore `toolchain/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/`.

Upstream: https://github.com/mstorsjo/llvm-mingw/releases/tag/20250709

Keep the complete directory, including licenses and runtime libraries.
Build entry: `app/qt_xcp_host/build_native.ps1`.
See [release restore instructions](../../docs/GITHUB_DELIVERY.md).
