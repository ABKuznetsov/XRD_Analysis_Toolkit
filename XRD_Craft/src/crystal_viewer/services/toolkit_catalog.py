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
    pass


class InstallerIntegrityError(RuntimeError):
    pass


class InstallerDownloadError(RuntimeError):
    pass


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


def _required_string(container: Mapping[str, Any], field: str, prefix: str) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CatalogUnavailableError(f"{prefix}.{field} must be a non-empty string.")
    return value.strip()


def _required_integer(container: Mapping[str, Any], field: str, prefix: str) -> int:
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
    for index, raw in enumerate(raw_applications):
        prefix = f"applications[{index}]"
        if not isinstance(raw, Mapping):
            raise CatalogUnavailableError(f"{prefix} must be an object.")
        app_id = _required_string(raw, "app_id", prefix)
        if app_id == current_app_id:
            continue
        if "windows" not in raw.get("platforms", ()):
            continue
        if "x86_64" not in raw.get("architectures", ()):
            continue
        installer = raw.get("installer")
        if not isinstance(installer, Mapping):
            raise CatalogUnavailableError(f"{prefix}.installer must be an object.")
        filename = _required_string(installer, "filename", f"{prefix}.installer")
        if Path(filename).name != filename or not filename.casefold().endswith(".exe"):
            raise CatalogUnavailableError(f"{prefix}.installer.filename is unsafe.")
        checksum = _required_string(installer, "sha256", f"{prefix}.installer").lower()
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise CatalogUnavailableError(f"{prefix}.installer.sha256 is invalid.")
        size = _required_integer(installer, "size_bytes", f"{prefix}.installer")
        if size <= 0:
            raise CatalogUnavailableError(f"{prefix}.installer.size_bytes must be positive.")
        applications.append(
            ToolkitApplication(
                app_id=app_id,
                name=_required_string(raw, "name", prefix),
                description=_required_string(raw, "description", prefix),
                version=_required_string(raw, "version", prefix),
                announcement_revision=_required_integer(raw, "announcement_revision", prefix),
                installer_url=_required_string(installer, "url", f"{prefix}.installer"),
                installer_filename=filename,
                installer_sha256=checksum,
                installer_size_bytes=size,
            )
        )
    return tuple(applications)


def _decode_catalog(data: bytes, source: str) -> Mapping[str, Any]:
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
    cache = default_catalog_cache_path() if cache_path is None else Path(cache_path)
    request = urllib.request.Request(
        catalog_url,
        headers={"User-Agent": "XRD-Analysis-Toolkit/1"},
    )
    remote_error: Exception | None = None
    try:
        with urlopen(request, timeout=15) as response:
            data = response.read()
        payload = _decode_catalog(data, catalog_url)
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
            return _decode_catalog(fallback.read_bytes(), str(fallback))
        except (OSError, CatalogUnavailableError):
            continue
    raise CatalogUnavailableError(
        "Could not load the XRD tools catalogue. Check the internet connection and try again."
    ) from remote_error


def cached_installer_path(app: ToolkitApplication, cache_root: Path | None = None) -> Path:
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
        return path.stat().st_size == app.installer_size_bytes and _sha256(path) == app.installer_sha256
    except OSError:
        return False


def download_installer(
    app: ToolkitApplication,
    cache_root: Path | None = None,
    *,
    progress: Callable[[int, int], None] | None = None,
    urlopen: Callable[..., BinaryIO] = urllib.request.urlopen,
) -> Path:
    target = cached_installer_path(app, cache_root)
    if installer_is_valid(target, app):
        if progress:
            progress(app.installer_size_bytes, app.installer_size_bytes)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    partial = target.with_name(target.name + ".part")
    request = urllib.request.Request(
        app.installer_url,
        headers={"User-Agent": "XRD-Analysis-Toolkit/1"},
    )
    received = 0
    try:
        with urlopen(request, timeout=60) as response, partial.open("wb") as output:
            while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                output.write(chunk)
                received += len(chunk)
                if progress:
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
