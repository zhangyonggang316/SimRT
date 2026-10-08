param(
    [switch]$Apply,
    [switch]$IncludeStagedDeliveries,
    [string]$ReportDirectory = ''
)
$ErrorActionPreference = 'Stop'
$WorkspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..')).TrimEnd('\')
if (-not $ReportDirectory) {
    $ReportDirectory = Join-Path $WorkspaceRoot ('tests/validation/project_cleanup_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
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
    'app/qt_xcp_host/build', 'app/qt_xcp_host/dist', 'app/qt_xcp_host/QtXCPHost.spec',
    'tests/validation/app12_app13_20260919/staging_delivery',
    'tests/validation/app12_app13_20260919/replaced_app_files',
    'tests/validation/zip_app_20260919/staging_delivery',
    'tests/validation/zip_app_20260919/replaced_app_files',
    'tests/validation/model_delete_20260918/QtXCPHost.previous.exe',
    'slprj', 'simrt_rt_single.slxc', 'tests/tools/scripts/__pycache__', 'tests/tools/unit/__pycache__'
)
if ($IncludeStagedDeliveries) {
    # Keep the latest rollback copy; these are superseded build deliveries only.
    $StagedDeliveries = @(
        'app/qt_xcp_host/staging_delivery', 'app/qt_xcp_host/staging_ports_20261005',
        'app/qt_xcp_host/staging_5555_ui_20261005', 'app/qt_xcp_host/staging_5555_ui_final_20261005',
        'app/qt_xcp_host/staging_network_fix_20261005', 'app/qt_xcp_host/staging_network_refresh_20261005',
        'app/qt_xcp_host/staging_startup_20261005'
    )
    $ModelHashes = @{}
    Get-ChildItem -LiteralPath @((Join-Path $WorkspaceRoot 'demos/Demo_XCP_Qt/models'),
        (Join-Path $WorkspaceRoot 'tests/validation')) -Recurse -File |
        Where-Object { $_.Extension -in @('.slx','.zip') } | ForEach-Object {
            $ModelHashes[(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash] = $true
        }
    foreach ($Relative in $StagedDeliveries) {
        $Stage = Join-Path $WorkspaceRoot $Relative
        if (-not (Test-Path -LiteralPath $Stage)) { continue }
        $Stage = Assert-WorkspacePath $Stage
        $ModelFolders = @('models','validation') | ForEach-Object { Join-Path $Stage $_ } |
            Where-Object { Test-Path -LiteralPath $_ }
        $UniqueModels = @(foreach ($ModelFolder in $ModelFolders) { Get-ChildItem -LiteralPath $ModelFolder -Recurse -File |
            Where-Object { $_.Extension -in @('.slx','.zip') } | Where-Object {
                -not $ModelHashes.ContainsKey((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)
            } })
        if ($UniqueModels.Count) {
            throw "Staged delivery contains models absent from the canonical model tree: $Relative"
        }
        $FixedOutputs += $Relative
    }
    $FixedOutputs += @(
        'tests/validation/network_refresh_20261005_previous_app/app',
        'tests/validation/network_unaddressed_20261005_previous_app/app',
        'tests/validation/xcp_5555_ui_20261005_previous_app/app',
        'tests/validation/xcp_5555_ui_20261005_previous_app/pre_rollback_fix_app',
        'tests/validation/xcp_ports_20261005_previous_app/app'
    )
}
foreach ($Relative in $FixedOutputs) {
    $Candidate = Join-Path $WorkspaceRoot $Relative
    if (Test-Path -LiteralPath $Candidate) { $CandidatePaths.Add((Assert-WorkspacePath $Candidate)) }
}
# Only remove expanded payloads after verifying all three files against the retained ZIP.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$PayloadRoot = Join-Path $WorkspaceRoot 'demos/Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single_local'
if (Test-Path -LiteralPath $PayloadRoot) {
    foreach ($Folder in (Get-ChildItem -LiteralPath $PayloadRoot -Directory | Where-Object { $_.Name -match '^\d{8}_\d{6}_\d{3}$' })) {
        $Expanded = Assert-WorkspacePath $Folder.FullName
        $ZipPath = $Expanded + '.zip'
        if (-not (Test-Path -LiteralPath $ZipPath -PathType Leaf)) { continue }
        $ZipPath = Assert-WorkspacePath $ZipPath
        $Children = @(Get-ChildItem -LiteralPath $Expanded -Force)
        if ($Children.Count -ne 3 -or @($Children | Where-Object { $_.PSIsContainer }).Count) { continue }
        foreach ($Child in $Children) { $null = Assert-WorkspacePath $Child.FullName }
        $Zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            $Entries = @($Zip.Entries | Where-Object { $_.Name })
            $Matches = $Entries.Count -eq 3
            foreach ($Child in $Children) {
                $Entry = $Zip.GetEntry($Folder.Name + '/' + $Child.Name)
                if (-not $Entry -or $Entry.Length -ne $Child.Length) { $Matches = $false; break }
                $Stream = $Entry.Open()
                $Hasher = [Security.Cryptography.SHA256]::Create()
                try { $Hash = ([BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace('-', '') }
                finally { $Hasher.Dispose(); $Stream.Dispose() }
                if ($Hash -ne (Get-FileHash -LiteralPath $Child.FullName -Algorithm SHA256).Hash) { $Matches = $false; break }
            }
            if ($Matches) { $CandidatePaths.Add($Expanded) }
        }
        finally { $Zip.Dispose() }
    }
}
# Only conventional caches within project-owned trees are discovered automatically.
foreach ($Relative in @('app/qt_xcp_host', 'shared/python', 'toolchain/simrt_linux_target', 'demos', 'tests/validation')) {
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
    foreach ($Relative in @('app/distribution', 'demos', 'app/qt_xcp_host', 'shared/python', 'toolchain/simrt_linux_target', 'linux', 'tests/tools/scripts')) {
        Get-ChildItem -LiteralPath (Join-Path $WorkspaceRoot $Relative) -File -Recurse -Force | Where-Object {
            $Path = $_.FullName
            $Owned = $Relative -eq 'app/distribution' -or $Relative -eq 'demos' -or $_.Extension -in @('.slx','.m','.py','.c','.cpp','.h','.dll','.zip','.ps1','.cmd')
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
