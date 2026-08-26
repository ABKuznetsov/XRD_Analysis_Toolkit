from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlparse


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class CatalogInstaller:
    url: str
    filename: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class CatalogApplication:
    app_id: str
    name: str
    description: str
    version: str
    announcement_revision: int
    platforms: tuple[str, ...]
    architectures: tuple[str, ...]
    update_manifest_url: str
    installer: CatalogInstaller


def _is_https(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _non_empty_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def validate_catalog(
    payload: Mapping[str, Any],
    *,
    allow_unbuilt: bool = False,
) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    applications = payload.get("applications")
    if not isinstance(applications, list) or not applications:
        return errors + ["applications must be a non-empty list"]

    seen_ids: set[str] = set()
    for index, raw_application in enumerate(applications):
        prefix = f"applications[{index}]"
        if not isinstance(raw_application, Mapping):
            errors.append(f"{prefix} must be an object")
            continue

        app_id = raw_application.get("app_id")
        if not isinstance(app_id, str) or not app_id.strip():
            errors.append(f"{prefix}.app_id must be a non-empty string")
        elif app_id in seen_ids:
            errors.append(f"{prefix}.app_id is duplicated: {app_id}")
        else:
            seen_ids.add(app_id)

        for field in ("name", "description", "icon"):
            value = raw_application.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} must be a non-empty string")

        version = raw_application.get("version")
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            errors.append(f"{prefix}.version must use MAJOR.MINOR.PATCH")

        revision = raw_application.get("announcement_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            errors.append(f"{prefix}.announcement_revision must be a non-negative integer")

        if not _non_empty_strings(raw_application.get("platforms")):
            errors.append(f"{prefix}.platforms must be a non-empty string list")
        if not _non_empty_strings(raw_application.get("architectures")):
            errors.append(f"{prefix}.architectures must be a non-empty string list")
        if not _is_https(raw_application.get("update_manifest_url")):
            errors.append(f"{prefix}.update_manifest_url must be an HTTPS URL")

        installer = raw_application.get("installer")
        if not isinstance(installer, Mapping):
            errors.append(f"{prefix}.installer must be an object")
            continue
        if not _is_https(installer.get("url")):
            errors.append(f"{prefix}.installer.url must be an HTTPS URL")
        filename = installer.get("filename")
        if not isinstance(filename, str) or not filename.lower().endswith(".exe"):
            errors.append(f"{prefix}.installer.filename must name a Windows EXE")
        size_bytes = installer.get("size_bytes")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
            errors.append(f"{prefix}.installer.size_bytes must be a positive integer")
        checksum = installer.get("sha256")
        if not isinstance(checksum, str) or not _SHA256_RE.fullmatch(checksum):
            errors.append(f"{prefix}.installer.sha256 must be lowercase SHA-256")
        elif checksum == "0" * 64 and not allow_unbuilt:
            errors.append(f"{prefix}.installer.sha256 contains an unbuilt SHA-256 placeholder")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the XRD toolkit application catalogue.")
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--allow-unbuilt", action="store_true")
    args = parser.parse_args(argv)

    payload = json.loads(args.catalog.read_text(encoding="utf-8"))
    errors = validate_catalog(payload, allow_unbuilt=args.allow_unbuilt)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Catalogue is valid: {args.catalog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
