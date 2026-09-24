param([switch]$SkipNativeBuild)
$ErrorActionPreference = 'Stop'
$ProjectDirectory = $PSScriptRoot
$WorkspaceDirectory = Split-Path -Parent $ProjectDirectory
$PythonExecutable = Join-Path $WorkspaceDirectory '.venv/Scripts/python.exe'
$BackendDirectory = Join-Path $WorkspaceDirectory 'x280_linux_target/python'
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw 'The workspace Python environment is missing. See qt_xcp_host/README.md.'
}
if (-not (Test-Path -LiteralPath (Join-Path $ProjectDirectory 'main.py') -PathType Leaf)) {
    throw 'The Qt application entry point has not been created yet.'
}
& $PythonExecutable -c "import sys, struct, PySide6, PyInstaller; assert sys.version_info[:3] == (3, 9, 10), sys.version; assert struct.calcsize('P') == 8; assert PySide6.__version__ == '6.8.3', PySide6.__version__; assert PyInstaller.__version__ == '6.22.2', PyInstaller.__version__"
if ($LASTEXITCODE -ne 0) { throw 'Build dependencies do not match the pinned environment.' }
& $PythonExecutable -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency consistency check failed.' }
if (-not $SkipNativeBuild) { & (Join-Path $ProjectDirectory 'build_native.ps1') }
$NativeLibrary = Join-Path $ProjectDirectory 'qt_host/native_bin/xcp_core.dll'
if (-not (Test-Path -LiteralPath $NativeLibrary -PathType Leaf)) { throw 'The required C++ DLL is missing.' }
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $ProjectDirectory + [IO.Path]::PathSeparator + $BackendDirectory
    & $PythonExecutable -c "from qt_host.native import NativeBuffer; b = NativeBuffer(); b.append(0, {'build_check': 1}); assert b.stats()['build_check'] == (1, 1, 1, 1); b.close()"
    if ($LASTEXITCODE -ne 0) { throw 'Native core loading check failed.' }
    & $PythonExecutable -m PyInstaller --noconfirm --clean --windowed --onedir `
        --name QtXCPHost `
        --distpath (Join-Path $ProjectDirectory 'dist') `
        --workpath (Join-Path $ProjectDirectory 'build') `
        --specpath $ProjectDirectory `
        --paths $ProjectDirectory --paths $BackendDirectory `
        --collect-all pyxcp --collect-submodules x280_xcp --collect-data qt_host `
        --copy-metadata PySide6-Essentials --copy-metadata shiboken6 `
        --add-binary ($NativeLibrary + ';qt_host/native_bin') `
        --exclude-module tkinter --exclude-module _tkinter --exclude-module pyxcp_host.ui `
        --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 `
        --hidden-import matplotlib.backends.backend_qtagg --exclude-module pyxcp.examples `
        (Join-Path $ProjectDirectory 'main.py')
    if ($LASTEXITCODE -ne 0) { throw "Qt application build failed: $LASTEXITCODE" }
}
finally {
    if ($null -eq $PreviousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $PreviousPythonPath }
}
$ApplicationDirectory = Join-Path $ProjectDirectory 'dist/QtXCPHost'
foreach ($RelativePath in @('QtXCPHost.exe', '_internal/qt_host/native_bin/xcp_core.dll',
                            '_internal/PySide6/Qt6Core.dll', '_internal/PySide6/Qt6Widgets.dll',
                            '_internal/PySide6/plugins/platforms/qwindows.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ApplicationDirectory $RelativePath) -PathType Leaf)) {
        throw "The built application is missing a required runtime file: $RelativePath"
    }
}
$ForbiddenFiles = @(Get-ChildItem -LiteralPath $ApplicationDirectory -File -Recurse | Where-Object {
    $_.Name -match '^(_tkinter|tk86t|tcl86t|Qt5Core|PyQt5|PyQt6)' -or $_.FullName -match '[\\/]PyQt[56][\\/]'
})
if ($ForbiddenFiles.Count) { throw "The Qt package unexpectedly includes legacy GUI files: $($ForbiddenFiles.FullName -join ', ')" }
Copy-Item -LiteralPath (Join-Path $ProjectDirectory 'README.md') -Destination $ApplicationDirectory -Force
$LicensesDirectory = Join-Path $ApplicationDirectory 'third_party'
New-Item -ItemType Directory -Path $LicensesDirectory -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $ProjectDirectory 'third_party') -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $LicensesDirectory -Force
}
foreach ($RelativePath in @('PySide6_Essentials-6.8.3.dist-info', 'shiboken6-6.8.3.dist-info')) {
    $DistributionDirectory = Join-Path $WorkspaceDirectory ('.venv/Lib/site-packages/' + $RelativePath)
    $DestinationDirectory = Join-Path $LicensesDirectory $RelativePath
    New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
    Get-ChildItem -LiteralPath $DistributionDirectory -File | Where-Object {
        $_.Name -match '^(LICENSE|COPYING|LicenseRef|METADATA)'
    } | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $DestinationDirectory -Force }
}
$ToolchainLicense = Join-Path $WorkspaceDirectory 'tools/qt_toolchain/llvm-mingw-20250709-ucrt-x86_64/LICENSE.TXT'
if (Test-Path -LiteralPath $ToolchainLicense -PathType Leaf) {
    Copy-Item -LiteralPath $ToolchainLicense -Destination (Join-Path $LicensesDirectory 'llvm-mingw-LICENSE.TXT') -Force
}
$BuildReport = [ordered]@{
    created_at = [DateTimeOffset]::Now.ToString('o')
    status = 'build_completed'
    runtime_validation = 'not_recorded_by_build_script'
    application = 'QtXCPHost.exe'
    python = '3.9.10'
    pyside6 = '6.8.3'
    pyinstaller = '6.22.2'
    native_abi = 1
    exe_sha256 = (Get-FileHash -LiteralPath (Join-Path $ApplicationDirectory 'QtXCPHost.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
    native_sha256 = (Get-FileHash -LiteralPath (Join-Path $ApplicationDirectory '_internal/qt_host/native_bin/xcp_core.dll') -Algorithm SHA256).Hash.ToLowerInvariant()
}
$BuildReport | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $ApplicationDirectory 'build_report.json') -Encoding UTF8
& (Join-Path $ProjectDirectory 'collect_licenses.ps1') -DestinationDirectory $LicensesDirectory
Write-Host "Built Qt application: $(Join-Path $ApplicationDirectory 'QtXCPHost.exe')"
Write-Host 'GUI and target validation must be recorded separately.'
