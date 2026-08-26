@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "APP_ROOT=%~dp0.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"
set "SCI_ROOT=%LOCALAPPDATA%\Sci"
set "ENV_ROOT=%SCI_ROOT%\env"
set "PYTHON_EXE=%ENV_ROOT%\Scripts\python.exe"
set "BIN_ROOT=%SCI_ROOT%\bin"
set "LOG_ROOT=%SCI_ROOT%\logs\craft"
set "LOG_FILE=%LOG_ROOT%\setup.log"
set "REQ_FILE=%APP_ROOT%\toolkit\requirements-windows.txt"

if not exist "%SCI_ROOT%" mkdir "%SCI_ROOT%"
if not exist "%BIN_ROOT%" mkdir "%BIN_ROOT%"
if not exist "%LOG_ROOT%" mkdir "%LOG_ROOT%"
echo [%date% %time%] Starting CRAFT setup>"%LOG_FILE%"
echo Application root: %APP_ROOT%>>"%LOG_FILE%"
echo Shared environment: %ENV_ROOT%>>"%LOG_FILE%"

if exist "%ENV_ROOT%" (
    call :validate_existing_environment
    if errorlevel 1 goto existing_environment_failed
) else (
    call :ensure_base_python
    if errorlevel 1 goto python_failed
    echo Creating the shared Sci environment...
    echo Creating the shared Sci environment with %BASE_PYTHON%>>"%LOG_FILE%"
    "%BASE_PYTHON%" -m venv "%ENV_ROOT%" >>"%LOG_FILE%" 2>&1
    if errorlevel 1 goto failed
)

echo Updating Python packaging tools...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --progress-bar on --timeout 120 --retries 3 --prefer-binary --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

echo Installing CRAFT dependencies. Existing compatible packages will be kept.
echo Large packages such as VTK may take several minutes on a slow connection.
echo Detailed setup log: %LOG_FILE%
echo Installing CRAFT dependencies>>"%LOG_FILE%"
call :install_requirements
if errorlevel 1 goto failed

echo Registering CRAFT in the shared Sci environment...
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --progress-bar on --timeout 120 --retries 3 --prefer-binary --no-deps -e "%APP_ROOT%" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

echo Validating CRAFT runtime...
"%PYTHON_EXE%" -c "import gemmi, networkx, numpy, platformdirs, pymatgen, pyvista, pyvistaqt, PySide6, scipy, vtk; import crystal_viewer" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

>"%BIN_ROOT%\craft.cmd" echo @echo off
>>"%BIN_ROOT%\craft.cmd" echo call "%APP_ROOT%\run_viewer.bat" %%*
echo [%date% %time%] CRAFT setup complete>>"%LOG_FILE%"
echo The shared Sci environment is ready for CRAFT.
exit /b 0

:validate_existing_environment
if not exist "%PYTHON_EXE%" exit /b 1
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>>"%LOG_FILE%"
exit /b %ERRORLEVEL%

:install_requirements
if not exist "%REQ_FILE%" (
    echo Requirements file was not found: %REQ_FILE%
    echo Requirements file was not found: %REQ_FILE%>>"%LOG_FILE%"
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
"%PYTHON_EXE%" -c "import sys; from importlib.metadata import version; from packaging.requirements import Requirement; r=Requirement(sys.argv[1]); v=version(r.name); raise SystemExit(0 if (not r.specifier or r.specifier.contains(v, prereleases=True)) else 1)" "!REQ!" >nul 2>>"%LOG_FILE%"
if not errorlevel 1 (
    echo Keeping compatible package: !REQ!
    echo Keeping compatible package: !REQ!>>"%LOG_FILE%"
    exit /b 0
)

echo Installing package: !REQ!
echo Installing package: !REQ!>>"%LOG_FILE%"
set /a ATTEMPT=0
:requirement_retry
set /a ATTEMPT+=1
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --progress-bar on --timeout 120 --retries 3 --prefer-binary "!REQ!" >>"%LOG_FILE%" 2>&1
if not errorlevel 1 exit /b 0
if !ATTEMPT! LSS 3 (
    echo Download interrupted. Retrying !ATTEMPT! of 3...
    timeout /t 5 /nobreak >nul
    goto requirement_retry
)
exit /b 1

:ensure_base_python
call :find_base_python
if not errorlevel 1 exit /b 0
where winget >nul 2>nul
if errorlevel 1 exit /b 1
echo Python 3.11 is required and will now be installed.
echo Installing Python 3.11 with winget>>"%LOG_FILE%"
winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements >>"%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
call :find_base_python
exit /b %ERRORLEVEL%

:find_base_python
set "BASE_PYTHON="
for %%P in (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
) do if not defined BASE_PYTHON if exist "%%~P" (
    "%%~P" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
    if not errorlevel 1 set "BASE_PYTHON=%%~P"
)
if defined BASE_PYTHON exit /b 0
for /f "usebackq delims=" %%P in (`py -3.12 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
for /f "usebackq delims=" %%P in (`py -3.11 -c "import sys; print(sys.executable)" 2^>nul`) do if not defined BASE_PYTHON set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
exit /b 1

:existing_environment_failed
echo.
echo The existing shared Sci environment is not usable by CRAFT.
echo It was preserved and no files were removed.
echo Repair the environment, then run this installer again.
echo Details: %LOG_FILE%
echo [%date% %time%] Existing shared environment validation failed>>"%LOG_FILE%"
exit /b 1

:python_failed
echo.
echo Python 3.11 or 3.12 could not be installed or found.
echo Check the internet connection and Windows Package Manager, then try again.
echo Details: %LOG_FILE%
echo [%date% %time%] Compatible base Python was not found>>"%LOG_FILE%"
exit /b 1

:failed
echo.
echo CRAFT setup failed. The existing shared environment was not deleted.
echo Check the connection and retry. Details: %LOG_FILE%
echo [%date% %time%] CRAFT setup failed>>"%LOG_FILE%"
exit /b 1
