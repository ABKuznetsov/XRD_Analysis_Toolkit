from __future__ import annotations

from collections.abc import Hashable, Mapping
from collections.abc import Iterable
from dataclasses import dataclass
import math
import statistics

from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY


GAIN_PROFILE_CANDIDATE_LIMIT = 24


@dataclass(frozen=True, slots=True)
class ResidualEvidenceSummary:
    kind: str
    significant_line_count: int
    strongest_two_fraction: float
    rare_line_fraction: float
    significant_records: tuple[object, ...] = ()


def significant_residual_records(
    observed_records: Iterable[object],
    *,
    sigma_threshold: float = 3.0,
) -> tuple[object, ...]:
    """Return finite positive residual lines that clear an available noise test.

    Older callers do not always provide a local SNR or noise estimate.  Those
    records remain eligible so this helper does not change legacy retrieval.
    When noise information is present, however, sub-threshold maxima are not
    promoted into candidate evidence.
    """

    threshold = max(float(sigma_threshold), 0.0)
    significant: list[object] = []
    for record in observed_records:
        try:
            position = float(getattr(record, "two_theta"))
            area = max(float(getattr(record, "area", 0.0) or 0.0), 0.0)
            height = max(float(getattr(record, "height", 0.0) or 0.0), 0.0)
            prominence = max(
                float(getattr(record, "prominence", 0.0) or 0.0), 0.0
            )
        except (TypeError, ValueError, AttributeError):
            continue
        if not math.isfinite(position) or not any(
            math.isfinite(value) and value > 0.0
            for value in (area, height, prominence)
        ):
            continue

        raw_snr = getattr(record, "local_snr", None)
        if raw_snr is None:
            raw_snr = getattr(record, "snr", None)
        if raw_snr is None:
            try:
                noise_floor = float(getattr(record, "noise_floor", 0.0) or 0.0)
            except (TypeError, ValueError):
                noise_floor = 0.0
            raw_snr = max(height, prominence) / noise_floor if noise_floor > 0.0 else None
        if raw_snr is not None:
            try:
                snr = float(raw_snr)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(snr) or snr < threshold:
                continue
        significant.append(record)
    return tuple(significant)


def summarize_residual_evidence(
    observed_records: Iterable[object],
    *,
    expected_fwhm: float,
) -> ResidualEvidenceSummary:
    """Describe whether the unexplained residual is rich, intermediate or sparse."""

    expected_width = max(float(expected_fwhm), 0.05)
    weighted: list[tuple[float, object]] = []
    for record in observed_records:
        try:
            area = max(float(getattr(record, "area", 0.0) or 0.0), 0.0)
            height = max(float(getattr(record, "height", 0.0) or 0.0), 0.0)
            width = max(float(getattr(record, "fwhm", expected_width) or expected_width), 0.05)
        except (TypeError, ValueError):
            continue
        strength = area if area > 0.0 else height * width
        if not math.isfinite(strength) or strength <= 0.0:
            continue
        # Broad unresolved humps are useful evidence, but weaker anchors than
        # well-resolved reflections when choosing a database retrieval path.
        width_reliability = min(1.0, (expected_width * 2.5) / width)
        fit_quality = float(getattr(record, "fit_quality", 0.0) or 0.0)
        fit_reliability = 1.0 if fit_quality <= 0.0 else 0.55 + 0.45 * min(fit_quality, 1.0)
        weighted.append((strength * max(width_reliability, 0.20) * fit_reliability, record))
    if not weighted:
        return ResidualEvidenceSummary("none", 0, 0.0, 0.0)

    weighted.sort(key=lambda item: item[0], reverse=True)
    maximum = weighted[0][0]
    significant = [(strength, record) for strength, record in weighted if strength >= maximum * 0.04]
    if not significant:
        return ResidualEvidenceSummary("none", 0, 0.0, 0.0)
    total = sum(strength for strength, _record in significant)
    strongest_two = sum(strength for strength, _record in significant[:2]) / max(total, 1.0e-12)
    count = len(significant)
    if count <= 2 or strongest_two >= 0.65:
        kind = "sparse"
        rare_fraction = 0.50
    elif count <= 6:
        kind = "intermediate"
        rare_fraction = 0.25
    else:
        kind = "rich"
        rare_fraction = 0.0
    return ResidualEvidenceSummary(
        kind,
        count,
        float(strongest_two),
        rare_fraction,
        tuple(record for _strength, record in significant),
    )


