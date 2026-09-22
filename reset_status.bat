@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" reset_status.py %*
) else (
    python reset_status.py %*
)

echo.
pause
