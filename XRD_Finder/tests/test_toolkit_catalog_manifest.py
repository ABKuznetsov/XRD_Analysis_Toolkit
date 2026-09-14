from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from validate_toolkit_catalog import validate_catalog  # noqa: E402


def _read_json(relative_path: str) -> dict:
    return json.loads((REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8"))


def test_repository_catalog_contains_only_the_finder_release() -> None:
    catalog = _read_json("toolkit/catalog.json")
    version = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]["version"]

    assert validate_catalog(catalog, allow_unbuilt=True) == []
    assert catalog["schema_version"] == 1

    applications = {entry["app_id"]: entry for entry in catalog["applications"]}
    assert set(applications) == {"xrd_finder"}
    assert applications["xrd_finder"]["version"] == version
    assert applications["xrd_finder"]["update_manifest_url"].endswith(
        "/toolkit/updates/xrd_finder.json"
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

    manifest = _read_json("toolkit/updates/xrd_finder.json")
    application = applications["xrd_finder"]
    windows_asset = next(
        asset
        for asset in manifest["assets"]
        if asset["platform"] == "windows-x64" and asset["type"] == "installer"
    )
    assert manifest["app_id"] == "xrd_finder"
    assert manifest["version"] == application["version"]
    assert windows_asset["name"] == application["installer"]["filename"]
    assert windows_asset["url"] == application["installer"]["url"]
    assert windows_asset["sha256"] == application["installer"]["sha256"]
    assert windows_asset["size_bytes"] == application["installer"]["size_bytes"]
