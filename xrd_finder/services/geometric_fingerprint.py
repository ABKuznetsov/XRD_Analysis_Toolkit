from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping


DEFAULT_BIN_WIDTH = 0.015
DEFAULT_NEIGHBOR_SPAN = 6


@dataclass(frozen=True, slots=True)
class FingerprintCandidateScore:
    key: tuple[str, str]
    votes: int
    coverage: float


def geometric_hashes_from_q(
    q_values: Iterable[float],
    *,
    bin_width: float = DEFAULT_BIN_WIDTH,
    neighbor_span: int = DEFAULT_NEIGHBOR_SPAN,
) -> set[int]:
    """Return affine-invariant four-line shape hashes.

    For q0 < q1 < q2 < q3, the two internal coordinates within the
    outer interval are unchanged by q' = a*q + b. Restricting the outer
    interval to nearby selected lines keeps the index compact.
    """

    return {
        _pack_bins(first_bin, second_bin)
        for first_bin, second_bin in _shape_bins(
            q_values,
            bin_width=bin_width,
            neighbor_span=neighbor_span,
        )
    }


def expanded_geometric_hashes_from_q(
    q_values: Iterable[float],
    *,
    bin_width: float = DEFAULT_BIN_WIDTH,
    neighbor_span: int = DEFAULT_NEIGHBOR_SPAN,
    bin_radius: int = 1,
) -> set[int]:
    """Return query hashes expanded into adjacent quantization bins."""

    expanded: set[int] = set()
    radius = max(0, int(bin_radius))
    maximum_bin = int(round(1.0 / max(float(bin_width), 1.0e-6)))
    for first_bin, second_bin in _shape_bins(
        q_values,
        bin_width=bin_width,
        neighbor_span=neighbor_span,
    ):
        for first_delta in range(-radius, radius + 1):
            for second_delta in range(-radius, radius + 1):
                first = first_bin + first_delta
                second = second_bin + second_delta
                if 0 < first < second < maximum_bin:
                    expanded.add(_pack_bins(first, second))
    return expanded


def peak_geometric_hashes(
    peaks: Iterable[object],
    *,
    max_peaks: int = 14,
    expanded: bool = False,
) -> set[int]:
    """Build hashes from the strongest usable two-theta peak records."""

    strongest: list[tuple[float, float]] = []
    for peak in peaks:
        try:
            two_theta_value = getattr(peak, "two_theta", None)
            two_theta = float(two_theta_value if two_theta_value is not None else peak[0])
            intensity_value = getattr(peak, "intensity", None)
            if intensity_value is None:
                intensity_value = getattr(peak, "height", None)
            if intensity_value is None:
                intensity_value = getattr(peak, "area", None)
            intensity = float(intensity_value if intensity_value is not None else peak[1])
        except (IndexError, TypeError, ValueError):
            continue
        if not 5.0 <= two_theta <= 120.0 or intensity <= 0.0:
            continue
        q_value = 2.0 * math.sin(math.radians(two_theta / 2.0))
        if q_value > 0.0:
            strongest.append((max(intensity, 0.0), q_value))
    strongest.sort(key=lambda item: item[0], reverse=True)
    q_values = [q for _intensity, q in strongest[: max(4, int(max_peaks))]]
    if expanded:
        return expanded_geometric_hashes_from_q(q_values)
    return geometric_hashes_from_q(q_values)


def rank_fingerprint_candidates(
    query_hashes: set[int],
    candidate_hashes: Mapping[tuple[str, str], set[int]],
    *,
    limit: int | None = None,
) -> list[FingerprintCandidateScore]:
    """Rank candidate hash sets by coherent geometric votes."""

    ranked = []
    for key, hashes in candidate_hashes.items():
        votes = len(query_hashes.intersection(hashes))
        if votes <= 0:
            continue
        coverage = votes / max(math.sqrt(len(query_hashes) * len(hashes)), 1.0)
        ranked.append(FingerprintCandidateScore(key=key, votes=votes, coverage=coverage))
    ranked.sort(key=lambda item: (-item.votes, -item.coverage, item.key))
    if limit is not None:
        return ranked[: max(0, int(limit))]
    return ranked


def _shape_bins(
    q_values: Iterable[float],
    *,
    bin_width: float,
    neighbor_span: int,
) -> list[tuple[int, int]]:
    values = sorted({float(value) for value in q_values if math.isfinite(float(value))})
    width = max(float(bin_width), 1.0e-6)
    span_limit = max(3, int(neighbor_span))
    bins = []
    for left_index, left in enumerate(values):
        last_index = min(len(values) - 1, left_index + span_limit)
        for right_index in range(left_index + 3, last_index + 1):
            right = values[right_index]
            span = right - left
            if span <= 1.0e-9:
                continue
            for first_index in range(left_index + 1, right_index - 1):
                for second_index in range(first_index + 1, right_index):
                    first_ratio = (values[first_index] - left) / span
                    second_ratio = (values[second_index] - left) / span
                    first_bin = int(round(first_ratio / width))
                    second_bin = int(round(second_ratio / width))
                    if 0 < first_bin < second_bin:
                        bins.append((first_bin, second_bin))
    return bins


def _pack_bins(first_bin: int, second_bin: int) -> int:
    return (int(first_bin) << 16) | int(second_bin)


__all__ = [
    "FingerprintCandidateScore",
    "expanded_geometric_hashes_from_q",
    "geometric_hashes_from_q",
    "peak_geometric_hashes",
    "rank_fingerprint_candidates",
]
