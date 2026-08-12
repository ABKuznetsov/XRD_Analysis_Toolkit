"""Versioned scientific-result contract stored inside portable XPFF projects."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import math
from typing import Any

import rfc8785


_EXCLUDED_RESULT_KEYS = {
    "analysis_id",
    "generated_at",
    "preview_path",
    "producer",
    "result_sha256",
    "revision_id",
    "sample_ref",
}


def scientific_projection(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return the deterministic scientific subset covered by ``result_sha256``."""
    if not isinstance(summary, Mapping):
        raise ValueError("analysis_summary must be a JSON object")
    projected = _project_value(deepcopy(dict(summary)))
    if not isinstance(projected, dict):
        raise ValueError("analysis_summary must be a JSON object")

    patterns = projected.get("patterns")
    if isinstance(patterns, list):
        referenced_phase_ids = {
            str(phase.get("phase_id", ""))
            for pattern in patterns
            if isinstance(pattern, dict)
            for phase in pattern.get("phases", [])
            if isinstance(phase, dict) and str(phase.get("phase_id", ""))
        }
        phase_catalog = projected.get("phase_catalog")
        if isinstance(phase_catalog, list):
            projected["phase_catalog"] = [
                phase
                for phase in phase_catalog
                if isinstance(phase, dict) and str(phase.get("phase_id", "")) in referenced_phase_ids
            ]
    return projected


def compute_result_sha256(summary: Mapping[str, Any]) -> str:
    """Hash the RFC 8785/JCS representation of the scientific projection."""
    projection = scientific_projection(summary)
    try:
        canonical_json = rfc8785.dumps(projection)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise ValueError(f"analysis_summary is not RFC 8785 compatible: {exc}") from exc
    return hashlib.sha256(canonical_json).hexdigest()


def finalize_analysis_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Return a detached summary with a freshly computed scientific hash."""
    finalized = deepcopy(dict(summary))
    finalized["result_sha256"] = compute_result_sha256(finalized)
    return finalized


def verify_analysis_summary(summary: Mapping[str, Any]) -> None:
    """Reject a stored summary whose scientific payload no longer matches its hash."""
    if not summary:
        return
    stored_hash = str(summary.get("result_sha256", "") or "").strip().lower()
    if len(stored_hash) != 64 or any(character not in "0123456789abcdef" for character in stored_hash):
        raise ValueError("analysis_summary result_sha256 is missing or invalid")
    calculated_hash = compute_result_sha256(summary)
    if stored_hash != calculated_hash:
        raise ValueError(
            "analysis_summary result_sha256 does not match the stored scientific result"
        )


def _project_value(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, Mapping):
        projected = {
            str(key): _project_value(item, parent_key=str(key))
            for key, item in value.items()
            if str(key) not in _EXCLUDED_RESULT_KEYS
        }
        return projected
    if isinstance(value, list):
        items = [_project_value(item, parent_key=parent_key) for item in value]
        if parent_key in {"phase_catalog", "phases"}:
            return sorted(items, key=lambda item: _text_sort_key(item, "phase_id"))
        if parent_key == "patterns":
            return sorted(items, key=lambda item: _text_sort_key(item, "pattern_id"))
        if parent_key == "unknown_peaks":
            return sorted(items, key=_unknown_peak_sort_key)
        return items
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("analysis_summary contains NaN or Infinity")
    return value


def _text_sort_key(value: Any, key: str) -> str:
    return str(value.get(key, "")) if isinstance(value, Mapping) else ""


def _unknown_peak_sort_key(value: Any) -> tuple[float, float]:
    if not isinstance(value, Mapping):
        return math.inf, math.inf
    return _finite_sort_number(value.get("two_theta")), _finite_sort_number(value.get("intensity"))


def _finite_sort_number(value: Any) -> float:
    if value is None:
        return math.inf
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.inf
    return number if math.isfinite(number) else math.inf
