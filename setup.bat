@echo off
rem setup.bat — one-click installer for FinanceOS.
rem Double-click before the first launch. Re-running is safe (idempotent).
rem
rem What it does:
rem   1. Confirms Python 3.11+ is installed and on PATH
rem   2. Creates a local .venv folder (skips if already present)
rem   3. Installs/updates dependencies from requirements.txt
rem
rem After this finishes successfully, launch the app via:
rem   launch.vbs  (silent, recommended for daily use)
rem   run.bat     (verbose with terminal, for debugging)

setlocal
cd /d "%~dp0"

echo ============================================
echo  FinanceOS - Setup
echo ============================================
echo.

rem --- Step 1: Python check -------------------------------------------------
where py >nul 2>&1
if errorlevel 1 (
    echo [X] ERROR: Python launcher 'py' not found.
    echo.
    echo Install Python 3.11 or newer from:
    echo     https://www.python.org/downloads/
    echo.
    echo During install, TICK "Add Python to PATH" — otherwise the
    echo command-line tools won't be available to this setup script.
    echo.
    pause
    exit /b 1
)
echo [1/3] Python launcher found.

rem --- Step 2: Virtual environment ----------------------------------------
if not exist ".venv\Scripts\activate.bat" (
    echo [2/3] Creating virtual environment in .venv\ ...
    py -m venv .venv
    if errorlevel 1 (
        echo [X] ERROR: Could not create virtual environment.
        echo This usually means the Python install is incomplete.
        pause
        exit /b 1
    )
) else (
    echo [2/3] Virtual environment already exists — skipping create.
)

rem --- Step 3: Dependencies -----------------------------------------------
echo [3/3] Installing dependencies from requirements.txt ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo [!] Warning: pip upgrade failed — continuing anyway.
)
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo [X] ERROR: Could not install dependencies.
    echo Check the messages above — usually means no internet, a corrupted
    echo pip cache, or a missing system dependency.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Setup complete.
echo ============================================
echo.
echo To LAUNCH the app:
echo     launch.vbs   ^(silent — recommended^)
echo     run.bat      ^(verbose with terminal — for debugging^)
echo.
echo To STOP the app later:
echo     stop.bat
echo.
echo For full documentation: open README.pdf or FinanceOS.md
echo.
pause
