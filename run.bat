@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo Virtual environment not found.
    echo Run first-time setup from README.md, then try again.
    echo.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
streamlit run Dashboard.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
