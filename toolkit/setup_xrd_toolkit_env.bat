@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"
set "XRD_TOOLKIT_ROOT=%LocalAppData%\XRD_Toolkit"
set "XRD_TOOLKIT_ENV=%XRD_TOOLKIT_ROOT%\env"
set "XRD_TOOLKIT_BIN=%XRD_TOOLKIT_ROOT%\bin"
set "XRD_TOOLKIT_LOGS=%XRD_TOOLKIT_ROOT%\logs"
set "LOG_FILE=%XRD_TOOLKIT_LOGS%\setup.log"

if not exist "%XRD_TOOLKIT_ROOT%" mkdir "%XRD_TOOLKIT_ROOT%"
if not exist "%XRD_TOOLKIT_BIN%" mkdir "%XRD_TOOLKIT_BIN%"
if not exist "%XRD_TOOLKIT_LOGS%" mkdir "%XRD_TOOLKIT_LOGS%"

echo [%date% %time%] Starting XRD_Toolkit setup > "%LOG_FILE%"
echo Application root: %APP_ROOT%>> "%LOG_FILE%"
echo Toolkit root: %XRD_TOOLKIT_ROOT%>> "%LOG_FILE%"

call :check_windows_version
if errorlevel 1 exit /b 1

call :find_python
if errorlevel 1 (
    call :install_python
    if errorlevel 1 (
        echo Python 3.11+ is required. Install Python and run setup again.
        echo Python 3.11+ not found.>> "%LOG_FILE%"
        exit /b 1
    )
    call :find_python
)

if errorlevel 1 (
    echo Python 3.11+ is installed but could not be launched.
    echo Python launch failed after install.>> "%LOG_FILE%"
    exit /b 1
)

echo Using Python: %PYTHON_CMD%
echo Using Python: %PYTHON_CMD%>> "%LOG_FILE%"

if not exist "%XRD_TOOLKIT_ENV%\Scripts\python.exe" (
    echo Creating shared XRD_Toolkit environment...
    echo Creating venv at %XRD_TOOLKIT_ENV%>> "%LOG_FILE%"
    %PYTHON_CMD% -m venv "%XRD_TOOLKIT_ENV%" >> "%LOG_FILE%" 2>&1
)

if not exist "%XRD_TOOLKIT_ENV%\Scripts\python.exe" (
    echo Failed to create XRD_Toolkit environment.
    echo venv creation failed.>> "%LOG_FILE%"
    exit /b 1
)

echo Upgrading pip...
call "%XRD_TOOLKIT_ENV%\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

echo Installing XRD Phase Finder requirements...
call "%XRD_TOOLKIT_ENV%\Scripts\python.exe" -m pip install -r "%APP_ROOT%\XRD_Finder\requirements.txt" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

call :write_launchers
call :ensure_user_path "%XRD_TOOLKIT_BIN%"

echo [%date% %time%] XRD_Toolkit setup complete.>> "%LOG_FILE%"
echo XRD_Toolkit environment is ready.
exit /b 0

:write_launchers
> "%XRD_TOOLKIT_BIN%\xrd-finder.cmd" echo @echo off
>> "%XRD_TOOLKIT_BIN%\xrd-finder.cmd" echo set "APP_ROOT=%APP_ROOT%"
>> "%XRD_TOOLKIT_BIN%\xrd-finder.cmd" echo set "PYTHONPATH=%%APP_ROOT%%\XRD_Finder;%%PYTHONPATH%%"
>> "%XRD_TOOLKIT_BIN%\xrd-finder.cmd" echo "%XRD_TOOLKIT_ENV%\Scripts\python.exe" -m xrd_finder.apps.finder_gui %%*
> "%XRD_TOOLKIT_BIN%\xrd-python.cmd" echo @echo off
>> "%XRD_TOOLKIT_BIN%\xrd-python.cmd" echo "%XRD_TOOLKIT_ENV%\Scripts\python.exe" %%*
exit /b 0

:ensure_user_path
set "BIN_PATH=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$bin=[Environment]::ExpandEnvironmentVariables('%BIN_PATH%'); $path=[Environment]::GetEnvironmentVariable('Path','User'); if (-not $path) { $path='' }; $parts=$path -split ';' | Where-Object { $_ }; if ($parts -notcontains $bin) { $new=($parts + $bin) -join ';'; [Environment]::SetEnvironmentVariable('Path',$new,'User') }" >> "%LOG_FILE%" 2>&1
exit /b 0

:check_windows_version
ver | findstr /r /c:" 10\." >nul
if errorlevel 1 (
    echo XRD Phase Finder requires Windows 10 or Windows 11.
    echo Windows 7 and Windows 8 are not supported because the required Python runtime and scientific packages no longer support them.
    echo Unsupported Windows version.>> "%LOG_FILE%"
    exit /b 1
)
exit /b 0
:find_python
set "PYTHON_CMD="
set "PYTHON_TEST=import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    "%LocalAppData%\Programs\Python\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=""%LocalAppData%\Programs\Python\Python311\python.exe"""& exit /b 0
)
if exist "%ProgramFiles%\Python311\python.exe" (
    "%ProgramFiles%\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=""%ProgramFiles%\Python311\python.exe"""& exit /b 0
)
py -3.11 -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3.11"& exit /b 0
python -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"& exit /b 0
exit /b 1

:install_python
where winget >nul 2>nul
if errorlevel 1 goto install_python_direct
echo Python 3.11+ was not found. Installing with winget...
winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements >> "%LOG_FILE%" 2>&1
if not errorlevel 1 exit /b 0

echo winget Python install failed or is unavailable. Trying direct Python installer...>> "%LOG_FILE%"
call :install_python_direct
exit /b %ERRORLEVEL%

:install_python_direct
set "PYTHON_INSTALLER_DIR=%XRD_TOOLKIT_ROOT%\downloads"
set "PYTHON_INSTALLER=%PYTHON_INSTALLER_DIR%\python-3.11.9-amd64.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
if not exist "%PYTHON_INSTALLER_DIR%" mkdir "%PYTHON_INSTALLER_DIR%"

echo Downloading Python 3.11.9 from python.org...>> "%LOG_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'" >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
if not exist "%PYTHON_INSTALLER%" exit /b 1

echo Installing Python 3.11.9 for current user...>> "%LOG_FILE%"
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0 Shortcuts=0 >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:failed
echo XRD_Toolkit setup failed. See log: %LOG_FILE%
echo [%date% %time%] setup failed.>> "%LOG_FILE%"
exit /b 1




