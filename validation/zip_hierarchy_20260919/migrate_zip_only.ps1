$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$Roots = @(
    'Demo_XCP_Qt/models/x280_rt_single/x280_rt_single_local',
    'x280_linux_target/drivers/tc1013/models/x280_can_loopback/x280_can_loopback_local'
)
$Verified = @()
foreach ($RelativeRoot in $Roots) {
    $Root = (Resolve-Path -LiteralPath (Join-Path $Workspace $RelativeRoot)).Path
    if (-not $Root.StartsWith($Workspace + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Output root outside workspace.' }
    foreach ($Directory in @(Get-ChildItem -LiteralPath $Root -Directory)) {
        if ($Directory.Parent.FullName -ne $Root -or $Directory.Name -notmatch '^\d{8}_\d{6}_\d{3}$' -or
            ($Directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Unexpected result directory: $($Directory.FullName)" }
        $Files = @(Get-ChildItem -LiteralPath $Directory.FullName -Force)
        if ($Files.Count -ne 3 -or @($Files | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) }).Count) {
            throw "Result must contain exactly three regular files: $($Directory.FullName)"
        }
        $ManifestFiles = @($Files | Where-Object Name -Like '*.xcp-manifest.json')
        if ($ManifestFiles.Count -ne 1) { throw 'Expected one manifest.' }
        $Manifest = Get-Content -LiteralPath $ManifestFiles[0].FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $ExpectedNames = @(($Manifest.ModelName + '.elf'), ($Manifest.ModelName + '.a2l'), ($Manifest.ModelName + '.xcp-manifest.json'))
        if (@(Compare-Object ($Files.Name | Sort-Object) ($ExpectedNames | Sort-Object)).Count) { throw 'Unexpected artifact names.' }
        if ((Get-FileHash -LiteralPath (Join-Path $Directory.FullName $Manifest.ELFFile)).Hash.ToLowerInvariant() -ne $Manifest.ELFSHA256 -or
            (Get-FileHash -LiteralPath (Join-Path $Directory.FullName $Manifest.A2LFile)).Hash.ToLowerInvariant() -ne $Manifest.A2LSHA256) { throw 'Manifest hash mismatch.' }
        $ZipPath = $Directory.FullName + '.zip'
        $Zip = [IO.Compression.ZipFile]::OpenRead($ZipPath)
        try {
            if ($Zip.Entries.Count -ne 3) { throw 'Expected exactly three ZIP members.' }
            foreach ($File in $Files) {
                $Name = $Directory.Name + '/' + $File.Name
                $Entries = @($Zip.Entries | Where-Object { $_.FullName -ceq $Name })
                if ($Entries.Count -ne 1) { throw "ZIP does not contain exact member: $Name" }
                $Stream = $Entries[0].Open()
                $SHA = [Security.Cryptography.SHA256]::Create()
                try { $Hash = [BitConverter]::ToString($SHA.ComputeHash($Stream)).Replace('-', '').ToLowerInvariant() }
                finally { $SHA.Dispose(); $Stream.Dispose() }
                if ($Hash -ne (Get-FileHash -LiteralPath $File.FullName).Hash.ToLowerInvariant()) { throw "ZIP member differs: $Name" }
            }
        } finally { $Zip.Dispose() }
        $Verified += [ordered]@{directory=$Directory.FullName; archive=$ZipPath; archive_sha256=(Get-FileHash -LiteralPath $ZipPath).Hash.ToLowerInvariant(); removed=$false}
    }
}
$ReportFile = Join-Path $PSScriptRoot 'zip_only_migration.json'
$Verified | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportFile -Encoding UTF8
foreach ($Item in $Verified) {
    $ModelDirectory = Split-Path -Parent (Split-Path -Parent $Item.directory)
    $Model = Split-Path -Leaf $ModelDirectory
    $BuildDirectory = Join-Path $ModelDirectory ($Model + '_ert_rtw')
    $LatestReport = Join-Path $BuildDirectory 'x280_local_build.json'
    $EvidenceReport = Join-Path $BuildDirectory ('x280_build_evidence/' + (Split-Path -Leaf $Item.directory) + '/build_report.json')
    foreach ($ReportPath in @($LatestReport, $EvidenceReport)) {
        if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) { continue }
        $BuildReport = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($BuildReport.payload -ne $Item.directory) { continue }
        $BuildReport | Add-Member -NotePropertyName archive -NotePropertyValue $Item.archive -Force
        $BuildReport | Add-Member -NotePropertyName archive_sha256 -NotePropertyValue $Item.archive_sha256 -Force
        $BuildReport.payload = $Item.archive
        [IO.File]::WriteAllText($ReportPath, ($BuildReport | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
    }
    # All resolved targets are direct timestamp children of the two verified output roots.
    Remove-Item -LiteralPath $Item.directory -Recurse
    $Item.removed = -not (Test-Path -LiteralPath $Item.directory)
    $Verified | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportFile -Encoding UTF8
}
$Verified | Select-Object directory, removed | Format-Table -AutoSize
