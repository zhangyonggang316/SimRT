param([string]$DestinationDirectory = '')
$ErrorActionPreference = 'Stop'
$WorkspaceDirectory = Split-Path -Parent $PSScriptRoot
if (-not $DestinationDirectory) { $DestinationDirectory = Join-Path $PSScriptRoot 'dist/QtXCPHost/third_party' }
$SitePackages = Join-Path $WorkspaceDirectory '.venv/Lib/site-packages'
New-Item -ItemType Directory -Path $DestinationDirectory -Force | Out-Null
foreach ($Distribution in Get-ChildItem -LiteralPath $SitePackages -Directory -Filter '*.dist-info') {
    foreach ($File in Get-ChildItem -LiteralPath $Distribution.FullName -File -Recurse) {
        $Relative = $File.FullName.Substring($Distribution.FullName.Length + 1)
        if ($File.Name -notmatch '^(LICENSE|LICENCE|COPYING|NOTICE|AUTHORS|METADATA)' -and $Relative -notmatch '^licenses[\\/]') { continue }
        $Destination = Join-Path $DestinationDirectory (Join-Path $Distribution.Name $Relative)
        New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force | Out-Null
        Copy-Item -LiteralPath $File.FullName -Destination $Destination -Force
    }
}
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'third_party') -File | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $DestinationDirectory -Force
}
