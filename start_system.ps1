# ===================================================
#  [VIGIL-AI] Safe System Launcher (Auto-Clears Port 8000)
# ===================================================

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  [VIGIL-AI] Clearing Port 8000 & Launching System  " -ForegroundColor Cyan
Write-Host "===================================================" -ForegroundColor Cyan

# 1. Terminate any previous process holding port 8000
$portProcesses = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($portProcesses) {
    foreach ($procId in $portProcesses) {
        Write-Host "Terminating stale process on port 8000 (PID: $procId)..." -ForegroundColor Yellow
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
} else {
    Write-Host "Port 8000 is clear." -ForegroundColor Green
}

# 2. Launch Uvicorn server in the backend directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path (Join-Path $scriptDir "backend")
Write-Host "Starting VIGIL-AI server on http://0.0.0.0:8000 ..." -ForegroundColor Green

if (Get-Command conda -ErrorAction SilentlyContinue) {
    conda run -n agentic_ai_env python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
} else {
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
}
