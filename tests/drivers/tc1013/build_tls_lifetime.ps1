param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$output = [IO.Path]::GetFullPath($OutputDirectory)
$sdk = Join-Path $output 'mock_sdk'
New-Item -ItemType Directory -Force -Path $sdk | Out-Null
$compiler = Join-Path $workspace 'toolchain/portable-linux-toolchain/toolchain/bin/linux-gcc.exe'
$include = Join-Path $workspace 'toolchain/simrt_linux_target/drivers/tc1013/src'
$source = Join-Path $include 'simrt_tc1013_can.c'
$fixture = Join-Path $PSScriptRoot 'test_tls_sdk.c'
$harness = Join-Path $PSScriptRoot 'test_tls_lifetime.c'
$baseline = Join-Path $output 'driver_without_nodelete.c'
# Preserve the pre-fix behavior as a negative control, without changing the source.
[IO.File]::WriteAllText($baseline, [IO.File]::ReadAllText($source).Replace('RTLD_NODELETE |', ''), [Text.UTF8Encoding]::new($false))
& $compiler -std=c99 -Wall -Wextra -Werror -O2 -fPIC -shared -pthread $fixture -o (Join-Path $sdk 'libTSCANApiOnLinux.so')
if ($LASTEXITCODE -ne 0) { throw 'TLS vendor fixture compilation failed.' }
& $compiler -std=c99 -Wall -Wextra -Werror -O2 -fPIC -shared -pthread -DTC1013_TEST_PLACEHOLDER $fixture -o (Join-Path $sdk 'libTSH.so')
if ($LASTEXITCODE -ne 0) { throw 'TLS dependency fixture compilation failed.' }
& $compiler -std=c99 -Wall -Wextra -Werror -O2 -pthread -I $include $harness $source -ldl -o (Join-Path $output 'tls_fixed.elf')
if ($LASTEXITCODE -ne 0) { throw 'TLS corrected driver harness compilation failed.' }
& $compiler -std=c99 -Wall -Wextra -Werror -O2 -pthread -I $include $harness $baseline -ldl -o (Join-Path $output 'tls_baseline.elf')
if ($LASTEXITCODE -ne 0) { throw 'TLS baseline driver harness compilation failed.' }
Write-Output 'Linux TLS fixture and corrected/baseline harnesses built locally; no hardware accessed.'
