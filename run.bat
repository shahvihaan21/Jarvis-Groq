@echo off
title Starting Jarvis AI Server...
echo ========================================================
echo               STARTING JARVIS AI SERVER
echo ========================================================
echo.

cd /d "%~dp0"

:: 1. Check if virtual environment exists
if not exist "django\Scripts\python.exe" (
    echo [ERROR] Virtual environment 'django' not found!
    echo Please make sure the 'django' folder exists in the project root.
    pause
    exit /b
)

:: 2. Auto-run database migrations to ensure everything is ready
echo [*] Checking database migrations...
"django\Scripts\python.exe" "backend\manage.py" migrate --noinput
echo.

:: 3. Open browser automatically after a short 2-second delay
start "" powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8000/'"

:: 4. Start Django development server
echo [*] Starting server at http://127.0.0.1:8000/ ...
echo [*] Press Ctrl+C in this window to stop the server anytime.
echo.
"django\Scripts\python.exe" "backend\manage.py" runserver 127.0.0.1:8000

pause
