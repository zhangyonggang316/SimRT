param(
    [string]$ManifestPath = ''
)

$ErrorActionPreference = 'Stop'
$archiveRoot = Split-Path -Parent $PSScriptRoot
if (-not $ManifestPath) {
    $ManifestPath = Join-Path $archiveRoot 'docs\archive_manifest_20260913.json'
}
$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ($manifest.format_version -ne 1 -or @($manifest.files).Count -eq 0) {
    throw 'Unsupported or empty archive manifest.'
}
$seen = @{}
$failures = @()
foreach ($entry in $manifest.files) {
    $relative = [string]$entry.path
    if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[/\\])\.\.([/\\]|$)' -or $relative.Contains(':')) {
        throw "Unsafe manifest path: $relative"
    }
    $target = [IO.Path]::GetFullPath((Join-Path $archiveRoot $relative))
    if (-not $target.StartsWith($archiveRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $seen.ContainsKey($target)) {
        throw "Invalid or duplicate manifest path: $relative"
    }
    $seen[$target] = $true
    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
        $failures += "Missing: $relative"
        continue
    }
    $item = Get-Item -LiteralPath $target
    if ($item.Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $entry.sha256) {
        $failures += "Changed: $relative"
    }
}
if ($failures.Count) {
    $failures | ForEach-Object { Write-Output $_ }
    throw "Archive verification failed for $($failures.Count) files."
}
Write-Output "Archive verified: $($manifest.files.Count) files."
