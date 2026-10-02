from __future__ import annotations

import math
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from xrd_finder.services.gain_shortlist import (
    rare_line_candidate_scores,
    residual_peak_is_explained,
    significant_residual_records,
)
from xrd_finder.services.residual_geometry import (
    ResidualGeometryIndex,
    residual_geometry_scores,
)


RETRIEVAL_CHANNELS = ("strong", "rare", "geometry", "overlap")


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    phase_id: str
    channel: str
    score: float
    rank: int
    evidence_count: int


@dataclass(frozen=True, slots=True)
class RetrievalChannelRun:
    channel: str
    hits: tuple[RetrievalHit, ...]
    elapsed_seconds: float
    diagnostic: str = ""


def rank_channel_scores(
    channel: str,
    scores: Mapping[str, float],
    evidence_counts: Mapping[str, int],
    *,
    limit: int,
) -> RetrievalChannelRun:
    """Return finite positive channel scores in deterministic rank order."""

    started = time.perf_counter()
    ranked: list[tuple[float, str, int]] = []
    for raw_phase_id, raw_score in scores.items():
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score) or score <= 0.0:
            continue
        phase_id = str(raw_phase_id)
        raw_evidence = evidence_counts.get(
            raw_phase_id, evidence_counts.get(phase_id, 0)
        )
        try:
            evidence_count = max(0, int(raw_evidence))
        except (TypeError, ValueError, OverflowError):
            evidence_count = 0
        ranked.append((score, phase_id, evidence_count))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = ranked[: max(0, int(limit))]
    hits = tuple(
        RetrievalHit(
            phase_id=phase_id,
            channel=str(channel),
            score=score,
            rank=rank,
            evidence_count=evidence_count,
        )
        for rank, (score, phase_id, evidence_count) in enumerate(
            selected, start=1
        )
    )
    elapsed = max(0.0, time.perf_counter() - started)
    return RetrievalChannelRun(
        channel=str(channel),
        hits=hits,
        elapsed_seconds=elapsed,
    )


def strong_residual_channel(
    candidate_peaks: Mapping[str, Iterable[object]],
    residual_records: Iterable[object],
    *,
    limit: int,
    tolerance: float = 0.45,
) -> RetrievalChannelRun:
    """Rank candidates by confidence-weighted support of strong residual lines."""

    started = time.perf_counter()
    records = significant_residual_records(residual_records)
    prepared_records = _weighted_residual_records(records)
    scores: dict[str, float] = {}
    evidence_counts: dict[str, int] = {}
    width = max(float(tolerance), 0.05)
    for raw_phase_id, peaks in candidate_peaks.items():
        phase_id = str(raw_phase_id)
        lines = _candidate_lines(peaks)
        score = 0.0
        evidence = 0
        for position, residual_weight in prepared_records:
            best = 0.0
            for candidate_position, candidate_weight in lines:
                delta = abs(candidate_position - position)
                if delta > width:
                    continue
                proximity = math.exp(-0.5 * (delta / width) ** 2)
                best = max(best, proximity * math.sqrt(candidate_weight))
            if best > 0.0:
                score += residual_weight * best
                evidence += 1
        scores[phase_id] = float(score)
        evidence_counts[phase_id] = evidence
    ranked = rank_channel_scores(
        "strong", scores, evidence_counts, limit=limit
    )
    return _with_total_elapsed(ranked, started)


def rare_line_channel(
    candidate_peaks: Mapping[str, Iterable[object]],
    residual_records: Iterable[object],
    *,
    limit: int,
    tolerance: float = 0.45,
) -> RetrievalChannelRun:
    """Rank candidates through the existing inverse-frequency line scorer."""

    started = time.perf_counter()
    records = significant_residual_records(residual_records)
    raw_scores = rare_line_candidate_scores(
        candidate_peaks,
        records,
        tolerance=tolerance,
    )
    evidence_counts = _matched_evidence_counts(
        candidate_peaks,
        records,
        tolerance=tolerance,
    )
    scores = {str(key): float(value) for key, value in raw_scores.items()}
    counts = {
        str(key): int(value) for key, value in evidence_counts.items()
    }
    ranked = rank_channel_scores("rare", scores, counts, limit=limit)
    return _with_total_elapsed(ranked, started)


def geometry_channel(
    index: ResidualGeometryIndex,
    residual_records: Iterable[object],
    *,
    limit: int,
) -> RetrievalChannelRun:
    """Rank candidates by common-zero-invariant pair/triplet evidence."""

    started = time.perf_counter()
    scores, evidence_counts = residual_geometry_scores(index, residual_records)
    ranked = rank_channel_scores(
        "geometry", scores, evidence_counts, limit=limit
    )
    return _with_total_elapsed(ranked, started)


