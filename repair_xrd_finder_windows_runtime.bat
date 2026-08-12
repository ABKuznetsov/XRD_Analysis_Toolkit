@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem XRD Phase Finder standalone Sci runtime repair tool.
rem Safe diagnostic modes:
rem   --describe
rem   --self-test-validator

set "SCRIPT_VERSION=1.0"
set "SCI_ROOT=%LocalAppData%\Sci"
set "SCI_ENV=%SCI_ROOT%\env"
set "SCI_LOGS=%SCI_ROOT%\logs"
set "SCI_LOCKS=%SCI_ROOT%\locks"
set "LOCK_DIR=%SCI_LOCKS%\xrd_runtime_repair.lock"
set "COMPLETE_FLAG=%SCI_ROOT%\runtime_complete.flag"
set "LOG_FILE=%SCI_LOGS%\runtime_repair.log"
set "PYTHON_EXE=%SCI_ENV%\Scripts\python.exe"
set "MAX_REPAIR_ATTEMPTS=2"
set "LOCK_ACQUIRED="

if /I "%~1"=="--describe" goto describe
if /I "%~1"=="--self-test-validator" goto self_test_validator
if not "%~1"=="" (
    echo Unknown option: %~1
    echo Use --describe or --self-test-validator, or run without arguments to repair.
    exit /b 2
)

call :prepare_folders
if errorlevel 1 exit /b 1

> "%LOG_FILE%" echo [%date% %time%] XRD Phase Finder runtime repair started
>> "%LOG_FILE%" echo Script version: %SCRIPT_VERSION%
>> "%LOG_FILE%" echo Sci root: %SCI_ROOT%
>> "%LOG_FILE%" echo Environment: %SCI_ENV%
>> "%LOG_FILE%" echo User: %USERNAME%
>> "%LOG_FILE%" echo Computer: %COMPUTERNAME%

echo XRD Phase Finder scientific runtime repair
echo Environment: %SCI_ENV%
echo Log: %LOG_FILE%
echo.

call :acquire_lock
if errorlevel 1 goto final_failure

if exist "%COMPLETE_FLAG%" del /q "%COMPLETE_FLAG%" >nul 2>> "%LOG_FILE%"

call :ensure_python_environment
if errorlevel 1 goto final_failure

set "WORK_DIR=%TEMP%\xrd_runtime_repair_%RANDOM%_%RANDOM%"
mkdir "%WORK_DIR%" >nul 2>> "%LOG_FILE%"
if errorlevel 1 (
    call :log_error "Could not create temporary folder: %WORK_DIR%"
    goto final_failure
)
set "REQ_FILE=%WORK_DIR%\requirements.txt"
set "VALIDATOR_FILE=%WORK_DIR%\validate_runtime.py"
set "VALIDATION_FILE=%WORK_DIR%\validation.txt"
call :write_requirements
if errorlevel 1 goto final_failure
call :write_validator "%VALIDATOR_FILE%"
if errorlevel 1 goto final_failure

echo [1/4] Upgrading pip and build tools...
>> "%LOG_FILE%" echo [%date% %time%] Upgrading pip, setuptools and wheel
"%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --prefer-binary --upgrade pip setuptools wheel >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log_error "pip bootstrap failed"
    goto final_failure
)

set "REPAIR_ATTEMPT=1"
:repair_attempt
echo [2/4] Installing all required packages, attempt !REPAIR_ATTEMPT! of %MAX_REPAIR_ATTEMPTS%...
>> "%LOG_FILE%" echo [%date% %time%] Installing complete requirement set, attempt !REPAIR_ATTEMPT!
if "!REPAIR_ATTEMPT!"=="1" (
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --resume-retries 30 --prefer-binary --upgrade --upgrade-strategy eager -r "%REQ_FILE%" >> "%LOG_FILE%" 2>&1
) else (
    "%PYTHON_EXE%" -m pip install --disable-pip-version-check --timeout 300 --retries 10 --resume-retries 30 --prefer-binary --upgrade --upgrade-strategy eager --force-reinstall --no-cache-dir -r "%REQ_FILE%" >> "%LOG_FILE%" 2>&1
)
if errorlevel 1 (
    call :log_error "pip installation failed on attempt !REPAIR_ATTEMPT!"
    if !REPAIR_ATTEMPT! LSS %MAX_REPAIR_ATTEMPTS% (
        set /a REPAIR_ATTEMPT+=1
        goto repair_attempt
    )
    goto final_failure
)

