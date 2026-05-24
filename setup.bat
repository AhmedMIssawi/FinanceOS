@echo off
rem setup.bat — bulletproof one-click installer for FinanceOS.
rem
rem What it does, in order, with stop-on-error at every step:
rem   1. Detect Python 3.11+ (tries py -3, python, then py). If missing,
rem      auto-installs via winget (Windows Package Manager). If winget
rem      isn't available, prints clear manual-install instructions.
rem   2. Create the .venv virtual environment if not present.
rem   3. Upgrade pip inside the venv (quiet, ignored on failure).
rem   4. Install everything from requirements.txt, then verify the
rem      critical packages actually import.
rem
rem Re-running is safe — each step skips if already complete.
rem No paths are hardcoded; the script works wherever the FinanceOS
rem folder lives (USB stick, Documents, Desktop, etc.).

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo  FinanceOS - Setup
echo ============================================
echo.

rem ----------------------------------------------------------------------
rem Step 1: Find Python 3.11+
rem ----------------------------------------------------------------------
echo [1/4] Looking for Python 3.11 or newer...
set "PYTHON_CMD="

call :check_python "py -3" && goto :python_ok
call :check_python "python" && goto :python_ok
call :check_python "py" && goto :python_ok

echo   Python 3.11+ was not found on this system.
echo.
echo [1a] Attempting installation via winget (Windows Package Manager)...
where winget >nul 2>&1
if errorlevel 1 (
    echo   winget is not available on this Windows version.
    goto :manual_install
)

echo   Installing Python 3.12 silently (per-user, no admin required)...
echo   ^(This takes 1-3 minutes. Accept any UAC prompt that appears.^)
winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements --scope user
if errorlevel 1 (
    echo.
    echo   [X] winget install failed.
    goto :manual_install
)
echo.
echo   Python installed successfully.
echo.
echo   IMPORTANT: close this window and double-click setup.bat AGAIN.
echo   ^(Windows needs to reload its PATH so the new Python is visible.^)
echo.
pause
exit /b 0

:manual_install
echo.
echo  =========================================================
echo  [X] Python 3.11+ is required but not available.
echo  =========================================================
echo.
echo  Install it manually:
echo    1. Open https://www.python.org/downloads/
echo    2. Download Python 3.11 or newer
echo    3. Run the installer
echo    4. TICK ^"Add Python to PATH^" before clicking Install
echo    5. Re-run setup.bat after install completes
echo.
pause
exit /b 1

:python_ok
echo.

rem ----------------------------------------------------------------------
rem Step 2: Virtual environment
rem ----------------------------------------------------------------------
echo [2/4] Setting up virtual environment in .venv\ ...
if exist ".venv\Scripts\activate.bat" (
    echo   .venv already exists - skipping create.
) else (
    !PYTHON_CMD! -m venv .venv
    if errorlevel 1 (
        echo   [X] Could not create venv. Python install may be incomplete
        echo       ^(the 'venv' module is missing^). Try reinstalling Python.
        pause
        exit /b 1
    )
    echo   Created .venv successfully.
)
echo.

rem ----------------------------------------------------------------------
rem Step 3: pip upgrade
rem ----------------------------------------------------------------------
echo [3/4] Upgrading pip inside the venv...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo   [X] Could not activate .venv. Delete the .venv folder and re-run setup.
    pause
    exit /b 1
)
python -m pip install --upgrade pip --quiet --disable-pip-version-check >nul 2>&1
echo   pip is current.
echo.

rem ----------------------------------------------------------------------
rem Step 4: Install dependencies + verify
rem ----------------------------------------------------------------------
echo [4/4] Installing dependencies from requirements.txt...
echo   ^(First-time install takes 1-3 minutes; subsequent runs are quick^)
echo.
pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo.
    echo   [X] Dependency install failed. Common causes:
    echo     - No internet connection
    echo     - Corporate proxy / firewall blocking pypi.org
    echo     - Anti-virus blocking pip
    echo.
    echo   To diagnose, run this manually and read the full error:
    echo     .venv\Scripts\activate
    echo     pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo   Verifying installed packages import cleanly...
python -c "import streamlit; import sqlalchemy; import plotly; import pandas" >nul 2>&1
if errorlevel 1 (
    echo   [X] Verification failed - one or more packages broken.
    echo       Try: delete the .venv folder and re-run setup.bat
    pause
    exit /b 1
)
echo   All dependencies installed and verified.
echo.

rem ----------------------------------------------------------------------
rem Done
rem ----------------------------------------------------------------------
echo ============================================
echo  Setup complete!
echo ============================================
echo.
echo TO LAUNCH the app:
echo     launch.vbs   ^(silent — recommended for daily use^)
echo     run.bat      ^(visible terminal — for debugging^)
echo.
echo TO STOP the app:
echo     stop.bat
echo.
echo USER GUIDE:  README.pdf  or  FinanceOS.md
echo.
pause
exit /b 0


rem ======================================================================
rem Subroutine: :check_python "command"
rem
rem Probes whether the given command points to a Python 3.11+ interpreter.
rem If yes, sets PYTHON_CMD to that command and returns 0; otherwise
rem returns 1 so the caller can try the next candidate.
rem ======================================================================
:check_python
%~1 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
%~1 -c "import sys; print('  Found Python ' + sys.version.split()[0] + ' via %~1')"
set "PYTHON_CMD=%~1"
exit /b 0
