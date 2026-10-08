$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceDir = Split-Path -Parent (Split-Path -Parent $projectDir)
$pythonExe = Join-Path $workspaceDir '.venv\Scripts\python.exe'
$backendDir = Join-Path $workspaceDir 'shared/python'
$env:PYTHONPATH = $projectDir + [IO.Path]::PathSeparator + $backendDir

& $pythonExe -m unittest discover -s (Join-Path $workspaceDir 'tests/app/services') -v
if ($LASTEXITCODE -ne 0) { throw 'Shared Qt service tests failed.' }

& $pythonExe -m unittest discover -s (Join-Path $workspaceDir 'tests/protocol') -v
if ($LASTEXITCODE -ne 0) { throw 'Shared XCP backend tests failed.' }

& $pythonExe (Join-Path $workspaceDir 'tests/validation/pyxcp_02232/validate_pyxcp_02232.py')
if ($LASTEXITCODE -ne 0) { throw 'pyXCP loopback validation failed.' }

& $pythonExe -m compileall -q $projectDir $backendDir
if ($LASTEXITCODE -ne 0) { throw 'Python compile validation failed.' }

& $pythonExe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency validation failed.' }

Write-Host 'All shared Qt service validations passed.'
