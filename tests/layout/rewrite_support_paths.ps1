$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$utf8 = New-Object System.Text.UTF8Encoding($false)
$mapping = (Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot 'move_map.json') | ConvertFrom-Json).moves
$lookup = @{}
foreach ($pair in $mapping) { $lookup[$pair[0]] = $pair[1] }
$keys = @($lookup.Keys | Sort-Object Length -Descending)
$pattern = '(?<![A-Za-z0-9_/])(' + (($keys | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')(?=/|[''"\s]|$)'
$files = @(Get-ChildItem -LiteralPath (Join-Path $root 'linux/tools') -File -Filter *.py)
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'tests/tools/scripts') -File | Where-Object Extension -in @('.py','.m'))
$files += @(Get-ChildItem -LiteralPath (Join-Path $root 'tests/maintenance') -File | Where-Object Extension -in @('.py','.ps1'))
foreach ($file in $files) {
    $text = [IO.File]::ReadAllText($file.FullName)
    $updated = [regex]::Replace($text, $pattern, { param($m) $lookup[$m.Groups[1].Value] })
    if ($file.DirectoryName -eq (Join-Path $root 'linux/tools')) {
        $updated = $updated.Replace('Path(__file__).resolve().parents[1]', 'Path(__file__).resolve().parents[2]')
    } elseif ($file.DirectoryName -eq (Join-Path $root 'tests/tools/scripts')) {
        $updated = $updated.Replace('Path(__file__).resolve().parents[1]', 'Path(__file__).resolve().parents[3]')
        $updated = $updated.Replace("fileparts(fileparts(mfilename('fullpath')))", "fileparts(fileparts(fileparts(fileparts(mfilename('fullpath')))))")
    } elseif ($file.Extension -eq '.py') {
        $updated = $updated.Replace('Path(__file__).resolve().parents[1]', 'Path(__file__).resolve().parents[2]')
    }
    $updated = $updated.Replace("'toolchain/simrt_linux_target' / 'console'", "'linux' / 'console'")
    if ($updated -cne $text) { [IO.File]::WriteAllText($file.FullName, $updated, $utf8) }
}
foreach ($file in (Get-ChildItem -LiteralPath (Join-Path $root 'tests/tools/unit') -File -Filter *.py)) {
    $text = [IO.File]::ReadAllText($file.FullName)
    $updated = $text.Replace('Path(__file__).resolve().parents[1]))', "Path(__file__).resolve().parents[1] / 'scripts'))")
    $updated = $updated.Replace('ROOT = Path(__file__).resolve().parents[2]', 'ROOT = Path(__file__).resolve().parents[3]')
    $updated = $updated.Replace("ROOT / 'tools' / 'build_local_bundles.py'", "ROOT / 'toolchain' / 'tools' / 'build_local_bundles.py'")
    if ($updated -cne $text) { [IO.File]::WriteAllText($file.FullName, $updated, $utf8) }
}
