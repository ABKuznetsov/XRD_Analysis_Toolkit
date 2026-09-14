@echo off
setlocal EnableExtensions

set "SCI_ROOT=%LocalAppData%\Sci"
set "SCI_ENV=%SCI_ROOT%\env"
set "SCI_LOGS=%SCI_ROOT%\logs"
set "SCI_DOWNLOADS=%SCI_ROOT%\downloads"
set "SCI_PIP_CACHE=%SCI_ROOT%\pip-cache"
set "SCI_TEMP=%SCI_ROOT%\temp"
set "SCI_PYTHON=%SCI_ROOT%\python311\python.exe"
set "PYTHON_EXE=%SCI_ENV%\Scripts\python.exe"
set "LOG_FILE=%SCI_LOGS%\runtime_install.log"
set "PYTHON_TEST=import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)"
set "PYTHON_INSTALLER=%SCI_DOWNLOADS%\python-3.11.9-amd64.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
set "OPTIONAL_PACKAGES="
set "INSTALLER_REVISION=3-diagnostic"
set "FAILED_PACKAGE="

title XRD Phase Finder - Windows Runtime Installer

if not exist "%SCI_ROOT%" mkdir "%SCI_ROOT%"
if not exist "%SCI_LOGS%" mkdir "%SCI_LOGS%"
if not exist "%SCI_DOWNLOADS%" mkdir "%SCI_DOWNLOADS%"
if not exist "%SCI_PIP_CACHE%" mkdir "%SCI_PIP_CACHE%"
if not exist "%SCI_TEMP%" mkdir "%SCI_TEMP%"

set "PIP_CACHE_DIR=%SCI_PIP_CACHE%"
set "TMP=%SCI_TEMP%"
set "TEMP=%SCI_TEMP%"

echo [%date% %time%] Starting standalone runtime installation > "%LOG_FILE%"
echo.
echo ============================================================
echo   XRD Phase Finder - Windows Runtime Installer
echo   Revision %INSTALLER_REVISION%
echo ============================================================
echo.
echo This installer will prepare:
echo   %SCI_ENV%
echo.

call :check_windows
if errorlevel 1 goto failed

call :remove_incompatible_env
if errorlevel 1 goto failed

call :find_python
if errorlevel 1 (
    call :install_python
    if errorlevel 1 goto failed
    call :find_python
    if errorlevel 1 goto failed
)

echo Using Python: %PYTHON_CMD%
echo Using Python: %PYTHON_CMD%>> "%LOG_FILE%"

if not exist "%PYTHON_EXE%" (
    echo Creating shared Sci environment...
    echo Creating venv: %SCI_ENV%>> "%LOG_FILE%"
    call %PYTHON_CMD% -m venv "%SCI_ENV%" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto failed
)

if not exist "%PYTHON_EXE%" (
    echo Sci Python was not created: %PYTHON_EXE%>> "%LOG_FILE%"
    goto failed
)

echo Upgrading pip and build tools...
call "%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 90 --retries 3 --prefer-binary --upgrade pip setuptools wheel >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

echo Installing required scientific packages...
call :install_package "certifi"
if errorlevel 1 goto failed
call :install_package "cristma==0.1.0b9"
if errorlevel 1 goto failed
if errorlevel 1 goto failed
call :install_package "numpy"
if errorlevel 1 goto failed
call :install_package "packaging"
if errorlevel 1 goto failed
call :install_package "pybaselines"
if errorlevel 1 goto failed
call :install_package "pyqtgraph==0.14.0"
if errorlevel 1 goto failed
call :install_package "PySide6==6.7.3"
if errorlevel 1 goto failed
call :install_package "rfc8785==0.1.4"
if errorlevel 1 goto failed
call :install_package "scipy"
if errorlevel 1 goto failed
call :install_package "mp-api"
if errorlevel 1 goto failed
echo Validating installed packages...
call "%PYTHON_EXE%" -c "import certifi, cristma, inspect, mp_api, numpy, packaging, pybaselines, pyqtgraph, rfc8785, scipy, PySide6; from cristma.crystallography import resolve_space_group_setting; from cristma.diffraction import PowderPatternCalculator, PowderProfileCalculator; assert 'd_spacing_scale' in inspect.signature(PowderProfileCalculator.calculate).parameters; print('Runtime packages are ready')" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

if exist "%~dp0xrd_finder\apps\runtime_check.py" (
    echo Validating XRD Phase Finder imports...
    set "PYTHONPATH=%~dp0;%PYTHONPATH%"
    call "%PYTHON_EXE%" -m xrd_finder.apps.runtime_check --mode gui >> "%LOG_FILE%" 2>&1
    if errorlevel 1 goto failed
)

