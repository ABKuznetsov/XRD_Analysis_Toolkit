from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib

from xrd_finder import __version__
from xrd_finder.services.cache_paths import default_data_root


APP_NAME = "XRD Phase Finder"
APP_ID = "{{7F3F4D7E-1E5B-4B54-B8B1-8C5D4F4A0101}"

EXCLUDED_NAMES = {
    ".DS_Store",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__MACOSX",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "updates",
}
EXCLUDED_SUFFIXES = {
    ".part",
    ".pyc",
    ".pyo",
    ".tmp",
}

ProgressCallback = Callable[[str], None]


def copy_secure_tree(source: str | Path, target: str | Path) -> None:
    source_path = Path(source).expanduser()
    target_path = Path(target).expanduser()
    if not source_path.exists():
        return
    if source_path.is_file():
        if _should_copy_path(source_path):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        return
    target_path.mkdir(parents=True, exist_ok=True)
    for child in source_path.iterdir():
        if not _should_copy_path(child):
            continue
        destination = target_path / child.name
        if child.is_dir():
            copy_secure_tree(child, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, destination)


def write_secure_mode_settings(data_root: str | Path) -> Path:
    settings_path = Path(data_root).expanduser() / "settings" / "security.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.update(
        {
            "schema": 1,
            "offline_mode": True,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "secure Windows installer",
        }
    )
    settings_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return settings_path


def build_secure_windows_installer(
    *,
    app_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    sci_root: str | Path | None = None,
    data_root: str | Path | None = None,
    version: str | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Secure Windows installer can be built only on Windows.")
    iscc = _find_inno_compiler()

    root = Path(app_root).expanduser().resolve() if app_root else _default_app_root()
    if not (root / "xrd_finder").is_dir() or not (root / "launcher").is_dir():
        raise RuntimeError(f"Application root does not look like XRD Phase Finder: {root}")

    build_version = version or _read_version(root)
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else root / "dist" / "secure"
    target_dir.mkdir(parents=True, exist_ok=True)

    stage_root = secure_stage_root(target_dir)
    app_stage = stage_root / "app"
    seed_root = stage_root / "seed"
    scripts_dir = stage_root / "scripts"
    iss_path = stage_root / "XRD_Phase_Finder_Secure_Windows.iss"
    setup_path = target_dir / f"XRD_Phase_Finder_Secure_Windows_{_safe_version(build_version)}.exe"

    _emit(progress, "Preparing secure Windows installer workspace")
    if stage_root.exists():
        shutil.rmtree(stage_root)
    app_stage.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)

    _prepare_app_payload(root, app_stage, progress)
    _prepare_secure_seed(
        seed_root,
        sci_root=Path(sci_root).expanduser() if sci_root else _default_sci_root(),
        data_root=Path(data_root).expanduser() if data_root else _default_data_root(),
        progress=progress,
    )
    _write_postinstall_script(scripts_dir / "apply_secure_windows_seed.ps1")

    _emit(progress, "Checking secure Windows installer payload")
    _assert_secure_payload(app_stage, seed_root, scripts_dir)

    write_secure_inno_script(
        iss_path,
        app_root=app_stage,
        seed_root=seed_root,
        output_dir=target_dir,
        version=build_version,
    )

    _emit(progress, "Building secure Windows installer")
    subprocess.run([str(iscc), str(iss_path)], check=True)
    if not setup_path.is_file():
        raise RuntimeError(f"Inno Setup did not create the expected installer: {setup_path}")
    _emit(progress, f"Created {setup_path}")
    return setup_path


