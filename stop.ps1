$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath 'data\server.pid')) { Write-Host 'No app-managed process found.'; exit 0 }
$taskPid = [int](Get-Content -LiteralPath 'data\server.pid')
$taskServer = Get-CimInstance Win32_Process -Filter "ProcessId=$taskPid" -ErrorAction SilentlyContinue
if (-not $taskServer) { Write-Host 'Server has already stopped.'; exit 0 }
$taskExpectedPython = (Resolve-Path -LiteralPath '.venv\Scripts\python.exe').Path
if ($taskServer.CommandLine -notmatch 'uvicorn backend.app:app' -or $taskServer.CommandLine -notmatch [regex]::Escape($taskExpectedPython)) { throw 'PID no longer belongs to this app. Nothing was stopped.' }
$taskChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId=$taskPid" -ErrorAction SilentlyContinue
foreach ($taskChild in $taskChildren) {
    if ($taskChild.CommandLine -match 'uvicorn backend.app:app') {
        Stop-Process -Id $taskChild.ProcessId -ErrorAction SilentlyContinue
    }
}
Stop-Process -Id $taskPid -ErrorAction SilentlyContinue
Write-Host 'Local learning workspace stopped. Your data is preserved.'
