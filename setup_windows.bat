@echo off
title Mikro Busway — First-Time Setup
color 0A
echo.
echo =============================================
echo   Mikro Busway Quotation Engine — Setup
echo =============================================
echo.

:: Check Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo ERROR: Python is not installed or not in PATH.
    echo.
    echo Please install Python 3.11 or newer from:
    echo   https://www.python.org/downloads/
    echo.
    echo IMPORTANT: During install, tick the box
    echo "Add Python to PATH" before clicking Install.
    echo.
    pause
    exit /b 1
)

echo [1/4] Python found:
python --version
echo.

:: Install dependencies
echo [2/4] Installing dependencies (this may take a minute)...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    color 0C
    echo ERROR: pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo.

:: Create data directories
echo [3/4] Creating data folders...
if not exist "data\price_list" mkdir "data\price_list"
if not exist "data\templates"  mkdir "data\templates"
if not exist "data\projects"   mkdir "data\projects"
echo.

:: Create .env if missing
if not exist ".env" (
    echo ANTHROPIC_API_KEY=> ".env"
    echo [4/4] Created .env file.
) else (
    echo [4/4] .env file already exists.
)
echo.

:: Seed database
python -m app.seed

echo.
color 0A
echo =============================================
echo   Setup complete!
echo   Now double-click  start_server.bat
echo =============================================
echo.
pause
