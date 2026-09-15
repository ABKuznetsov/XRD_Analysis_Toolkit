from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tomllib

from xrd_finder import __version__
from xrd_finder.services.cache_paths import default_data_root


APP_NAME = "XRD Phase Finder"
APP_IDENTIFIER = "com.xrdphasefinder.app"
PKG_IDENTIFIER = "com.xrdphasefinder.secure.pkg"
SECURE_SEED_INSTALL_ROOT = Path("/Library/Application Support/XRD Phase Finder/SecureSeed")

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
            "source": "secure macOS installer",
        }
    )
    settings_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return settings_path


def build_secure_macos_pkg(
    *,
    app_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    sci_root: str | Path | None = None,
    data_root: str | Path | None = None,
    version: str | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("Secure macOS installer can be built only on macOS.")
    _require_tool("pkgbuild")
    _require_tool("productbuild")

    root = Path(app_root).expanduser().resolve() if app_root else _default_app_root()
    if not (root / "xrd_finder").is_dir() or not (root / "launcher").is_dir():
        raise RuntimeError(f"Application root does not look like XRD Phase Finder: {root}")

    build_version = version or _read_version(root)
    target_dir = Path(output_dir).expanduser().resolve() if output_dir else root / "dist"
    target_dir.mkdir(parents=True, exist_ok=True)

    stage_root = target_dir / "secure_macos_pkg"
    payload_root = stage_root / "payload"
    scripts_dir = stage_root / "scripts"
    component_pkg = stage_root / f"{APP_NAME}.secure.component.pkg"
    pkg_path = target_dir / f"XRD_Phase_Finder_Secure_macOS_{build_version}.pkg"

    _emit(progress, "Preparing secure installer workspace")
    if stage_root.exists():
        shutil.rmtree(stage_root)
    app_payload_dir = _prepare_app_bundle(root, payload_root, build_version, progress)
    seed_root = payload_root / SECURE_SEED_INSTALL_ROOT.relative_to("/")
    _prepare_secure_seed(
        seed_root,
        sci_root=Path(sci_root).expanduser() if sci_root else _default_sci_root(),
        data_root=Path(data_root).expanduser() if data_root else _default_data_root(),
        progress=progress,
    )

    scripts_dir.mkdir(parents=True, exist_ok=True)
    _write_postinstall(scripts_dir / "postinstall")

    _emit(progress, "Checking secure installer payload")
    _strip_macos_metadata(payload_root)
    _assert_secure_payload(app_payload_dir, seed_root)

    _emit(progress, "Building secure component package")
    subprocess.run(
        [
            "pkgbuild",
            "--root",
            str(payload_root),
            "--scripts",
            str(scripts_dir),
            "--install-location",
            "/",
            "--identifier",
            PKG_IDENTIFIER,
            "--version",
            build_version,
            "--filter",
            r"(^|/)\._[^/]*$",
            "--filter",
            r"(^|/)\.DS_Store$",
            str(component_pkg),
        ],
        check=True,
        env=_subprocess_env(),
    )

    _emit(progress, "Building secure macOS installer")
    subprocess.run(
        ["productbuild", "--package", str(component_pkg), str(pkg_path)],
        check=True,
        env=_subprocess_env(),
    )
    subprocess.run(["xattr", "-cr", str(pkg_path)], check=False)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(pkg_path)], check=False)
    _emit(progress, f"Created {pkg_path}")
    return pkg_path


