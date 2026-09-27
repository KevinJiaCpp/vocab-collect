param(
    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { throw 'Run scripts\setup.ps1 first.' }
Push-Location $projectRoot
try {
    & $venvPython -m uvicorn app.main:app --app-dir backend --host $HostAddress --port $Port
} finally { Pop-Location }

