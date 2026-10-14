param([switch]$NoBrowser, [ValidateRange(1,65535)][int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython) -or -not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Run setup.cmd first.' }
$taskListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($taskListener) { throw "Port $Port is in use. No process was stopped. Check it, or use the already running application." }
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot 'data\server.out.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data\server.err.log')
$taskProcess.Id | Set-Content -LiteralPath 'data\server.pid' -Encoding ascii
for ($taskAttempt=0; $taskAttempt -lt 60; $taskAttempt++) {
    if ($taskProcess.HasExited) { throw 'Server exited. Read data\server.err.log.' }
    try { $taskHealth=Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2; break } catch { Start-Sleep -Seconds 1 }
}
if (-not $taskHealth) { throw 'Server did not become reachable. Read data\server.err.log.' }
if (-not $NoBrowser) { Start-Process "http://localhost:$Port" }
Write-Host "Application started: http://localhost:$Port"
Write-Host 'The embedding model may take a moment to load. Run stop.cmd to stop this application.'
