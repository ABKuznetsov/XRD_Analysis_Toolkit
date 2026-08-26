@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"
set "SCI_ROOT=%LOCALAPPDATA%\Sci"
set "ENV_ROOT=%SCI_ROOT%\env"
set "BIN_ROOT=%SCI_ROOT%\bin"
set "APP_DATA_ROOT=%SCI_ROOT%\apps\craft"
set "LOG_ROOT=%SCI_ROOT%\logs\craft"
set "LOG_FILE=%LOG_ROOT%\setup.log"

if not exist "%BIN_ROOT%" mkdir "%BIN_ROOT%"
if not exist "%APP_DATA_ROOT%" mkdir "%APP_DATA_ROOT%"
if not exist "%LOG_ROOT%" mkdir "%LOG_ROOT%"
echo [%date% %time%] Starting CRAFT setup>"%LOG_FILE%"

call :find_python
if errorlevel 1 call :install_python
if errorlevel 1 goto failed
call :find_python
if errorlevel 1 goto failed

if exist "%ENV_ROOT%\Scripts\python.exe" (
    "%ENV_ROOT%\Scripts\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo Repairing shared Sci environment...>>"%LOG_FILE%"
        %PYTHON_CMD% -m venv --upgrade "%ENV_ROOT%" >>"%LOG_FILE%" 2>&1
    )
) else (
    %PYTHON_CMD% -m venv "%ENV_ROOT%" >>"%LOG_FILE%" 2>&1
)
if errorlevel 1 goto failed

"%ENV_ROOT%\Scripts\python.exe" -m pip install --disable-pip-version-check --timeout 60 --retries 3 --prefer-binary --upgrade pip setuptools wheel >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto failed
echo Installing CRAFT dependencies. The VTK download is about 80 MB and can take several minutes.
echo Detailed setup log: %LOG_FILE%
echo Installing CRAFT dependencies>>"%LOG_FILE%"
"%ENV_ROOT%\Scripts\python.exe" -m pip install --disable-pip-version-check --progress-bar on --timeout 60 --retries 3 --prefer-binary -r "%APP_ROOT%\toolkit\requirements-windows.txt"
if errorlevel 1 goto failed
echo Registering CRAFT in the shared Sci environment...
"%ENV_ROOT%\Scripts\python.exe" -m pip install --disable-pip-version-check --no-deps -e "%APP_ROOT%" >>"%LOG_FILE%" 2>&1
if errorlevel 1 goto failed

>"%BIN_ROOT%\craft.cmd" echo @echo off
>>"%BIN_ROOT%\craft.cmd" echo call "%APP_ROOT%\run_viewer.bat" %%*
echo [%date% %time%] Setup complete>>"%LOG_FILE%"
echo Sci environment is ready for CRAFT.
exit /b 0

:find_python
set "PYTHON_CMD="
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=""%LOCALAPPDATA%\Programs\Python\Python311\python.exe"""& exit /b 0
)
if exist "%ProgramFiles%\Python311\python.exe" (
    "%ProgramFiles%\Python311\python.exe" -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] < (3,13) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=""%ProgramFiles%\Python311\python.exe"""& exit /b 0
)
py -3.11 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3.11"& exit /b 0
exit /b 1

:install_python
where winget >nul 2>nul
if errorlevel 1 exit /b 1
echo Installing Python 3.11 for the shared Sci runtime...
winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements >>"%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:failed
echo CRAFT setup failed. See %LOG_FILE%
echo [%date% %time%] Setup failed>>"%LOG_FILE%"
exit /b 1
