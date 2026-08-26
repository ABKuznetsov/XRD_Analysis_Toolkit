from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_installer_contract_exists() -> None:
    required = [
        ROOT / "run_viewer.bat",
        ROOT / "run_viewer_silent.vbs",
        ROOT / "toolkit" / "setup_sci_env.bat",
        ROOT / "toolkit" / "requirements-windows.txt",
        ROOT / "installer" / "Crystal_Blocks.iss",
        ROOT / "installer" / "build_installer.bat",
    ]

    assert all(path.is_file() for path in required), [
        str(path.relative_to(ROOT)) for path in required if not path.is_file()
    ]


def test_installer_reuses_shared_sci_runtime() -> None:
    installer = (ROOT / "installer" / "Crystal_Blocks.iss").read_text(encoding="utf-8-sig")
    launcher = (ROOT / "run_viewer.bat").read_text(encoding="utf-8-sig")

    assert "CRAFT_Setup_{#MyAppVersion}" in installer
    assert "{localappdata}\\Sci\\apps\\craft" in installer
    assert "setup_sci_env.bat" in installer
    assert "%LOCALAPPDATA%\\Sci\\env\\Scripts\\pythonw.exe" in launcher
    assert "-m crystal_viewer.app" in launcher


def test_environment_setup_reports_long_running_install_progress() -> None:
    setup = (ROOT / "toolkit" / "setup_sci_env.bat").read_text(encoding="utf-8-sig")

    assert "Installing CRAFT dependencies" in setup
    assert "--progress-bar on" in setup
    requirements_command = next(
        line for line in setup.splitlines() if "requirements-windows.txt" in line and "pip install" in line
    )
    assert ">>" not in requirements_command
