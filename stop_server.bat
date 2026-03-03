@echo off
echo [STOP] Stopping Google Ads Tools Web Interface...
echo.

echo [INFO] Looking for Python processes running simple_web.py...
tasklist /FI "IMAGENAME eq python.exe" /FO TABLE

echo.
echo [INFO] Stopping Python processes that might be running the server...
taskkill /F /IM python.exe 2>nul
if errorlevel 1 (
    echo [INFO] No Python processes found or already stopped.
) else (
    echo [SUCCESS] Python processes stopped.
)

echo.
echo [INFO] Checking if port 8080 is still in use...
netstat -ano | findstr :8080
if errorlevel 1 (
    echo [SUCCESS] Port 8080 is free.
) else (
    echo [WARNING] Port 8080 might still be in use. Check the output above.
)

echo.
echo [COMPLETE] Server stop attempt completed.
echo [INFO] Press any key to close this window...
pause >nul
