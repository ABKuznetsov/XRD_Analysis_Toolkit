"""Build the public XPFF analysis summary from saved per-pattern results."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any
import uuid

from xrd_finder.core.base import utc_now
from xrd_finder.core.project import Project
from xrd_finder.io.analysis_summary import finalize_analysis_summary


def result_snapshot(
    result: Any,
    candidate_by_key: dict[str, dict[str, str]],
    *,
    fit_score_percent: float,
    explained_peaks: int,
    total_peaks: int,
) -> dict[str, Any]:
    """Serialize one already calculated Finder result without recomputing it."""
    phases = []
    for candidate_result in getattr(result, "candidates", []) or []:
        candidate = candidate_by_key.get(str(getattr(candidate_result, "entry_id", "")))
        if not isinstance(candidate, dict):
            continue
        source = str(candidate.get("Source", "") or candidate.get("Qual.", "") or "").strip().upper()
        source_id = str(candidate.get("Entry", "") or "").strip()
        phase_record = {
                "phase_id": _stable_phase_id({
                    "source": source,
                    "source_id": source_id,
                    "formula": str(candidate.get("Formula", "") or ""),
                    "name": str(candidate.get("_DisplayName", "") or candidate.get("Phase", "") or ""),
                }),
                "name": str(
                    candidate.get("_DisplayName", "")
                    or candidate.get("Phase", "")
                    or candidate.get("Name", "")
                    or source_id
                ),
                "formula": str(candidate.get("Formula", "") or ""),
                "source": source,
                "source_id": source_id,
                "fraction_percent": _nullable_finite_float(
                    getattr(candidate_result, "quantity_percent", None)
                ),
            }
        structure_sha256 = _candidate_structure_sha256(candidate)
        if structure_sha256:
            phase_record["structure_sha256"] = structure_sha256
        phases.append(phase_record)

    unknown_peaks = []
    for peak in getattr(result, "observed_peaks", []) or []:
        if getattr(peak, "assignments", None):
            continue
        two_theta = _nullable_finite_float(getattr(peak, "two_theta", None))
        intensity = _nullable_finite_float(getattr(peak, "intensity", None))
        if two_theta is None:
            continue
        unknown_peaks.append(
            {
                "two_theta": two_theta,
                "intensity": intensity,
                "significance": None,
            }
        )

    return {
        "phases": phases,
        "quantification": {
            "method": "profile_scale_cell_mass",
            "is_estimate": True,
        },
        "fit": {
            "score_percent": float(fit_score_percent),
            "explained_peaks": int(explained_peaks),
            "total_peaks": int(total_peaks),
            "unknown_peak_count": len(unknown_peaks),
        },
        "unknown_peaks": unknown_peaks,
        "preview_path": None,
    }


def build_analysis_summary(
    project: Project,
    producer_version: str,
    *,
    generated_at: str | None = None,
    revision_id: str | None = None,
) -> dict[str, Any]:
    """Create one deduplicated summary from results already calculated by Finder."""
    existing = deepcopy(project.analysis_summary) if isinstance(project.analysis_summary, dict) else {}
    phase_catalog: dict[str, dict[str, Any]] = {}
    patterns: list[dict[str, Any]] = []
    pattern_by_id = {pattern.id: pattern for pattern in project.patterns}
    profile_states = project.finder_state.profile_states or {}
    sample_refs = project.finder_state.pattern_sample_refs or {}
    preview_paths = project.finder_state.analysis_preview_paths or {}

    for pattern_id in sorted(pattern_by_id):
        state = profile_states.get(pattern_id, {})
        snapshot = state.get("result_snapshot") if isinstance(state, dict) else None
        if not isinstance(snapshot, dict):
            continue
        phase_references = []
        for phase in snapshot.get("phases", []) or []:
            if not isinstance(phase, dict):
                continue
            phase_id = str(phase.get("phase_id", "") or _stable_phase_id(phase))
            catalog_entry = {
                "phase_id": phase_id,
                "name": str(phase.get("name", "") or ""),
                "formula": str(phase.get("formula", "") or ""),
                "source": str(phase.get("source", "") or ""),
                "source_id": str(phase.get("source_id", "") or ""),
            }
            structure_sha256 = str(phase.get("structure_sha256", "") or "")
            if structure_sha256:
                catalog_entry["structure_sha256"] = structure_sha256
            phase_catalog.setdefault(phase_id, catalog_entry)
            fraction = phase.get("fraction_percent")
            phase_references.append(
                {
                    "phase_id": phase_id,
                    "fraction_percent": None if fraction is None else float(fraction),
                }
            )

        sample_ref = sample_refs.get(pattern_id)
        pattern = pattern_by_id[pattern_id]
        patterns.append(
            {
                "pattern_id": pattern_id,
                "title": pattern.name,
                "sample_ref": deepcopy(sample_ref) if isinstance(sample_ref, dict) else None,
                "phases": phase_references,
                "quantification": deepcopy(
                    snapshot.get(
                        "quantification",
                        {"method": "profile_scale_cell_mass", "is_estimate": True},
                    )
                ),
                "fit": deepcopy(snapshot.get("fit", {})),
                "unknown_peaks": deepcopy(snapshot.get("unknown_peaks", [])),
                "preview_path": preview_paths.get(pattern_id) or snapshot.get("preview_path"),
            }
        )

    if not patterns:
        return existing

    analysis_id = str(existing.get("analysis_id", "") or f"ANL-{uuid.uuid4()}")
    candidate = {
        "schema_version": 1,
        "analysis_id": analysis_id,
        "revision_id": revision_id or f"REV-{uuid.uuid4()}",
        "generated_at": generated_at or utc_now(),
        "producer": {
            "application": "XRD Phase Finder",
            "version": str(producer_version),
        },
        "phase_catalog": list(phase_catalog.values()),
        "patterns": patterns,
    }
    finalized = finalize_analysis_summary(candidate)
    if existing.get("result_sha256") == finalized["result_sha256"]:
        finalized["revision_id"] = str(existing.get("revision_id", "") or finalized["revision_id"])
        finalized["generated_at"] = str(existing.get("generated_at", "") or finalized["generated_at"])
    return finalized


def _stable_phase_id(phase: dict[str, Any]) -> str:
    source = str(phase.get("source", "") or "").strip().upper()
    source_id = str(phase.get("source_id", "") or "").strip()
    if source_id:
        identity = f"xrd-phase:{source}:{source_id}"
    else:
        formula = str(phase.get("formula", "") or "").strip()
        name = str(phase.get("name", "") or "").strip()
        identity = f"xrd-phase:{source}:{formula}:{name}"
    return f"PHASE-{uuid.uuid5(uuid.NAMESPACE_URL, identity)}"


def _nullable_finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _candidate_structure_sha256(candidate: dict[str, Any]) -> str:
    raw_path = str(candidate.get("_CifPath", "") or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()
