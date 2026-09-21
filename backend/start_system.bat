@echo off
echo ===================================================
echo   [VIGIL-AI] Clearing Port 8000 and Starting Server
echo ===================================================

echo Clearing any lingering process on port 8000...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"
timeout /t 1 /nobreak >nul

echo Starting VIGIL-AI FastAPI backend on http://0.0.0.0:8000 ...

where conda >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    call conda run -n agentic_ai_env python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
) else (
    python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
)
pause
