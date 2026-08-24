@echo off
setlocal

set "SCRIPT_DIR=%~dp0"

if exist "%SCRIPT_DIR%dist\WSLManager.exe" (
    start "" "%SCRIPT_DIR%dist\WSLManager.exe"
    exit /b 0
)

if exist "%SCRIPT_DIR%.venv\Scripts\pythonw.exe" (
    start "" "%SCRIPT_DIR%.venv\Scripts\pythonw.exe" "%SCRIPT_DIR%wslmgr.py"
    exit /b 0
)

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%SCRIPT_DIR%wslmgr.py"
    exit /b 0
)

echo Python 3 was not found. Install Python 3.10 or later, or build dist\WSLManager.exe.
pause
exit /b 1
