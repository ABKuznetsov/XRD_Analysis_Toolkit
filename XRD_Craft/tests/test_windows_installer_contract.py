from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
ROOT = MODULE_ROOT.parent
INSTALLER = ROOT / "installer" / "craft_setup" / "CRAFT.iss"
BUILD_SCRIPT = ROOT / "installer" / "craft_setup" / "build_installer.bat"


def test_windows_installer_contract_exists() -> None:
    required = [
        MODULE_ROOT / "run_viewer.bat",
        MODULE_ROOT / "run_viewer_silent.vbs",
        MODULE_ROOT / "toolkit" / "setup_sci_env.bat",
        MODULE_ROOT / "toolkit" / "register_craft_install.ps1",
        MODULE_ROOT / "toolkit" / "requirements-windows.txt",
        INSTALLER,
        BUILD_SCRIPT,
    ]

    assert all(path.is_file() for path in required), [
        str(path.relative_to(ROOT)) for path in required if not path.is_file()
    ]


def test_installer_keeps_program_files_separate_from_shared_sci_metadata() -> None:
    installer = INSTALLER.read_text(encoding="utf-8-sig")
    launcher = (MODULE_ROOT / "run_viewer.bat").read_text(encoding="utf-8-sig")

    assert "CRAFT_Setup_{#MyAppVersion}" in installer
    assert "DefaultDirName={autopf}\\XRD CRAFT" in installer
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in installer
    assert "PrivilegesRequired=admin" in installer
    assert "UsePreviousAppDir=no" in installer
    assert "register_craft_install.ps1" in installer
    assert '-InstallDir ""{app}"" -Version ""{#MyAppVersion}""' in installer
    assert "{localappdata}" not in installer
    assert "setup_sci_env.bat" in installer
    assert "runasoriginaluser" in installer
    assert ".xpff" not in installer
    assert 'Source: "..\\..\\XRD_Finder\\*"' not in installer
    assert "%LOCALAPPDATA%\\Sci\\env\\Scripts\\pythonw.exe" in launcher
    assert "-m crystal_viewer.app" in launcher


def test_install_registration_keeps_only_metadata_under_sci_apps() -> None:
    registration = (
        MODULE_ROOT / "toolkit" / "register_craft_install.ps1"
    ).read_text(encoding="utf-8-sig")

    assert 'Join-Path $env:LOCALAPPDATA "Sci\\apps\\craft"' in registration
    assert '"installed.ini"' in registration
    assert '"InstallDir=$resolvedInstallDir"' in registration
    assert '"Version=$Version"' in registration
    assert '"run_viewer_silent.vbs"' in registration
    assert "Remove-Item" in registration


def test_environment_setup_reports_long_running_install_progress() -> None:
    setup = (MODULE_ROOT / "toolkit" / "setup_sci_env.bat").read_text(encoding="utf-8-sig")

    assert "Installing CRAFT dependencies" in setup
    assert ":install_current_requirement" in setup
    assert "importlib.metadata" in setup
    assert "--progress-bar on" in setup
    assert "Remove-Item" not in setup
    assert "\nrmdir " not in setup.lower()


def test_craft_installer_excludes_development_payload() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")

    for excluded in ("tests\\*", "__pycache__\\*", "*.pyc", "docs\\superpowers\\*"):
        assert excluded in source


def test_craft_installer_offers_verified_finder_install_without_bundling_it() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")

    assert 'Name: "installfinder"' in source
    assert 'Description: "Download and install XRD Phase Finder 1.5.0"' in source
    assert "Tasks: installfinder" in source
    assert "install_companion_app.ps1" in source
    assert '-TargetAppId ""xrd_finder""' in source
    assert "XRD Phase Finder identifies and interprets phases" in source
    assert "It is installed and updated independently." in source
    assert 'Source: "..\\..\\XRD_Finder\\*"' not in source


def test_craft_installer_skips_finder_offer_when_finder_is_already_installed() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")

    assert "FinderIsInstalled" in source
    assert "{commonpf64}\\XRD Phase Finder" in source
    assert "not FinderIsInstalled" in source
