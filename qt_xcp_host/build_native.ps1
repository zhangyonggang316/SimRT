param([string]$Compiler = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
$WorkspaceRoot = Split-Path -Parent $ProjectRoot
if (-not $Compiler) {
    $Compiler = Join-Path $WorkspaceRoot 'tools/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/bin/clang++.exe'
}
if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
    throw "C++17 compiler not found: $Compiler. See qt_xcp_host/native/README.md."
}
$OutputDirectory = Join-Path $ProjectRoot 'qt_host/native_bin'
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputPath = Join-Path $OutputDirectory 'xcp_core.dll'
& $Compiler '--version'
if ($LASTEXITCODE -ne 0) { throw 'Cannot query compiler version.' }
& $Compiler '-std=c++17' '-O2' '-DNDEBUG' '-Wall' '-Wextra' '-Werror' '-shared' '-static' '-static-libgcc' '-static-libstdc++' '-Wl,--no-insert-timestamp' (Join-Path $ProjectRoot 'native/xcp_core.cpp') '-o' $OutputPath
if ($LASTEXITCODE -ne 0) { throw "Native C++ core build failed: $LASTEXITCODE" }
Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256
