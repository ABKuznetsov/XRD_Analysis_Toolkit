@echo off
setlocal EnableExtensions
set "APP_ROOT=%~dp0.."
for %%I in ("%APP_ROOT%") do set "APP_ROOT=%%~fI"
set "XRD_TOOLKIT_ROOT=%LocalAppData%\XRD_Toolkit"
set "XRD_TOOLKIT_ENV=%XRD_TOOLKIT_ROOT%\env"
set "XRD_FINDER_USER_ROOT=%XRD_TOOLKIT_ROOT%\XRD_Finder"
set "PYTHONW=%XRD_TOOLKIT_ENV%\Scripts\pythonw.exe"

call :check_windows_version
if errorlevel 1 (
    pause
    exit /b 1
)

if not exist "%PYTHONW%" (
    call "%APP_ROOT%\toolkit\setup_xrd_toolkit_env.bat"
    if errorlevel 1 (
        echo XRD_Toolkit environment setup failed.
        pause
        exit /b 1
    )
)

if not exist "%PYTHONW%" (
    echo XRD_Toolkit environment was not found.
    pause
    exit /b 1
)

if not exist "%XRD_FINDER_USER_ROOT%" mkdir "%XRD_FINDER_USER_ROOT%"
set "PYTHONDONTWRITEBYTECODE=1"
set "XRD_FINDER_DATA_DIR=%XRD_FINDER_USER_ROOT%\data"
set "MPLCONFIGDIR=%XRD_FINDER_USER_ROOT%\matplotlib"
set "PYTHONPATH=%APP_ROOT%\XRD_Finder;%PYTHONPATH%"
start "" "%PYTHONW%" -m xrd_finder.apps.finder_gui %*
endlocal
exit /b 0

:check_windows_version
ver | findstr /r /c:" 10\." >nul
if errorlevel 1 (
    echo XRD Phase Finder requires Windows 10 or Windows 11.
    echo Windows 7 and Windows 8 are not supported.
    exit /b 1
)
exit /b 0
