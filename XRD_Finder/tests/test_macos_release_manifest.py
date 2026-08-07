from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERSION = json.loads(
    (REPOSITORY_ROOT / "XRD_Finder" / "app.json").read_text(encoding="utf-8")
)["version"]
PKG_NAME = f"XRD_Phase_Finder_macOS_{VERSION}.pkg"
PKG_URL = (
    "https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/"
    f"releases/download/v{VERSION}/{PKG_NAME}"
)


def test_macos_release_manifests_match_built_installer() -> None:
    package = REPOSITORY_ROOT / "dist" / PKG_NAME
    update_manifest = json.loads(
        (REPOSITORY_ROOT / "toolkit" / "updates" / "xrd_finder.json").read_text(encoding="utf-8")
    )
    toolkit_manifest = json.loads(
        (REPOSITORY_ROOT / "toolkit" / "manifest.json").read_text(encoding="utf-8")
    )["apps"]["xrd_finder"]

    macos_asset = next(asset for asset in update_manifest["assets"] if asset["platform"] == "macos")

    assert update_manifest["version"] == VERSION
    assert macos_asset["name"] == PKG_NAME
    assert macos_asset["type"] == "installer"
    assert macos_asset["url"] == PKG_URL
    assert update_manifest["macos_installer_url"] == PKG_URL
    assert toolkit_manifest["macos_installer_url"] == PKG_URL
    assert macos_asset["sha256"] == update_manifest["macos_installer_sha256"]
    assert macos_asset["sha256"] == toolkit_manifest["macos_installer_sha256"]

    if package.is_file():
        package_sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
        assert macos_asset["sha256"] == package_sha256
        assert macos_asset["size_bytes"] == package.stat().st_size
