$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' } }
$taskRequirements = if (Test-Path -LiteralPath 'requirements.lock.txt') { 'requirements.lock.txt' } else { 'requirements.txt' }
& '.\.venv\Scripts\python.exe' -m pip install -r $taskRequirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& '.\.venv\Scripts\python.exe' prepare_data.py
if ($LASTEXITCODE -ne 0) { throw 'Knowledge preparation failed.' }
Push-Location -LiteralPath 'frontend'
try {
    if (Test-Path -LiteralPath 'package-lock.json') { npm.cmd ci --no-audit --no-fund } else { npm.cmd install --no-audit --no-fund }
    if ($LASTEXITCODE -ne 0) { throw 'Frontend installation failed.' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Host 'Setup complete. Fill .env locally, then run start.cmd.'
