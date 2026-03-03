# PowerShell script om de Google Ads Tools server op de achtergrond te starten
# Start de server als een achtergrond proces

Write-Host "[START] Starting Google Ads Tools Web Interface in background..." -ForegroundColor Green

# Controleer of we in de juiste directory zijn
$projectDir = "C:\Users\Yuri\Documents\adwords-tool"
if (Test-Path $projectDir) {
    Set-Location $projectDir
    Write-Host "[INFO] Changed to project directory: $projectDir" -ForegroundColor Yellow
} else {
    Write-Host "[ERROR] Project directory not found: $projectDir" -ForegroundColor Red
    exit 1
}

# Controleer of Python beschikbaar is
try {
    $pythonVersion = py --version 2>&1
    Write-Host "[INFO] Python found: $pythonVersion" -ForegroundColor Yellow
    $pythonCmd = "py"
} catch {
    try {
        $pythonVersion = python --version 2>&1
        Write-Host "[INFO] Python found: $pythonVersion" -ForegroundColor Yellow
        $pythonCmd = "python"
    } catch {
        Write-Host "[ERROR] Python not found! Please install Python first." -ForegroundColor Red
        exit 1
    }
}

# Sla installatie-stap over (sneller starten, voorkomt psycopg2 build errors)
Write-Host "[INFO] Skipping pip install step" -ForegroundColor Yellow

# Start de server op de achtergrond
Write-Host "[INFO] Starting server on port 8080 in background..." -ForegroundColor Yellow
Write-Host "[URL] Open your browser and go to: http://localhost:8080" -ForegroundColor Green
Write-Host "[INFO] Server is running in background. Use 'Get-Process -Name python' to see running processes" -ForegroundColor Cyan
Write-Host "[STOP] Use 'Stop-Process -Name python' to stop all Python processes" -ForegroundColor Red

# Start de server als een achtergrond job
$job = Start-Job -ScriptBlock {
    param($pythonCmd, $projectDir)
    Set-Location $projectDir
    & $pythonCmd simple_web.py
} -ArgumentList $pythonCmd, $projectDir

Write-Host "[SUCCESS] Server started in background with Job ID: $($job.Id)" -ForegroundColor Green
Write-Host "[INFO] To check server status, run: Get-Job -Id $($job.Id)" -ForegroundColor Cyan
Write-Host "[INFO] To stop the server, run: Stop-Job -Id $($job.Id)" -ForegroundColor Red

# Wacht even om te controleren of de server succesvol is gestart
Start-Sleep -Seconds 3

# Controleer of de server draait
$serverProcess = Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object {$_.ProcessName -eq "python"}
if ($serverProcess) {
    Write-Host "[SUCCESS] Server is running! Process ID: $($serverProcess.Id)" -ForegroundColor Green
    Write-Host "[URL] 🌐 Open: http://localhost:8080" -ForegroundColor Green
} else {
    Write-Host "[WARNING] Server process not found. Check the job status." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== SERVER MANAGEMENT COMMANDS ===" -ForegroundColor Cyan
Write-Host "Check server status: Get-Job -Id $($job.Id)" -ForegroundColor White
Write-Host "View server output: Receive-Job -Id $($job.Id)" -ForegroundColor White
Write-Host "Stop server: Stop-Job -Id $($job.Id)" -ForegroundColor White
Write-Host "Remove job: Remove-Job -Id $($job.Id)" -ForegroundColor White
Write-Host "==================================" -ForegroundColor Cyan
