from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from xrd_finder.services.geometric_fingerprint import peak_geometric_hashes


@dataclass(frozen=True, slots=True)
class PhasePatternComparison:
    equivalent: bool
    reference_coverage: float
    candidate_coverage: float
    matched_lines: int
    reference_lines: int
    candidate_lines: int
    fingerprint_coverage: float = 0.0
    fingerprint_votes: int = 0


def compare_phase_patterns(
    reference_peaks: Iterable[object],
    candidate_peaks: Iterable[object],
    *,
    fwhm: float = 0.18,
    max_lines: int = 24,
    minimum_coverage: float = 0.82,
    allow_geometric_fingerprint: bool = True,
) -> PhasePatternComparison:
    """Compare two already aligned stick patterns without using their metadata.

    Gain calls this after both phases have been aligned to the same experimental
    axis.  Mutual intensity-weighted coverage is deliberately required: a phase
    sharing only a few strong reflections with an accepted phase must remain a
    candidate, while a duplicate database card should be suppressed.
    """

    reference_peaks = tuple(reference_peaks)
    candidate_peaks = tuple(candidate_peaks)
    reference = _strong_lines(reference_peaks, max_lines=max_lines)
    candidate = _strong_lines(candidate_peaks, max_lines=max_lines)
    if len(reference) < 3 or len(candidate) < 3:
        return PhasePatternComparison(False, 0.0, 0.0, 0, len(reference), len(candidate))

    # Reference-card positions are much more precise than an observed peak
    # width.  FWHM only gives a modest allowance for refined cell differences;
    # using the full experimental width would merge nearby polymorphs.
    tolerance = max(0.12, min(0.28, abs(float(fwhm)) * 0.90))
    possible_matches: list[tuple[float, int, int, float]] = []
    for reference_index, (reference_position, reference_weight) in enumerate(reference):
        for candidate_index, (candidate_position, candidate_weight) in enumerate(candidate):
            delta = abs(reference_position - candidate_position)
            if delta > tolerance:
                continue
            proximity = math.exp(-0.5 * (delta / tolerance) ** 2)
            priority = proximity * math.sqrt(reference_weight * candidate_weight)
            possible_matches.append(
                (priority, reference_index, candidate_index, proximity)
            )

    used_reference: set[int] = set()
    used_candidate: set[int] = set()
    matched: list[tuple[int, int, float]] = []
    for _priority, reference_index, candidate_index, proximity in sorted(
        possible_matches, reverse=True
    ):
        if reference_index in used_reference or candidate_index in used_candidate:
            continue
        used_reference.add(reference_index)
        used_candidate.add(candidate_index)
        matched.append((reference_index, candidate_index, proximity))

    reference_total = sum(weight for _position, weight in reference)
    candidate_total = sum(weight for _position, weight in candidate)
    reference_coverage = sum(
        reference[reference_index][1] * proximity
        for reference_index, _candidate_index, proximity in matched
    ) / max(reference_total, 1.0e-12)
    candidate_coverage = sum(
        candidate[candidate_index][1] * proximity
        for _reference_index, candidate_index, proximity in matched
    ) / max(candidate_total, 1.0e-12)
    minimum_matches = 3 if min(len(reference), len(candidate)) <= 4 else 4
    position_equivalent = (
        len(matched) >= minimum_matches
        and reference_coverage >= float(minimum_coverage)
        and candidate_coverage >= float(minimum_coverage)
    )
    reference_hashes = peak_geometric_hashes(reference_peaks, max_peaks=14)
    candidate_hashes = peak_geometric_hashes(candidate_peaks, max_peaks=14)
    fingerprint_votes = len(reference_hashes.intersection(candidate_hashes))
    fingerprint_coverage = fingerprint_votes / max(
        math.sqrt(len(reference_hashes) * len(candidate_hashes)),
        1.0,
    )
    # The four-line geometry is invariant to q' = a*q+b.  It catches duplicate
    # cards whose lattice parameters differ enough that a fixed 2theta window
    # misses them.  Requiring many independent hashes avoids treating a few
    # shared reflections as the same phase.
    fingerprint_equivalent = (
        bool(allow_geometric_fingerprint)
        and
        fingerprint_votes >= 48
        and fingerprint_coverage >= 0.50
    )
    equivalent = position_equivalent or fingerprint_equivalent
    return PhasePatternComparison(
        equivalent,
        reference_coverage,
        candidate_coverage,
        len(matched),
        len(reference),
        len(candidate),
        float(fingerprint_coverage),
        int(fingerprint_votes),
    )


def phase_patterns_equivalent(
    reference_peaks: Iterable[object],
    candidate_peaks: Iterable[object],
    *,
    fwhm: float = 0.18,
    max_lines: int = 24,
    minimum_coverage: float = 0.82,
    allow_geometric_fingerprint: bool = True,
) -> bool:
    return compare_phase_patterns(
        reference_peaks,
        candidate_peaks,
        fwhm=fwhm,
        max_lines=max_lines,
        minimum_coverage=minimum_coverage,
        allow_geometric_fingerprint=allow_geometric_fingerprint,
    ).equivalent


def _strong_lines(peaks: Iterable[object], *, max_lines: int) -> list[tuple[float, float]]:
    lines: list[tuple[float, float]] = []
    for peak in peaks:
        try:
            position = float(getattr(peak, "two_theta"))
            intensity = float(getattr(peak, "intensity"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not math.isfinite(position) or not math.isfinite(intensity) or intensity <= 0.0:
            continue
        lines.append((position, intensity))
    if not lines:
        return []
    maximum = max(intensity for _position, intensity in lines)
    threshold = maximum * 0.01
    strongest = sorted(
        (line for line in lines if line[1] >= threshold),
        key=lambda line: line[1],
        reverse=True,
    )[: max(3, int(max_lines))]
    return sorted(strongest, key=lambda line: line[0])
