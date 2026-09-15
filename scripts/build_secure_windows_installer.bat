@echo off
setlocal EnableExtensions

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

cd /d "%ROOT%"
"%PYTHON%" -m xrd_finder.tools.secure_windows_package --app-root "%ROOT%" --output-dir "%ROOT%\dist\secure" %*
