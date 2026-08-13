@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "APP_ROOT=%~dp0.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"
set "SCI_ROOT=%LocalAppData%\Sci"
set "SCI_ENV=%SCI_ROOT%\env"
set "SCI_BIN=%SCI_ROOT%\bin"
set "SCI_LOGS=%SCI_ROOT%\logs"
set "LOG_FILE=%SCI_LOGS%\setup.log"
set "PYTHON_EXE=%SCI_ENV%\Scripts\python.exe"
set "RUNTIME_CHECK=%APP_ROOT%\toolkit\check_sci_runtime.py"
set "REQ_FILE=%APP_ROOT%\XRD_Finder\requirements.txt"
set "PYTHON_TEST=import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)"

if not exist "%SCI_ROOT%" mkdir "%SCI_ROOT%"
if not exist "%SCI_BIN%" mkdir "%SCI_BIN%"
if not exist "%SCI_LOGS%" mkdir "%SCI_LOGS%"

echo [%date% %time%] Starting Sci environment setup > "%LOG_FILE%"
echo Application root: %APP_ROOT%>> "%LOG_FILE%"
echo Sci root: %SCI_ROOT%>> "%LOG_FILE%"

call :remove_user_path "%LocalAppData%\XRD_Toolkit\bin"

call :check_windows_version
if errorlevel 1 exit /b 1

call :ensure_environment
if errorlevel 1 goto failed

echo Upgrading pip and build tools...
echo Upgrading pip and build tools...>> "%LOG_FILE%"
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --prefer-binary --upgrade pip setuptools wheel >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

echo Installing XRD Phase Finder requirements...
echo Installing XRD Phase Finder requirements...>> "%LOG_FILE%"
call :install_requirements "%REQ_FILE%"
if errorlevel 1 goto failed

echo Validating installed packages...
echo Validating installed packages...>> "%LOG_FILE%"
"%PYTHON_EXE%" "%RUNTIME_CHECK%" --requirements "%REQ_FILE%" --full >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto validation_failed
"%PYTHON_EXE%" -m pip check >> "%LOG_FILE%" 2>&1
if errorlevel 1 echo WARNING: pip check reported metadata or dependency warnings; runtime imports and numerical tests passed.>> "%LOG_FILE%"

echo Writing launchers...>> "%LOG_FILE%"
call :write_launchers
echo Updating user PATH...>> "%LOG_FILE%"
call :ensure_user_path "%SCI_BIN%"

echo [%date% %time%] Sci environment setup complete.>> "%LOG_FILE%"
echo Sci environment is ready.
exit /b 0

:install_requirements
set "REQ_FILE=%~1"
if not exist "%REQ_FILE%" (
    echo Requirements file was not found: %REQ_FILE%
    echo Requirements file was not found: %REQ_FILE%>> "%LOG_FILE%"
    exit /b 1
)
for /f "usebackq tokens=* delims=" %%P in ("%REQ_FILE%") do (
    set "REQ=%%P"
    if not "!REQ!"=="" if not "!REQ:~0,1!"=="#" (
        call :install_current_requirement
        if errorlevel 1 exit /b 1
    )
)
exit /b 0

:install_current_requirement
echo Installing package: !REQ!
echo Installing package: !REQ!>> "%LOG_FILE%"
if /I "!REQ:~0,7!"=="PySide6" (
    echo PySide6 is a large package. Downloading can take several minutes on a slow connection.
    echo PySide6 is a large package. Downloading can take several minutes on a slow connection.>> "%LOG_FILE%"
)
if /I "!REQ!"=="pymatgen" (
    echo pymatgen and its scientific dependencies can take several minutes.
    echo pymatgen and its scientific dependencies can take several minutes.>> "%LOG_FILE%"
)
set "INSTALL_ATTEMPT=1"
:install_current_retry
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --resume-retries 30 --prefer-binary "!REQ!" >> "%LOG_FILE%" 2>&1
if not errorlevel 1 exit /b 0
if !INSTALL_ATTEMPT! GEQ 3 (
    echo ERROR: failed to install !REQ! after three attempts.
    echo Failed to install package: !REQ!>> "%LOG_FILE%"
    exit /b 1
)
set /a INSTALL_ATTEMPT+=1
echo Retry !INSTALL_ATTEMPT! of 3 for !REQ! in 15 seconds...
echo Retry !INSTALL_ATTEMPT! of 3 for !REQ!>> "%LOG_FILE%"
timeout /t 15 /nobreak >nul
goto install_current_retry

:ensure_environment
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "%PYTHON_TEST%" >nul 2>> "%LOG_FILE%"
    if not errorlevel 1 (
        echo Existing Sci Python can be launched. Repairing packages in place.>> "%LOG_FILE%"
        exit /b 0
    )
    echo ERROR: Existing Sci Python cannot be launched or uses an unsupported version.
    echo Existing Sci environment was preserved and requires explicit repair: %SCI_ENV%>> "%LOG_FILE%"
    exit /b 1
)

call :find_python
if errorlevel 1 (
    call :install_python
    if errorlevel 1 (
        echo ERROR: Python 3.11 or 3.12 could not be installed.
        echo Python 3.11 or 3.12 not found.>> "%LOG_FILE%"
        exit /b 1
    )
    call :find_python
)
if errorlevel 1 (
    echo ERROR: Python was installed but could not be launched.
    echo Python launch failed after install.>> "%LOG_FILE%"
    exit /b 1
)

