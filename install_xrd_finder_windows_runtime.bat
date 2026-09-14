@echo off
setlocal EnableExtensions EnableDelayedExpansion

title XRD Phase Finder - Complete Windows Runtime

set "SCI_ROOT=%LocalAppData%\Sci"
set "SCI_ENV=%SCI_ROOT%\env"
set "SCI_LOGS=%SCI_ROOT%\logs"
set "SCI_PIP_CACHE=%SCI_ROOT%\pip-cache"
set "SCI_TEMP=%SCI_ROOT%\temp"
set "PYTHON_EXE=%SCI_ENV%\Scripts\python.exe"
set "LOG_FILE=%SCI_LOGS%\runtime_repair.log"
set "PYTHON_TEST=import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)"
set "FAILED_PACKAGES="
set "PACKAGE_INDEX=0"
set "PACKAGE_TOTAL=13"

if not exist "%SCI_ROOT%" mkdir "%SCI_ROOT%"
if not exist "%SCI_LOGS%" mkdir "%SCI_LOGS%"
if not exist "%SCI_PIP_CACHE%" mkdir "%SCI_PIP_CACHE%"
if not exist "%SCI_TEMP%" mkdir "%SCI_TEMP%"

set "PIP_CACHE_DIR=%SCI_PIP_CACHE%"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "TMP=%SCI_TEMP%"
set "TEMP=%SCI_TEMP%"

echo [%date% %time%] Starting complete runtime installation > "%LOG_FILE%"
echo.
echo ============================================================
echo   XRD Phase Finder - Complete Windows Runtime
echo ============================================================
echo.
echo Downloads are cached in:
echo   %SCI_PIP_CACHE%
echo.
echo Interrupted downloads will be resumed automatically.
echo Do not close this window. A slow connection can take a while.
echo.

call :prepare_python
if errorlevel 1 goto no_python

echo Using Python:
echo   %PYTHON_EXE%
echo Using Python: %PYTHON_EXE%>> "%LOG_FILE%"
echo.

echo Updating pip tools...
call :run_pip_tools
if errorlevel 1 (
    echo Failed to update pip tools. Retrying in 15 seconds...
    timeout /t 15 /nobreak >nul
    call :run_pip_tools
)
if errorlevel 1 goto pip_failed

echo.
echo Installing packages one at a time...
call :install_step "numpy"
call :install_step "packaging"
call :install_step "pybaselines"
call :install_step "pyqtgraph"
call :install_step "shiboken6==6.7.3"
call :install_step "PySide6-Essentials==6.7.3"
call :install_step "PySide6-Addons==6.7.3"
call :install_step "PySide6==6.7.3"
call :install_step "scipy"
call :install_step "certifi"
call :install_step "cristma==0.1.0b9"
call :install_step "rfc8785==0.1.4"
call :install_step "mp-api"

echo.
if defined FAILED_PACKAGES goto packages_failed

echo Validating the complete runtime...
call "%PYTHON_EXE%" -c "import certifi, cristma, mp_api, numpy, packaging, pybaselines, pyqtgraph, rfc8785, scipy, PySide6; from PySide6 import QtCore, QtGui, QtWidgets; print('Complete runtime is ready')" >> "%LOG_FILE%" 2>&1
if errorlevel 1 goto validation_failed

echo.
echo ============================================================
echo   Installation completed successfully
echo ============================================================
echo.
echo The XRD Phase Finder runtime is ready.
echo Log:
echo   %LOG_FILE%
echo.
pause
exit /b 0

:prepare_python
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "%PYTHON_TEST%" >nul 2>nul
    if not errorlevel 1 exit /b 0
)

set "BASE_PYTHON="
if exist "%SCI_ROOT%\python311\python.exe" set "BASE_PYTHON=%SCI_ROOT%\python311\python.exe"
if not defined BASE_PYTHON if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "BASE_PYTHON=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined BASE_PYTHON if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "BASE_PYTHON=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined BASE_PYTHON if exist "%ProgramFiles%\Python312\python.exe" set "BASE_PYTHON=%ProgramFiles%\Python312\python.exe"
if not defined BASE_PYTHON if exist "%ProgramFiles%\Python311\python.exe" set "BASE_PYTHON=%ProgramFiles%\Python311\python.exe"

