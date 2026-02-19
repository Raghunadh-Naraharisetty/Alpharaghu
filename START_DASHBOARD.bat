@echo off
title ALPHARAGHU Dashboard
color 0B

cd /d "%~dp0"

echo.
echo ============================================================
echo    ALPHARAGHU - Streamlit Dashboard
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

echo Installing streamlit if needed...
pip install streamlit -q --disable-pip-version-check

echo.
echo Opening dashboard at http://localhost:8501
echo.

streamlit run dashboard.py --server.headless false

pause
