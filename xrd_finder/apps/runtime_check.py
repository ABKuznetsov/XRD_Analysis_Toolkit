from __future__ import annotations

import argparse
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version as distribution_version
from inspect import signature
import sys

from packaging.specifiers import SpecifierSet


REQUIRED_RUNTIME_PACKAGES = (
    ("certifi", "certifi", ""),
    ("cristma", "cristma", "==0.1.0b9"),
    ("numpy", "numpy", ""),
    ("packaging", "packaging", ""),
    ("pybaselines", "pybaselines", ""),
    ("pyqtgraph", "pyqtgraph", "==0.14.0"),
    ("PySide6", "PySide6", "==6.7.3"),
    ("rfc8785", "rfc8785", "==0.1.4"),
    ("scipy", "scipy", ""),
    ("mp-api", "mp_api", ""),
)
PLATFORM_VERSION_SPECIFIERS = {
    ("darwin", "PySide6"): "==6.11.1",
}


def _check_cristma_powder_api() -> None:
    try:
        from cristma.crystallography import resolve_space_group_setting  # noqa: F401
        from cristma.diffraction import (  # noqa: F401
            PowderPatternCalculator,
            PowderProfileCalculator,
        )
    except ImportError as exc:
        raise RuntimeError(
            "The installed CrIStMa build does not provide the powder API required "
            "by XRD Phase Finder. Reinstall the Finder runtime."
        ) from exc

    if "d_spacing_scale" not in signature(PowderProfileCalculator.calculate).parameters:
        raise RuntimeError(
            "The installed CrIStMa 0.1.0b9 build is outdated and does not support "
            "d_spacing_scale. Reinstall the Finder runtime."
        )


def check_runtime(mode: str = "gui") -> None:
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        python_version = ".".join(str(part) for part in sys.version_info[:3])
        raise RuntimeError(f"Python 3.11 or 3.12 is required; found {python_version}")

    for distribution_name, module_name, version_specifier in REQUIRED_RUNTIME_PACKAGES:
        version_specifier = PLATFORM_VERSION_SPECIFIERS.get(
            (sys.platform, distribution_name),
            version_specifier,
        )
        try:
            installed_version = distribution_version(distribution_name)
        except PackageNotFoundError as exc:
            raise RuntimeError(f"Required package is missing: {distribution_name}") from exc
        if version_specifier and installed_version not in SpecifierSet(version_specifier):
            raise RuntimeError(
                f"{distribution_name}{version_specifier} is required; "
                f"found {installed_version}"
            )
        import_module(module_name)

    _check_cristma_powder_api()

    if mode == "gui":
        from xrd_finder.ui.analysis_windows import PhaseFinderWindow  # noqa: F401
    elif mode == "cli":
        from xrd_finder.apps.finder_cli import main  # noqa: F401
    else:
        raise ValueError(f"Unknown runtime-check mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the XRD Phase Finder runtime")
    parser.add_argument("--mode", choices=("gui", "cli"), default="gui")
    args = parser.parse_args()
    check_runtime(args.mode)
    print(f"XRD Phase Finder {args.mode} runtime is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
