param(
    [switch]$Apply,
    [string]$ReportDirectory = ''
)
$ErrorActionPreference = 'Stop'
$WorkspaceRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd('\')
if (-not $ReportDirectory) {
    $ReportDirectory = Join-Path $WorkspaceRoot ('validation/project_cleanup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
}
$ReportDirectory = [IO.Path]::GetFullPath($ReportDirectory)
if (-not $ReportDirectory.StartsWith($WorkspaceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The cleanup report must stay inside the workspace.'
}
function Assert-WorkspacePath([string]$CandidatePath) {
    $Resolved = [IO.Path]::GetFullPath($CandidatePath)
    if (-not $Resolved.StartsWith($WorkspaceRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup path escaped the workspace: $Resolved"
    }
    $Cursor = Get-Item -LiteralPath $Resolved -Force
    while ($Cursor.FullName -ne $WorkspaceRoot) {
        if ($Cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to traverse a junction or symlink: $($Cursor.FullName)"
        }
        $Cursor = Get-Item -LiteralPath (Split-Path -Parent $Cursor.FullName) -Force
    }
    return $Resolved
}
$CandidatePaths = [Collections.Generic.List[string]]::new()
$FixedOutputs = @(
    'qt_xcp_host/build', 'qt_xcp_host/dist', 'qt_xcp_host/QtXCPHost.spec',
    'validation/app12_app13_20260919/staging_delivery',
    'validation/app12_app13_20260919/replaced_app_files',
    'validation/zip_app_20260919/staging_delivery',
    'validation/zip_app_20260919/replaced_app_files',
    'validation/model_delete_20260918/QtXCPHost.previous.exe',
    'slprj', 'x280_rt_single.slxc', 'tools/__pycache__', 'tools/tests/__pycache__'
)
foreach ($Relative in $FixedOutputs) {
    $Candidate = Join-Path $WorkspaceRoot $Relative
    if (Test-Path -LiteralPath $Candidate) { $CandidatePaths.Add((Assert-WorkspacePath $Candidate)) }
}
# Only conventional caches within project-owned trees are discovered automatically.
foreach ($Relative in @('qt_xcp_host', 'x280_linux_target', 'Demo_XCP_Qt/models', 'validation')) {
    Get-ChildItem -LiteralPath (Join-Path $WorkspaceRoot $Relative) -Recurse -Force | Where-Object {
        ($_.PSIsContainer -and $_.Name -in @('__pycache__', 'slprj')) -or
        (-not $_.PSIsContainer -and $_.Extension -eq '.slxc')
    } | ForEach-Object { $CandidatePaths.Add((Assert-WorkspacePath $_.FullName)) }
}
$Targets = [Collections.Generic.List[string]]::new()
foreach ($Candidate in ($CandidatePaths | Sort-Object Length, { $_ } -Unique)) {
    if (-not @($Targets | Where-Object { $Candidate.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) }).Count) {
        $Targets.Add($Candidate)
    }
}
foreach ($Target in $Targets) {
    if ($ReportDirectory -eq $Target -or $ReportDirectory.StartsWith($Target + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'A cleanup report cannot be written inside an output selected for removal.'
    }
    $Linked = @(Get-ChildItem -LiteralPath $Target -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    if ($Linked.Count) { throw "Cleanup target contains links: $Target" }
}
New-Item -ItemType Directory -Path $ReportDirectory -Force | Out-Null
$Files = @()
$Plan = foreach ($Target in $Targets) {
    $Item = Get-Item -LiteralPath $Target -Force
    $Children = if ($Item.PSIsContainer) { @(Get-ChildItem -LiteralPath $Target -File -Recurse -Force) } else { @($Item) }
    foreach ($File in $Children) {
        $Files += [ordered]@{ path=$File.FullName.Substring($WorkspaceRoot.Length + 1); bytes=$File.Length;
            sha256=(Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
    [ordered]@{ path=$Target.Substring($WorkspaceRoot.Length + 1); files=$Children.Count;
        bytes=($Children | Measure-Object Length -Sum).Sum }
}
$Plan = @($Plan)
ConvertTo-Json -InputObject @($Plan) -Depth 4 | Set-Content -LiteralPath (Join-Path $ReportDirectory 'cleanup_plan.json') -Encoding UTF8
ConvertTo-Json -InputObject @($Files) -Depth 4 | Set-Content -LiteralPath (Join-Path $ReportDirectory 'removed_files.json') -Encoding UTF8
$TotalBytes = ($Files | ForEach-Object { $_.bytes } | Measure-Object -Sum).Sum
$Summary = [ordered]@{ apply=[bool]$Apply; targets=$Targets.Count; files=$Files.Count; bytes=$TotalBytes;
    mib=[math]::Round($TotalBytes/1MB,2); protected_files=0; removed=@(); failed=@(); passed=$false }
if ($Apply) {
    $BuildProcesses = @(Get-Process -Name 'linux-gcc','linux-g++','linux-make','linux-ld','pyinstaller' -ErrorAction SilentlyContinue)
    if ($BuildProcesses.Count) { throw 'A build process is active; retry after it completes.' }
    $Protected = @{}
    foreach ($Relative in @('Demo_XCP_Qt', 'qt_xcp_host', 'x280_linux_target', 'tools')) {
        Get-ChildItem -LiteralPath (Join-Path $WorkspaceRoot $Relative) -File -Recurse -Force | Where-Object {
            $Path = $_.FullName
            $Owned = $Relative -eq 'Demo_XCP_Qt' -or $_.Extension -in @('.slx','.m','.py','.c','.cpp','.h','.dll','.zip','.ps1','.cmd')
            $Owned -and -not @($Targets | Where-Object { $Path -eq $_ -or $Path.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) }).Count
        } | ForEach-Object { $Protected[$_.FullName] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    }
    $Summary.protected_files = $Protected.Count
    foreach ($Target in $Targets) {
        $Resolved = Assert-WorkspacePath $Target
        try {
            Remove-Item -LiteralPath $Resolved -Recurse -Force
            $Summary.removed += $Resolved.Substring($WorkspaceRoot.Length + 1)
        }
        catch { $Summary.failed += [ordered]@{path=$Resolved; error=$_.Exception.Message} }
    }
    foreach ($Path in $Protected.Keys) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Protected[$Path]) {
            $Summary.failed += [ordered]@{path=$Path; error='Protected file missing or changed during cleanup'}
        }
    }
    $Summary.passed = $Summary.failed.Count -eq 0
}
$Summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $ReportDirectory 'cleanup_result.json') -Encoding UTF8
$Summary | ConvertTo-Json -Depth 5
if ($Summary.failed.Count) { throw 'Cleanup had failures. Inspect cleanup_result.json.' }
