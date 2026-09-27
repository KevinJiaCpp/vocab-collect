param(
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $venvPython)) {
    if (-not $PythonExecutable) {
        $detected = Get-Command py -ErrorAction SilentlyContinue
        if ($detected) { $PythonExecutable = $detected.Source }
        else {
            $detected = Get-Command python -ErrorAction SilentlyContinue
            if ($detected) { $PythonExecutable = $detected.Source }
        }
    }
    if (-not $PythonExecutable) { throw 'Python 3.11+ is required. Pass -PythonExecutable with its full path.' }
    & $PythonExecutable -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
}

Push-Location (Join-Path $projectRoot 'backend')
try {
    & $venvPython -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Python package installation failed.' }
    & $venvPython -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'Application installation failed.' }
    & $venvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
} finally { Pop-Location }

Push-Location (Join-Path $projectRoot 'frontend')
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend package installation failed.' }
    & $venvPython (Join-Path $projectRoot 'scripts\generate_api_types.py')
    if ($LASTEXITCODE -ne 0) { throw 'API type generation failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }

& $venvPython (Join-Path $projectRoot 'scripts\bootstrap_data.py')
if ($LASTEXITCODE -ne 0) { Write-Warning 'Optional dictionary data could not be prepared. Retry bootstrap_data.py after network access is restored.' }
Write-Host 'Setup complete. Run scripts\run.ps1 to start Vocab Collect.'