def write_secure_inno_script(
    path: str | Path,
    *,
    app_root: str | Path,
    seed_root: str | Path,
    output_dir: str | Path,
    version: str,
) -> Path:
    script_path = Path(path)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    app_source = _inno_path(Path(app_root) / "*")
    sci_source = _inno_path(Path(seed_root) / "Sci" / "*")
    postinstall_source = _inno_path(script_path.parent / "scripts" / "apply_secure_windows_seed.ps1")
    output = _inno_path(Path(output_dir))
    safe_version = _safe_version(version)
    script_path.write_text(
        f'''#define MyAppName "{APP_NAME}"
#define MyAppVersion "{version}"
#define MyAppPublisher "ABKuznetsov"
#define MyAppURL "https://github.com/ABKuznetsov/XRD_Analysis_Toolkit"

[Setup]
AppId={APP_ID}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
AppPublisherURL={{#MyAppURL}}
AppSupportURL={{#MyAppURL}}
DefaultDirName={{autopf}}\\XRD Phase Finder
DefaultGroupName=XRD Phase Finder
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
OutputDir={output}
OutputBaseFilename=XRD_Phase_Finder_Secure_Windows_{safe_version}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={_inno_path(Path(app_root) / "icon.ico")}
UninstallDisplayIcon={{app}}\\icon.ico
VersionInfoVersion={{#MyAppVersion}}
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "{app_source}"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{sci_source}"; DestDir: "{{localappdata}}\\Sci"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{postinstall_source}"; DestDir: "{{tmp}}"; Flags: deleteafterinstall

[Icons]
Name: "{{group}}\\XRD Phase Finder"; Filename: "{{win}}\\System32\\wscript.exe"; Parameters: """{{app}}\\launch_xrd_finder_silent.vbs"""; WorkingDir: "{{app}}"; IconFilename: "{{app}}\\icon.ico"
Name: "{{group}}\\Uninstall XRD Phase Finder"; Filename: "{{uninstallexe}}"
Name: "{{autodesktop}}\\XRD Phase Finder"; Filename: "{{win}}\\System32\\wscript.exe"; Parameters: """{{app}}\\launch_xrd_finder_silent.vbs"""; WorkingDir: "{{app}}"; IconFilename: "{{app}}\\icon.ico"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "Software\\Classes\\.xpff"; ValueType: string; ValueName: ""; ValueData: "XRDPhaseFinder.Project"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\\Classes\\.xpff\\OpenWithProgids"; ValueType: string; ValueName: "XRDPhaseFinder.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\\Classes\\XRDPhaseFinder.Project"; ValueType: string; ValueName: ""; ValueData: "XRD Phase Finder File"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\\Classes\\XRDPhaseFinder.Project\\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{{app}}\\icon.ico,0"
Root: HKLM; Subkey: "Software\\Classes\\XRDPhaseFinder.Project\\shell\\open\\command"; ValueType: string; ValueName: ""; ValueData: """{{win}}\\System32\\wscript.exe"" ""{{app}}\\launch_xrd_finder_silent.vbs"" ""%1"""
Root: HKLM; Subkey: "Software\\RegisteredApplications"; ValueType: string; ValueName: "XRD Phase Finder"; ValueData: "Software\\XRDPhaseFinder\\Capabilities"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\\XRDPhaseFinder\\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "XRD Phase Finder"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\\XRDPhaseFinder\\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Phase identification from X-ray diffraction data"
Root: HKLM; Subkey: "Software\\XRDPhaseFinder\\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{{app}}\\icon.ico"
Root: HKLM; Subkey: "Software\\XRDPhaseFinder\\Capabilities\\FileAssociations"; ValueType: string; ValueName: ".xpff"; ValueData: "XRDPhaseFinder.Project"

[Run]
Filename: "{{win}}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{{tmp}}\\apply_secure_windows_seed.ps1"""; Flags: runhidden waituntilterminated runascurrentuser
Filename: "{{win}}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{{app}}\\launcher\\stop_running_finder.ps1"""; Flags: runhidden waituntilterminated runascurrentuser
Filename: "{{win}}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{{app}}\\launcher\\register_xpff_file_type.ps1"" -AppRoot ""{{app}}"" -Quiet"; Flags: runhidden waituntilterminated runascurrentuser

[UninstallRun]
Filename: "{{win}}\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{{app}}\\launcher\\register_xpff_file_type.ps1"" -AppRoot ""{{app}}"" -Unregister -Quiet"; Flags: runhidden waituntilterminated runascurrentuser

[UninstallDelete]
Type: filesandordirs; Name: "{{app}}"
''',
        encoding="utf-8",
    )
    return script_path


def secure_stage_root(output_dir: str | Path) -> Path:
    output_path = Path(output_dir).expanduser().resolve()
    suffix = abs(hash(str(output_path))) % 1_000_000
    return Path(tempfile.gettempdir()) / f"xrd_secure_windows_setup_{suffix:06d}"


def _prepare_app_payload(root: Path, app_stage: Path, progress: ProgressCallback | None) -> None:
    _emit(progress, "Copying XRD Phase Finder application")
    copy_secure_tree(root / "xrd_finder", app_stage / "xrd_finder")
    copy_secure_tree(root / "launcher", app_stage / "launcher")
    for runtime_file in (
        "app.json",
        "requirements.txt",
        "icon.png",
        "icon.ico",
        "launch_xrd_finder.bat",
        "launch_xrd_finder_silent.vbs",
        "README.md",
        "SECURITY.md",
        "LICENSE",
        "THIRD_PARTY_DATA_SOURCES.md",
    ):
        source = root / runtime_file
        if source.is_file():
            copy_secure_tree(source, app_stage / runtime_file)


