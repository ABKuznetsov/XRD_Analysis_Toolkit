from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, BinaryIO
import urllib.request


DOWNLOAD_CHUNK_SIZE = 1024 * 1024
TOOLKIT_CATALOG_URL = (
    "https://raw.githubusercontent.com/ABKuznetsov/"
    "XRD_Analysis_Toolkit/main/toolkit/catalog.json"
)


class CatalogUnavailableError(RuntimeError):
    """Raised when the catalogue cannot be parsed or fetched."""


class InstallerIntegrityError(RuntimeError):
    """Raised when downloaded installer bytes do not match the catalogue."""


class InstallerDownloadError(RuntimeError):
    """Raised when an installer download cannot be completed."""


@dataclass(frozen=True)
class ToolkitApplication:
    app_id: str
    name: str
    description: str
    version: str
    announcement_revision: int
    installer_url: str
    installer_filename: str
    installer_sha256: str
    installer_size_bytes: int


def default_toolkit_download_cache() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Sci" / "downloads" / "toolkit"
    return Path.home() / "AppData" / "Local" / "Sci" / "downloads" / "toolkit"


def default_catalog_cache_path() -> Path:
    return default_toolkit_download_cache() / "catalog.json"


def _decode_catalog(data: bytes, *, source: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogUnavailableError(f"Toolkit catalogue is invalid: {source}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        raise CatalogUnavailableError(f"Toolkit catalogue is unsupported: {source}")
    return payload


def load_catalog_payload(
    *,
    catalog_url: str = TOOLKIT_CATALOG_URL,
    cache_path: Path | None = None,
    bundled_path: Path | None = None,
    urlopen: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> Mapping[str, Any]:
    """Load the remote catalogue, falling back to cached or bundled JSON."""
    cache = default_catalog_cache_path() if cache_path is None else Path(cache_path)
    request = urllib.request.Request(
        catalog_url,
        headers={"User-Agent": "XRD-Analysis-Toolkit/1"},
    )
    remote_error: Exception | None = None
    try:
        with urlopen(request, timeout=15) as response:
            data = response.read()
        payload = _decode_catalog(data, source=catalog_url)
        cache.parent.mkdir(parents=True, exist_ok=True)
        partial = cache.with_name(cache.name + ".part")
        partial.write_bytes(data)
        partial.replace(cache)
        return payload
    except Exception as error:
        remote_error = error

    for fallback in (cache, Path(bundled_path) if bundled_path is not None else None):
        if fallback is None or not fallback.is_file():
            continue
        try:
            return _decode_catalog(fallback.read_bytes(), source=str(fallback))
        except (OSError, CatalogUnavailableError):
            continue

    raise CatalogUnavailableError(
        "Could not load the XRD tools catalogue. Check the internet connection and try again."
    ) from remote_error


def _required_string(container: Mapping[str, Any], field: str, *, prefix: str) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CatalogUnavailableError(f"{prefix}.{field} must be a non-empty string.")
    return value.strip()


def _required_integer(container: Mapping[str, Any], field: str, *, prefix: str) -> int:
    value = container.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CatalogUnavailableError(f"{prefix}.{field} must be an integer.")
    return value


def parse_catalog(
    payload: Mapping[str, Any],
    *,
    current_app_id: str,
) -> tuple[ToolkitApplication, ...]:
    if payload.get("schema_version") != 1:
        raise CatalogUnavailableError("Unsupported toolkit catalogue schema.")
    raw_applications = payload.get("applications")
    if not isinstance(raw_applications, list):
        raise CatalogUnavailableError("Toolkit catalogue applications are missing.")

    applications: list[ToolkitApplication] = []
    for index, raw_application in enumerate(raw_applications):
        prefix = f"applications[{index}]"
        if not isinstance(raw_application, Mapping):
            raise CatalogUnavailableError(f"{prefix} must be an object.")
        app_id = _required_string(raw_application, "app_id", prefix=prefix)
        if app_id == current_app_id:
            continue

        platforms = raw_application.get("platforms")
        architectures = raw_application.get("architectures")
        if not isinstance(platforms, list) or "windows" not in platforms:
            continue
        if not isinstance(architectures, list) or "x86_64" not in architectures:
            continue

        raw_installer = raw_application.get("installer")
        if not isinstance(raw_installer, Mapping):
            raise CatalogUnavailableError(f"{prefix}.installer must be an object.")
        filename = _required_string(raw_installer, "filename", prefix=f"{prefix}.installer")
        if Path(filename).name != filename or not filename.casefold().endswith(".exe"):
            raise CatalogUnavailableError(f"{prefix}.installer.filename is unsafe.")
        checksum = _required_string(raw_installer, "sha256", prefix=f"{prefix}.installer").lower()
        if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
            raise CatalogUnavailableError(f"{prefix}.installer.sha256 is invalid.")
        size_bytes = _required_integer(raw_installer, "size_bytes", prefix=f"{prefix}.installer")
        if size_bytes <= 0:
            raise CatalogUnavailableError(f"{prefix}.installer.size_bytes must be positive.")

        applications.append(
            ToolkitApplication(
                app_id=app_id,
                name=_required_string(raw_application, "name", prefix=prefix),
                description=_required_string(raw_application, "description", prefix=prefix),
                version=_required_string(raw_application, "version", prefix=prefix),
                announcement_revision=_required_integer(
                    raw_application,
                    "announcement_revision",
                    prefix=prefix,
                ),
                installer_url=_required_string(
                    raw_installer,
                    "url",
                    prefix=f"{prefix}.installer",
                ),
                installer_filename=filename,
                installer_sha256=checksum,
                installer_size_bytes=size_bytes,
            )
        )
    return tuple(applications)


def cached_installer_path(
    app: ToolkitApplication,
    cache_root: Path | None = None,
) -> Path:
    root = default_toolkit_download_cache() if cache_root is None else Path(cache_root)
    return root / app.app_id / app.version / app.installer_filename


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(DOWNLOAD_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def installer_is_valid(path: Path, app: ToolkitApplication) -> bool:
    try:
        if path.stat().st_size != app.installer_size_bytes:
            return False
        return _sha256(path) == app.installer_sha256
    except OSError:
        return False


def _open_response(
    urlopen: Callable[..., BinaryIO],
    request: urllib.request.Request,
) -> BinaryIO:
    return urlopen(request, timeout=60)


def download_installer(
    app: ToolkitApplication,
    cache_root: Path | None = None,
    *,
    progress: Callable[[int, int], None] | None = None,
    urlopen: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> Path:
    target = cached_installer_path(app, cache_root)
    if installer_is_valid(target, app):
        if progress is not None:
            progress(app.installer_size_bytes, app.installer_size_bytes)
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(
        app.installer_url,
        headers={"User-Agent": "XRD-Analysis-Toolkit/1"},
    )
    received = 0
    try:
        with _open_response(urlopen, request) as response, partial.open("wb") as output:
            while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                output.write(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, app.installer_size_bytes)
            output.flush()
            os.fsync(output.fileno())
    except Exception as error:
        raise InstallerDownloadError(
            f"Could not download {app.name}. The partial download was kept for Retry: {partial}"
        ) from error

    if received != app.installer_size_bytes:
        partial.unlink(missing_ok=True)
        raise InstallerIntegrityError(
            f"Downloaded installer size does not match the catalogue for {app.name}."
        )
    if _sha256(partial) != app.installer_sha256:
        partial.unlink(missing_ok=True)
        raise InstallerIntegrityError(
            f"Downloaded installer checksum does not match the catalogue for {app.name}."
        )

    partial.replace(target)
    return target
