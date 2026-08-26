from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def _define_version(path: Path) -> str:
    match = re.search(r'#define MyAppVersion "([^"]+)"', path.read_text(encoding="utf-8-sig"))
    assert match is not None
    return match.group(1)


def test_finder_release_version_is_consistent() -> None:
    version = "1.5.0"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    update = json.loads((ROOT / "toolkit" / "updates" / "xrd_finder.json").read_text(encoding="utf-8"))
    package_source = (ROOT / "XRD_Finder" / "xrd_finder" / "__init__.py").read_text(encoding="utf-8")
    notes = ROOT / "XRD_Finder" / f"RELEASE_NOTES_{version}.md"

    assert project["project"]["version"] == version
    assert f'__version__ = "{version}"' in package_source
    assert _define_version(ROOT / "installer" / "finder_setup" / "XRD_Phase_Finder.iss") == version
    assert update["version"] == version
    assert notes.is_file()
    assert version in notes.read_text(encoding="utf-8")


def test_craft_release_version_is_consistent() -> None:
    version = "1.0.1"
    project = tomllib.loads((ROOT / "XRD_Craft" / "pyproject.toml").read_text(encoding="utf-8"))
    update = json.loads((ROOT / "toolkit" / "updates" / "xrd_craft.json").read_text(encoding="utf-8"))
    package_source = (ROOT / "XRD_Craft" / "src" / "crystal_viewer" / "__init__.py").read_text(encoding="utf-8")
    notes = ROOT / "XRD_Craft" / f"RELEASE_NOTES_{version}.md"

    assert project["project"]["version"] == version
    assert f'__version__ = "{version}"' in package_source
    assert _define_version(ROOT / "installer" / "craft_setup" / "CRAFT.iss") == version
    assert update["version"] == version
    assert notes.is_file()
    assert version in notes.read_text(encoding="utf-8")


def test_release_notes_cover_user_facing_release_themes() -> None:
    combined = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8").lower()
        for relative in (
            "XRD_Finder/RELEASE_NOTES_1.5.0.md",
            "XRD_Craft/RELEASE_NOTES_1.0.1.md",
        )
    )

    for phrase in ("independent install", "performance", "reliability", "xrd tools"):
        assert phrase in combined
    assert "sci manager" not in combined