echo Using base Python: %PYTHON_CMD%
echo Using base Python: %PYTHON_CMD%>> "%LOG_FILE%"
echo Creating shared Sci environment...
echo Creating venv at %SCI_ENV%>> "%LOG_FILE%"
%PYTHON_CMD% -m venv "%SCI_ENV%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
if not exist "%PYTHON_EXE%" exit /b 1
"%PYTHON_EXE%" -c "%PYTHON_TEST%" >nul 2>> "%LOG_FILE%"
exit /b %ERRORLEVEL%

:write_launchers
> "%SCI_BIN%\xrd-finder.cmd" echo @echo off
>> "%SCI_BIN%\xrd-finder.cmd" echo set "APP_ROOT=%APP_ROOT%"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "SCI_APP_ROOT=%SCI_ROOT%\apps\xrd_phase_finder"
>> "%SCI_BIN%\xrd-finder.cmd" echo if not exist "%%SCI_APP_ROOT%%" mkdir "%%SCI_APP_ROOT%%"
>> "%SCI_BIN%\xrd-finder.cmd" echo if not exist "%%SCI_APP_ROOT%%\data" mkdir "%%SCI_APP_ROOT%%\data"
>> "%SCI_BIN%\xrd-finder.cmd" echo if not exist "%%SCI_APP_ROOT%%\matplotlib" mkdir "%%SCI_APP_ROOT%%\matplotlib"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "XRD_FINDER_DATA_DIR=%%SCI_APP_ROOT%%\data"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "MPLCONFIGDIR=%%SCI_APP_ROOT%%\matplotlib"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "PYTHONPATH=%%APP_ROOT%%\XRD_Finder;%%PYTHONPATH%%"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "QT_OPENGL=software"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "QT_QUICK_BACKEND=software"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "QT_ANGLE_PLATFORM=warp"
>> "%SCI_BIN%\xrd-finder.cmd" echo set "QT_QPA_PLATFORM=windows"
>> "%SCI_BIN%\xrd-finder.cmd" echo "%SCI_ENV%\Scripts\python.exe" -m xrd_finder.apps.finder_gui %%*
> "%SCI_BIN%\xrd-python.cmd" echo @echo off
>> "%SCI_BIN%\xrd-python.cmd" echo "%SCI_ENV%\Scripts\python.exe" %%*
exit /b 0

:ensure_user_path
set "BIN_PATH=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$bin=[Environment]::ExpandEnvironmentVariables('%BIN_PATH%'); $path=[Environment]::GetEnvironmentVariable('Path','User'); if (-not $path) { $path='' }; $parts=$path -split ';' | Where-Object { $_ }; if ($parts -notcontains $bin) { $new=($parts + $bin) -join ';'; [Environment]::SetEnvironmentVariable('Path',$new,'User') }" >> "%LOG_FILE%" 2>&1
exit /b 0

:remove_user_path
set "OLD_BIN_PATH=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$old=[Environment]::ExpandEnvironmentVariables('%OLD_BIN_PATH%'); $path=[Environment]::GetEnvironmentVariable('Path','User'); if ($path) { $parts=$path -split ';' | Where-Object { $_ -and ($_ -ine $old) }; [Environment]::SetEnvironmentVariable('Path',($parts -join ';'),'User') }" >> "%LOG_FILE%" 2>&1
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
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" (
    "%LocalAppData%\Programs\Python\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%LocalAppData%\Programs\Python\Python311\python.exe"""
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
if exist "%ProgramFiles%\Python311\python.exe" (
    "%ProgramFiles%\Python311\python.exe" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_CMD=""%ProgramFiles%\Python311\python.exe"""
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
py -3.11 -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.11"
    exit /b 0
)
py -3.12 -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py -3.12"
    exit /b 0
)
python -c "%PYTHON_TEST%" >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)
exit /b 1

:install_python
where winget >nul 2>nul
if errorlevel 1 goto install_python_direct
echo Python 3.11+ was not found. Installing with winget...
echo Installing Python 3.11 with winget...>> "%LOG_FILE%"
winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements >> "%LOG_FILE%" 2>&1
if not errorlevel 1 exit /b 0

echo winget Python install failed or is unavailable. Trying direct Python installer...>> "%LOG_FILE%"
call :install_python_direct
exit /b %ERRORLEVEL%

:install_python_direct
set "PYTHON_INSTALLER_DIR=%SCI_ROOT%\downloads"
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
echo Sci environment setup failed. See log: %LOG_FILE%
echo [%date% %time%] setup failed.>> "%LOG_FILE%"
call :show_failure_tail
exit /b 1

:validation_failed
echo ERROR: packages were installed, but the runtime self-test failed.
echo [%date% %time%] runtime validation failed.>> "%LOG_FILE%"
call :show_failure_tail
exit /b 1

:show_failure_tail
echo.
echo Last diagnostic messages:
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '%LOG_FILE%') { Get-Content -LiteralPath '%LOG_FILE%' -Tail 25 }"
echo.
echo Full log: %LOG_FILE%
exit /b 0












