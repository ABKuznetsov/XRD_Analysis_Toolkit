"""Import crystal structures saved inside XRD Finder ``.xpff`` projects."""

from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.model import CrystalStructure


_MANIFEST = "project.json"
_MAX_CIF_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _StructureAsset:
    identity: str
    name: str
    member: str


def load_xpff_structures(path: str | Path) -> list[CrystalStructure]:
    """Load selected/saved structures without exposing Finder's candidate cache.

    Explicit ``structures`` and ``phases`` are imported first.  Candidate CIFs
    referenced by the project-level match and by every saved pattern profile
    follow in first-use order.  Unreferenced path-map entries are ignored.
    """
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    try:
        with zipfile.ZipFile(source) as archive:
            manifest = _read_manifest(archive)
            assets = _structure_assets(manifest)
            if not assets:
                raise ValueError("XPFF project contains no selected or saved crystal structures.")
            structures = [
                _load_asset(source, archive, asset)
                for asset in assets
            ]
    except zipfile.BadZipFile as error:
        raise ValueError(f"{source.name} is not a valid XPFF archive.") from error
    return structures


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = archive.read(_MANIFEST)
    except KeyError as error:
        raise ValueError("XPFF archive does not contain project.json.") from error
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("XPFF project.json is not valid UTF-8 JSON.") from error
    if not isinstance(data, dict):
        raise ValueError("XPFF project.json root must be an object.")
    return data


def _structure_assets(data: dict[str, Any]) -> list[_StructureAsset]:
    assets: list[_StructureAsset] = []
    seen_members: set[str] = set()

    for collection_name in ("structures", "phases"):
        records = data.get(collection_name, [])
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            member = str(record.get("source_path", "") or "").strip()
            if not member or member in seen_members:
                continue
            identity = str(record.get("id", "") or f"{collection_name}-{index + 1}")
            name = str(record.get("name", "") or identity)
            assets.append(_StructureAsset(identity, name, member))
            seen_members.add(member)

    finder_state = data.get("finder_state", {})
    if not isinstance(finder_state, dict):
        return assets
    candidates: list[Any] = []
    match_candidates = finder_state.get("match_candidates", [])
    if isinstance(match_candidates, list):
        candidates.extend(match_candidates)
    profile_states = finder_state.get("profile_states", {})
    if isinstance(profile_states, dict):
        for profile in profile_states.values():
            if not isinstance(profile, dict):
                continue
            profile_candidates = profile.get("candidates", [])
            if isinstance(profile_candidates, list):
                candidates.extend(profile_candidates)
    paths = finder_state.get("candidate_cif_paths", {})
    if not isinstance(paths, dict):
        return assets
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        source = str(
            candidate.get("Source", "") or candidate.get("Qual.", "") or "UNKNOWN"
        ).strip()
        entry = str(candidate.get("Entry", "") or candidate.get("Phase", "") or "unknown").strip()
        key = f"{source}:{entry}"
        member = str(paths.get(key, "") or "").strip()
        if not member:
            raise ValueError(f"Selected XPFF candidate {key} has no embedded CIF path.")
        if member in seen_members:
            continue
        phase_name = str(candidate.get("Phase", "") or candidate.get("Formula", "") or entry).strip()
        display_name = f"{phase_name} · {source} {entry}" if source != "UNKNOWN" else phase_name
        assets.append(_StructureAsset(key, display_name, member))
        seen_members.add(member)
    return assets


def _safe_member(member: str) -> str:
    raw_parts = member.split("/")
    path = PurePosixPath(member)
    if (
        not member.startswith("assets/")
        or "\\" in member
        or ":" in member
        or path.is_absolute()
        or path.suffix.lower() != ".cif"
        or any(part in {"", ".", ".."} for part in raw_parts)
    ):
        raise ValueError(f"Unsafe XPFF archive member: {member}")
    return path.as_posix()


def _load_asset(
    archive_path: Path,
    archive: zipfile.ZipFile,
    asset: _StructureAsset,
) -> CrystalStructure:
    member = _safe_member(asset.member)
    try:
        info = archive.getinfo(member)
    except KeyError as error:
        raise ValueError(
            f"XPFF structure {asset.identity} refers to missing archive member {member}."
        ) from error
    if info.file_size > _MAX_CIF_BYTES:
        raise ValueError(f"XPFF structure {asset.identity} is too large to import safely.")
    content = archive.read(info)
    with tempfile.TemporaryDirectory(prefix="crystal-blocks-xpff-") as directory:
        temporary = Path(directory) / "structure.cif"
        temporary.write_bytes(content)
        structure = load_cif(temporary)
    structure.name = asset.name
    structure.source_path = Path(f"{archive_path}#{asset.identity}")
    return structure


__all__ = ["load_xpff_structures"]
