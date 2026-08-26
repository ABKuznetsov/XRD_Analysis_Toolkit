@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
set "ISCC="

for /f "delims=" %%I in ('where ISCC.exe 2^>nul') do if not defined ISCC set "ISCC=%%I"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo Inno Setup 6 was not found. Install it and run this script again.
    exit /b 1
)

"%ISCC%" "%SCRIPT_DIR%CRAFT.iss"
exit /b %ERRORLEVEL%
