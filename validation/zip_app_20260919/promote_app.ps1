param([string]$RunDirectory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$WorkspaceDirectory = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$RunDirectory = (Resolve-Path -LiteralPath $RunDirectory).Path
$SourceDirectory = (Resolve-Path -LiteralPath (Join-Path $RunDirectory 'staging_delivery/app')).Path
$DestinationDirectory = (Resolve-Path -LiteralPath (Join-Path $WorkspaceDirectory 'Demo_XCP_Qt/app')).Path
$BackupDirectory = Join-Path $RunDirectory 'replaced_app_files'
foreach ($Directory in @($SourceDirectory, $DestinationDirectory, $BackupDirectory)) {
    if (-not [IO.Path]::GetFullPath($Directory).StartsWith($WorkspaceDirectory + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Application update path escaped the workspace.'
    }
}
if (Test-Path -LiteralPath $BackupDirectory) { throw 'This application update has already run.' }
$Running = @(Get-Process -Name QtXCPHost -ErrorAction SilentlyContinue)
if ($Running.Count) { throw 'Close the application before replacing its executable.' }
$Smoke = Get-Content -LiteralPath (Join-Path $RunDirectory 'packaged_startup.json') -Raw | ConvertFrom-Json
$SourceHash = (Get-FileHash -LiteralPath (Join-Path $SourceDirectory 'QtXCPHost.exe')).Hash.ToLowerInvariant()
if (-not $Smoke.passed -or $Smoke.executable_sha256 -ne $SourceHash) { throw 'The staged executable has not passed its startup check.' }
$SourceFiles = @(Get-ChildItem -LiteralPath $SourceDirectory -File -Recurse)
$RelativeFiles = @($SourceFiles | ForEach-Object { $_.FullName.Substring($SourceDirectory.Length + 1) })
$ExtraFiles = @(Get-ChildItem -LiteralPath $DestinationDirectory -File -Recurse | Where-Object {
    $_.FullName.Substring($DestinationDirectory.Length + 1) -notin $RelativeFiles
})
if ($ExtraFiles.Count) { throw 'Unexpected existing application files require review before replacement.' }
New-Item -ItemType Directory -Path $BackupDirectory | Out-Null
$Changed = @()
foreach ($File in $SourceFiles) {
    $Relative = $File.FullName.Substring($SourceDirectory.Length + 1)
    $Target = Join-Path $DestinationDirectory $Relative
    $ExpectedHash = (Get-FileHash -LiteralPath $File.FullName).Hash
    if ((Test-Path -LiteralPath $Target -PathType Leaf) -and (Get-FileHash -LiteralPath $Target).Hash -eq $ExpectedHash) { continue }
    if (Test-Path -LiteralPath $Target) {
        $Backup = Join-Path $BackupDirectory $Relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $Backup) -Force | Out-Null
        Copy-Item -LiteralPath $Target -Destination $Backup
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $Target) -Force | Out-Null
    Copy-Item -LiteralPath $File.FullName -Destination $Target -Force
    if ((Get-FileHash -LiteralPath $Target).Hash -ne $ExpectedHash) { throw "Application copy failed: $Relative" }
    $Changed += $Relative
}
foreach ($File in $SourceFiles) {
    $Relative = $File.FullName.Substring($SourceDirectory.Length + 1)
    if ((Get-FileHash -LiteralPath $File.FullName).Hash -ne (Get-FileHash -LiteralPath (Join-Path $DestinationDirectory $Relative)).Hash) {
        throw "Installed application differs from the verified stage: $Relative"
    }
}
$Report = [ordered]@{ passed = $true; changed_files = $Changed; verified_files = $SourceFiles.Count; executable_sha256 = $SourceHash }
$Report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $RunDirectory 'promotion_report.json') -Encoding UTF8
$Report | ConvertTo-Json
