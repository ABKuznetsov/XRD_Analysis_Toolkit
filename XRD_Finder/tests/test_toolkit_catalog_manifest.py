from __future__ import annotations

import copy
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from validate_toolkit_catalog import validate_catalog  # noqa: E402


def _read_json(relative_path: str) -> dict:
    return json.loads((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))


def test_repository_catalog_contains_independent_finder_and_craft_releases() -> None:
    catalog = _read_json("toolkit/catalog.json")

    assert validate_catalog(catalog, allow_unbuilt=True) == []
    assert catalog["schema_version"] == 1

    applications = {entry["app_id"]: entry for entry in catalog["applications"]}
    assert set(applications) == {"xrd_finder", "xrd_craft"}
    assert applications["xrd_finder"]["version"] == "1.5.0"
    assert applications["xrd_craft"]["version"] == "1.0.1"
    assert applications["xrd_craft"]["announcement_revision"] == 1
    assert applications["xrd_finder"]["update_manifest_url"].endswith(
        "/toolkit/updates/xrd_finder.json"
    )
    assert applications["xrd_craft"]["update_manifest_url"].endswith(
        "/toolkit/updates/xrd_craft.json"
    )


def test_strict_validation_rejects_an_unbuilt_checksum() -> None:
    catalog = _read_json("toolkit/catalog.json")
    unbuilt = copy.deepcopy(catalog)
    unbuilt["applications"][0]["installer"]["sha256"] = "0" * 64

    errors = validate_catalog(unbuilt, allow_unbuilt=False)

    assert any("unbuilt SHA-256" in error for error in errors)


def test_update_manifests_match_catalog_versions_and_assets() -> None:
    catalog = _read_json("toolkit/catalog.json")
    applications = {entry["app_id"]: entry for entry in catalog["applications"]}

    for app_id in ("xrd_finder", "xrd_craft"):
        manifest = _read_json(f"toolkit/updates/{app_id}.json")
        application = applications[app_id]
        windows_asset = next(
            asset
            for asset in manifest["assets"]
            if asset["platform"] == "windows-x64" and asset["type"] == "installer"
        )
        assert manifest["app_id"] == app_id
        assert manifest["version"] == application["version"]
        assert windows_asset["name"] == application["installer"]["filename"]
        assert windows_asset["url"] == application["installer"]["url"]
        assert windows_asset["sha256"] == application["installer"]["sha256"]
        assert windows_asset["size_bytes"] == application["installer"]["size_bytes"]
