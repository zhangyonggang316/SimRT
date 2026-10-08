$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$package = Join-Path $projectRoot 'portable-linux-toolchain/portable-linux-toolchain'
$manifest = Get-Content -LiteralPath (Join-Path $package 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$failures = @()
foreach ($entry in $manifest.files) {
    $file = Join-Path $package $entry.path
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        $failures += "Missing: $($entry.path)"
    } elseif ((Get-Item -LiteralPath $file).Length -ne $entry.bytes -or
              (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ne $entry.sha256) {
        $failures += "Mismatch: $($entry.path)"
    }
}
$invoke = Join-Path $package 'scripts/invoke-tool.ps1'
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$versions = & $python -c "import sys,platform,json,importlib.metadata as m; print(json.dumps({'python':sys.version,'executable':sys.executable,'base_executable':sys._base_executable,'architecture':platform.architecture(),'packages':{n:m.version(n) for n in ['pyxcp','paramiko','PySide6-Essentials','shiboken6','numpy','matplotlib','pyinstaller']}}))" | ConvertFrom-Json
$pipCheck = & $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency check failed.' }
$report = [ordered]@{
    checked_utc = [DateTime]::UtcNow.ToString('o')
    operating_system = (Get-CimInstance Win32_OperatingSystem).Caption
    python = $versions
    pip_check = [string]$pipCheck
    toolchain_root = $package
    compiler_version = (& $invoke -Tool gcc -ToolArguments @('--version')) -join "`n"
    compiler_target = (& $invoke -Tool gcc -ToolArguments @('-dumpmachine')) -join "`n"
    manifest_file_count = $manifest.files.Count
    manifest_verified_count = $manifest.files.Count - $failures.Count
    manifest_failures = $failures
    remote_operations_performed = $false
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'windows_environment.json') -Encoding UTF8
$report | ConvertTo-Json -Depth 8
if ($failures.Count) { throw 'Toolchain manifest verification failed.' }
