from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import zipfile
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path, PurePosixPath
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.phase import Phase
from xrd_finder.core.project import Project
from xrd_finder.core.result import AnalysisResult
from xrd_finder.core.series import SeriesAnalysis, SeriesPoint
from xrd_finder.core.structure import AtomSite, CellParameters, Structure


PORTABLE_PROJECT_SUFFIX = ".xpff"
PORTABLE_PROJECT_TYPE_NAME = "XRD Phase Finder File"
PORTABLE_MANIFEST_NAME = "project.json"


def _to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    return value


def save_project_manifest(project: Project, path: str | Path) -> None:
    project.prune_series_memberships()
    target = Path(path)
    if target.suffix.lower() == PORTABLE_PROJECT_SUFFIX:
        _save_portable_project(project, target)
        return
    target.write_text(json.dumps(_to_plain(project), indent=2), encoding="utf-8")


def load_project_manifest(path: str | Path) -> Project:
    source = Path(path)
    if source.suffix.lower() == PORTABLE_PROJECT_SUFFIX or zipfile.is_zipfile(source):
        return _load_portable_project(source)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Project manifest must contain a JSON object.")
    project = _from_dataclass(Project, data)
    project.root_path = str(source)
    project.prune_series_memberships()
    return project


def _save_portable_project(project: Project, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _to_plain(project)
    data["root_path"] = ""
    file_members: dict[str, str] = {}
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            _embed_collection_sources(archive, data.get("patterns", []), "xrd", ".xy", file_members)
            _embed_collection_sources(archive, data.get("phases", []), "cif", ".cif", file_members)
            _embed_collection_sources(archive, data.get("structures", []), "cif", ".cif", file_members)
            archive.writestr(
                PORTABLE_MANIFEST_NAME,
                json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"),
            )
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)


def _embed_collection_sources(
    archive: zipfile.ZipFile,
    records: Any,
    folder: str,
    default_suffix: str,
    file_members: dict[str, str],
) -> None:
    if not isinstance(records, list):
        return
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        raw_path = str(record.get("source_path", "") or "").strip()
        if not raw_path:
            continue
        source = Path(raw_path)
        if not source.is_file():
            continue
        try:
            source_key = str(source.resolve()).casefold()
        except OSError:
            source_key = str(source.absolute()).casefold()
        member = file_members.get(source_key)
        if member is None:
            record_id = _safe_member_stem(str(record.get("id", "") or f"item-{index + 1}"))
            suffix = source.suffix.lower() or default_suffix
            member = f"assets/{folder}/{record_id}{suffix}"
            archive.write(source, member)
            file_members[source_key] = member
        record["source_path"] = member


def _safe_member_stem(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return safe or "asset"


def _load_portable_project(source: Path) -> Project:
    with zipfile.ZipFile(source, mode="r") as archive:
        try:
            data = json.loads(archive.read(PORTABLE_MANIFEST_NAME).decode("utf-8-sig"))
        except KeyError as exc:
            raise ValueError(f"{PORTABLE_PROJECT_TYPE_NAME} does not contain {PORTABLE_MANIFEST_NAME}.") from exc
        if not isinstance(data, dict):
            raise ValueError("Project manifest must contain a JSON object.")
        project = _from_dataclass(Project, data)
        extraction_root = _portable_extraction_root(source)
        for item in [*project.patterns, *project.phases, *project.structures]:
            member = str(getattr(item, "source_path", "") or "")
            if not member.startswith("assets/"):
                continue
            extracted = _extract_portable_member(archive, member, extraction_root)
            item.source_path = str(extracted)
    project.root_path = str(source)
    project.prune_series_memberships()
    return project


def _portable_extraction_root(source: Path) -> Path:
    stat = source.stat()
    identity = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8", errors="surrogatepass")
    digest = hashlib.sha256(identity).hexdigest()[:20]
    root = Path(tempfile.gettempdir()) / "XRDPhaseFinder" / "projects" / digest
    root.mkdir(parents=True, exist_ok=True)
    return root


def _extract_portable_member(archive: zipfile.ZipFile, member: str, root: Path) -> Path:
    member_path = PurePosixPath(member)
    if member_path.is_absolute() or ".." in member_path.parts or not member_path.parts:
        raise ValueError(f"Unsafe file path in {PORTABLE_PROJECT_TYPE_NAME}: {member}")
    target = root.joinpath(*member_path.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member, mode="r") as source_stream, target.open("wb") as target_stream:
        while True:
            block = source_stream.read(1024 * 1024)
            if not block:
                break
            target_stream.write(block)
    return target


def _from_dataclass(cls: type, data: Any):
    if not isinstance(data, dict):
        return data
    values = {}
    type_hints = get_type_hints(cls)
    for field in fields(cls):
        if field.name in data:
            values[field.name] = _convert_value(type_hints.get(field.name, field.type), data[field.name])
    return cls(**values)


def _convert_value(annotation: Any, value: Any) -> Any:
    origin = get_origin(annotation)
    if origin is list:
        item_type = get_args(annotation)[0] if get_args(annotation) else Any
        return [_convert_value(item_type, item) for item in value or []]
    if origin in {UnionType, Union}:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        return None if value is None else _convert_value(args[0], value) if args else value
    if annotation in {
        Project,
        Pattern,
        Phase,
        Structure,
        CellParameters,
        AtomSite,
        AnalysisResult,
        SeriesAnalysis,
        SeriesPoint,
        FinderProjectState,
    }:
        return _from_dataclass(annotation, value)
    return value
