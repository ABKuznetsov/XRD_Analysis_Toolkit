from __future__ import annotations

from pathlib import Path


XRD_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = XRD_ROOT.parent


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(
        encoding="utf-8",
        errors="strict",
    )


def test_windows_runtime_installers_avoid_store_alias_and_backups() -> None:
    installers = (
        _read("XRD_Finder/install_windows_runtime_direct.bat"),
        _read("toolkit/setup_sci_env.bat"),
    )

    for installer in installers:
        lowered = installer.lower()
        assert "winget" not in lowered
        assert 'set "python_cmd=python"' not in lowered
        assert "env_incompatible" not in lowered
        assert "rmdir /s /q" in lowered
        assert r"%localappdata%\sci\env" in lowered or r"%sci_env%" in lowered


def test_direct_runtime_installer_uses_managed_python() -> None:
    installer = _read("XRD_Finder/install_windows_runtime_direct.bat").lower()

    assert "python.org/ftp/python/3.11.9/" in installer
    assert r"%sci_root%\python311" in installer
    assert "targetdir=" in installer
    assert "runtime_check --mode gui" in installer
    assert ":install_package" in installer
    assert "failed package:" in installer
    assert "get-content" in installer


def test_optional_connectors_do_not_block_windows_startup() -> None:
    direct_installer = _read("XRD_Finder/install_windows_runtime_direct.bat").lower()
    setup = _read("toolkit/setup_sci_env.bat").lower()

    required_block = direct_installer.split("echo validating installed packages", 1)[0]
    assert 'call :install_package "mp-api"' not in required_block
    assert 'call :install_package "pymatgen"' not in required_block
    assert 'if /i "%~1"=="--with-online"' in direct_installer
    assert "requirements-optional.txt" not in setup


def test_windows_installers_resume_large_downloads() -> None:
    installers = (
        _read("XRD_Finder/install_windows_runtime_direct.bat").lower(),
        _read("toolkit/setup_sci_env.bat").lower(),
    )

    for installer in installers:
        assert "pip_cache_dir" in installer
        assert "--timeout 300" in installer
        assert "--retries 10" in installer
        assert "--resume-retries 20" in installer
        assert "timeout /t 15" in installer


def test_standalone_runtime_repair_shows_download_progress() -> None:
    repair = _read("install_xrd_finder_windows_runtime.bat").lower()

    assert "package_total=13" in repair
    assert 'call :install_step "shiboken6==6.7.3"' in repair
    assert 'call :install_step "pyside6-essentials==6.7.3"' in repair
    assert 'call :install_step "pyside6-addons==6.7.3"' in repair
    assert 'call :install_step "pyside6==6.7.3"' in repair
    assert "for %%p in (%packages%)" not in repair
    assert "--progress-bar on" in repair
    assert "tee-object" in repair
    assert "out-file" in repair
    assert "-encoding utf8" in repair
    assert "--resume-retries 30" in repair
    assert "retry 3 of 3" in repair


def test_windows_preview_repairs_runtime_and_selects_windows_update() -> None:
    preview = _read("toolkit/launch_xrd_finder_preview.ps1").lower()

    assert "xrd_finder.apps.runtime_check --mode gui" in preview
    assert "setup_sci_env.bat" in preview
    assert 'startswith("windows")' in preview
    assert 'endswith(".exe")' in preview


def test_windows_launcher_chain_is_complete() -> None:
    launcher = _read("XRD_Finder/launch_xrd_finder.bat").lower()
    silent_launcher = _read("XRD_Finder/launch_xrd_finder_silent.vbs").lower()

    assert "launch_xrd_finder_preview.ps1" in launcher
    assert "launch_xrd_finder_preview.ps1" in silent_launcher
    assert (REPOSITORY_ROOT / "toolkit/setup_sci_env.bat").is_file()
    assert (XRD_ROOT / "install_windows_runtime_direct.bat").is_file()
