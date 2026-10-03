from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY, GainPolicy, GainStage


@dataclass(frozen=True, slots=True)
class GainIndexedEvidence:
    stage: GainStage
    indexed_matches: tuple[tuple[int, int, int, float, float], ...]


def build_gain_indexed_evidence(
    *,
    peaks,
    records,
    stage: GainStage,
    base_fwhm: float,
) -> GainIndexedEvidence:
    """Create one-to-one hkl/observed pairs from the lines that support Gain."""

    strong = sorted(
        (
            peak
            for peak in peaks
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
            and (int(getattr(peak, "h", 0)), int(getattr(peak, "k", 0)), int(getattr(peak, "l", 0))) != (0, 0, 0)
        ),
        key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0),
        reverse=True,
    )[:42]
    available = set(range(len(records)))
    matches: list[tuple[int, int, int, float, float]] = []

    def record_value(record, attribute: str, index: int) -> float:
        value = getattr(record, attribute, None)
        if value is None:
            value = record[index]
        return float(value)

    for peak in strong:
        calculated = float(getattr(peak, "two_theta", 0.0) or 0.0)
        best_index = -1
        best_delta = float("inf")
        for index in available:
            record = records[index]
            observed = record_value(record, "two_theta", 0)
            line_fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), float(base_fwhm), 0.05)
            tolerance = max(0.26, min(0.72, line_fwhm * 2.4))
            delta = abs(observed - calculated)
            if delta <= tolerance and delta < best_delta:
                best_index = index
                best_delta = delta
        if best_index < 0:
            continue
        available.remove(best_index)
        record = records[best_index]
        observed = record_value(record, "two_theta", 0)
        area = max(record_value(record, "area", 1), 1.0)
        matches.append(
            (
                int(getattr(peak, "h", 0)),
                int(getattr(peak, "k", 0)),
                int(getattr(peak, "l", 0)),
                observed,
                area,
            )
        )
    return GainIndexedEvidence(stage=stage, indexed_matches=tuple(matches))


def fit_residual_candidate_scale(
    *,
    target: np.ndarray,
    selected_total: np.ndarray,
    profile: np.ndarray,
    weights: np.ndarray,
) -> float:
    """Fit one non-negative candidate scale against the positive residual."""

    target = np.asarray(target, dtype=float)
    current = np.asarray(selected_total, dtype=float)
    candidate = np.asarray(profile, dtype=float)
    fit_weights = np.clip(np.asarray(weights, dtype=float), 0.0, None)
    usable = (
        np.isfinite(target)
        & np.isfinite(current)
        & np.isfinite(candidate)
        & np.isfinite(fit_weights)
        & (fit_weights > 0.0)
    )
    if not np.any(usable) or float(np.nanmax(candidate[usable])) <= 0.0:
        return 0.0
    residual = np.clip(target - current, 0.0, None)
    weighted_profile = candidate * fit_weights
    denominator = float(np.dot(weighted_profile[usable], candidate[usable]))
    if denominator <= 1.0e-12:
        return 0.0
    initial = max(
        0.0,
        float(np.dot(weighted_profile[usable], residual[usable])) / denominator,
    )
    if initial <= 1.0e-12:
        return 0.0

    def weighted_error(calculated: np.ndarray) -> float:
        difference = np.asarray(calculated, dtype=float) - target
        asymmetric = np.where(difference > 0.0, difference * 5.0, -difference)
        return float(np.trapezoid(asymmetric * fit_weights, dx=1.0))

    best_scale = 0.0
    best_error = weighted_error(current)
    for factor in np.linspace(0.05, 1.35, 27):
        scale = initial * float(factor)
        error = weighted_error(current + candidate * scale)
        if error < best_error:
            best_error = error
            best_scale = scale
    return float(best_scale)


def profile_residual_gain(
    *,
    residual_target: np.ndarray,
    calculated: np.ndarray,
    weights: np.ndarray,
    residual_area: float,
    before_fit: float,
) -> float:
    """Score the additional profile area explained without profile excess."""

    residual_target = np.asarray(residual_target, dtype=float)
    calculated = np.asarray(calculated, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if not (
        len(residual_target)
        and len(calculated) == len(residual_target)
        and len(weights) == len(residual_target)
    ):
        return 0.0
    covered = np.minimum(residual_target, calculated)
    excess = np.clip(calculated - residual_target, 0.0, None)
    covered_area = float(np.trapezoid(covered * weights))
    excess_area = float(np.trapezoid(excess * weights))
    if covered_area <= 0.0:
        return 0.0
    residual_fraction = covered_area / max(float(residual_area), 1.0e-12)
    support_fraction = covered_area / max(covered_area + 3.0 * excess_area, 1.0e-12)
    gain = 100.0 * residual_fraction * support_fraction
    remaining_fit = max(0.0, 100.0 - float(before_fit))
    return float(np.clip(min(gain, remaining_fit), 0.0, 100.0))
