@echo off
setlocal
set "TOOLKIT_ROOT=%~dp0.."
cd /d "%TOOLKIT_ROOT%"
set "PYTHONPATH=%TOOLKIT_ROOT%\XRD_Finder;%PYTHONPATH%"

if not exist ".venv\Scripts\python.exe" (
    echo Shared Toolkit environment was not found.
    echo Run setup_env.bat from the XRD_Analysis_Toolkit root first.
    pause
    exit /b 1
)

call ".venv\Scripts\python.exe" -m xrd_finder.apps.finder_gui %*
endlocal