def _prepare_secure_seed(
    seed_root: Path,
    *,
    sci_root: Path,
    data_root: Path,
    progress: ProgressCallback | None,
) -> None:
    seed_sci_root = seed_root / "Sci"
    seed_data_root = seed_sci_root / "apps" / "xrd_phase_finder" / "data"
    seed_sci_root.mkdir(parents=True, exist_ok=True)

    env_dir = sci_root / "env"
    if not env_dir.is_dir():
        raise RuntimeError(
            f"No Sci runtime environment was found in {env_dir}. "
            "Run XRD Phase Finder once and let it prepare the runtime first."
        )
    base_python = _venv_base_python_home(env_dir)
    if base_python is None or not _is_readable_dir(base_python):
        raise RuntimeError(
            "The Sci env points to a base Python runtime that was not found. "
            "Repair the Sci runtime on this Windows computer before building a secure installer."
        )

    _emit(progress, "Copying Sci runtime: env")
    copy_secure_tree(env_dir, seed_sci_root / "env")

    _emit(progress, "Copying base Python runtime")
    copy_secure_tree(base_python, seed_sci_root / "python")

    _emit(progress, "Copying local Finder data and caches")
    if data_root.exists():
        copy_secure_tree(data_root, seed_data_root)
    else:
        seed_data_root.mkdir(parents=True, exist_ok=True)
    write_secure_mode_settings(seed_data_root)


def _write_postinstall_script(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '''$ErrorActionPreference = "SilentlyContinue"
$SciRoot = Join-Path $env:LOCALAPPDATA "Sci"
$DataRoot = Join-Path $SciRoot "apps\\xrd_phase_finder\\data"
$SettingsRoot = Join-Path $DataRoot "settings"
$SecurityPath = Join-Path $SettingsRoot "security.json"
New-Item -ItemType Directory -Force -Path $SettingsRoot | Out-Null
$SecurityPayload = @{
    schema = 1
    offline_mode = $true
    source = "secure Windows installer"
} | ConvertTo-Json
Set-Content -LiteralPath $SecurityPath -Value $SecurityPayload -Encoding UTF8

$VenvCfg = Join-Path $SciRoot "env\\pyvenv.cfg"
$PortablePython = Join-Path $SciRoot "python\\python.exe"
if ((Test-Path -LiteralPath $VenvCfg) -and (Test-Path -LiteralPath $PortablePython)) {
    $PythonHome = Split-Path -Parent $PortablePython
    @"
home = $PythonHome
include-system-site-packages = false
version = 3.11.9
executable = $PortablePython
command = $PortablePython -m venv $SciRoot\\env
"@ | Set-Content -LiteralPath $VenvCfg -Encoding UTF8
}
exit 0
''',
        encoding="utf-8",
    )


def _assert_secure_payload(app_stage: Path, seed_root: Path, scripts_dir: Path) -> None:
    required_files = (
        app_stage / "xrd_finder" / "apps" / "finder_gui.py",
        app_stage / "launcher" / "launch_xrd_finder_preview.ps1",
        app_stage / "requirements.txt",
        seed_root / "Sci" / "env" / "Scripts" / "python.exe",
        seed_root / "Sci" / "apps" / "xrd_phase_finder" / "data" / "settings" / "security.json",
        scripts_dir / "apply_secure_windows_seed.ps1",
    )
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise RuntimeError("Secure Windows installer payload is incomplete:\n" + "\n".join(missing))
    forbidden = list(app_stage.rglob("*.pyc"))
    forbidden.extend(seed_root.rglob("*.pyc"))
    if forbidden:
        raise RuntimeError(f"Forbidden generated file in secure installer payload: {forbidden[0]}")


def _venv_base_python_home(env_dir: Path) -> Path | None:
    cfg = env_dir / "pyvenv.cfg"
    if not cfg.is_file():
        return None
    for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.lower().startswith("home") and "=" in line:
            return Path(line.split("=", 1)[1].strip()).expanduser()
    return None


def _is_readable_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _should_copy_path(path: Path) -> bool:
    if path.name in EXCLUDED_NAMES:
        return False
    if path.name.startswith("._"):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return True


def _find_inno_compiler() -> Path:
    found = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if found:
        return Path(found)
    for candidate in (
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    ):
        if candidate.is_file():
            return candidate
    raise RuntimeError("Inno Setup compiler ISCC.exe was not found.")


def _read_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            return str(tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"])
        except Exception:
            pass
    app_json = root / "app.json"
    if app_json.is_file():
        try:
            payload = json.loads(app_json.read_text(encoding="utf-8"))
            if payload.get("version"):
                return str(payload["version"])
        except Exception:
            pass
    return __version__


def _safe_version(version: str) -> str:
    return str(version).replace(".", "_").replace("-", "_")


def _inno_path(path: Path) -> str:
    return str(path)


def _default_app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_sci_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is not set.")
    return Path(local_app_data) / "Sci"


def _default_data_root() -> Path:
    return default_data_root()


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
    else:
        print(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a secure/offline Windows installer for XRD Phase Finder.")
    parser.add_argument("--app-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--sci-root", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args(argv)
    setup_path = build_secure_windows_installer(
        app_root=args.app_root,
        output_dir=args.output_dir,
        sci_root=args.sci_root,
        data_root=args.data_root,
    )
    print(setup_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
