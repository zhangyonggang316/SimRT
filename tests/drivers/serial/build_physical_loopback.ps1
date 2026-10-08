param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot 'physical_loopback_results' }
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$compiler = Join-Path $workspace 'toolchain/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/bin/clang.exe'
$crossCompiler = Join-Path $workspace 'toolchain/portable-linux-toolchain/toolchain/bin/linux-gcc.exe'
$include = Join-Path $workspace 'toolchain/simrt_linux_target/drivers/serial/src'
$source = Join-Path $include 'simrt_serial.c'
$harness = Join-Path $PSScriptRoot 'serial_physical_loopback.c'
$protocolTest = Join-Path $PSScriptRoot 'test_serial_loopback_protocol.c'
$protocolExecutable = Join-Path $output 'test_serial_loopback_protocol.exe'
$elf = Join-Path $output 'serial_physical_loopback.elf'
& $compiler -std=c99 -Wall -Wextra -Werror -O2 $protocolTest -static -o $protocolExecutable
if ($LASTEXITCODE -ne 0) { throw 'Serial protocol test compilation failed.' }
& $protocolExecutable
if ($LASTEXITCODE -ne 0) { throw 'Serial protocol tests failed.' }
& $crossCompiler -std=c99 -Wall -Wextra -Werror -O2 $harness $source ('-I' + $include) -pthread -o $elf
if ($LASTEXITCODE -ne 0) { throw 'Physical serial harness cross compilation failed.' }
$restoreTest = Join-Path $output 'test_serial_restore.elf'
& $crossCompiler -std=c99 -Wall -Wextra -Werror -O2 (Join-Path $PSScriptRoot 'test_serial_restore.c') $source ('-I' + $include) -pthread -o $restoreTest
if ($LASTEXITCODE -ne 0) { throw 'Serial restoration test cross compilation failed.' }
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $elf).Hash.ToLowerInvariant()
$report = [ordered]@{
    utc = [DateTime]::UtcNow.ToString('o')
    protocol_test_passed = $true
    linux_cross_compile_passed = $true
    elf_sha256 = $hash
    harness_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $harness).Hash.ToLowerInvariant()
    driver_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
    physical_test_run = $false
    limitations = 'Protocol executes locally on Windows; Linux harness is compiled only. Run verify_serial_loopback_pty.py on Linux for PTY execution before physical testing.'
}
$report | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $output 'build_report.json') -Encoding UTF8
Write-Output ('ELF: ' + $elf)
Write-Output ('SHA256: ' + $hash)
