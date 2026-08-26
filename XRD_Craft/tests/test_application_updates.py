from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from crystal_viewer.services.application_updates import (
    UpdateManifestError,
    compare_versions,
    download_update,
    parse_update_manifest,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


def _manifest(payload: bytes = b"craft installer", version: str = "0.2.0") -> dict:
    return {
        "app_id": "xrd_craft",
        "name": "XRD CRAFT",
        "version": version,
        "summary": ["Faster startup.", "More reliable structure loading."],
        "assets": [
            {
                "name": f"CRAFT_Setup_{version}.exe",
                "type": "installer",
                "platform": "windows-x64",
                "url": f"https://example.test/CRAFT_Setup_{version}.exe",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }


def test_semantic_version_ordering() -> None:
    assert compare_versions("0.2.0", "0.1.9") > 0
    assert compare_versions("1.0.0", "1.0.0") == 0
    assert compare_versions("1.4.9", "1.5.0") < 0


def test_current_or_older_manifest_is_not_an_update() -> None:
    assert parse_update_manifest(_manifest(version="0.1.0"), current_version="0.1.0") is None
    assert parse_update_manifest(_manifest(version="0.0.9"), current_version="0.1.0") is None


def test_valid_update_is_parsed_with_release_notes() -> None:
    update = parse_update_manifest(_manifest(), current_version="0.1.0")

    assert update is not None
    assert update.version == "0.2.0"
    assert "Faster startup." in update.release_notes
    assert update.installer_filename == "CRAFT_Setup_0.2.0.exe"


def test_malformed_update_checksum_is_rejected() -> None:
    manifest = _manifest()
    manifest["assets"][0]["sha256"] = "INVALID"

    with pytest.raises(UpdateManifestError, match="SHA-256"):
        parse_update_manifest(manifest, current_version="0.1.0")


def test_update_download_is_verified_and_reused(tmp_path: Path) -> None:
    payload = b"craft installer"
    update = parse_update_manifest(_manifest(payload), current_version="0.1.0")
    assert update is not None
    calls = 0

    def urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _Response(payload)

    first = download_update(update, tmp_path, urlopen=urlopen)
    second = download_update(update, tmp_path, urlopen=urlopen)

    assert first == second
    assert first.read_bytes() == payload
    assert calls == 1