echo [3/4] Running package, import, numerical and Qt tests...
>> "%LOG_FILE%" echo [%date% %time%] Running full runtime validator
"%PYTHON_EXE%" "%VALIDATOR_FILE%" --requirements "%REQ_FILE%" > "%VALIDATION_FILE%" 2>&1
set "VALIDATION_EXIT=!ERRORLEVEL!"
type "%VALIDATION_FILE%" >> "%LOG_FILE%"

echo [4/4] Checking dependency consistency...
>> "%LOG_FILE%" echo [%date% %time%] Running pip check
"%PYTHON_EXE%" -m pip check >> "%LOG_FILE%" 2>&1
set "PIP_CHECK_EXIT=!ERRORLEVEL!"

if not "!VALIDATION_EXIT!"=="0" (
    call :log_error "runtime validator failed on attempt !REPAIR_ATTEMPT!"
    if !REPAIR_ATTEMPT! LSS %MAX_REPAIR_ATTEMPTS% (
        set /a REPAIR_ATTEMPT+=1
        goto repair_attempt
    )
    goto final_failure
)
if not "!PIP_CHECK_EXIT!"=="0" (
    call :log_error "pip check found incompatible packages on attempt !REPAIR_ATTEMPT!"
    if !REPAIR_ATTEMPT! LSS %MAX_REPAIR_ATTEMPTS% (
        set /a REPAIR_ATTEMPT+=1
        goto repair_attempt
    )
    goto final_failure
)

> "%COMPLETE_FLAG%" echo XRD_RUNTIME_READY
>> "%COMPLETE_FLAG%" echo repaired_at=%date% %time%
>> "%COMPLETE_FLAG%" echo script_version=%SCRIPT_VERSION%
"%PYTHON_EXE%" -c "import sys; print('python=' + sys.version.split()[0])" >> "%COMPLETE_FLAG%" 2>nul
"%PYTHON_EXE%" -c "import importlib.metadata as m; print('mp-api=' + m.version('mp-api')); print('pymatgen=' + m.version('pymatgen')); print('pandas=' + m.version('pandas'))" >> "%COMPLETE_FLAG%" 2>nul

>> "%LOG_FILE%" echo [%date% %time%] RUNTIME_REPAIR_COMPLETE
call :cleanup_work_dir
call :release_lock
echo.
echo Runtime repair completed successfully.
echo All required packages passed validation and pip check.
echo Log: %LOG_FILE%
exit /b 0

:final_failure
set "FINAL_EXIT=1"
call :cleanup_work_dir
call :release_lock
echo.
echo Runtime repair FAILED.
echo Last diagnostic messages:
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath $env:LOG_FILE) { Get-Content -LiteralPath $env:LOG_FILE -Tail 35 }"
echo.
echo Full log: %LOG_FILE%
echo Send this log when reporting the problem.
pause
exit /b %FINAL_EXIT%

:prepare_folders
if not exist "%SCI_ROOT%" mkdir "%SCI_ROOT%" >nul 2>nul
if not exist "%SCI_LOGS%" mkdir "%SCI_LOGS%" >nul 2>nul
if not exist "%SCI_LOCKS%" mkdir "%SCI_LOCKS%" >nul 2>nul
if not exist "%SCI_ROOT%" exit /b 1
if not exist "%SCI_LOGS%" exit /b 1
if not exist "%SCI_LOCKS%" exit /b 1
exit /b 0

:acquire_lock
2>nul mkdir "%LOCK_DIR%"
if not errorlevel 1 (
    set "LOCK_ACQUIRED=1"
    > "%LOCK_DIR%\owner.txt" echo started=%date% %time%
    >> "%LOCK_DIR%\owner.txt" echo computer=%COMPUTERNAME%
    >> "%LOCK_DIR%\owner.txt" echo user=%USERNAME%
    exit /b 0
)

echo Another runtime repair appears to be active. Waiting for it to finish...
>> "%LOG_FILE%" echo [%date% %time%] Repair lock already exists: %LOCK_DIR%
for /l %%N in (1,1,360) do (
    if not exist "%LOCK_DIR%" goto retry_lock
    timeout /t 5 /nobreak >nul
)
call :log_error "Timed out waiting for another repair process"
exit /b 1

