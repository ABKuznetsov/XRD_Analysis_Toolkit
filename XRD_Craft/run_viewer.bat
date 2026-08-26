@echo off
setlocal
set "APP_ROOT=%~dp0"
set "SCI_PYTHON=%LOCALAPPDATA%\Sci\env\Scripts\pythonw.exe"

if not exist "%SCI_PYTHON%" (
    call "%APP_ROOT%toolkit\setup_sci_env.bat"
    if errorlevel 1 exit /b 1
)

set "PYTHONPATH=%APP_ROOT%src;%PYTHONPATH%"
set "QT_API=pyside6"
start "" /b "%SCI_PYTHON%" -m crystal_viewer.app %*

