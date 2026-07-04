@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher "py" was not found.
    echo Install Python 3.11+ from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating shared Toolkit virtual environment at %CD%\.venv...
    py -3.11 -m venv .venv
    if errorlevel 1 (
        echo Python 3.11 was not found. Trying default Python...
        py -m venv .venv
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Failed to create .venv.
    pause
    exit /b 1
)

echo Upgrading pip...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed

echo Installing XRD Toolkit requirements...
call ".venv\Scripts\python.exe" -m pip install -r "XRD_Finder\requirements.txt"
if errorlevel 1 goto failed

echo.
echo Environment is ready.
echo Run the app with XRD_Finder\run_finder.bat
pause
exit /b 0

:failed
echo.
echo Environment setup failed.
pause
exit /b 1