def _prepare_app_bundle(
    root: Path,
    payload_root: Path,
    version: str,
    progress: ProgressCallback | None,
) -> Path:
    _emit(progress, "Copying XRD Phase Finder application")
    app_bundle = payload_root / "Applications" / f"{APP_NAME}.app"
    contents_dir = app_bundle / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"
    app_payload_dir = resources_dir / "app"
    macos_dir.mkdir(parents=True, exist_ok=True)
    app_payload_dir.mkdir(parents=True, exist_ok=True)

    copy_secure_tree(root / "xrd_finder", app_payload_dir / "xrd_finder")
    copy_secure_tree(root / "launcher", app_payload_dir / "launcher")

    for runtime_file in (
        "app.json",
        "requirements.txt",
        "icon.png",
        "icon.ico",
        "run_finder.command",
        "run_finder.sh",
        "run_finder.bat",
        "run_finder_silent.vbs",
        "launch_xrd_finder.bat",
        "launch_xrd_finder_silent.vbs",
        "README.md",
        "SECURITY.md",
        "LICENSE",
        "THIRD_PARTY_DATA_SOURCES.md",
    ):
        source = root / runtime_file
        if source.is_file():
            copy_secure_tree(source, app_payload_dir / runtime_file)

    for command_file in (app_payload_dir / "launcher").glob("*.command"):
        command_file.chmod(command_file.stat().st_mode | 0o111)
    for command_file in (app_payload_dir / "launcher").glob("*.sh"):
        command_file.chmod(command_file.stat().st_mode | 0o111)
    for command_file in (app_payload_dir / "run_finder.command", app_payload_dir / "run_finder.sh"):
        if command_file.exists():
            command_file.chmod(command_file.stat().st_mode | 0o111)

    icon_path = app_payload_dir / "icon.png"
    if icon_path.is_file():
        shutil.copy2(icon_path, resources_dir / "icon.png")

    (contents_dir / "Info.plist").write_text(_info_plist(version), encoding="utf-8")
    launcher_path = macos_dir / "xrd-phase-finder"
    launcher_path.write_text(_app_bundle_launcher(), encoding="utf-8")
    launcher_path.chmod(0o755)

    return app_payload_dir


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

    env_dirs = [path for path in sci_root.glob("env-*") if path.is_dir()]
    if not env_dirs:
        raise RuntimeError(
            f"No Sci runtime environments were found in {sci_root}. "
            "Run XRD Phase Finder once on this Mac and let it prepare the runtime first."
        )
    for env_dir in env_dirs:
        _emit(progress, f"Copying Sci runtime: {env_dir.name}")
        copy_secure_tree(env_dir, seed_sci_root / env_dir.name)

    _emit(progress, "Copying local Finder data and caches")
    if data_root.exists():
        copy_secure_tree(data_root, seed_data_root)
    else:
        seed_data_root.mkdir(parents=True, exist_ok=True)
    write_secure_mode_settings(seed_data_root)


