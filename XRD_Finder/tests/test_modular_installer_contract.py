from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "installer" / "finder_setup" / "XRD_Phase_Finder.iss"
BUILD_SCRIPT = ROOT / "installer" / "finder_setup" / "build_installer.bat"


def test_finder_has_an_independent_system_installer() -> None:
    assert INSTALLER.is_file()
    assert BUILD_SCRIPT.is_file()
    source = INSTALLER.read_text(encoding="utf-8-sig")

    assert "DefaultDirName={autopf}\\XRD Phase Finder" in source
    assert "PrivilegesRequired=admin" in source
    assert "XRD_Phase_Finder_Setup_{#MyAppVersion}" in source
    assert ".xpff" in source
    assert "XRD_Craft" not in source


def test_finder_installer_excludes_development_payload() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")

    for excluded in ("tests\\*", "__pycache__\\*", "*.pyc", "docs\\superpowers\\*"):
        assert excluded in source
    assert "%LocalAppData%\\Sci\\env" not in source


def test_finder_installer_offers_verified_craft_install_without_bundling_it() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")

    assert 'Name: "installcraft"' in source
    assert 'Description: "Download and install XRD CRAFT 1.0.1"' in source
    assert "Tasks: installcraft" in source
    assert "install_companion_app.ps1" in source
    assert '-TargetAppId ""xrd_craft""' in source
    assert "XRD CRAFT provides interactive crystal-structure" in source
    assert "It is installed and updated independently." in source
    assert "Source: \"..\\..\\XRD_Craft\\*\"" not in source


def test_finder_installer_skips_craft_offer_when_craft_is_already_installed() -> None:
    source = INSTALLER.read_text(encoding="utf-8-sig")

    assert "CraftIsInstalled" in source
    assert "{localappdata}\\Sci\\apps\\craft" in source
    assert "not CraftIsInstalled" in source


def test_companion_loader_verifies_catalogue_size_and_sha256() -> None:
    loader = ROOT / "toolkit" / "install_companion_app.ps1"
    source = loader.read_text(encoding="utf-8-sig")

    assert "ConvertFrom-Json" in source
    assert "size_bytes" in source
    assert "Get-FileHash" in source
    assert "sha256" in source
    assert "Start-Process" in source
