$ErrorActionPreference = 'Stop'
$Workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$Source = [IO.Path]::GetFullPath((Join-Path $Workspace 'tests/linux/validate_tmux.py'))
$Destination = [IO.Path]::GetFullPath((Join-Path $Workspace 'linux/console/validate_tmux.py'))
foreach ($Candidate in @($Source, $Destination)) {
    if (-not $Candidate.StartsWith($Workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Console asset path escaped the workspace.'
    }
}
if (Test-Path -LiteralPath $Destination) { throw 'Console validation asset already exists.' }
Move-Item -LiteralPath $Source -Destination $Destination
