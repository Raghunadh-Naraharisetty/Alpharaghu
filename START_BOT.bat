@echo off
title ALPHARAGHU Trading Bot
color 0A

echo.
echo ============================================================
echo    ALPHARAGHU - Algo Trading Bot
echo ============================================================
echo.

:: Change to the folder where this .bat file lives
cd /d "%~dp0"

:: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

:: Check .env exists
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and fill in your API keys.
    pause
    exit /b 1
)

:: Install/update requirements silently
echo [1/3] Checking requirements...
pip install -r requirements.txt -q --disable-pip-version-check

echo [2/3] Starting bot...
echo.
echo Bot is running. Press Ctrl+C to stop gracefully.
echo Telegram commands: /start /stop /status /positions /help
echo Dashboard: run "streamlit run dashboard.py" in another window
echo.
echo ============================================================

:: Run the bot — restart automatically if it crashes
:loop
python main.py
if errorlevel 1 (
    echo.
    echo [WARN] Bot crashed or stopped. Restarting in 10 seconds...
    echo Press Ctrl+C to cancel restart.
    timeout /t 10
    goto loop
)

echo.
echo Bot exited cleanly.
pause
