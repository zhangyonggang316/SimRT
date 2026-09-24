param(
    [string]$OutputDirectory = '',
    [string]$BaselineDirectory = '',
    [string]$QtValidationDirectory = ''
)
$ErrorActionPreference = 'Stop'
$ProjectDirectory = $PSScriptRoot
$WorkspaceDirectory = Split-Path -Parent $ProjectDirectory
$PythonExecutable = Join-Path $WorkspaceDirectory '.venv/Scripts/python.exe'
if (-not $BaselineDirectory) { $BaselineDirectory = Join-Path $WorkspaceDirectory 'Demo_XCP_Qt' }
$BaselineDirectory = (Resolve-Path -LiteralPath $BaselineDirectory).Path
if (-not $OutputDirectory) {
    throw 'Specify -OutputDirectory with a new directory. Demo_XCP_Qt is the current delivery and model baseline; it must not be overwritten by packaging.'
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $OutputDirectory) {
    throw 'Output already exists. Choose a new staging directory; promote the verified result to Demo_XCP_Qt separately.'
}
if ($OutputDirectory.TrimEnd('\', '/') -eq $BaselineDirectory.TrimEnd('\', '/') -or
    $OutputDirectory.StartsWith($BaselineDirectory.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The Qt staging directory must be separate from the model baseline, not inside it.'
}
$ApplicationDirectory = Join-Path $ProjectDirectory 'dist/QtXCPHost'
foreach ($RelativePath in @('QtXCPHost.exe', '_internal/qt_host/native_bin/xcp_core.dll', 'build_report.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $ApplicationDirectory $RelativePath) -PathType Leaf)) {
        throw "Build the Qt application first; missing $RelativePath"
    }
}
foreach ($RelativePath in @('demo.json', 'models')) {
    if (-not (Test-Path -LiteralPath (Join-Path $BaselineDirectory $RelativePath))) {
        throw "The model baseline is incomplete: $RelativePath"
    }
}
$ModelDirectories = @(Get-ChildItem -LiteralPath (Join-Path $BaselineDirectory 'models') -Directory)
if ($ModelDirectories.Count -ne 1 -or $ModelDirectories[0].Name -ne 'x280_rt_single') {
    throw 'The delivery must contain only the x280_rt_single 1 ms model.'
}
$SelectionJSON = & $PythonExecutable -c "import json, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from pyxcp_host.demo import load_demo; from pyxcp_host.services.payload_archive import PayloadArchive; settings = load_demo(sys.argv[2]); archive = settings.payload_archive or Path(str(settings.payload_dir) + '.zip'); loader = PayloadArchive(); selected = loader.load(archive); print(json.dumps({'model': selected['model'], 'archive': str(archive)})); loader.close()" $ProjectDirectory $BaselineDirectory
if ($LASTEXITCODE -ne 0) { throw 'The selected demo payload failed integrity validation.' }
$Selected = $SelectionJSON | ConvertFrom-Json
$ModelDirectory = $ModelDirectories[0].FullName
if ($Selected.model -ne 'x280_rt_single' -or
    -not $Selected.archive.StartsWith($ModelDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The selected payload must belong to models/x280_rt_single.'
}
$SelectedArchive = $Selected.archive
$SelectedModelFiles = @((Join-Path $ModelDirectory 'x280_rt_single.slx'), $SelectedArchive)
foreach ($SelectedFile in $SelectedModelFiles) {
    if (-not (Test-Path -LiteralPath $SelectedFile -PathType Leaf)) { throw "Missing model artifact: $SelectedFile" }
}
if ($QtValidationDirectory) {
    $QtValidationDirectory = (Resolve-Path -LiteralPath $QtValidationDirectory).Path
    if (-not (Test-Path -LiteralPath (Join-Path $QtValidationDirectory 'test_report.json') -PathType Leaf)) {
        throw '-QtValidationDirectory must identify one Qt validation run containing test_report.json, not the parent validation directory.'
    }
    if (Test-Path -LiteralPath (Join-Path $QtValidationDirectory 'model_baseline') -PathType Container) {
        throw '-QtValidationDirectory must identify one Qt validation run, not a delivery validation tree.'
    }
}
& $PythonExecutable -c 'import sys; sys.path.insert(0, sys.argv[1]); from pyxcp_host.demo import load_demo; selected = load_demo(sys.argv[2]); print(selected.payload_archive or selected.payload_dir)' $ProjectDirectory $BaselineDirectory
if ($LASTEXITCODE -ne 0) { throw 'The model baseline preset or ELF/A2L integrity check failed.' }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
Copy-Item -LiteralPath $ApplicationDirectory -Destination (Join-Path $OutputDirectory 'app') -Recurse
$DemoConfig = Get-Content -LiteralPath (Join-Path $BaselineDirectory 'demo.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$ArchiveRelative = $SelectedArchive.Substring($BaselineDirectory.Length + 1).Replace('\', '/')
$DemoConfig | Add-Member -NotePropertyName archive -NotePropertyValue $ArchiveRelative -Force
$DemoConfig.PSObject.Properties.Remove('manifest')
$DemoConfig | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $OutputDirectory 'demo.json') -Encoding UTF8
$CopiedModelFiles = @()
# Only the selected build is distributable; generated sources and caches stay in the workspace.
foreach ($SelectedFile in $SelectedModelFiles) {
    $SourceFile = Get-Item -LiteralPath $SelectedFile
    $RelativePath = $SourceFile.FullName.Substring($BaselineDirectory.Length + 1)
    $DestinationFile = Join-Path $OutputDirectory $RelativePath
    New-Item -ItemType Directory -Path (Split-Path -Parent $DestinationFile) -Force | Out-Null
    $SourceHash = (Get-FileHash -LiteralPath $SourceFile.FullName -Algorithm SHA256).Hash
    Copy-Item -LiteralPath $SourceFile.FullName -Destination $DestinationFile
    $DestinationHash = (Get-FileHash -LiteralPath $DestinationFile -Algorithm SHA256).Hash
    if ($SourceHash -ne $DestinationHash) { throw "Model artifact changed during copy: $RelativePath" }
    $CopiedModelFiles += [ordered]@{
        path = $RelativePath.Replace('\', '/')
        bytes = $SourceFile.Length
        sha256 = $SourceHash.ToLowerInvariant()
    }
}
foreach ($Name in @('BUILD_TEST_1MS.md', 'SOLUTION_1MS.md', 'TOOLCHAIN.md')) {
    $BaselineFile = Join-Path $BaselineDirectory $Name
    if (Test-Path -LiteralPath $BaselineFile -PathType Leaf) { Copy-Item -LiteralPath $BaselineFile -Destination $OutputDirectory }
}
$ValidationDirectory = Join-Path $OutputDirectory 'validation'
New-Item -ItemType Directory -Path $ValidationDirectory | Out-Null
$BaselineEvidence = Join-Path $BaselineDirectory 'validation/model_baseline'
if (-not (Test-Path -LiteralPath $BaselineEvidence -PathType Container)) {
    $BaselineEvidence = Join-Path $BaselineDirectory 'validation'
}
if (Test-Path -LiteralPath $BaselineEvidence -PathType Container) {
    $EvidenceDestination = Join-Path $ValidationDirectory 'model_baseline'
    New-Item -ItemType Directory -Path $EvidenceDestination | Out-Null
    # Model evidence is a flat set; never copy a delivery's Qt/history subtrees recursively.
    Get-ChildItem -LiteralPath $BaselineEvidence -File | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $EvidenceDestination
    }
}
if ($QtValidationDirectory) {
    Copy-Item -LiteralPath $QtValidationDirectory -Destination (Join-Path $ValidationDirectory 'qt_ui') -Recurse
}
Copy-Item -LiteralPath (Join-Path $ProjectDirectory 'demo/START_DEMO.cmd'), (Join-Path $ProjectDirectory 'demo/README.md'), (Join-Path $ProjectDirectory 'demo/MANUAL_TEST.md') -Destination $OutputDirectory
& $PythonExecutable -c 'import sys; sys.path.insert(0, sys.argv[1]); from pyxcp_host.demo import load_demo; print(load_demo(sys.argv[2]).payload_archive)' $ProjectDirectory $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'The new Qt demo preset or ELF/A2L integrity check failed.' }
$PackageReport = [ordered]@{
    created_at = [DateTimeOffset]::Now.ToString('o')
    application = 'QtXCPHost.exe'
    model_integrity = 'all_copied_model_files_sha256_match_baseline'
    baseline_directory = $BaselineDirectory
    qt_runtime_evidence_included = [bool]$QtValidationDirectory
    baseline_validation_is_not_qt_validation = $true
    model_files = $CopiedModelFiles
}
$PackageReport | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'package_report.json') -Encoding UTF8
Write-Host "New Qt delivery: $OutputDirectory"
Write-Host "Unchanged model artifacts verified: $($CopiedModelFiles.Count)"
