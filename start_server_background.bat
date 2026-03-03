@echo off
echo [START] Starting Google Ads Tools Web Interface in background...
echo [INFO] Changing to project directory...
cd /d "C:\Users\Yuri\Documents\adwords-tool"
echo [INFO] Current directory: %CD%

echo [CHECK] Checking if Python is available...
py --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Trying alternatives...
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found! Please install Python first.
        pause
        exit /b 1
    ) else (
        echo [INFO] Using 'python' command
        set PYTHON_CMD=python
    )
) else (
    echo [INFO] Using 'py' command
    set PYTHON_CMD=py
)

echo [CHECK] Checking if requirements are installed...
if not exist "requirements.txt" (
    echo [WARNING] requirements.txt not found
) else (
    echo [INFO] Installing requirements...
    %PYTHON_CMD% -m pip install -r requirements.txt
)

echo [INFO] Starting server on port 8080 in background...
echo [URL] Open your browser and go to: http://localhost:8080
echo [INFO] Server will run in background. Close this window to continue.
echo.

REM Start the server in a new window
start "Google Ads Tools Server" %PYTHON_CMD% simple_web.py

echo [SUCCESS] Server started in background!
echo [INFO] The server window will open separately.
echo [URL] 🌐 Open: http://localhost:8080
echo.
echo [STOP] To stop the server, close the server window or use Task Manager.
echo [INFO] Press any key to close this window...
pause >nul
