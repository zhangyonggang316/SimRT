param(
    [string]$ApplicationDirectory = '',
    [string]$DemoDirectory = '',
    [string]$ReportName = 'packaged_startup.json'
)
$ErrorActionPreference = 'Stop'
$WorkspaceDirectory = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $DemoDirectory) { $DemoDirectory = Join-Path $PSScriptRoot 'staging_delivery' }
if (-not $ApplicationDirectory) { $ApplicationDirectory = Join-Path $DemoDirectory 'app' }
$ApplicationDirectory = (Resolve-Path -LiteralPath $ApplicationDirectory).Path
$DemoDirectory = (Resolve-Path -LiteralPath $DemoDirectory).Path
$Executable = Join-Path $ApplicationDirectory 'QtXCPHost.exe'
$ReportPath = Join-Path $PSScriptRoot $ReportName
$Started = Get-Date
$Arguments = '--demo-dir "' + $DemoDirectory + '"'
$AppProcess = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
try {
    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        Start-Sleep -Milliseconds 250
        $AppProcess.Refresh()
        if ($AppProcess.HasExited) { throw 'Packaged application exited during startup.' }
        $Modules = @($AppProcess.Modules | ForEach-Object ModuleName)
        if ('Qt6Widgets.dll' -in $Modules -and 'xcp_core.dll' -in $Modules) {
            $Ready = $true
            break
        }
    }
    if (-not $Ready) { throw 'Packaged Qt/native modules did not load.' }
    Start-Sleep -Seconds 2
    $StartupLog = Join-Path ([IO.Path]::GetTempPath()) 'QtXCPHost-startup.log'
    $FreshError = (Test-Path -LiteralPath $StartupLog) -and (Get-Item -LiteralPath $StartupLog).LastWriteTime -ge $Started
    if ($FreshError) { throw 'Packaged application wrote a startup failure report.' }
    $AppProcess.Refresh()
    if ($AppProcess.HasExited) { throw 'Packaged application failed after loading native modules.' }
    $Report = [ordered]@{
        passed = $true
        kind = 'hidden_packaged_startup'
        executable = $Executable
        executable_sha256 = (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
        qt_widgets_loaded = $true
        native_core_loaded = $true
        fresh_startup_error = [bool]$FreshError
        remote_operations_performed = $false
    }
    $Report | ConvertTo-Json | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    $Report | ConvertTo-Json
}
finally {
    $AppProcess.Refresh()
    if (-not $AppProcess.HasExited) {
        $null = $AppProcess.CloseMainWindow()
        if (-not $AppProcess.WaitForExit(5000)) {
            Stop-Process -Id $AppProcess.Id
            $AppProcess.WaitForExit()
        }
    }
}
