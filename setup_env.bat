@echo off
setlocal
cd /d "%~dp0"

echo Checking write access...
2>nul (
    > ".write_test.tmp" echo test
)
if not exist ".write_test.tmp" (
    echo This folder is not writable for the current user.
    echo Move XRD_Analysis_Toolkit to a user-writable folder, for example Documents, Desktop, or another personal workspace.
    echo Avoid Program Files unless you intentionally want to run setup as Administrator.
    pause
    exit /b 1
)
del ".write_test.tmp" >nul 2>nul

call :find_python
if errorlevel 1 (
    call :install_python
    if errorlevel 1 (
        echo Install Python 3.11+ from https://www.python.org/downloads/windows/
        pause
        exit /b 1
    )
    call :find_python
)

if errorlevel 1 (
    echo Python 3.11+ is installed but could not be launched from this setup script.
    echo Open a new Command Prompt and run setup_env.bat again.
    pause
    exit /b 1
)

echo Using Python: %PYTHON_CMD%

if not exist ".venv\Scripts\python.exe" (
    echo Creating shared Toolkit virtual environment at %CD%\.venv...
    %PYTHON_CMD% -m venv .venv
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

echo Creating Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$root=(Get-Location).Path; $desktop=[Environment]::GetFolderPath('Desktop'); $shortcutPath=Join-Path $desktop 'XRD Phase Finder.lnk'; $shell=New-Object -ComObject WScript.Shell; $shortcut=$shell.CreateShortcut($shortcutPath); $shortcut.TargetPath=Join-Path $root 'XRD_Finder\run_finder_silent.vbs'; $shortcut.WorkingDirectory=$root; $icon=Join-Path $root 'XRD_Finder\icon.ico'; if (Test-Path $icon) { $shortcut.IconLocation=$icon }; $shortcut.Description='Launch XRD Phase Finder without a console window'; $shortcut.Save()"
if errorlevel 1 echo Could not create Desktop shortcut. You can still run XRD_Finder\run_finder_silent.vbs manually.

echo.
echo Environment is ready.
echo Quiet launcher: XRD_Finder\run_finder_silent.vbs
echo Console launcher for diagnostics: XRD_Finder\run_finder.bat
echo Desktop shortcut: XRD Phase Finder
pause
exit /b 0

:find_python
set "PYTHON_CMD="
set "PYTHON_TEST=import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"

if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    "%LocalAppData%\Programs\Python\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set PYTHON_CMD="%LocalAppData%\Programs\Python\Python311\python.exe"
        exit /b 0
    )
)

if exist "%ProgramFiles%\Python311\python.exe" (
    "%ProgramFiles%\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set PYTHON_CMD="%ProgramFiles%\Python311\python.exe"
        exit /b 0
    )
)

if exist "%ProgramFiles(x86)%\Python311\python.exe" (
    "%ProgramFiles(x86)%\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set PYTHON_CMD="%ProgramFiles(x86)%\Python311\python.exe"
        exit /b 0
    )
)

py -3.11 -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)

python -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)

python3 -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python3"
    exit /b 0
)

exit /b 1

:install_python
echo Python 3.11+ was not found or could not be launched.
where winget >nul 2>nul
if errorlevel 1 goto install_python_direct

echo.
set /p INSTALL_PY=Install Python 3.11 with winget now? [Y/N]:
if /I not "%INSTALL_PY%"=="Y" exit /b 1

winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements
if not errorlevel 1 exit /b 0

echo winget install failed. Trying direct Python installer...
call :install_python_direct
exit /b %ERRORLEVEL%

:install_python_direct
set "PYTHON_INSTALLER_DIR=%LocalAppData%\XRD_Toolkit\downloads"
set "PYTHON_INSTALLER=%PYTHON_INSTALLER_DIR%\python-3.11.9-amd64.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
if not exist "%PYTHON_INSTALLER_DIR%" mkdir "%PYTHON_INSTALLER_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'"
if errorlevel 1 exit /b 1
if not exist "%PYTHON_INSTALLER%" exit /b 1

"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0 Shortcuts=0
if errorlevel 1 exit /b 1
exit /b 0

:failed
echo.
echo Environment setup failed.
pause
exit /b 1




