param([string]$DemoDirectory = '')
$ErrorActionPreference = 'Stop'
$ProjectDirectory = $PSScriptRoot
$WorkspaceDirectory = Split-Path -Parent $ProjectDirectory
$PythonExecutable = Join-Path $WorkspaceDirectory '.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw 'The workspace Python environment is missing. See qt_xcp_host/README.md.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDirectory 'qt_host/native_bin/xcp_core.dll') -PathType Leaf)) {
    throw 'The required native data core is missing. Run qt_xcp_host/build_native.ps1 first.'
}
if (-not $DemoDirectory) { $DemoDirectory = Join-Path $WorkspaceDirectory 'Demo_XCP_Qt' }
$DemoDirectory = (Resolve-Path -LiteralPath $DemoDirectory).Path
$StartInfo = New-Object System.Diagnostics.ProcessStartInfo
$StartInfo.FileName = $PythonExecutable
$StartInfo.Arguments = '"' + (Join-Path $ProjectDirectory 'main.py') + '" --demo-dir "' + $DemoDirectory + '"'
$StartInfo.WorkingDirectory = $ProjectDirectory
$StartInfo.UseShellExecute = $false
$StartInfo.CreateNoWindow = $true
$StartInfo.EnvironmentVariables['PYTHONPATH'] = $ProjectDirectory + [IO.Path]::PathSeparator +
    (Join-Path $WorkspaceDirectory 'x280_linux_target/python')
[void][System.Diagnostics.Process]::Start($StartInfo)