echo Materials Project support is included through mp-api.

echo.
echo ============================================================
echo   Installation completed successfully
echo ============================================================
echo.
echo Python:
echo   %PYTHON_EXE%
echo.
echo Log:
echo   %LOG_FILE%
echo.
pause
exit /b 0

:install_package
set "REQ=%~1"
echo   Installing %REQ%...
echo Installing required package: %REQ%>> "%LOG_FILE%"
call "%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --resume-retries 20 --prefer-binary --upgrade "%REQ%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo   Download interrupted. Retrying %REQ% in 15 seconds...
    echo Retrying required package after failure: %REQ%>> "%LOG_FILE%"
    timeout /t 15 /nobreak >nul
    call "%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --resume-retries 20 --prefer-binary --upgrade "%REQ%" >> "%LOG_FILE%" 2>&1
)
if errorlevel 1 (
    set "FAILED_PACKAGE=%REQ%"
    echo   ERROR: failed to install %REQ%.
    echo Failed required package: %REQ%>> "%LOG_FILE%"
    exit /b 1
)
echo   %REQ%: OK
exit /b 0

:install_optional_package
set "REQ=%~1"
echo   Installing optional %REQ%...
echo Installing optional package: %REQ%>> "%LOG_FILE%"
call "%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --resume-retries 20 --prefer-binary --upgrade "%REQ%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    echo   WARNING: optional %REQ% was not installed.
    echo Optional package failed: %REQ%>> "%LOG_FILE%"
) else (
    echo   %REQ%: OK
)
exit /b 0

:remove_incompatible_env
if not exist "%PYTHON_EXE%" exit /b 0
"%PYTHON_EXE%" -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 exit /b 0
echo Existing Sci environment is incompatible.
echo Removing it before clean installation:
echo   %SCI_ENV%
echo Removing incompatible environment: %SCI_ENV%>> "%LOG_FILE%"
rmdir /s /q "%SCI_ENV%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
if exist "%SCI_ENV%" exit /b 1
exit /b 0

:check_windows
ver | findstr /r /c:" 10\." >nul
if errorlevel 1 (
    echo XRD Phase Finder requires Windows 10 or Windows 11.
    echo Unsupported Windows version.>> "%LOG_FILE%"
    exit /b 1
)
exit /b 0

:find_python
set "PYTHON_CMD="
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%PYTHON_EXE%"""
        exit /b 0
    )
)
if exist "%SCI_PYTHON%" (
    "%SCI_PYTHON%" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%SCI_PYTHON%"""
        exit /b 0
    )
)
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%LocalAppData%\Programs\Python\Python312\python.exe"""
        exit /b 0
    )
)
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    "%LocalAppData%\Programs\Python\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%LocalAppData%\Programs\Python\Python311\python.exe"""
        exit /b 0
    )
)
if exist "%ProgramFiles%\Python312\python.exe" (
    "%ProgramFiles%\Python312\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%ProgramFiles%\Python312\python.exe"""
        exit /b 0
    )
)
if exist "%ProgramFiles%\Python311\python.exe" (
    "%ProgramFiles%\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%ProgramFiles%\Python311\python.exe"""
        exit /b 0
    )
)
py -3.12 -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.12"
    exit /b 0
)
py -3.11 -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)
exit /b 1

:install_python
echo Python 3.11 or 3.12 was not found.
echo Downloading Python 3.11.9...
echo Downloading Python 3.11.9 from python.org...>> "%LOG_FILE%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'" >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
if not exist "%PYTHON_INSTALLER%" exit /b 1

echo Installing Python 3.11.9 in:
echo   %SCI_ROOT%\python311
echo Installing managed Python: %SCI_ROOT%\python311>> "%LOG_FILE%"
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 TargetDir="%SCI_ROOT%\python311" PrependPath=0 Include_launcher=0 Include_pip=1 Include_tcltk=1 Include_test=0 Shortcuts=0 >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
if not exist "%SCI_PYTHON%" exit /b 1
exit /b 0

:failed
echo.
echo ============================================================
echo   Installation failed
echo ============================================================
echo.
if defined FAILED_PACKAGE echo Failed package: %FAILED_PACKAGE%
if defined FAILED_PACKAGE echo.
echo See log:
echo   %LOG_FILE%
echo.
echo Last installation messages:
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '%LOG_FILE%') { Get-Content -LiteralPath '%LOG_FILE%' -Tail 25 }"
echo.
pause
exit /b 1
