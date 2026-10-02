from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from xrd_finder.services.gain_shortlist import significant_residual_records


@dataclass(frozen=True, slots=True)
class _GeometryPosting:
    phase_id: str
    weight: float


@dataclass(frozen=True, slots=True)
class ResidualGeometryIndex:
    pair_bin_deg: float
    ratio_bin: float
    span_log_bin: float
    pair_postings: Mapping[int, tuple[_GeometryPosting, ...]]
    triplet_postings: Mapping[tuple[int, int], tuple[_GeometryPosting, ...]]


def build_residual_geometry_index(
    candidate_peaks: Mapping[str, Iterable[object]],
    *,
    max_lines: int = 14,
    pair_bin_deg: float = 0.08,
    ratio_bin: float = 0.02,
) -> ResidualGeometryIndex:
    """Precompute common-zero-invariant pair and triplet geometry postings."""

    pair_width = max(float(pair_bin_deg), 0.01)
    ratio_width = max(float(ratio_bin), 0.005)
    span_log_width = 0.10
    pair_lists: dict[int, list[_GeometryPosting]] = {}
    triplet_lists: dict[tuple[int, int], list[_GeometryPosting]] = {}
    for raw_phase_id, peaks in candidate_peaks.items():
        phase_id = str(raw_phase_id)
        lines = _prepared_lines(peaks, max_lines=max_lines, strength_name="intensity")
        for first, second in itertools.combinations(lines, 2):
            delta = second[0] - first[0]
            if delta <= 0.0:
                continue
            key = int(round(delta / pair_width))
            weight = math.sqrt(first[1] * second[1])
            pair_lists.setdefault(key, []).append(
                _GeometryPosting(phase_id, weight)
            )
        for first, middle, last in itertools.combinations(lines, 3):
            span = last[0] - first[0]
            if span <= pair_width:
                continue
            ratio = (middle[0] - first[0]) / span
            key = (
                int(round(math.log(span) / span_log_width)),
                int(round(ratio / ratio_width)),
            )
            weight = (first[1] * middle[1] * last[1]) ** (1.0 / 3.0)
            triplet_lists.setdefault(key, []).append(
                _GeometryPosting(phase_id, weight)
            )
    return ResidualGeometryIndex(
        pair_bin_deg=pair_width,
        ratio_bin=ratio_width,
        span_log_bin=span_log_width,
        pair_postings={
            key: tuple(sorted(value, key=lambda posting: posting.phase_id))
            for key, value in pair_lists.items()
        },
        triplet_postings={
            key: tuple(sorted(value, key=lambda posting: posting.phase_id))
            for key, value in triplet_lists.items()
        },
    )


def residual_geometry_scores(
    index: ResidualGeometryIndex,
    residual_records: Iterable[object],
    *,
    max_lines: int = 10,
) -> tuple[dict[str, float], dict[str, int]]:
    """Vote for candidates through residual pair/triplet geometry."""

    significant = significant_residual_records(residual_records)
    lines = _prepared_lines(significant, max_lines=max_lines, strength_name="area")
    if len(lines) < 2:
        return {}, {}
    scores: dict[str, float] = {}
    evidence_counts: dict[str, int] = {}

    for first, second in itertools.combinations(lines, 2):
        delta = second[0] - first[0]
        if delta <= 0.0:
            continue
        center_key = int(round(delta / index.pair_bin_deg))
        observation_weight = math.sqrt(first[1] * second[1])
        for key in range(center_key - 1, center_key + 2):
            bin_reliability = 1.0 / (1.0 + abs(key - center_key))
            for posting in index.pair_postings.get(key, ()):
                scores[posting.phase_id] = scores.get(posting.phase_id, 0.0) + (
                    observation_weight * posting.weight * bin_reliability
                )
                evidence_counts[posting.phase_id] = (
                    evidence_counts.get(posting.phase_id, 0) + 1
                )

    if len(lines) >= 3:
        for first, middle, last in itertools.combinations(lines, 3):
            span = last[0] - first[0]
            if span <= index.pair_bin_deg:
                continue
            ratio = (middle[0] - first[0]) / span
            span_key = int(round(math.log(span) / index.span_log_bin))
            ratio_key = int(round(ratio / index.ratio_bin))
            observation_weight = (first[1] * middle[1] * last[1]) ** (1.0 / 3.0)
            for span_neighbor in range(span_key - 1, span_key + 2):
                for ratio_neighbor in range(ratio_key - 1, ratio_key + 2):
                    distance = abs(span_neighbor - span_key) + abs(
                        ratio_neighbor - ratio_key
                    )
                    bin_reliability = 1.0 / (1.0 + distance)
                    for posting in index.triplet_postings.get(
                        (span_neighbor, ratio_neighbor), ()
                    ):
                        scores[posting.phase_id] = scores.get(
                            posting.phase_id, 0.0
                        ) + observation_weight * posting.weight * bin_reliability
                        evidence_counts[posting.phase_id] = (
                            evidence_counts.get(posting.phase_id, 0) + 1
                        )
    return scores, evidence_counts


def _prepared_lines(
    records: Iterable[object],
    *,
    max_lines: int,
    strength_name: str,
) -> tuple[tuple[float, float], ...]:
    by_position: dict[int, tuple[float, float]] = {}
    for record in records:
        try:
            position = float(getattr(record, "two_theta"))
            strength = float(getattr(record, strength_name, 0.0) or 0.0)
            if strength <= 0.0:
                strength = float(
                    getattr(record, "height", 0.0)
                    or getattr(record, "prominence", 0.0)
                    or getattr(record, "intensity", 0.0)
                )
        except (TypeError, ValueError, AttributeError):
            continue
        if not math.isfinite(position) or not math.isfinite(strength) or strength <= 0.0:
            continue
        position_key = int(round(position * 10000.0))
        previous = by_position.get(position_key)
        if previous is None or strength > previous[1]:
            by_position[position_key] = (position, strength)
    strongest = sorted(
        by_position.values(), key=lambda item: (-item[1], item[0])
    )[: max(0, int(max_lines))]
    maximum = max((strength for _position, strength in strongest), default=0.0)
    if maximum <= 0.0:
        return ()
    return tuple(
        sorted(
            (
                (position, strength / maximum)
                for position, strength in strongest
            ),
            key=lambda item: item[0],
        )
    )


__all__ = [
    "ResidualGeometryIndex",
    "build_residual_geometry_index",
    "residual_geometry_scores",
]
