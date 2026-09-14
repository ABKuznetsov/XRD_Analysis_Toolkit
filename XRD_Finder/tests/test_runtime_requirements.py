from __future__ import annotations

from pathlib import Path
import re
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from xrd_finder.apps.runtime_check import REQUIRED_RUNTIME_PACKAGES


XRD_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = XRD_ROOT.parent


def _requirement_map(requirements: list[str] | tuple[str, ...]) -> dict[str, str]:
    parsed = (Requirement(requirement) for requirement in requirements)
    return {
        canonicalize_name(requirement.name): str(requirement.specifier)
        for requirement in parsed
    }


def test_runtime_check_matches_requirements_and_pyproject() -> None:
    runtime_requirements = {
        canonicalize_name(name): version_specifier
        for name, _, version_specifier in REQUIRED_RUNTIME_PACKAGES
    }
    requirement_lines = [
        line
        for line in (XRD_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert runtime_requirements == _requirement_map(requirement_lines)
    assert runtime_requirements == _requirement_map(project["project"]["dependencies"])


def test_runtime_pins_required_cristma_powder_beta() -> None:
    runtime_requirements = {
        canonicalize_name(name): version_specifier
        for name, _, version_specifier in REQUIRED_RUNTIME_PACKAGES
    }

    assert runtime_requirements["cristma"] == "==0.1.0b9"


def test_launchers_validate_cristma_powder_api() -> None:
    macos_launcher = (XRD_ROOT / "run_finder.command").read_text(encoding="utf-8")
    windows_installer = (
        XRD_ROOT / "install_windows_runtime_direct.bat"
    ).read_text(encoding="ascii")

    for launcher in (macos_launcher, windows_installer):
        assert "PowderPatternCalculator" in launcher
        assert "PowderProfileCalculator" in launcher
        assert "resolve_space_group_setting" in launcher
        assert "d_spacing_scale" in launcher


def test_online_connectors_are_optional() -> None:
    requirement_lines = [
        line
        for line in (XRD_ROOT / "requirements-optional.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    optional_requirements = _requirement_map(requirement_lines)
    runtime_names = {
        canonicalize_name(name)
        for name, _, _ in REQUIRED_RUNTIME_PACKAGES
    }

    assert optional_requirements == _requirement_map(
        project["project"]["optional-dependencies"]["online"]
    )
    assert set(optional_requirements).isdisjoint(runtime_names)


def test_standalone_windows_installer_matches_runtime_requirements() -> None:
    installer = (XRD_ROOT / "install_windows_runtime_direct.bat").read_text(encoding="ascii")
    installer_requirements = _requirement_map(
        re.findall(
            r'^call :install_package "([^"]+)"$',
            installer,
            flags=re.MULTILINE,
        )
    )
    runtime_requirements = {
        canonicalize_name(name): version_specifier
        for name, _, version_specifier in REQUIRED_RUNTIME_PACKAGES
    }

    assert installer_requirements == runtime_requirements
