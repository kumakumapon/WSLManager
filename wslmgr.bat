@echo off
rem WSL Manager CLI launcher.
rem
rem Runs wslmgr_cli.py with every argument passed through and returns its exit code
rem unchanged (0 success, 1 error, 2 bad arguments, 3 cancelled, 4 WSL failure,
rem 5 partial failure), so it can be used from scripts.
rem
rem Python is looked up in this order: .venv, the Python Launcher (py -3), python.

setlocal
set "SCRIPT_DIR=%~dp0"
set "CLI=%SCRIPT_DIR%wslmgr_cli.py"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"

if exist "%VENV_PY%" goto run_venv
where py >nul 2>nul
if not errorlevel 1 goto run_py
where python >nul 2>nul
if not errorlevel 1 goto run_python
goto no_python

:run_venv
"%VENV_PY%" "%CLI%" %*
exit /b %ERRORLEVEL%

:run_py
py -3 "%CLI%" %*
exit /b %ERRORLEVEL%

:run_python
python "%CLI%" %*
exit /b %ERRORLEVEL%

:no_python
echo Python 3 was not found. Install Python 3.10 or later, or create .venv. 1>&2
exit /b 1
