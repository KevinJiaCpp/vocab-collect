param(
    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8000,
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { throw 'Run scripts\setup.ps1 first.' }
Push-Location $projectRoot
try {
    $serverArguments = @('--host', $HostAddress, '--port', $Port)
    if ($Reload) { $serverArguments += '--reload' }
    & $venvPython (Join-Path $projectRoot 'backend\run_server.py') @serverArguments
    $serverExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $serverExitCode

