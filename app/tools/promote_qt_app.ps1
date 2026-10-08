param([string]$ReportDirectory = '', [string]$ValidationDirectory = '')
$ErrorActionPreference = 'Stop'
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$source = Join-Path $workspace 'app/qt_xcp_host/dist/SimRT'
$destination = Join-Path $workspace 'app/distribution'
if (-not $ReportDirectory) { throw 'Specify -ReportDirectory with a new workspace directory for the report and backup.' }
$report = [IO.Path]::GetFullPath($ReportDirectory)
if (-not $report.StartsWith($workspace + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The promotion report and backup must remain in the workspace.'
}
if (-not $ValidationDirectory) { throw 'Specify -ValidationDirectory containing the current APP test_report.json.' }
$tests = Get-Content -Raw -Encoding UTF8 (Join-Path $ValidationDirectory 'test_report.json') | ConvertFrom-Json
if (-not $tests.passed) { throw 'Qt regression tests did not pass.' }
foreach ($item in $tests.source_sha256.PSObject.Properties) {
    $base = if ($tests.source_path_base -eq 'workspace') { $workspace } else { Join-Path $workspace 'app/qt_xcp_host' }
    $path = Join-Path $base $item.Name
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item.Value) {
        throw "Source changed since verification: $($item.Name)"
    }
}
$build = Get-Content -Raw -Encoding UTF8 (Join-Path $source 'build_report.json') | ConvertFrom-Json
if ($build.application -ne 'SimRT.exe') { throw 'Expected the SimRT application build.' }
if ((Get-FileHash -LiteralPath (Join-Path $source $build.application) -Algorithm SHA256).Hash.ToLowerInvariant() -ne $build.exe_sha256) {
    throw 'Built EXE hash mismatch.'
}
$running = @(Get-Process QtXCPHost, SimRT -ErrorAction SilentlyContinue | Where-Object { $_.Path.StartsWith($workspace, [StringComparison]::OrdinalIgnoreCase) })
if ($running.Count) { throw 'Close the workspace Qt APP before promotion.' }
if (Test-Path -LiteralPath $report) { throw 'Choose a new promotion report directory.' }
New-Item -ItemType Directory -Path $report | Out-Null
$changes = @()
foreach ($file in Get-ChildItem -LiteralPath $source -File -Recurse) {
    $relative = $file.FullName.Substring($source.Length + 1)
    $target = Join-Path $destination $relative
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    $oldHash = if (Test-Path -LiteralPath $target -PathType Leaf) { (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash } else { '' }
    if ($oldHash -ne $hash) {
        if ($oldHash) {
            $backup = Join-Path (Join-Path $report 'previous_files') $relative
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
            Copy-Item -LiteralPath $target -Destination $backup
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $hash) { throw "Copy verification failed: $relative" }
        $changes += [ordered]@{ path=$relative; previous_sha256=$oldHash; sha256=$hash }
    }
}
$previousExecutable = Join-Path $destination 'QtXCPHost.exe'
if (Test-Path -LiteralPath $previousExecutable -PathType Leaf) {
    $backup = Join-Path $report 'previous_files/QtXCPHost.exe'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
    Move-Item -LiteralPath $previousExecutable -Destination $backup
}
[ordered]@{ passed=$true; application=$build.application; exe_sha256=$build.exe_sha256; changed_files=$changes; models_changed=$false } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $report 'promotion.json') -Encoding UTF8
Write-Output "Updated app/distribution: $($changes.Count) files."