def summarize_combined_residual_evidence(
    direct_records: Iterable[object],
    overlap_records: Iterable[object],
    *,
    expected_fwhm: float,
) -> ResidualEvidenceSummary:
    """Summarize independent and intensity-deficit peaks as one retrieval signal."""

    combined = [*direct_records, *overlap_records]
    combined.sort(
        key=lambda item: float(getattr(item, "area", 0.0) or 0.0),
        reverse=True,
    )
    unique: list[object] = []
    seen_positions: set[int] = set()
    for record in combined:
        try:
            position_key = int(round(float(getattr(record, "two_theta")) * 1000.0))
        except (TypeError, ValueError, AttributeError):
            continue
        if position_key in seen_positions:
            continue
        seen_positions.add(position_key)
        unique.append(record)
    return summarize_residual_evidence(unique, expected_fwhm=expected_fwhm)


def residual_peak_is_explained(
    *,
    observed_height: float,
    calculated_height: float,
    residual_height: float,
    noise_floor: float,
    overlaps_accepted_phase: bool,
    minimum_deficit_fraction: float = 0.18,
) -> bool:
    """Return whether an accepted-phase profile explains a peak in intensity as well as position."""

    if not overlaps_accepted_phase:
        return False
    observed = max(float(observed_height), 0.0)
    calculated = max(float(calculated_height), 0.0)
    deficit = max(float(residual_height), observed - calculated, 0.0)
    if deficit <= max(float(noise_floor), 0.0):
        return True
    if observed <= 0.0:
        return True
    return deficit / observed < max(float(minimum_deficit_fraction), 0.0)


def adaptive_gain_secondary_scores(
    summary: ResidualEvidenceSummary,
    candidate_peaks: Mapping[Hashable, Iterable[object]],
    observed_records: Iterable[object],
) -> dict[Hashable, float] | None:
    """Enable rare-line retrieval when the residual itself has limited evidence."""

    if float(summary.rare_line_fraction) <= 0.0:
        return None
    return rare_line_candidate_scores(candidate_peaks, observed_records)


def common_zero_shift(values: Iterable[float]) -> float:
    """Return the single scan zero shift shared by every candidate phase."""

    finite = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            finite.append(number)
    return float(statistics.median(finite)) if finite else 0.0


def select_profile_candidate_indices(
    line_scores: Mapping[int, float],
    *,
    secondary_scores: Mapping[int, float] | None = None,
    secondary_fraction: float = 0.25,
    secondary_extra_limit: int = 0,
    limit: int = GAIN_PROFILE_CANDIDATE_LIMIT,
) -> list[int]:
    """Select the strongest residual-line candidates for profile scoring."""

    ranked = [
        (max(float(score), 0.0), int(index))
        for index, score in line_scores.items()
        if float(score) > 0.0
    ]
    ranked.sort(key=lambda item: (-item[0], item[1]))
    base_limit = max(0, int(limit))
    extra_limit = max(0, int(secondary_extra_limit))
    shortlist_limit = base_limit + extra_limit
    if not secondary_scores or shortlist_limit <= 1:
        return [index for _score, index in ranked[:base_limit]]

    secondary_count = min(
        shortlist_limit,
        max(1, int(round(shortlist_limit * float(secondary_fraction)))),
    )
    primary_count = base_limit if extra_limit else max(0, shortlist_limit - secondary_count)
    eligible = {index for _score, index in ranked}
    secondary_ranked = sorted(
        (
            (max(float(score), 0.0), int(index))
            for index, score in secondary_scores.items()
            if int(index) in eligible and float(score) > 0.0
        ),
        key=lambda item: (-item[0], item[1]),
    )
    selected: list[int] = []
    seen: set[int] = set()
    for _score, index in ranked[:primary_count]:
        selected.append(index)
        seen.add(index)
    secondary_take = extra_limit if extra_limit else secondary_count
    for _score, index in secondary_ranked[:secondary_take]:
        if index not in seen:
            selected.append(index)
            seen.add(index)
    for order in (ranked, secondary_ranked):
        for _score, index in order:
            if len(selected) >= shortlist_limit:
                break
            if index not in seen:
                selected.append(index)
                seen.add(index)
    return selected[:shortlist_limit]


