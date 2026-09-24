$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$workspaceDir = Split-Path -Parent $projectDir
$pythonExe = Join-Path $workspaceDir '.venv\Scripts\python.exe'
$backendDir = Join-Path $workspaceDir 'x280_linux_target\python'
$env:PYTHONPATH = $projectDir + [IO.Path]::PathSeparator + $backendDir

& $pythonExe -m unittest discover -s (Join-Path $projectDir 'service_tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Shared Qt service tests failed.' }

& $pythonExe -m unittest discover -s (Join-Path $backendDir 'tests') -v
if ($LASTEXITCODE -ne 0) { throw 'Shared XCP backend tests failed.' }

& $pythonExe (Join-Path $workspaceDir 'validation\pyxcp_02232\validate_pyxcp_02232.py')
if ($LASTEXITCODE -ne 0) { throw 'pyXCP loopback validation failed.' }

& $pythonExe -m compileall -q $projectDir $backendDir
if ($LASTEXITCODE -ne 0) { throw 'Python compile validation failed.' }

& $pythonExe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency validation failed.' }

Write-Host 'All shared Qt service validations passed.'