:retry_lock
2>nul mkdir "%LOCK_DIR%"
if errorlevel 1 (
    call :log_error "Could not acquire repair lock after waiting"
    exit /b 1
)
set "LOCK_ACQUIRED=1"
> "%LOCK_DIR%\owner.txt" echo started=%date% %time%
>> "%LOCK_DIR%\owner.txt" echo computer=%COMPUTERNAME%
>> "%LOCK_DIR%\owner.txt" echo user=%USERNAME%
exit /b 0

:release_lock
if defined LOCK_ACQUIRED (
    if exist "%LOCK_DIR%" rmdir /s /q "%LOCK_DIR%" >nul 2>nul
    set "LOCK_ACQUIRED="
)
exit /b 0

:ensure_python_environment
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>> "%LOG_FILE%"
    if not errorlevel 1 (
        >> "%LOG_FILE%" echo Existing Sci Python is launchable; repairing it in place.
        "%PYTHON_EXE%" -c "import sys; print('Python executable: ' + sys.executable); print('Python version: ' + sys.version)" >> "%LOG_FILE%" 2>&1
        exit /b 0
    )
    echo Existing Sci environment is damaged. Recreating it...
    >> "%LOG_FILE%" echo Existing Sci Python could not be launched or has an unsupported version.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$target=$env:SCI_ENV; $expected=Join-Path $env:LOCALAPPDATA 'Sci\env'; if ([IO.Path]::GetFullPath($target) -ne [IO.Path]::GetFullPath($expected)) { throw 'Unsafe environment path' }; Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop" >> "%LOG_FILE%" 2>&1
    if errorlevel 1 (
        call :log_error "could not remove the damaged Sci environment"
        exit /b 1
    )
)

call :find_base_python
if errorlevel 1 (
    call :install_base_python
    if errorlevel 1 exit /b 1
    call :find_base_python
)
if errorlevel 1 (
    call :log_error "Python 3.11 or 3.12 could not be found after installation"
    exit /b 1
)

echo Creating shared Sci environment with %BASE_PYTHON%...
>> "%LOG_FILE%" echo Base Python: %BASE_PYTHON%
"%BASE_PYTHON%" -m venv "%SCI_ENV%" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log_error "venv creation failed"
    exit /b 1
)
if not exist "%PYTHON_EXE%" (
    call :log_error "venv did not create Scripts\python.exe"
    exit /b 1
)
"%PYTHON_EXE%" -c "import sys; print('Python executable: ' + sys.executable); print('Python version: ' + sys.version)" >> "%LOG_FILE%" 2>&1
exit /b %ERRORLEVEL%

:find_base_python
set "BASE_PYTHON="
if defined XRD_REPAIR_TEST_PYTHON if exist "%XRD_REPAIR_TEST_PYTHON%" (
    "%XRD_REPAIR_TEST_PYTHON%" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
    if not errorlevel 1 set "BASE_PYTHON=%XRD_REPAIR_TEST_PYTHON%"& exit /b 0
)
for %%P in ("%LocalAppData%\Programs\Python\Python311\python.exe" "%LocalAppData%\Programs\Python\Python312\python.exe" "%ProgramFiles%\Python311\python.exe" "%ProgramFiles%\Python312\python.exe") do (
    if exist "%%~P" (
        "%%~P" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
        if not errorlevel 1 set "BASE_PYTHON=%%~P"& exit /b 0
    )
)
for /f "usebackq delims=" %%P in (`py -3.11 -c "import sys; print(sys.executable)" 2^>nul`) do if exist "%%P" set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
for /f "usebackq delims=" %%P in (`py -3.12 -c "import sys; print(sys.executable)" 2^>nul`) do if exist "%%P" set "BASE_PYTHON=%%P"
if defined BASE_PYTHON exit /b 0
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$c=Get-Command python.exe -ErrorAction SilentlyContinue; if($c){$c.Source}" 2^>nul`) do if exist "%%P" set "BASE_PYTHON=%%P"
if defined BASE_PYTHON (
    "%BASE_PYTHON%" -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 13) else 1)" >nul 2>nul
    if not errorlevel 1 exit /b 0
)
set "BASE_PYTHON="
exit /b 1

