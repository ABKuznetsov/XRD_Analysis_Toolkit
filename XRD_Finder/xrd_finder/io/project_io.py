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
from xrd_finder.io.analysis_summary import finalize_analysis_summary, verify_analysis_summary


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
    data = _to_plain(project)
    if data.get("analysis_summary"):
        data["analysis_summary"] = finalize_analysis_summary(data["analysis_summary"])
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_project_manifest(path: str | Path) -> Project:
    source = Path(path)
    if source.suffix.lower() == PORTABLE_PROJECT_SUFFIX or zipfile.is_zipfile(source):
        return _load_portable_project(source)
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("Project manifest must contain a JSON object.")
    verify_analysis_summary(data.get("analysis_summary", {}))
    project = _from_dataclass(Project, data)
    project.root_path = str(source)
    project.prune_series_memberships()
    return project


def _save_portable_project(project: Project, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _to_plain(project)
    data["root_path"] = ""
    if data.get("analysis_summary"):
        data["analysis_summary"] = finalize_analysis_summary(data["analysis_summary"])
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
            finder_state = data.get("finder_state", {})
            if isinstance(finder_state, dict):
                candidate_cif_paths = finder_state.get("candidate_cif_paths")
                if isinstance(candidate_cif_paths, dict):
                    finder_state["candidate_cif_paths"] = {
                        key: value
                        for key, value in candidate_cif_paths.items()
                        if str(key) in _referenced_candidate_keys(finder_state)
                    }
                _embed_path_mapping(
                    archive,
                    finder_state.get("candidate_cif_paths"),
                    "candidates",
                    ".cif",
                    file_members,
                )
                preview_paths = finder_state.get("analysis_preview_paths")
                if isinstance(preview_paths, dict):
                    _embed_preview_mapping(archive, preview_paths, file_members)
                    _rewrite_analysis_preview_paths(data.get("analysis_summary"), preview_paths)
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
        record_name = str(record.get("name", "") or record.get("id", "") or f"item-{index + 1}")
        if not source.is_file():
            raise ValueError(
                f"Cannot save {folder.upper()} asset for {record_name!r}: "
                f"source file is absent or unreadable: {raw_path}"
            )
        source_key = _source_path_key(source)
        member = file_members.get(source_key)
        if member is None:
            record_id = _safe_member_stem(str(record.get("id", "") or f"item-{index + 1}"))
            suffix = source.suffix.lower() or default_suffix
            member = f"assets/{folder}/{record_id}{suffix}"
            try:
                archive.write(source, member)
            except OSError as exc:
                raise ValueError(
                    f"Cannot save {folder.upper()} asset for {record_name!r}: "
                    f"source file is absent or unreadable: {raw_path}"
                ) from exc
            file_members[source_key] = member
        record["source_path"] = member


def _embed_path_mapping(
    archive: zipfile.ZipFile,
    paths: Any,
    folder: str,
    default_suffix: str,
    file_members: dict[str, str],
) -> None:
    """Rewrite local mapping values to deduplicated ZIP member paths."""
    if not isinstance(paths, dict):
        return
    for key, raw_path in paths.items():
        source_path = str(raw_path or "").strip()
        source = Path(source_path)
        if not source_path or not source.is_file():
            raise ValueError(f"Candidate CIF for {key!r} is absent or unreadable: {source_path}")
        source_key = _source_path_key(source)
        member = file_members.get(source_key)
        if member is None:
            suffix = source.suffix.lower() or default_suffix
            key_text = str(key)
            key_digest = hashlib.sha256(key_text.encode("utf-8", errors="surrogatepass")).hexdigest()[:12]
            member = f"assets/{folder}/{_safe_member_stem(key_text)}-{key_digest}{suffix}"
            try:
                archive.write(source, member)
            except OSError as exc:
                raise ValueError(f"Candidate CIF for {key!r} is absent or unreadable: {source_path}") from exc
            file_members[source_key] = member
        paths[key] = member


def _source_path_key(source: Path) -> str:
    """Return a resolved deduplication key using the host filesystem's case rules."""
    try:
        resolved = source.resolve()
    except OSError:
        resolved = source.absolute()
    return os.path.normcase(str(resolved))


def _referenced_candidate_keys(finder_state: dict[str, Any]) -> set[str]:
    candidate_records: list[Any] = []
    match_candidates = finder_state.get("match_candidates", [])
    if isinstance(match_candidates, list):
        candidate_records.extend(match_candidates)
    profile_states = finder_state.get("profile_states", {})
    if isinstance(profile_states, dict):
        for state in profile_states.values():
            if isinstance(state, dict):
                candidates = state.get("candidates", [])
                if isinstance(candidates, list):
                    candidate_records.extend(candidates)
    keys: set[str] = set()
    for candidate in candidate_records:
        if not isinstance(candidate, dict):
            continue
        source = str(candidate.get("Source", "") or candidate.get("Qual.", ""))
        entry = str(candidate.get("Entry", ""))
        if source or entry:
            keys.add(f"{source}:{entry}")
    return keys


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
        verify_analysis_summary(data.get("analysis_summary", {}))
        project = _from_dataclass(Project, data)
        extraction_root = _portable_extraction_root(source)
        for item in [*project.patterns, *project.phases, *project.structures]:
            member = str(getattr(item, "source_path", "") or "")
            if not member.startswith("assets/"):
                continue
            extracted = _extract_portable_member(archive, member, extraction_root)
            item.source_path = str(extracted)
        project.finder_state.candidate_cif_paths = _extract_path_mapping(
            archive,
            project.finder_state.candidate_cif_paths,
            extraction_root,
        )
        project.finder_state.analysis_preview_paths = _extract_path_mapping(
            archive,
            project.finder_state.analysis_preview_paths,
            extraction_root,
            allowed_prefix="previews/",
        )
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


def _extract_path_mapping(
    archive: zipfile.ZipFile,
    paths: dict[str, str],
    extraction_root: Path,
    *,
    allowed_prefix: str = "assets/",
) -> dict[str, str]:
    """Return candidate keys mapped to project-private extracted paths."""
    if not isinstance(paths, dict):
        return {}
    extracted_paths: dict[str, str] = {}
    for key, member in paths.items():
        member_path = str(member or "").strip()
        if not member_path:
            continue
        extracted_paths[str(key)] = str(
            _extract_portable_member(archive, member_path, extraction_root, allowed_prefix=allowed_prefix)
        )
    return extracted_paths


def _extract_portable_member(
    archive: zipfile.ZipFile,
    member: str,
    root: Path,
    *,
    allowed_prefix: str = "assets/",
) -> Path:
    raw_parts = member.split("/")
    member_path = PurePosixPath(member)
    if (
        not member.startswith(allowed_prefix)
        or "\\" in member
        or ":" in member
        or any(part in {"", ".", ".."} for part in raw_parts)
        or member_path.is_absolute()
        or not member_path.parts
    ):
        raise ValueError(f"Unsafe file path in {PORTABLE_PROJECT_TYPE_NAME}: {member}")
    resolved_root = root.resolve()
    target = resolved_root.joinpath(*member_path.parts).resolve()
    if target == resolved_root or resolved_root not in target.parents:
        raise ValueError(f"Unsafe file path in {PORTABLE_PROJECT_TYPE_NAME}: {member}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member, mode="r") as source_stream, target.open("wb") as target_stream:
        while True:
            block = source_stream.read(1024 * 1024)
            if not block:
                break
            target_stream.write(block)
    return target


def _embed_preview_mapping(
    archive: zipfile.ZipFile,
    paths: dict[str, str],
    file_members: dict[str, str],
) -> None:
    for pattern_id, raw_path in paths.items():
        source = Path(str(raw_path or "").strip())
        if not source.is_file():
            raise ValueError(f"Analysis preview for {pattern_id!r} is absent or unreadable: {source}")
        source_key = _source_path_key(source)
        member = file_members.get(source_key)
        if member is None or not member.startswith("previews/"):
            member = f"previews/{_safe_member_stem(str(pattern_id))}.png"
            archive.write(source, member)
            file_members[source_key] = member
        paths[pattern_id] = member


def _rewrite_analysis_preview_paths(summary: Any, preview_paths: dict[str, str]) -> None:
    if not isinstance(summary, dict):
        return
    patterns = summary.get("patterns")
    if not isinstance(patterns, list):
        return
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        pattern_id = str(pattern.get("pattern_id", "") or "")
        if pattern_id in preview_paths:
            pattern["preview_path"] = preview_paths[pattern_id]


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
