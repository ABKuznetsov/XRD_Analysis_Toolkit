from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable

from xrd_finder.finder.fingerprint_matching import fingerprint_match_score
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    radiation_lines_from_wavelength,
)


CandidateRow = list[str]
ReferencePeakLoader = Callable[[CandidateRow], Iterable[object]]
ProgressCallback = Callable[[str, int, int], None]

FINGERPRINT_PRIORITY_REFINE_LIMIT = 40
MATCH_PRIORITY_REFINE_LIMIT = 60


@dataclass(frozen=True, slots=True)
class AutoSearchRankingResult:
    rows: list[CandidateRow]
    scored_keys: set[tuple[str, str]]
    matched_count: int


def rank_candidate_rows(
    rows: list[CandidateRow],
    observed_records,
    *,
    wavelength: float,
    reference_peak_loader: ReferencePeakLoader,
    rank_limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> AutoSearchRankingResult:
    """Rank the initial local auto-search pool without touching Qt objects."""

    normalized_rows = [_normalized_row(row) for row in rows]
    limit = (
        len(normalized_rows)
        if rank_limit is None
        else min(len(normalized_rows), max(0, int(rank_limit)))
    )
    scored_rows: list[tuple[float, int, CandidateRow, list[object]]] = []
    scored_keys: set[tuple[str, str]] = set()
    matched_count = 0

    for index, original in enumerate(normalized_rows[:limit]):
        row = list(original)
        row[5] = ""
        row[6] = ""
        source = row[0].strip().upper()
        entry_id = row[1].strip()
        if source and entry_id:
            scored_keys.add((source, entry_id))
        try:
            reference_peaks = list(reference_peak_loader(row))
            probability = fingerprint_match_score(
                reference_peaks,
                observed_records,
                wavelength=float(wavelength),
                refine_alignment=False,
            ).score
        except Exception:
            reference_peaks = []
            probability = 0.0
        if probability > 0.0:
            row[5] = f"{probability:.0f}%"
            matched_count += 1
        scored_rows.append((float(probability), index, row, reference_peaks))
        if progress is not None and (index == 0 or (index + 1) % 25 == 0):
            progress("Ranking local candidates", index + 1, limit)

    if progress is not None:
        progress("Ranking local candidates", limit, limit)

    # Refine a bounded union. The first rows carry the geometric-fingerprint
    # retrieval order, while the second group carries the quick Match order.
    # This lets shifted phases recover without running the expensive fit for
    # the complete shortlist.
    refine_indices = set(range(min(FINGERPRINT_PRIORITY_REFINE_LIMIT, len(scored_rows))))
    quick_order = sorted(scored_rows, key=lambda item: (-item[0], item[1]))
    refine_indices.update(
        item[1]
        for item in quick_order[: min(MATCH_PRIORITY_REFINE_LIMIT, len(quick_order))]
    )
    refined_rows: list[tuple[float, int, CandidateRow, list[object]]] = []
    for probability, index, row, reference_peaks in scored_rows:
        if index in refine_indices and len(reference_peaks) >= 3:
            try:
                probability = fingerprint_match_score(
                    reference_peaks,
                    observed_records,
                    wavelength=float(wavelength),
                    refine_alignment=True,
                ).score
            except Exception:
                pass
            row[5] = f"{probability:.0f}%" if probability > 0.0 else ""
        refined_rows.append((float(probability), index, row, reference_peaks))
    scored_rows = refined_rows

    if any(probability > 0.0 for probability, _index, _row, _peaks in scored_rows):
        scored_rows.sort(key=lambda item: (-item[0], item[1]))
    ranked = [row for _probability, _index, row, _peaks in scored_rows]
    ranked.extend(normalized_rows[limit:])
    return AutoSearchRankingResult(
        rows=ranked,
        scored_keys=scored_keys,
        matched_count=matched_count,
    )


def create_local_reference_peak_loader(
    cache_root: str | Path,
    pdf2_root: str | Path | None,
    wavelength: float,
) -> ReferencePeakLoader:
    """Create a worker-owned loader for the local structural and PDF-2 indexes."""

    # Imports are intentionally local. The pure ranking function remains usable
    # in lightweight test environments, while each worker owns its DB services.
    from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION, LocalPhaseCache
    from xrd_finder.services.match_pdf2_service import MatchPdf2Service

    cache = LocalPhaseCache(cache_root)
    pdf2 = MatchPdf2Service(pdf2_root) if pdf2_root else None
    active_wavelength = float(wavelength)
    primary_wavelength = radiation_lines_from_wavelength(
        active_wavelength,
        include_kalpha2=False,
    )[0][0]

    def load(row: CandidateRow) -> list[object]:
        source = row[0].strip().upper() if row else ""
        entry_id = row[1].strip() if len(row) > 1 else ""
        if not source or not entry_id:
            return []
        if source == "PDF2":
            if pdf2 is None:
                return []
            return _pdf2_reference_peaks(
                pdf2.diffraction_peaks(entry_id),
                active_wavelength,
            )
        if source not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"}:
            return []
        entry = cache.get(source, entry_id)
        if entry is None or int(entry.derived_version or 0) != DERIVED_CACHE_VERSION:
            return []
        return _cached_reference_peaks(
            cache.peak_records(source, entry_id),
            primary_wavelength,
        )

    return load


def _normalized_row(row: CandidateRow) -> CandidateRow:
    result = [str(value or "") for value in row[:8]]
    result.extend([""] * (8 - len(result)))
    return result


def _cached_reference_peaks(records, wavelength: float) -> list[object]:
    peaks = []
    use_cached_angles = math.isclose(
        float(wavelength),
        CU_KA1_WAVELENGTH,
        rel_tol=0.0,
        abs_tol=1.0e-4,
    )
    for record in records:
        try:
            d_spacing = float(record.get("d", 0.0) or 0.0)
            two_theta = float(record.get("two_theta", 0.0) or 0.0)
            normalized_intensity = float(record.get("norm_intensity", 0.0) or 0.0)
            intensity = max(
                100.0 * normalized_intensity
                if normalized_intensity > 0.0
                else float(record.get("intensity", 0.0) or 0.0),
                0.0,
            )
            if not use_cached_angles:
                two_theta = _two_theta_from_d(d_spacing, wavelength)
            if not 5.0 <= two_theta <= 120.0 or intensity <= 0.0:
                continue
            peaks.append(SimpleNamespace(two_theta=two_theta, intensity=intensity))
        except (TypeError, ValueError):
            continue
    return peaks


def _pdf2_reference_peaks(records, wavelength: float) -> list[object]:
    peaks = []
    for record in records:
        try:
            two_theta = _two_theta_from_d(float(record.d_spacing), wavelength)
            intensity = max(float(record.intensity), 0.0)
            if 5.0 <= two_theta <= 120.0 and intensity > 0.0:
                peaks.append(SimpleNamespace(two_theta=two_theta, intensity=intensity))
        except (TypeError, ValueError):
            continue
    return peaks


def _two_theta_from_d(d_spacing: float, wavelength: float) -> float:
    if d_spacing <= 0.0:
        return 0.0
    argument = float(wavelength) / (2.0 * float(d_spacing))
    if not 0.0 < argument <= 1.0:
        return 0.0
    return math.degrees(2.0 * math.asin(argument))


__all__ = [
    "AutoSearchRankingResult",
    "create_local_reference_peak_loader",
    "rank_candidate_rows",
]
