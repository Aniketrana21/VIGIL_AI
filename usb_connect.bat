@echo off
echo =======================================================
echo   Connecting Phone via USB (ADB Reverse Port Forward)
echo =======================================================

set ADB="%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"

if not exist %ADB% (
    echo Error: adb.exe not found at %ADB%
    pause
    exit /b
)

echo Checking for connected phone...
%ADB% devices

echo.
echo Forwarding port 8000 over USB cable...
%ADB% reverse tcp:8000 tcp:8000

echo.
echo [SUCCESS] USB reverse tunnel established!
echo In the phone app, change Server URL to:
echo     http://localhost:8000
echo (or http://127.0.0.1:8000)
echo.
pause
