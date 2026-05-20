@echo off
rem stop.bat — fully stop FinanceOS, including any orphaned worker processes.
rem Two-pronged: kill anything on Streamlit's port AND kill any python.exe
rem whose executable lives inside this folder's .venv (safe — won't touch
rem Python processes from other projects).

setlocal enabledelayedexpansion
echo Stopping FinanceOS...
set found=0

rem Method 1 — kill whoever is listening on port 8501
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501 " ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
    if not errorlevel 1 (
        echo   Stopped PID %%a [port 8501]
        set found=1
    )
)

rem Method 2 — kill any python.exe still running from this venv (orphans)
powershell -NoProfile -Command ^
  "$root = '%~dp0.venv'; ^
   Get-Process | Where-Object { $_.Path -like \"$root*\" } | ForEach-Object { ^
     Write-Host ('  Stopped PID ' + $_.Id + ' [' + $_.Name + ' from venv]'); ^
     $_ | Stop-Process -Force ^
   }"

if "!found!"=="0" (
    echo   No process found on port 8501.
)

echo.
echo Done. You can close this window.
timeout /t 3 /nobreak >nul
