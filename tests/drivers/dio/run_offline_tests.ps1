param([string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $PSScriptRoot 'results' }
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $output | Out-Null
$compiler = Join-Path $workspace 'toolchain/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/bin/clang.exe'
$crossCompiler = Join-Path $workspace 'toolchain/portable-linux-toolchain/toolchain/bin/linux-gcc.exe'
$source = Join-Path $workspace 'toolchain/simrt_linux_target/drivers/dio/src/simrt_dio.c'
$harness = Join-Path $PSScriptRoot 'test_dio_runtime.c'
$executable = Join-Path $output 'test_dio_runtime.exe'
$linkedFile = Join-Path $output 'simrt_dio_linux.so'
& $compiler -std=c99 -Wall -Wextra -Werror -O2 $harness -static -pthread -o $executable
if ($LASTEXITCODE -ne 0) { throw 'DIO harness compilation failed.' }
& $executable
if ($LASTEXITCODE -ne 0) { throw 'DIO runtime verification failed.' }
& $crossCompiler -std=c99 -Wall -Wextra -Werror -O2 -fPIC -shared $source -pthread '-Wl,--no-undefined' -o $linkedFile
if ($LASTEXITCODE -ne 0) { throw 'DIO Linux runtime cross compilation failed.' }
$report = [ordered]@{
    utc = [DateTime]::UtcNow.ToString('o')
    passed = $true
    checks = @('GPIO v2 ABI', 'validation', 'atomic initial output', 'line ordering',
        '64-line read/write masks', 'errno propagation', 'stale ownership',
        'resource cleanup', 'input write rejection', 'trylock contention', 'Linux cross link')
    source_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash
    harness_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $harness).Hash
    limitations = 'GPIO syscalls are mocked; no hardware lines or ARK board mapping are accessed. Linux runtime is cross-compiled and linked only.'
}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $output 'dio_runtime_tests.json') -Encoding UTF8
Write-Output 'DIO offline verification passed.'
