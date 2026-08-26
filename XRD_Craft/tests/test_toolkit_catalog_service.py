from __future__ import annotations

import hashlib
import io
from pathlib import Path

from crystal_viewer.services.toolkit_catalog import (
    ToolkitApplication,
    cached_installer_path,
    download_installer,
    installer_is_valid,
    parse_catalog,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


def _catalog() -> dict:
    return {
        "schema_version": 1,
        "applications": [
            {
                "app_id": "xrd_craft",
                "name": "XRD CRAFT",
                "description": "Current application",
                "version": "1.0.1",
                "announcement_revision": 1,
                "platforms": ["windows"],
                "architectures": ["x86_64"],
                "installer": {
                    "url": "https://example.test/craft.exe",
                    "filename": "craft.exe",
                    "size_bytes": 1,
                    "sha256": "a" * 64,
                },
            },
            {
                "app_id": "xrd_finder",
                "name": "XRD Phase Finder",
                "description": "Phase identification",
                "version": "1.5.0",
                "announcement_revision": 1,
                "platforms": ["windows"],
                "architectures": ["x86_64"],
                "installer": {
                    "url": "https://example.test/finder.exe",
                    "filename": "finder.exe",
                    "size_bytes": 2,
                    "sha256": "b" * 64,
                },
            },
        ],
    }


def test_craft_excludes_itself_and_offers_finder() -> None:
    applications = parse_catalog(_catalog(), current_app_id="xrd_craft")

    assert [app.app_id for app in applications] == ["xrd_finder"]


def test_craft_reuses_the_shared_verified_installer_cache(tmp_path: Path) -> None:
    payload = b"finder installer"
    app = ToolkitApplication(
        app_id="xrd_finder",
        name="XRD Phase Finder",
        description="Phase identification",
        version="1.5.0",
        announcement_revision=1,
        installer_url="https://example.test/finder.exe",
        installer_filename="finder.exe",
        installer_sha256=hashlib.sha256(payload).hexdigest(),
        installer_size_bytes=len(payload),
    )

    result = download_installer(
        app,
        tmp_path,
        urlopen=lambda *_args, **_kwargs: _Response(payload),
    )

    assert result == cached_installer_path(app, tmp_path)
    assert result.read_bytes() == payload
    assert installer_is_valid(result, app)
