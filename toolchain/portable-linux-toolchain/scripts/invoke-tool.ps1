[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('gcc', 'g++', 'cpp', 'ar', 'as', 'ld', 'nm', 'objcopy', 'objdump',
        'ranlib', 'readelf', 'size', 'strings', 'strip', 'addr2line', 'c++filt',
        'elfedit', 'gcc-ar', 'gcc-nm', 'gcc-ranlib', 'gcov', 'gcov-dump', 'gcov-tool')]
    [string]$Tool,

    [Parameter(Mandatory = $true)]
    [AllowEmptyCollection()]
    [string[]]$ToolArguments
)

$ErrorActionPreference = 'Stop'
$packageRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$toolchain = Join-Path $packageRoot 'toolchain'
$toolBin = Join-Path $toolchain 'bin'
$executable = Join-Path $toolBin ("linux-{0}.exe" -f $Tool)
$sysroot = (Join-Path $toolchain 'x86_64-linux').Replace('\', '/')
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Tool not found: $executable. Invoke the script from the extracted package's scripts directory."
}

$environmentNames = @('PATH', 'GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH',
    'CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH')
$savedEnvironment = @{}
foreach ($name in $environmentNames) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ($name -ne 'PATH') { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
}

try {
    $env:PATH = "$toolBin;$(Join-Path $packageRoot 'host-bin');$env:SystemRoot\System32;$env:SystemRoot"
    $arguments = @()
    if ($Tool -in @('gcc', 'g++', 'cpp', 'ld')) { $arguments += "--sysroot=$sysroot" }
    $arguments += $ToolArguments
    & $executable @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Tool failed with exit code $LASTEXITCODE."
    }
}
finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process')
    }
}