def overlap_deficit_channel(
    candidate_peaks: Mapping[str, Iterable[object]],
    overlap_records: Iterable[object],
    *,
    limit: int,
    tolerance: float = 0.45,
) -> RetrievalChannelRun:
    """Rank candidates only from noise-significant accepted-profile deficits."""

    started = time.perf_counter()
    deficits: list[object] = []
    for record in overlap_records:
        has_explicit_model = any(
            hasattr(record, attribute)
            for attribute in (
                "observed_height",
                "calculated_height",
                "residual_height",
                "noise_floor",
            )
        )
        if has_explicit_model:
            try:
                observed = float(
                    getattr(record, "observed_height", getattr(record, "height", 0.0))
                    or 0.0
                )
                calculated = float(getattr(record, "calculated_height", 0.0) or 0.0)
                residual = float(
                    getattr(record, "residual_height", getattr(record, "height", 0.0))
                    or 0.0
                )
                noise = float(getattr(record, "noise_floor", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if residual_peak_is_explained(
                observed_height=observed,
                calculated_height=calculated,
                residual_height=residual,
                noise_floor=noise,
                overlaps_accepted_phase=bool(
                    getattr(record, "overlaps_accepted_phase", True)
                ),
            ):
                continue
        deficits.append(record)
    strong = strong_residual_channel(
        candidate_peaks,
        deficits,
        limit=max(len(candidate_peaks), int(limit)),
        tolerance=tolerance,
    )
    scores = {hit.phase_id: hit.score for hit in strong.hits}
    counts = {hit.phase_id: hit.evidence_count for hit in strong.hits}
    ranked = rank_channel_scores("overlap", scores, counts, limit=limit)
    return _with_total_elapsed(ranked, started)


def _weighted_residual_records(
    records: Iterable[object],
) -> tuple[tuple[float, float], ...]:
    parsed: list[tuple[float, float, float | None, float, float | None]] = []
    valid_widths: list[float] = []
    for record in records:
        try:
            position = float(getattr(record, "two_theta"))
            area = max(float(getattr(record, "area", 0.0) or 0.0), 0.0)
            height = max(float(getattr(record, "height", 0.0) or 0.0), 0.0)
            prominence = max(
                float(getattr(record, "prominence", 0.0) or 0.0), 0.0
            )
        except (TypeError, ValueError, AttributeError):
            continue
        strength = area if area > 0.0 else max(height, prominence)
        if not math.isfinite(position) or not math.isfinite(strength) or strength <= 0.0:
            continue
        try:
            width = float(getattr(record, "fwhm"))
            if not math.isfinite(width) or width <= 0.0:
                width = None
        except (TypeError, ValueError, AttributeError):
            width = None
        if width is not None:
            valid_widths.append(width)
        try:
            fit_quality = float(getattr(record, "fit_quality", 0.0) or 0.0)
        except (TypeError, ValueError):
            fit_quality = 0.0
        try:
            snr = float(
                getattr(record, "local_snr", getattr(record, "snr", math.nan))
            )
            if not math.isfinite(snr):
                snr = None
        except (TypeError, ValueError):
            snr = None
        parsed.append((position, strength, width, fit_quality, snr))
    if not parsed:
        return ()
    maximum = max(strength for _position, strength, _width, _fit, _snr in parsed)
    typical_width = (
        sorted(valid_widths)[max(0, (len(valid_widths) - 1) // 2)]
        if valid_widths
        else None
    )
    weighted: list[tuple[float, float]] = []
    for position, strength, width, fit_quality, snr in parsed:
        strength_weight = strength / max(maximum, 1.0e-12)
        if width is None or typical_width is None:
            width_reliability = 0.85
        else:
            width_reliability = max(
                0.20, min(1.0, typical_width * 2.5 / width)
            )
        fit_reliability = (
            0.80
            if fit_quality <= 0.0
            else 0.55 + 0.45 * min(max(fit_quality, 0.0), 1.0)
        )
        snr_reliability = (
            0.80 if snr is None else min(1.0, max(snr, 0.0) / 8.0)
        )
        # Matched-profile hypotheses may stay available to rescue channels
        # while contributing less to the primary strong-line channel.
        source_record = next(
            (
                record
                for record in records
                if abs(float(getattr(record, "two_theta", math.inf)) - position)
                <= 1.0e-6
            ),
            None,
        )
        evidence_class = str(
            getattr(source_record, "evidence_class", "") or ""
        )
        class_reliability = {
            "strong": 1.0,
            "weak": 0.60,
            "tentative": 0.25,
        }.get(evidence_class, 1.0)
        weighted.append(
            (
                position,
                strength_weight
                * width_reliability
                * fit_reliability
                * snr_reliability
                * class_reliability,
            )
        )
    weighted.sort(key=lambda item: (-item[1], item[0]))
    return tuple(weighted)


def _candidate_lines(peaks: Iterable[object]) -> tuple[tuple[float, float], ...]:
    parsed: list[tuple[float, float]] = []
    for peak in peaks:
        try:
            position = float(getattr(peak, "two_theta"))
            intensity = float(getattr(peak, "intensity"))
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(position) and math.isfinite(intensity) and intensity > 0.0:
            parsed.append((position, intensity))
    maximum = max((intensity for _position, intensity in parsed), default=0.0)
    if maximum <= 0.0:
        return ()
    return tuple(
        (position, intensity / maximum)
        for position, intensity in sorted(parsed, key=lambda item: -item[1])[:24]
        if intensity / maximum >= 0.01
    )


def _matched_evidence_counts(
    candidate_peaks: Mapping[str, Iterable[object]],
    records: Iterable[object],
    *,
    tolerance: float,
) -> dict[str, int]:
    positions: list[float] = []
    for record in records:
        try:
            position = float(getattr(record, "two_theta"))
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(position):
            positions.append(position)
    width = max(float(tolerance), 0.05)
    counts: dict[str, int] = {}
    for phase_id, peaks in candidate_peaks.items():
        lines = _candidate_lines(peaks)
        counts[str(phase_id)] = sum(
            1
            for position in positions
            if any(
                abs(candidate_position - position) <= width
                for candidate_position, _weight in lines
            )
        )
    return counts


def _with_total_elapsed(
    run: RetrievalChannelRun,
    started: float,
) -> RetrievalChannelRun:
    return RetrievalChannelRun(
        channel=run.channel,
        hits=run.hits,
        elapsed_seconds=max(0.0, time.perf_counter() - started),
        diagnostic=run.diagnostic,
    )


__all__ = [
    "RETRIEVAL_CHANNELS",
    "RetrievalChannelRun",
    "RetrievalHit",
    "geometry_channel",
    "overlap_deficit_channel",
    "rare_line_channel",
    "rank_channel_scores",
    "strong_residual_channel",
]
