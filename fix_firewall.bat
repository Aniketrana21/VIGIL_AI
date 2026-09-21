@echo off
:: Elevate script to Administrator if not already elevated
net session >nul 2>&1
if %errorlevel% NEQ 0 (
    echo Requesting Administrator privileges to open port 8000 in Windows Firewall...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo =======================================================
echo   Opening Port 8000 in Windows Firewall for VIGIL-AI
echo =======================================================

netsh advfirewall firewall delete rule name="VIGIL_AI_8000" >nul 2>&1
netsh advfirewall firewall add rule name="VIGIL_AI_8000" dir=in action=allow protocol=TCP localport=8000

echo.
echo [SUCCESS] Port 8000 is now allowed through Windows Firewall!
echo Your phone can now reach http://10.233.185.235:8000
echo.
pause
