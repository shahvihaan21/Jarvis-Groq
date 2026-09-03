@echo off
REM ============================================================
REM  Jarvis AI - one-click local runner
REM  Usage: double-click run.bat  (or run it from a terminal)
REM ============================================================
setlocal
cd /d "%~dp0.."

REM --- Create virtualenv on first run ---
if not exist ".venv-deploy\Scripts\python.exe" (
    echo [Jarvis] Creating virtual environment...
    python -m venv .venv-deploy || goto :error
)

REM --- Install/refresh dependencies ---
echo [Jarvis] Checking dependencies...
".venv-deploy\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error

REM --- Load .env into this session ---
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" if not "%%a:~0,1%"=="#" set "%%a=%%b"
    )
) else (
    echo [Jarvis] WARNING: no .env found - copy .env.example to .env and add GROQ_API_KEY
)

REM --- Sanity check ---
if "%GROQ_API_KEY%"=="" (
    echo [Jarvis] ERROR: GROQ_API_KEY is not set. Put it in the .env file.
    pause
    exit /b 1
)

echo.
echo ================================================
echo   Jarvis AI starting on http://127.0.0.1:8000
echo   Press Ctrl+C to stop.
echo ================================================
echo.

".venv-deploy\Scripts\python.exe" backend\manage.py runserver 127.0.0.1:8000
goto :eof

:error
echo.
echo [Jarvis] Failed to start. See the message above.
pause
