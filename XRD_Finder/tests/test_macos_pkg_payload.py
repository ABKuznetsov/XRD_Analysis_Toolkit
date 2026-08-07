from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build_macos_pkg.command"


def test_macos_pkg_keeps_and_validates_required_finder_modules() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    required_modules = (
        "XRD_Finder/xrd_finder/core/refinement.py",
        "XRD_Finder/xrd_finder/core/series.py",
    )
    for module in required_modules:
        assert f'--exclude "{module}"' not in script
        assert module in script


def test_macos_pkg_excludes_local_development_artifacts() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    excluded_paths = (
        "PORTABLE_CHANGES.md",
        "PORTABLE_README.md",
        "manuscript_work/",
        "XRD_Finder/benchmark_results/",
        "XRD_Finder/requirements-dev.txt",
        "XRD_Finder/scripts/",
        "XRD_Finder/xrd_finder.zip",
        "XRD_Finder/install_windows_runtime_direct.bat",
        "install_xrd_finder_windows_runtime.bat",
    )
    for path in excluded_paths:
        assert f'--exclude "{path}"' in script
