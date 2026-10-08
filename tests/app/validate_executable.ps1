$ErrorActionPreference = 'Stop'
$Workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$Output = Join-Path $PSScriptRoot 'layout_results'
$StartupLog = Join-Path ([IO.Path]::GetTempPath()) 'SimRT-startup.log'
$Records = @()
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class SimRTValidationWindow {
    private delegate bool Callback(IntPtr window, IntPtr state);
    [DllImport("user32.dll")] private static extern bool EnumWindows(Callback callback, IntPtr state);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr window, StringBuilder text, int length);
    public static string Title(int process) {
        string title = "";
        EnumWindows((window, state) => {
            uint owner;
            GetWindowThreadProcessId(window, out owner);
            if (owner != process) return true;
            StringBuilder text = new StringBuilder(256);
            GetWindowText(window, text, text.Capacity);
            if (text.ToString() == "SimRT") { title = text.ToString(); return false; }
            return true;
        }, IntPtr.Zero);
        return title;
    }
}
'@
foreach ($Entry in @(
    @{ Application='app/distribution/SimRT.exe'; Demo='demos/Demo_XCP_Qt' },
    @{ Application='tests/app/layout_results/portable_package/app/SimRT.exe'; Demo='tests/app/layout_results/portable_package' }
)) {
    $Exe = Join-Path $Workspace $Entry.Application
    $Demo = Join-Path $Workspace $Entry.Demo
    $BeforeLog = if (Test-Path -LiteralPath $StartupLog) { (Get-Item -LiteralPath $StartupLog).LastWriteTimeUtc } else { $null }
    $Process = Start-Process -FilePath $Exe -ArgumentList @('--demo-dir', ('"' + $Demo + '"')) -WorkingDirectory $Workspace -WindowStyle Hidden -PassThru
    try {
        $Deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            Start-Sleep -Milliseconds 200
            $Process.Refresh()
            if ($Process.HasExited) { throw "APP exited during startup: $($Process.ExitCode)" }
            $Title = [SimRTValidationWindow]::Title($Process.Id)
        } while ($Title -ne 'SimRT' -and [DateTime]::UtcNow -lt $Deadline)
        if ($Title -ne 'SimRT') { throw "APP window did not become ready: $Title" }
        Start-Sleep -Seconds 2
        $AfterLog = if (Test-Path -LiteralPath $StartupLog) { (Get-Item -LiteralPath $StartupLog).LastWriteTimeUtc } else { $null }
        if ($AfterLog -ne $BeforeLog) { throw 'APP wrote a new startup error log.' }
        $Records += [ordered]@{
            application=$Entry.Application
            demo=$Entry.Demo
            exe_sha256=(Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
            window_title=$Title
            startup_error=$false
        }
    }
    finally {
        if (-not $Process.HasExited) {
            [void]$Process.CloseMainWindow()
            if (-not $Process.WaitForExit(5000)) { $Process.Kill(); $Process.WaitForExit() }
        }
        $Process.Dispose()
    }
}
[ordered]@{passed=$true; hardware_test=$false; applications=$Records} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Output 'executable_startup.json') -Encoding UTF8
Write-Output 'Published and portable APP startup checks passed; only validation processes were closed.'
