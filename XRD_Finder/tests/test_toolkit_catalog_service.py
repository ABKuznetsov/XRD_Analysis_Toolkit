from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from xrd_finder.services.toolkit_catalog import (
    InstallerIntegrityError,
    ToolkitApplication,
    cached_installer_path,
    download_installer,
    installer_is_valid,
    parse_catalog,
)


def _application(payload: bytes = b"verified installer") -> ToolkitApplication:
    return ToolkitApplication(
        app_id="xrd_craft",
        name="XRD CRAFT",
        description="Crystal structure analysis.",
        version="0.1.0",
        announcement_revision=1,
        installer_url="https://example.test/CRAFT_Setup_0.1.0.exe",
        installer_filename="CRAFT_Setup_0.1.0.exe",
        installer_sha256=hashlib.sha256(payload).hexdigest(),
        installer_size_bytes=len(payload),
    )


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


def test_parse_catalog_excludes_current_application_and_unsupported_platforms() -> None:
    payload = {
        "schema_version": 1,
        "applications": [
            {
                "app_id": "xrd_finder",
                "name": "Finder",
                "description": "Current application",
                "version": "1.5.0",
                "announcement_revision": 0,
                "platforms": ["windows"],
                "architectures": ["x86_64"],
                "installer": {
                    "url": "https://example.test/finder.exe",
                    "filename": "finder.exe",
                    "sha256": "a" * 64,
                    "size_bytes": 10,
                },
            },
            {
                "app_id": "xrd_craft",
                "name": "CRAFT",
                "description": "Crystal analysis",
                "version": "0.1.0",
                "announcement_revision": 1,
                "platforms": ["windows"],
                "architectures": ["x86_64"],
                "installer": {
                    "url": "https://example.test/craft.exe",
                    "filename": "craft.exe",
                    "sha256": "b" * 64,
                    "size_bytes": 20,
                },
            },
            {
                "app_id": "mac_only",
                "name": "macOS only",
                "description": "Unsupported",
                "version": "1.0.0",
                "announcement_revision": 1,
                "platforms": ["macos"],
                "architectures": ["arm64"],
                "installer": {
                    "url": "https://example.test/mac.exe",
                    "filename": "mac.exe",
                    "sha256": "c" * 64,
                    "size_bytes": 30,
                },
            },
        ],
    }

    applications = parse_catalog(payload, current_app_id="xrd_finder")

    assert [application.app_id for application in applications] == ["xrd_craft"]
    assert applications[0].announcement_revision == 1


def test_cache_path_is_scoped_by_application_and_version(tmp_path: Path) -> None:
    application = _application()

    result = cached_installer_path(application, tmp_path)

    assert result == tmp_path / "xrd_craft" / "0.1.0" / "CRAFT_Setup_0.1.0.exe"


def test_valid_cached_installer_is_reused_without_network(tmp_path: Path) -> None:
    payload = b"verified installer"
    application = _application(payload)
    target = cached_installer_path(application, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(payload)

    def unexpected_urlopen(*_args, **_kwargs):
        raise AssertionError("network must not be used for a valid cache entry")

    result = download_installer(application, tmp_path, urlopen=unexpected_urlopen)

    assert result == target
    assert installer_is_valid(result, application)


def test_invalid_cached_file_is_replaced_atomically(tmp_path: Path) -> None:
    payload = b"verified installer"
    application = _application(payload)
    target = cached_installer_path(application, tmp_path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"wrong")
    progress: list[tuple[int, int]] = []

    result = download_installer(
        application,
        tmp_path,
        progress=lambda received, total: progress.append((received, total)),
        urlopen=lambda *_args, **_kwargs: _Response(payload),
    )

    assert result.read_bytes() == payload
    assert progress[-1] == (len(payload), len(payload))
    assert not target.with_name(target.name + ".part").exists()


def test_checksum_mismatch_is_never_promoted_to_executable(tmp_path: Path) -> None:
    expected = b"verified installer"
    application = _application(expected)
    target = cached_installer_path(application, tmp_path)

    with pytest.raises(InstallerIntegrityError, match="checksum"):
        download_installer(
            application,
            tmp_path,
            urlopen=lambda *_args, **_kwargs: _Response(b"tampered installer"),
        )

    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()
