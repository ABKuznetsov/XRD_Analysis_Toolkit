from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_craft_source_and_release_surfaces_are_absent() -> None:
    forbidden = (
        "XRD_Craft",
        "installer/craft_setup",
        "toolkit/install_companion_app.ps1",
        "toolkit/updates/xrd_craft.json",
        "dist/CRAFT_macOS_1.0.1.pkg",
        "dist/craft_macos_pkg_build",
    )

    assert [path for path in forbidden if (ROOT / path).exists()] == []


def test_finder_release_surfaces_do_not_reference_craft() -> None:
    paths = (
        ROOT / "installer/finder_setup/XRD_Phase_Finder.iss",
        ROOT / "toolkit/catalog.json",
        ROOT / "XRD_Finder/xrd_finder/ui/phase_finder_menu.py",
        ROOT / "XRD_Finder/xrd_finder/ui/analysis_windows.py",
    )
    forbidden_tokens = ("xrd_craft", "xrd craft", "crystal_viewer")

    for path in paths:
        source = path.read_text(encoding="utf-8-sig").casefold()
        assert all(token not in source for token in forbidden_tokens), path


def test_obsolete_manager_scaffolding_is_absent() -> None:
    obsolete = (
        "PROJECT_HEALTH.md",
        "scripts/build_macos_dmg.command",
        "XRD_Finder/xrd_finder/app.py",
        "XRD_Finder/xrd_finder/io/exporters.py",
        "XRD_Finder/xrd_finder/services/thermo_service.py",
        "XRD_Finder/xrd_finder/services/solid_solution_service.py",
        "XRD_Finder/xrd_finder/services/structure_service.py",
        "XRD_Finder/xrd_finder/ui/legacy_windows.py",
        "XRD_Finder/xrd_finder/ui/main_window.py",
        "XRD_Finder/tests/solid_solution_probe.py",
    )

    assert [path for path in obsolete if (ROOT / path).exists()] == []


def test_only_current_finder_release_notes_remain() -> None:
    notes = sorted(path.name for path in (ROOT / "XRD_Finder").glob("RELEASE_NOTES_*.md"))

    assert notes == ["RELEASE_NOTES_1.5.0.md"]