def rare_line_candidate_scores(
    candidate_peaks: Mapping[Hashable, Iterable[object]],
    observed_records: Iterable[object],
    *,
    tolerance: float = 0.45,
    max_candidate_lines: int = 18,
    max_observed_lines: int = 12,
) -> dict[Hashable, float]:
    """Score candidates by matches to residual lines that are rare in the database subset."""

    observed = []
    for record in observed_records:
        try:
            position = float(getattr(record, "two_theta"))
            strength = float(
                getattr(record, "area", 0.0)
                or getattr(record, "height", 0.0)
                or getattr(record, "intensity", 0.0)
            )
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(position) and math.isfinite(strength) and strength > 0.0:
            observed.append((strength, position))
    observed.sort(reverse=True)
    observed = observed[: max(1, int(max_observed_lines))]
    if not observed or not candidate_peaks:
        return {key: 0.0 for key in candidate_peaks}
    observed_max = max(value for value, _position in observed)
    observed = [(value / observed_max, position) for value, position in observed]

    prepared: dict[Hashable, list[tuple[float, float]]] = {}
    for key, peaks in candidate_peaks.items():
        lines = []
        for peak in peaks:
            try:
                position = float(getattr(peak, "two_theta"))
                intensity = float(getattr(peak, "intensity"))
            except (TypeError, ValueError, AttributeError):
                continue
            if math.isfinite(position) and math.isfinite(intensity) and intensity > 0.0:
                lines.append((intensity, position))
        lines.sort(reverse=True)
        lines = lines[: max(1, int(max_candidate_lines))]
        maximum = max((value for value, _position in lines), default=0.0)
        prepared[key] = [
            (value / maximum, position)
            for value, position in lines
            if maximum > 0.0 and value / maximum >= 0.03
        ]

    width = max(float(tolerance), 0.05)
    frequencies = []
    for _strength, observed_position in observed:
        frequencies.append(
            sum(
                1
                for lines in prepared.values()
                if any(abs(position - observed_position) <= width for _weight, position in lines)
            )
        )
    candidate_count = max(len(prepared), 1)
    scores: dict[Hashable, float] = {}
    for key, lines in prepared.items():
        score = 0.0
        for (observed_weight, observed_position), frequency in zip(observed, frequencies, strict=True):
            best = 0.0
            for candidate_weight, candidate_position in lines:
                delta = abs(candidate_position - observed_position)
                if delta > width:
                    continue
                proximity = math.exp(-0.5 * (delta / width) ** 2)
                best = max(best, proximity * math.sqrt(candidate_weight))
            if best > 0.0:
                inverse_frequency = math.log((candidate_count + 1.0) / (frequency + 1.0)) + 1.0
                score += observed_weight * inverse_frequency * best
        scores[key] = float(score)
    return scores


