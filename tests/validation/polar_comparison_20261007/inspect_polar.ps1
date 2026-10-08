param(
    [string]$Package = 'D:\CPO\P042\03matlabModel_0918V2\Data\PolarDriver_V3.2.2.1_Beta(R2022a~R2025b)\PolarDriver.mltbx'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($Package)
try {
    $names = @(
        'metadata/coreProperties.xml', 'metadata/systemRequirements.xml',
        'metadata/mwcorePropertiesReleaseInfo.xml',
        'fsroot/simulink/coder/rtwTargetInfo.m',
        'fsroot/simulink/coder/GY1005_make_rtw_hook.m',
        'fsroot/simulink/coder/rtw/GY1005.tlc',
        'fsroot/slblocks.m', 'fsroot/toolstrip/sl_customization.m'
    )
    $texts = @{}
    foreach ($name in $names) {
        $entry = $archive.GetEntry($name)
        if ($null -eq $entry) { throw "Missing archive entry: $name" }
        $reader = [IO.StreamReader]::new($entry.Open())
        try { $texts[$name] = $reader.ReadToEnd() } finally { $reader.Dispose() }
    }
    [xml]$properties = $texts['metadata/coreProperties.xml']
    [xml]$requirements = $texts['metadata/systemRequirements.xml']
    $hook = $texts['fsroot/simulink/coder/GY1005_make_rtw_hook.m']
    $filter = $texts['fsroot/toolstrip/sl_customization.m']
    $report = [ordered]@{
        package = $Package
        sha256 = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $Package).Length
        version = $properties.coreProperties.version
        release_start = $requirements.systemRequirements.releaseCompatibility.start
        release_end = $requirements.systemRequirements.releaseCompatibility.end
        entry_count = $archive.Entries.Count
        protected_p_files = @($archive.Entries | Where-Object { $_.FullName.EndsWith('.p') }).Count
        source_entries_reviewed = $names
        uses_toolchain_registry = $texts['fsroot/simulink/coder/rtwTargetInfo.m'].Contains('coder.make.ToolchainInfoRegistry')
        checks_model_before_codegen = $hook.Contains('checkModelFixedStep')
        uses_build_phases = ($hook.Contains('before_make') -and $hook.Contains('after_tlc'))
        uses_xenomai_libraries = ($hook.Contains('-lcobalt') -and $hook.Contains('-lalchemy'))
        gy1005_enables_avx512 = $hook.Contains('-mavx512f')
        has_unconditional_hardware_build_disable = ($filter.Contains('buildHardwareBoardAction2') -and $filter.Contains("state = 'Disabled'"))
        archive_installed_or_executed = $false
        protected_code_decompiled = $false
    }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'polar_inventory.json') -Encoding UTF8
    $report | ConvertTo-Json -Depth 5
} finally {
    $archive.Dispose()
}
