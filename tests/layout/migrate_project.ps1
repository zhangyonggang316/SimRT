param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..')).TrimEnd('\')
$mapping = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'move_map.json') | ConvertFrom-Json
$records = [Collections.Generic.List[object]]::new()
function WorkspacePath([string]$relative) {
    $full = [IO.Path]::GetFullPath((Join-Path $root $relative))
    if (-not $full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes workspace: $full"
    }
    return $full
}
foreach ($pair in $mapping.moves) {
    $source = WorkspacePath $pair[0]
    $destination = WorkspacePath $pair[1]
    if (-not (Test-Path -LiteralPath $source)) { throw "Missing source: $source" }
    if (Test-Path -LiteralPath $destination) { throw "Destination already exists: $destination" }
    $item = Get-Item -LiteralPath $source -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing linked source: $source" }
}
foreach ($pair in $mapping.moves) {
    $source = WorkspacePath $pair[0]
    $destination = WorkspacePath $pair[1]
    $item = Get-Item -LiteralPath $source -Force
    $files = if ($item.PSIsContainer) { @(Get-ChildItem -LiteralPath $source -File -Recurse -Force) } else { @($item) }
    $record = [ordered]@{ source=$pair[0]; destination=$pair[1]; files=$files.Count;
        bytes=($files | Measure-Object -Property Length -Sum).Sum; moved=$false }
    if ($Apply) {
        $parent = Split-Path -Parent $destination
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Move-Item -LiteralPath $source -Destination $destination
        $record.moved = $true
    }
    $records.Add([pscustomobject]$record)
    ConvertTo-Json -InputObject @($records.ToArray()) -Depth 5 |
        Set-Content -LiteralPath (Join-Path $PSScriptRoot 'moves_completed.json') -Encoding UTF8
}
if ($Apply) {
    $emptyWrapper = WorkspacePath 'portable-linux-toolchain'
    if ((Test-Path -LiteralPath $emptyWrapper) -and -not (Get-ChildItem -LiteralPath $emptyWrapper -Force)) {
        Remove-Item -LiteralPath $emptyWrapper
    }
}
$records | Format-Table source,destination,files,moved -AutoSize