:install_base_python
where winget.exe >nul 2>nul
if not errorlevel 1 (
    echo Python 3.11 was not found. Installing it with winget...
    >> "%LOG_FILE%" echo Installing Python 3.11 with winget.
    winget install --id Python.Python.3.11 -e --source winget --accept-package-agreements --accept-source-agreements >> "%LOG_FILE%" 2>&1
    if not errorlevel 1 exit /b 0
)

set "DOWNLOAD_DIR=%SCI_ROOT%\downloads"
set "PYTHON_INSTALLER=%DOWNLOAD_DIR%\python-3.11.9-amd64.exe"
set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
if not exist "%DOWNLOAD_DIR%" mkdir "%DOWNLOAD_DIR%" >nul 2>> "%LOG_FILE%"
echo Downloading Python 3.11.9 from python.org...
>> "%LOG_FILE%" echo Downloading %PYTHON_URL%
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri $env:PYTHON_URL -OutFile $env:PYTHON_INSTALLER" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log_error "Python installer download failed"
    exit /b 1
)
echo Installing Python 3.11.9 for the current user...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=1 Include_pip=1 Include_tcltk=1 Include_test=0 Shortcuts=0 >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log_error "Python installer failed"
    exit /b 1
)
exit /b 0

:write_requirements
> "%REQ_FILE%" echo gemmi
>> "%REQ_FILE%" echo numpy
>> "%REQ_FILE%" echo pybaselines
>> "%REQ_FILE%" echo pyqtgraph
>> "%REQ_FILE%" echo PySide6==6.7.3
>> "%REQ_FILE%" echo scipy
>> "%REQ_FILE%" echo certifi
>> "%REQ_FILE%" echo pandas^>=2,^<3
>> "%REQ_FILE%" echo mp-api
>> "%REQ_FILE%" echo pymatgen
if not exist "%REQ_FILE%" exit /b 1
exit /b 0

:write_validator
set "XRD_BAT_SELF=%~f0"
set "XRD_VALIDATOR_PATH=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$raw=[IO.File]::ReadAllText($env:XRD_BAT_SELF); $a='#<PYTHON_VALIDATOR>'; $b='#</PYTHON_VALIDATOR>'; $start=$raw.LastIndexOf($a); $finish=$raw.LastIndexOf($b); if($start -lt 0 -or $finish -le $start){throw 'Embedded validator markers are missing'}; $body=$raw.Substring($start+$a.Length,$finish-($start+$a.Length)).TrimStart([char]13,[char]10); [IO.File]::WriteAllText($env:XRD_VALIDATOR_PATH,$body,(New-Object Text.UTF8Encoding($false)))" >> "%LOG_FILE%" 2>&1
if errorlevel 1 (
    call :log_error "could not extract embedded validator"
    exit /b 1
)
exit /b 0

:cleanup_work_dir
if defined WORK_DIR if exist "%WORK_DIR%" rmdir /s /q "%WORK_DIR%" >nul 2>nul
exit /b 0

:log_error
echo ERROR: %~1
>> "%LOG_FILE%" echo [%date% %time%] ERROR: %~1
exit /b 0

:describe
echo XRD Phase Finder standalone runtime repair %SCRIPT_VERSION%
echo SCI_ENV=%%LocalAppData%%\Sci\env
echo MANDATORY=gemmi numpy pybaselines pyqtgraph PySide6==6.7.3 scipy certifi pandas^>=2,^<3 mp-api pymatgen
echo MAX_REPAIR_ATTEMPTS=%MAX_REPAIR_ATTEMPTS%
echo LOCK=%%LocalAppData%%\Sci\locks\xrd_runtime_repair.lock
echo COMPLETE=%%LocalAppData%%\Sci\runtime_complete.flag
echo LOG=%%LocalAppData%%\Sci\logs\runtime_repair.log
exit /b 0

:self_test_validator
call :find_base_python
if errorlevel 1 (
    echo VALIDATOR_SELF_TEST_FAILED: Python 3.11 or 3.12 was not found.
    exit /b 1
)
set "WORK_DIR=%TEMP%\xrd_validator_self_test_%RANDOM%_%RANDOM%"
mkdir "%WORK_DIR%" >nul 2>nul
if errorlevel 1 exit /b 1
set "LOG_FILE=%WORK_DIR%\extract.log"
set "VALIDATOR_FILE=%WORK_DIR%\validate_runtime.py"
call :write_validator "%VALIDATOR_FILE%"
if errorlevel 1 (
    call :cleanup_work_dir
    exit /b 1
)
"%BASE_PYTHON%" "%VALIDATOR_FILE%" --self-test
set "SELF_TEST_EXIT=%ERRORLEVEL%"
call :cleanup_work_dir
exit /b %SELF_TEST_EXIT%