if not defined BASE_PYTHON exit /b 1
"%BASE_PYTHON%" -c "%PYTHON_TEST%" >nul 2>nul
if errorlevel 1 exit /b 1

echo Creating shared Sci environment...
echo Creating environment with: %BASE_PYTHON%>> "%LOG_FILE%"
"%BASE_PYTHON%" -m venv "%SCI_ENV%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 exit /b 1
if not exist "%PYTHON_EXE%" exit /b 1
exit /b 0

:install_step
set "STEP_REQ=%~1"
set /a PACKAGE_INDEX+=1
echo.
echo [!PACKAGE_INDEX!/%PACKAGE_TOTAL%] Installing !STEP_REQ!
call :install_one "!STEP_REQ!"
if errorlevel 1 set "FAILED_PACKAGES=!FAILED_PACKAGES! !STEP_REQ!"
exit /b 0

:install_one
set "REQ=%~1"
echo Installing package: %REQ%>> "%LOG_FILE%"
if /I "%REQ%"=="PySide6-Addons==6.7.3" echo This is the largest Qt file, about 124 MB. Please wait.
if /I "%REQ%"=="mp-api" echo Installing Materials Project connector and its dependencies.

call :run_pip_package "%REQ%"
if not errorlevel 1 (
    echo %REQ%: OK
    exit /b 0
)

echo Download interrupted. Retry 2 of 3 in 15 seconds...
echo Retry 2 for package: %REQ%>> "%LOG_FILE%"
timeout /t 15 /nobreak >nul
call :run_pip_package "%REQ%"
if not errorlevel 1 (
    echo %REQ%: OK
    exit /b 0
)

echo Download interrupted. Retry 3 of 3 in 30 seconds...
echo Retry 3 for package: %REQ%>> "%LOG_FILE%"
timeout /t 30 /nobreak >nul
call :run_pip_package "%REQ%"
if not errorlevel 1 (
    echo %REQ%: OK
    exit /b 0
)

echo %REQ%: FAILED
echo Package failed after three attempts: %REQ%>> "%LOG_FILE%"
exit /b 1

:run_pip_tools
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%PYTHON_EXE%' -m pip install --progress-bar on --timeout 300 --retries 10 --upgrade pip setuptools wheel 2>&1 | Tee-Object -Variable pipOutput; $code=$LASTEXITCODE; $pipOutput | Out-File -LiteralPath '%LOG_FILE%' -Append -Encoding utf8; exit $code"
exit /b %ERRORLEVEL%

:run_pip_package
set "REQ=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%PYTHON_EXE%' -m pip install --progress-bar on --timeout 300 --retries 10 --resume-retries 30 --prefer-binary --upgrade '%REQ%' 2>&1 | Tee-Object -Variable pipOutput; $code=$LASTEXITCODE; $pipOutput | Out-File -LiteralPath '%LOG_FILE%' -Append -Encoding utf8; exit $code"
exit /b %ERRORLEVEL%

:show_log
echo.
echo Last installation messages:
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '%LOG_FILE%') { Get-Content -LiteralPath '%LOG_FILE%' -Tail 35 }"
echo.
echo Full log:
echo   %LOG_FILE%
echo.
exit /b 0

:no_python
echo ERROR: Python 3.11 or 3.12 was not found.
echo Run the main XRD Phase Finder installer first, then run this file again.
call :show_log
pause
exit /b 1

:pip_failed
echo ERROR: pip could not be updated.
call :show_log
pause
exit /b 1

:packages_failed
echo ============================================================
echo   Some packages could not be downloaded
echo ============================================================
echo.
echo Failed packages:
echo  %FAILED_PACKAGES%
echo.
echo Run this BAT again. Completed files remain in the cache.
call :show_log
pause
exit /b 1

:validation_failed
echo ERROR: packages were downloaded, but runtime validation failed.
call :show_log
pause
exit /b 1
