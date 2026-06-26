@echo off
title Mikro Busway — Quotation Engine
color 0A
echo.
echo =============================================
echo   Mikro Busway Quotation Engine
echo =============================================
echo.

:: Check .env exists and has a real API key
if not exist ".env" (
    color 0C
    echo ERROR: .env file not found.
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

findstr /C:"sk-ant-..." ".env" >nul
if %errorlevel% equ 0 (
    color 0E
    echo WARNING: Your .env file still has the placeholder API key.
    echo Open .env in Notepad and replace "sk-ant-..." with your real key.
    echo.
    pause
    exit /b 1
)

echo Starting server...
echo.
echo Open your browser and go to:
echo.
echo     http://localhost:8000
echo.
echo Keep this window open while you work.
echo Press Ctrl+C to stop the server.
echo.
echo =============================================
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000

pause
