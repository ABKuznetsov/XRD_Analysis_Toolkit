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