def dominant_line_candidate_scores(
    candidate_peaks: Mapping[Hashable, Iterable[object]],
    observed_records: Iterable[object],
    *,
    tolerance: float = 0.65,
    max_observed_lines: int = 12,
) -> dict[Hashable, float]:
    """Retrieve sparse candidates from their one or two dominant reflections."""

    observed = []
    for record in observed_records:
        try:
            position = float(getattr(record, "two_theta"))
            strength = float(
                getattr(record, "area", 0.0)
                or getattr(record, "height", 0.0)
                or getattr(record, "intensity", 0.0)
            )
        except (TypeError, ValueError, AttributeError):
            continue
        if math.isfinite(position) and math.isfinite(strength) and strength > 0.0:
            observed.append((strength, position))
    observed.sort(reverse=True)
    observed = observed[: max(1, int(max_observed_lines))]
    if not observed:
        return {key: 0.0 for key in candidate_peaks}
    maximum_observed = max(value for value, _position in observed)
    observed = [(value / maximum_observed, position) for value, position in observed]

    dominant: dict[Hashable, list[tuple[float, float]]] = {}
    for key, peaks in candidate_peaks.items():
        lines = []
        for peak in peaks:
            try:
                position = float(getattr(peak, "two_theta"))
                intensity = float(getattr(peak, "intensity"))
            except (TypeError, ValueError, AttributeError):
                continue
            if math.isfinite(position) and math.isfinite(intensity) and intensity > 0.0:
                lines.append((intensity, position))
        lines.sort(reverse=True)
        strongest = lines[:10]
        total = sum(value for value, _position in strongest)
        if len(strongest) < 3 or total <= 0.0:
            dominant[key] = []
        elif strongest[0][0] / total >= DEFAULT_GAIN_POLICY.sparse_strongest_fraction:
            dominant[key] = [(1.0, strongest[0][1])]
        elif sum(value for value, _position in strongest[:2]) / total >= DEFAULT_GAIN_POLICY.sparse_two_strongest_fraction:
            top = strongest[0][0]
            dominant[key] = [(value / top, position) for value, position in strongest[:2]]
        else:
            dominant[key] = []

    width = max(float(tolerance), 0.05)
    frequencies = [
        sum(
            1
            for lines in dominant.values()
            if any(abs(position - observed_position) <= width for _weight, position in lines)
        )
        for _observed_weight, observed_position in observed
    ]
    candidate_count = max(len(candidate_peaks), 1)
    scores: dict[Hashable, float] = {}
    for key, lines in dominant.items():
        score = 0.0
        for candidate_weight, candidate_position in lines:
            best = 0.0
            best_frequency = candidate_count
            for (observed_weight, observed_position), frequency in zip(observed, frequencies, strict=True):
                delta = abs(candidate_position - observed_position)
                if delta > width:
                    continue
                proximity = math.exp(-0.5 * (delta / width) ** 2)
                value = observed_weight * proximity
                if value > best:
                    best = value
                    best_frequency = frequency
            if best > 0.0:
                inverse_frequency = math.log((candidate_count + 1.0) / (best_frequency + 1.0)) + 1.0
                score += candidate_weight * best * inverse_frequency
        scores[key] = float(score)
    return scores


def has_sparse_line_distribution(intensities: Iterable[float]) -> bool:
    """Return whether one or two lines dominate a candidate stick pattern."""
    return DEFAULT_GAIN_POLICY.is_sparse(intensities)


def estimate_matched_profile_fwhm(
    reference_peaks: Iterable[object],
    observed_records: Iterable[object],
    *,
    default_fwhm: float,
    tolerance: float,
) -> float:
    """Estimate an accepted phase width from its matched experimental peaks."""

    default = max(float(default_fwhm), 0.05)
    references = []
    for peak in reference_peaks:
        try:
            position = float(getattr(peak, "two_theta"))
            intensity = max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(position) and intensity > 0.0:
            references.append((intensity, position))
    references.sort(reverse=True)
    observed = []
    for record in observed_records:
        try:
            position = float(getattr(record, "two_theta"))
            fwhm = float(getattr(record, "fwhm"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(position) and math.isfinite(fwhm) and 0.03 <= fwhm <= 1.2:
            observed.append((position, fwhm))
    if not references or not observed:
        return default

    available = set(range(len(observed)))
    widths: list[tuple[float, float]] = []
    for intensity, position in references[:24]:
        if not available:
            break
        index = min(available, key=lambda item: abs(observed[item][0] - position))
        if abs(observed[index][0] - position) > max(float(tolerance), 0.05):
            continue
        available.remove(index)
        widths.append((observed[index][1], math.sqrt(intensity)))
    if len(widths) < 3:
        return default

    widths.sort(key=lambda item: item[0])
    total_weight = sum(weight for _width, weight in widths)
    threshold = total_weight * 0.5
    accumulated = 0.0
    median = default
    for width, weight in widths:
        accumulated += weight
        if accumulated >= threshold:
            median = width
            break
    return max(max(0.06, default * 0.65), min(median, min(0.90, default * 2.8)))


__all__ = [
    "GAIN_PROFILE_CANDIDATE_LIMIT",
    "ResidualEvidenceSummary",
    "adaptive_gain_secondary_scores",
    "common_zero_shift",
    "dominant_line_candidate_scores",
    "estimate_matched_profile_fwhm",
    "has_sparse_line_distribution",
    "rare_line_candidate_scores",
    "residual_peak_is_explained",
    "significant_residual_records",
    "summarize_combined_residual_evidence",
    "summarize_residual_evidence",
    "select_profile_candidate_indices",
]
