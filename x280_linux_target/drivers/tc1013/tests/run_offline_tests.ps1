param(
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $workspace 'validation/tc1013_canfd_20260919'
}
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$compiler = Join-Path $workspace 'tools/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/bin/clang.exe'
$crossCompiler = Join-Path $workspace 'portable-linux-toolchain/portable-linux-toolchain/toolchain/bin/linux-gcc.exe'
$source = Join-Path $PSScriptRoot '../src/x280_tc1013_can.c'
$harness = Join-Path $PSScriptRoot 'test_can_runtime.c'
$executable = Join-Path $output 'test_can_runtime.exe'
$objectFile = Join-Path $output 'x280_tc1013_can.o'
$linkedFile = Join-Path $output 'x280_tc1013_can_test_link.so'
& $compiler -std=c99 -Wall -Wextra -Werror -O2 -I $PSScriptRoot $harness -static -pthread -o $executable
if ($LASTEXITCODE -ne 0) { throw 'Offline C harness compilation failed.' }
& $executable
if ($LASTEXITCODE -ne 0) { throw 'Offline C harness execution failed.' }
& $executable --fatal-cwd-restore
if ($LASTEXITCODE -ne 1) { throw 'Unrecoverable SDK working-directory restore did not stop the process.' }
& $crossCompiler -std=c99 -Wall -Wextra -Werror -O2 -pthread -c $source -o $objectFile
if ($LASTEXITCODE -ne 0) { throw 'Linux cross compilation failed.' }
& $crossCompiler -std=c99 -Wall -Wextra -Werror -O2 -fPIC -shared $source -ldl -pthread '-Wl,--no-undefined' -o $linkedFile
if ($LASTEXITCODE -ne 0) { throw 'Linux POSIX library link failed.' }
$report = [ordered]@{
    utc = [DateTime]::UtcNow.ToString('o')
    passed = $true
    tests = @('24-byte CAN and 80-byte CAN FD vendor ABI', 'absolute SDK path', 'missing SDK and symbol cleanup',
        'connect/configure failure cleanup', 'already-connected return code 5',
        'shared adapter and per-channel configuration', 'duplicate setup ownership', 'invalid CAN values',
        'nonblocking trylock', 'stalled USB and bounded transmit queue',
        'stale ownership tokens', 'persistent setup errors on send/receive', 'serial and directory conflicts',
        'FIFO frames and empty outputs', 'SDK receive/transmit errors',
        'invalid vendor receive count', 'receive queue overflow', 'idempotent close',
        'ISO CAN FD bitrate configuration', 'all 16 CAN FD DLC/length conversions',
        '64-byte payloads and BRS/ESI', 'CAN/CAN FD mode mismatches',
        'SDK cwd enter/restore and error cleanup', 'bounded EINTR restore retry',
        'no persistent or per-step cwd change', 'unrecoverable cwd restore stops process',
        'Linux x86_64 cross compilation and POSIX library link')
    source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
    linux_object_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $objectFile).Hash
    linux_link_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $linkedFile).Hash
    limitations = 'Vendor API is mocked for local Windows execution. Linux source cross-compiles; no real Linux SDK binary, USB adapter, target deployment or hardware timing was tested.'
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'runtime_offline_tests.json') -Encoding UTF8
Write-Output 'Offline CAN runtime verification passed; hardware was not accessed.'