def _write_postinstall(path: Path) -> None:
    path.write_text(
        """#!/bin/zsh
set -e

APP_BUNDLE="/Applications/XRD Phase Finder.app"
SEED_ROOT="/Library/Application Support/XRD Phase Finder/SecureSeed"

xattr -dr com.apple.quarantine "$APP_BUNDLE" >/dev/null 2>&1 || true
touch "$APP_BUNDLE" >/dev/null 2>&1 || true

CONSOLE_USER="$(/usr/sbin/scutil <<<'show State:/Users/ConsoleUser' | /usr/bin/awk '/Name :/ {print $3; exit}')"
if [ -z "$CONSOLE_USER" ] || [ "$CONSOLE_USER" = "loginwindow" ] || [ "$CONSOLE_USER" = "_mbsetupuser" ]; then
    exit 0
fi

USER_HOME="$(/usr/bin/dscl . -read "/Users/$CONSOLE_USER" NFSHomeDirectory 2>/dev/null | /usr/bin/awk '{print $2; exit}')"
if [ -z "$USER_HOME" ] || [ ! -d "$USER_HOME" ]; then
    exit 0
fi

SCI_ROOT="$USER_HOME/Library/Application Support/Sci"
FINDER_ROOT="$SCI_ROOT/apps/xrd_phase_finder"
DATA_ROOT="$FINDER_ROOT/data"

/bin/mkdir -p "$SCI_ROOT" "$FINDER_ROOT" "$DATA_ROOT/settings"

for ENV_DIR in "$SEED_ROOT/Sci"/env-*; do
    if [ -d "$ENV_DIR" ]; then
        /usr/bin/ditto "$ENV_DIR" "$SCI_ROOT/$(basename "$ENV_DIR")"
    fi
done

if [ -d "$SEED_ROOT/Sci/apps/xrd_phase_finder/data" ]; then
    /usr/bin/ditto "$SEED_ROOT/Sci/apps/xrd_phase_finder/data" "$DATA_ROOT"
fi

/bin/mkdir -p "$DATA_ROOT/settings"
/bin/cat > "$DATA_ROOT/settings/security.json" <<'JSON'
{
  "offline_mode": true,
  "schema": 1,
  "source": "secure macOS installer"
}
JSON

/usr/sbin/chown -R "$CONSOLE_USER":staff "$SCI_ROOT" >/dev/null 2>&1 || true
xattr -dr com.apple.quarantine "$SCI_ROOT" >/dev/null 2>&1 || true

exit 0
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _assert_secure_payload(app_payload_dir: Path, seed_root: Path) -> None:
    required_files = (
        app_payload_dir / "xrd_finder" / "apps" / "finder_gui.py",
        app_payload_dir / "launcher" / "launch_xrd_finder_preview.command",
        app_payload_dir / "launcher" / "launch_xrd_finder_preview_macos.py",
        app_payload_dir / "requirements.txt",
        seed_root / "Sci" / "apps" / "xrd_phase_finder" / "data" / "settings" / "security.json",
    )
    missing = [str(path) for path in required_files if not path.exists()]
    if missing:
        raise RuntimeError("Secure installer payload is incomplete:\n" + "\n".join(missing))
    forbidden = list(app_payload_dir.rglob("*.pyc"))
    forbidden.extend(app_payload_dir.rglob(".DS_Store"))
    forbidden.extend(app_payload_dir.rglob("._*"))
    forbidden.extend(seed_root.rglob(".DS_Store"))
    forbidden.extend(seed_root.rglob("._*"))
    if forbidden:
        raise RuntimeError(f"Forbidden generated file in secure installer payload: {forbidden[0]}")


def _strip_macos_metadata(path: Path) -> None:
    subprocess.run(["xattr", "-cr", str(path)], check=False)
    for attr in ("com.apple.provenance", "com.apple.quarantine"):
        subprocess.run(
            ["find", str(path), "-exec", "xattr", "-d", attr, "{}", ";"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    for pattern in ("._*", ".DS_Store"):
        for junk in path.rglob(pattern):
            try:
                junk.unlink()
            except OSError:
                pass


def _should_copy_path(path: Path) -> bool:
    if path.name in EXCLUDED_NAMES:
        return False
    if path.name.startswith("._"):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return True


def _require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} was not found. Install Xcode Command Line Tools.")


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["COPYFILE_DISABLE"] = "1"
    return env


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


def _default_app_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_sci_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "Sci"


def _default_data_root() -> Path:
    sci_data_root = _default_sci_root() / "apps" / "xrd_phase_finder" / "data"
    if sci_data_root.exists():
        return sci_data_root
    return default_data_root()


def _info_plist(version: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>{APP_NAME}</string>
    <key>CFBundleExecutable</key>
    <string>xrd-phase-finder</string>
    <key>CFBundleIdentifier</key>
    <string>{APP_IDENTIFIER}</string>
    <key>CFBundleIconFile</key>
    <string>icon.icns</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>{APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>{version}</string>
    <key>CFBundleVersion</key>
    <string>{version}</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""


def _app_bundle_launcher() -> str:
    return """#!/bin/zsh
set -e

APP_BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
APP_ROOT="$APP_BUNDLE/Contents/Resources/app"
exec "$APP_ROOT/launcher/launch_xrd_finder_preview.command" "$@"
"""


def _emit(progress: ProgressCallback | None, message: str) -> None:
    if progress is not None:
        progress(message)
    else:
        print(message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a secure/offline macOS PKG for XRD Phase Finder.")
    parser.add_argument("--app-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--sci-root", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args(argv)
    pkg_path = build_secure_macos_pkg(
        app_root=args.app_root,
        output_dir=args.output_dir,
        sci_root=args.sci_root,
        data_root=args.data_root,
    )
    print(pkg_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
