param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $workspace 'tests/validation/network_runtime' }
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$compiler = Join-Path $workspace 'toolchain/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/bin/clang.exe'
$crossCompiler = Join-Path $workspace 'toolchain/portable-linux-toolchain/toolchain/bin/linux-gcc.exe'
$source = Join-Path $workspace 'toolchain/simrt_linux_target/drivers/network/src/simrt_network.c'
$harness = Join-Path $PSScriptRoot 'test_network_runtime.c'
$executable = Join-Path $output 'test_network_runtime.exe'
$linkedFile = Join-Path $output 'simrt_network_linux.so'
& $compiler -std=c99 -Wall -Wextra -Werror -O2 $harness -static -pthread -lws2_32 -o $executable
if ($LASTEXITCODE -ne 0) { throw 'Network harness compilation failed.' }
& $executable
if ($LASTEXITCODE -ne 0) { throw 'Network runtime verification failed.' }
& $crossCompiler -std=c99 -Wall -Wextra -Werror -O2 -fPIC -shared $source -pthread '-Wl,--no-undefined' -o $linkedFile
if ($LASTEXITCODE -ne 0) { throw 'Network Linux runtime cross compilation failed.' }
$report = [ordered]@{
    utc = [DateTime]::UtcNow.ToString('o')
    passed = $true
    checks = @('parameter validation', 'nonblocking trylock paths', 'bounded queue pressure',
        'UDP real localhost datagrams', 'UDP receive truncation', 'TCP stream smaller receive buffers',
        'bidirectional TCP', 'TCP reconnect', 'duplicate and stale ownership', 'Linux cross compilation and link')
    source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
    harness_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $harness).Hash
    linux_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $linkedFile).Hash
    limitations = 'Sockets execute on Windows Winsock; Linux source is cross-compiled and linked. No ARK2120 hardware timing or Linux execution was tested.'
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'network_runtime_tests.json') -Encoding UTF8
Write-Output 'Network runtime verification passed.'
