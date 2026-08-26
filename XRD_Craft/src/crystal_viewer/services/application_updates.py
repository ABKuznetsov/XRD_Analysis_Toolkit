from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, BinaryIO
import urllib.request

from crystal_viewer.services.toolkit_catalog import (
    ToolkitApplication,
    download_installer,
)


CRAFT_UPDATE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/ABKuznetsov/"
    "XRD_Analysis_Toolkit/main/toolkit/updates/xrd_craft.json"
)
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


class UpdateManifestError(RuntimeError):
    pass


class UpdateCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class ApplicationUpdate:
    version: str
    release_notes: str
    installer_url: str
    installer_filename: str
    installer_size_bytes: int
    installer_sha256: str


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_PATTERN.fullmatch(str(value).strip())
    if match is None:
        raise UpdateManifestError(f"Invalid application version: {value!r}")
    return tuple(int(part) for part in match.groups())


def compare_versions(left: str, right: str) -> int:
    left_value = _version_tuple(left)
    right_value = _version_tuple(right)
    return (left_value > right_value) - (left_value < right_value)


def _release_notes(payload: Mapping[str, Any]) -> str:
    notes = payload.get("release_notes")
    if isinstance(notes, str) and notes.strip():
        return notes.strip()
    summary = payload.get("summary")
    if isinstance(summary, list):
        lines = [str(item).strip() for item in summary if str(item).strip()]
        if lines:
            return "\n".join(f"• {line}" for line in lines)
    return "A new CRAFT version is available."


def parse_update_manifest(
    payload: Mapping[str, Any],
    *,
    current_version: str,
) -> ApplicationUpdate | None:
    if payload.get("app_id") != "xrd_craft":
        raise UpdateManifestError("This update manifest is not for XRD CRAFT.")
    version = payload.get("version")
    if not isinstance(version, str):
        raise UpdateManifestError("The update version is missing.")
    if compare_versions(version, current_version) <= 0:
        return None
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateManifestError("The update installer list is missing.")
    installer = next(
        (
            item
            for item in assets
            if isinstance(item, Mapping)
            and item.get("type") == "installer"
            and item.get("platform") == "windows-x64"
        ),
        None,
    )
    if installer is None:
        raise UpdateManifestError("No Windows x64 installer is available for this update.")
    filename = installer.get("name")
    url = installer.get("url")
    size = installer.get("size_bytes")
    checksum = installer.get("sha256")
    if not isinstance(filename, str) or Path(filename).name != filename or not filename.lower().endswith(".exe"):
        raise UpdateManifestError("The update installer filename is unsafe.")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise UpdateManifestError("The update installer URL must use HTTPS.")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise UpdateManifestError("The update installer size is invalid.")
    if (
        not isinstance(checksum, str)
        or len(checksum) != 64
        or checksum != checksum.lower()
        or any(character not in "0123456789abcdef" for character in checksum)
    ):
        raise UpdateManifestError("The update installer SHA-256 is invalid.")
    return ApplicationUpdate(
        version=version,
        release_notes=_release_notes(payload),
        installer_url=url,
        installer_filename=filename,
        installer_size_bytes=size,
        installer_sha256=checksum,
    )


def fetch_update_manifest(
    *,
    manifest_url: str = CRAFT_UPDATE_MANIFEST_URL,
    urlopen: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        manifest_url,
        headers={"User-Agent": "XRD-CRAFT-Updater/1"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            data = response.read()
        payload = json.loads(data.decode("utf-8"))
    except Exception as error:
        raise UpdateCheckError(
            "Could not check for CRAFT updates. Check the internet connection and try again."
        ) from error
    if not isinstance(payload, Mapping):
        raise UpdateManifestError("The CRAFT update manifest is invalid.")
    return payload


def default_update_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Sci" / "downloads" / "updates" / "craft"
    return Path.home() / "AppData" / "Local" / "Sci" / "downloads" / "updates" / "craft"


def download_update(
    update: ApplicationUpdate,
    cache_root: Path | None = None,
    *,
    progress: Callable[[int, int], None] | None = None,
    urlopen: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> Path:
    application = ToolkitApplication(
        app_id="xrd_craft",
        name="XRD CRAFT",
        description="CRAFT application update",
        version=update.version,
        announcement_revision=0,
        installer_url=update.installer_url,
        installer_filename=update.installer_filename,
        installer_sha256=update.installer_sha256,
        installer_size_bytes=update.installer_size_bytes,
    )
    return download_installer(
        application,
        default_update_cache_root() if cache_root is None else Path(cache_root),
        progress=progress,
        urlopen=urlopen,
    )
