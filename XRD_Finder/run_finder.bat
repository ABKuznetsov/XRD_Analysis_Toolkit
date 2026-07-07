@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"
set "XRD_TOOLKIT_ROOT=%LocalAppData%\XRD_Toolkit"
set "XRD_TOOLKIT_ENV=%XRD_TOOLKIT_ROOT%\env"
set "XRD_FINDER_USER_ROOT=%XRD_TOOLKIT_ROOT%\XRD_Finder"
set "PYTHON_EXE=%XRD_TOOLKIT_ENV%\Scripts\python.exe"
set "LOG_FILE=%XRD_TOOLKIT_ROOT%\logs\xrd_finder_console.log"

if not exist "%PYTHON_EXE%" (
    call "%APP_ROOT%\toolkit\setup_xrd_toolkit_env.bat"
    if errorlevel 1 (
        echo XRD_Toolkit environment setup failed.
        echo See log: %XRD_TOOLKIT_ROOT%\logs\setup.log
        pause
        exit /b 1
    )
)

if not exist "%PYTHON_EXE%" (
    echo XRD_Toolkit Python executable was not found:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

if not exist "%XRD_TOOLKIT_ROOT%\logs" mkdir "%XRD_TOOLKIT_ROOT%\logs"
if not exist "%XRD_FINDER_USER_ROOT%" mkdir "%XRD_FINDER_USER_ROOT%"
set "PYTHONDONTWRITEBYTECODE=1"
set "XRD_FINDER_DATA_DIR=%XRD_FINDER_USER_ROOT%\data"
set "MPLCONFIGDIR=%XRD_FINDER_USER_ROOT%\matplotlib"
set "QT_OPENGL=software"
set "QT_QUICK_BACKEND=software"
set "QT_ANGLE_PLATFORM=warp"
set "PYTHONPATH=%APP_ROOT%\XRD_Finder;%PYTHONPATH%"

echo Starting XRD Phase Finder with console diagnostics...
echo Log file: %LOG_FILE%
echo [%date% %time%] Starting XRD Phase Finder > "%LOG_FILE%"
call "%PYTHON_EXE%" -m xrd_finder.apps.finder_gui %* 1>> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo XRD Phase Finder exited with code %EXIT_CODE%.
    echo Last log lines:
    powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path '%LOG_FILE%') { Get-Content -LiteralPath '%LOG_FILE%' -Tail 30 }"
    pause
)
endlocal & exit /b %EXIT_CODE%