rem The Python program below is extracted at runtime. Batch execution never reaches it.
exit /b 0

#<PYTHON_VALIDATOR>
from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import re
import sys
from pathlib import Path


MODULES = {
    "certifi": "certifi",
    "gemmi": "gemmi",
    "mp-api": "mp_api",
    "numpy": "numpy",
    "pandas": "pandas",
    "pybaselines": "pybaselines",
    "pymatgen": "pymatgen",
    "pyqtgraph": "pyqtgraph",
    "PySide6": "PySide6",
    "scipy": "scipy",
}


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def validate(requirements_path: Path) -> list[str]:
    failures: list[str] = []
    if not ((3, 11) <= sys.version_info[:2] < (3, 13)):
        failures.append(
            f"unsupported Python {sys.version.split()[0]}; expected 3.11 or 3.12"
        )
    if not requirements_path.is_file():
        return [f"requirements file is missing: {requirements_path}"]

    try:
        from packaging.requirements import Requirement
    except Exception as exc:
        return [f"packaging import failed: {type(exc).__name__}: {exc}"]

    requirements = []
    for raw_line in requirements_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            try:
                requirements.append(Requirement(line))
            except Exception as exc:
                failures.append(f"invalid requirement {line!r}: {exc}")

    missing: set[str] = set()
    for requirement in requirements:
        name = requirement.name
        try:
            version = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            failures.append(f"{name} is not installed")
            missing.add(normalized(name))
            continue
        if requirement.specifier and not requirement.specifier.contains(
            version, prereleases=True
        ):
            failures.append(
                f"{name} version mismatch: installed {version}, required {requirement.specifier}"
            )

    for package_name, module_name in MODULES.items():
        if normalized(package_name) in missing:
            continue
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            failures.append(
                f"{package_name} import failed: {type(exc).__name__}: {exc}"
            )

    if not failures:
        try:
            import numpy as np
            from scipy.optimize import nnls

            matrix = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=float)
            values, _ = nnls(matrix, np.asarray([1.0, 2.0], dtype=float))
            if not np.allclose(values, [1.0, 2.0]):
                failures.append("NumPy/SciPy numerical self-test returned invalid values")
        except Exception as exc:
            failures.append(
                f"NumPy/SciPy self-test failed: {type(exc).__name__}: {exc}"
            )

        try:
            from PySide6 import QtCore, QtGui, QtWidgets

            if not (QtCore and QtGui and QtWidgets):
                failures.append("PySide6 Qt modules are incomplete")
        except Exception as exc:
            failures.append(f"PySide6 Qt test failed: {type(exc).__name__}: {exc}")

    return failures


def self_test() -> int:
    sample = [
        "gemmi",
        "PySide6==6.7.3",
        "pandas>=2,<3",
        "mp-api",
        "pymatgen",
    ]
    names = []
    for line in sample:
        match = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if not match:
            print(f"VALIDATOR_SELF_TEST_FAILED: could not parse {line!r}")
            return 1
        names.append(normalized(match.group(1)))
    expected = ["gemmi", "pyside6", "pandas", "mp-api", "pymatgen"]
    if names != expected:
        print(f"VALIDATOR_SELF_TEST_FAILED: {names!r}")
        return 1
    compile(Path(__file__).read_text(encoding="utf-8"), str(Path(__file__)), "exec")
    print("VALIDATOR_SELF_TEST_OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.requirements is None:
        parser.error("--requirements is required")
    failures = validate(args.requirements)
    if failures:
        print("RUNTIME_VALIDATION_FAILED")
        print(f"Python: {sys.executable}")
        print(f"Version: {sys.version.split()[0]}")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("RUNTIME_VALIDATION_OK")
    print(f"Python: {sys.executable}")
    print(f"Version: {sys.version.split()[0]}")
    print(f"Validated packages: {len(MODULES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#</PYTHON_VALIDATOR>
