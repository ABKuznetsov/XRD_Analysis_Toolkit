from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks


@dataclass(slots=True)
class PhaseAlignmentEstimate:
    zero_shift: float = 0.0
    matched_peaks: int = 0
    total_peaks: int = 0
    score: float = float("inf")
    status: str = "unmatched"


def nearest_index(sorted_values: np.ndarray, value: float) -> int:
    index = int(np.searchsorted(sorted_values, value, side="left"))
    if index <= 0:
        return 0
    if index >= len(sorted_values):
        return len(sorted_values) - 1
    before = index - 1
    return before if abs(float(sorted_values[before]) - value) <= abs(float(sorted_values[index]) - value) else index


def observed_peak_positions(x, corrected_y) -> np.ndarray:
    y = np.asarray(corrected_y, dtype=float)
    x_values = np.asarray(x, dtype=float)
    if len(y) < 5 or float(np.nanmax(y)) <= 0:
        return np.array([], dtype=float)
    peak_indices, _properties = _observed_peak_indices(x_values, y, prominence_factor=4.2, relative_prominence=0.030)
    if len(peak_indices) > 80:
        heights = y[peak_indices]
        keep = np.argsort(heights)[-80:]
        peak_indices = peak_indices[keep]
    return np.sort(x_values[peak_indices])


def observed_peak_records(x, corrected_y, limit: int = 24) -> list[tuple[float, float]]:
    y = np.asarray(corrected_y, dtype=float)
    x_values = np.asarray(x, dtype=float)
    if len(y) < 5 or float(np.nanmax(y)) <= 0:
        return []
    peak_indices, properties = _observed_peak_indices(x_values, y, prominence_factor=3.4, relative_prominence=0.020)
    if len(peak_indices) == 0:
        return []
    prominences = properties.get("prominences", np.zeros_like(peak_indices, dtype=float))
    records = [
        (float(x_values[index]), max(float(y[index]), float(prominence), 0.0))
        for index, prominence in zip(peak_indices, prominences, strict=False)
        if np.isfinite(x_values[index]) and np.isfinite(y[index]) and y[index] > 0
    ]
    records.sort(key=lambda item: item[1], reverse=True)
    return records[:limit]


def _observed_peak_indices(
    x: np.ndarray,
    y: np.ndarray,
    *,
    prominence_factor: float,
    relative_prominence: float,
) -> tuple[np.ndarray, dict]:
    step = _median_step(x)
    noise = _robust_noise(y)
    finite = y[np.isfinite(y)]
    p95 = float(np.nanpercentile(finite, 95)) if len(finite) else 0.0
    prominence = max(noise * float(prominence_factor), p95 * float(relative_prominence), 1.0)
    distance = max(3, int(round(0.11 / max(step, 1.0e-6))))
    max_width = max(5, int(round(1.4 / max(step, 1.0e-6))))
    indices, properties = find_peaks(
        y,
        prominence=prominence,
        distance=distance,
        width=(1, max_width),
    )
    return indices, properties


def _median_step(x: np.ndarray) -> float:
    diffs = np.diff(np.asarray(x, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    return float(np.nanmedian(diffs)) if len(diffs) else 0.03


def _robust_noise(y: np.ndarray) -> float:
    values = np.asarray(y, dtype=float)
    finite = values[np.isfinite(values)]
    if len(finite) < 3:
        return 1.0
    diffs = np.diff(finite)
    mad = float(np.nanmedian(np.abs(diffs - np.nanmedian(diffs)))) if len(diffs) else 0.0
    if mad > 0:
        return max(1.4826 * mad / np.sqrt(2.0), 1.0)
    mad = float(np.nanmedian(np.abs(finite - np.nanmedian(finite))))
    return max(1.4826 * mad, 1.0)


def estimate_phase_alignment(peaks, observed_positions: np.ndarray, structure) -> PhaseAlignmentEstimate:
    if len(observed_positions) == 0 or not peaks:
        return PhaseAlignmentEstimate()
    strong_peaks = [
        peak
        for peak in peaks
        if getattr(peak, "intensity", 0.0) >= 5.0 and 5.0 <= getattr(peak, "two_theta", 0.0) <= 120.0
    ]
    strong_peaks = sorted(strong_peaks, key=lambda peak: peak.intensity, reverse=True)[:35]
    pairs = []
    for peak in strong_peaks:
        calc_tt = float(peak.two_theta)
        nearest = nearest_index(observed_positions, calc_tt)
        obs_tt = float(observed_positions[nearest])
        delta = obs_tt - calc_tt
        if abs(delta) > 0.45:
            continue
        pairs.append((peak, obs_tt))
    total_peaks = len(strong_peaks)
    if len(pairs) < 3:
        return PhaseAlignmentEstimate(matched_peaks=len(pairs), total_peaks=total_peaks, status="weak")
    residuals = []
    weights = []
    for peak, obs_tt in pairs:
        residuals.append(obs_tt - float(peak.two_theta))
        weights.append(max(float(getattr(peak, "intensity", 1.0)), 1.0))
    residuals = np.asarray(residuals, dtype=float)
    weights = np.asarray(weights, dtype=float)
    best_zero = float(np.average(residuals, weights=weights))
    centered = residuals - best_zero
    best_score = float(np.average(np.abs(centered), weights=weights))
    if not np.isfinite(best_score):
        return PhaseAlignmentEstimate(matched_peaks=len(pairs), total_peaks=total_peaks, status="weak")

    matched_fraction = len(pairs) / max(total_peaks, 1)
    if best_score > 0.18 or matched_fraction < 0.18:
        return PhaseAlignmentEstimate(
            matched_peaks=len(pairs),
            total_peaks=total_peaks,
            score=best_score,
            status="weak",
        )
    status = "good" if best_score <= 0.08 and matched_fraction >= 0.3 else "ok"
    return PhaseAlignmentEstimate(
        zero_shift=float(np.clip(best_zero, -0.5, 0.5)),
        matched_peaks=len(pairs),
        total_peaks=total_peaks,
        score=best_score,
        status=f"{status} shift-only",
    )


def peak_probability_from_alignment(alignment: PhaseAlignmentEstimate) -> float:
    if alignment.total_peaks <= 0:
        return 0.0
    matched_fraction = alignment.matched_peaks / max(alignment.total_peaks, 1)
    residual_penalty = 1.0
    if alignment.score > 0:
        residual_penalty = max(0.15, 1.0 - min(alignment.score / 0.45, 1.0))
    enough_peaks_factor = min(alignment.matched_peaks / 8.0, 1.0)
    return float(np.clip(100.0 * matched_fraction * residual_penalty * enough_peaks_factor, 0.0, 100.0))


def peak_presence_probability(peaks, observed_x: np.ndarray, corrected_y: np.ndarray, structure) -> float:
    return peak_presence_probability_from_records(
        peaks,
        observed_peak_records(observed_x, corrected_y, limit=80),
        structure,
    )


def peak_presence_probability_from_records(peaks, observed_records: list[tuple[float, float]], structure) -> float:
    if not observed_records or not peaks:
        return 0.0
    observed_pairs = sorted(
        (
            (float(position), max(float(height), 0.0))
            for position, height in observed_records
            if np.isfinite(position) and np.isfinite(height)
        ),
        key=lambda item: item[0],
    )
    if not observed_pairs:
        return 0.0
    observed_positions = np.asarray([position for position, _height in observed_pairs], dtype=float)
    observed_heights = np.asarray([height for _position, height in observed_pairs], dtype=float)
    if len(observed_positions) == 0 or float(np.nanmax(observed_heights, initial=0.0)) <= 0:
        return 0.0
    observed_relative = observed_heights / max(float(np.nanmax(observed_heights)), 1.0)

    strong_calc = [
        peak
        for peak in peaks
        if getattr(peak, "intensity", 0.0) >= 1.0 and 5.0 <= getattr(peak, "two_theta", 0.0) <= 120.0
    ]
    strong_calc = sorted(strong_calc, key=lambda peak: float(getattr(peak, "intensity", 0.0)), reverse=True)[:24]
    if not strong_calc:
        return 0.0

    alignment = estimate_phase_alignment(strong_calc, np.sort(observed_positions), structure)
    zero_seed = alignment.zero_shift if alignment.matched_peaks >= 3 else 0.0
    base_positions = np.asarray([float(peak.two_theta) for peak in strong_calc], dtype=float)
    calc_intensities = np.asarray([max(float(getattr(peak, "intensity", 0.0)), 0.0) for peak in strong_calc], dtype=float)
    strongest_calc = max(float(np.nanmax(calc_intensities)), 1.0)
    calc_relative = np.clip(calc_intensities / strongest_calc, 0.0, 1.0)

    tolerance = 0.34
    (
        calc_positions,
        calc_coverage,
        top_matches,
        strongest_match_quality,
        fit_penalty,
        intensity_fit,
    ) = _best_candidate_position_fit(
        base_positions,
        calc_relative,
        observed_positions,
        observed_relative,
        tolerance,
        zero_seed,
    )

    observed_total = 0.0
    observed_weighted = 0.0
    sorted_calc_positions = np.sort(calc_positions)
    max_observed = max(float(np.nanmax(observed_heights)), 1.0)
    for obs_position, obs_height in observed_records[:30]:
        rel_height = max(float(obs_height), 0.0) / max_observed
        weight = max(rel_height, 0.03) ** 0.45
        observed_total += weight
        nearest = _nearest_delta(sorted_calc_positions, obs_position)
        if nearest <= tolerance:
            quality = max(0.0, 1.0 - nearest / tolerance)
            observed_weighted += weight * (0.35 + 0.65 * quality)
    observed_coverage = observed_weighted / observed_total if observed_total > 0 else 0.0

    # Primary ranking follows the candidate's own strongest peaks. Observed coverage
    # is deliberately weak because unrelated strong peaks often belong to other phases.
    probability = 100.0 * (0.78 * calc_coverage + 0.16 * observed_coverage + 0.06 * min(top_matches / 6.0, 1.0))
    if strongest_match_quality <= 0.0:
        probability = min(probability, 22.0)
    elif top_matches < 2:
        probability = min(probability, 45.0)
    elif top_matches < 3:
        probability = min(probability, 68.0)
    probability *= fit_penalty * (0.72 + 0.28 * intensity_fit)
    if alignment.score > 0.20:
        probability *= max(0.68, 1.0 - min((alignment.score - 0.20) / 0.45, 0.32))
    return float(np.clip(probability, 0.0, 100.0))


def _best_candidate_position_fit(
    base_positions: np.ndarray,
    calc_relative: np.ndarray,
    observed_positions: np.ndarray,
    observed_relative: np.ndarray,
    tolerance: float,
    zero_seed: float,
) -> tuple[np.ndarray, float, int, float, float, float]:
    best_positions = base_positions
    best_coverage = 0.0
    best_top_matches = 0
    best_strongest_quality = 0.0
    best_penalty = 1.0
    best_intensity_fit = 0.0
    best_score = -1.0
    scale_candidates = (-0.003, -0.0015, 0.0, 0.0015, 0.003)
    zero_candidates = sorted({
        -0.35,
        -0.20,
        -0.10,
        0.0,
        0.10,
        0.20,
        0.35,
        float(np.clip(zero_seed, -0.45, 0.45)),
    })
    pivot = 45.0
    for scale in scale_candidates:
        scaled = base_positions + (base_positions - pivot) * scale
        for zero in zero_candidates:
            positions = scaled + zero
            coverage, top_matches, strongest_quality, intensity_fit = _candidate_position_coverage(
                positions,
                calc_relative,
                observed_positions,
                observed_relative,
                tolerance,
            )
            deformation_penalty = max(0.84, 1.0 - abs(scale) * 22.0 - abs(zero) * 0.16)
            score = coverage * deformation_penalty * (0.85 + 0.15 * intensity_fit)
            if score > best_score:
                best_score = score
                best_positions = positions
                best_coverage = coverage
                best_top_matches = top_matches
                best_strongest_quality = strongest_quality
                best_penalty = deformation_penalty
                best_intensity_fit = intensity_fit
    return best_positions, best_coverage, best_top_matches, best_strongest_quality, best_penalty, best_intensity_fit


def _candidate_position_coverage(
    calc_positions: np.ndarray,
    calc_relative: np.ndarray,
    observed_positions: np.ndarray,
    observed_relative: np.ndarray,
    tolerance: float,
) -> tuple[float, int, float, float]:
    calc_weighted = 0.0
    calc_total = 0.0
    top_matches = 0
    strongest_match_quality = 0.0
    matched_calc: list[float] = []
    matched_observed: list[float] = []
    matched_weights: list[float] = []
    for index, (calc_position, rel_intensity) in enumerate(zip(calc_positions, calc_relative)):
        calc_rel = max(float(rel_intensity), 0.03)
        weight = calc_rel ** 0.55
        calc_total += weight
        nearest, observed_index = _nearest_delta_index(observed_positions, float(calc_position))
        if nearest <= tolerance:
            quality = max(0.0, 1.0 - nearest / tolerance)
            obs_rel = max(float(observed_relative[observed_index]), 0.001)
            intensity_quality = _relative_intensity_quality(calc_rel, obs_rel, matched_calc, matched_observed, matched_weights)
            calc_weighted += weight * (0.30 + 0.50 * quality + 0.20 * quality * intensity_quality)
            matched_calc.append(calc_rel)
            matched_observed.append(obs_rel)
            matched_weights.append(weight)
            if index < 8:
                top_matches += 1
            if index == 0:
                strongest_match_quality = quality * (0.65 + 0.35 * intensity_quality)
    coverage = calc_weighted / calc_total if calc_total > 0 else 0.0
    intensity_fit = _relative_intensity_fit(matched_calc, matched_observed, matched_weights)
    return coverage, top_matches, strongest_match_quality, intensity_fit


def _relative_intensity_quality(
    calc_rel: float,
    obs_rel: float,
    matched_calc: list[float],
    matched_observed: list[float],
    matched_weights: list[float],
) -> float:
    scale = _relative_intensity_scale(matched_calc, matched_observed, matched_weights)
    expected = max(calc_rel * scale, 1e-6)
    ratio = max(obs_rel, 1e-6) / expected
    return float(np.clip(np.exp(-abs(np.log(ratio)) * 0.85), 0.0, 1.0))


def _relative_intensity_fit(
    matched_calc: list[float],
    matched_observed: list[float],
    matched_weights: list[float],
) -> float:
    if len(matched_calc) < 2:
        return 0.55 if matched_calc else 0.0
    scale = _relative_intensity_scale(matched_calc, matched_observed, matched_weights)
    qualities = []
    for calc_rel, obs_rel in zip(matched_calc, matched_observed):
        expected = max(calc_rel * scale, 1e-6)
        ratio = max(obs_rel, 1e-6) / expected
        qualities.append(float(np.clip(np.exp(-abs(np.log(ratio)) * 0.85), 0.0, 1.0)))
    weights = np.asarray(matched_weights, dtype=float)
    values = np.asarray(qualities, dtype=float)
    return float(np.average(values, weights=weights)) if float(np.sum(weights)) > 0 else float(np.mean(values))


def _relative_intensity_scale(
    matched_calc: list[float],
    matched_observed: list[float],
    matched_weights: list[float],
) -> float:
    if not matched_calc:
        return 1.0
    calc = np.asarray(matched_calc, dtype=float)
    observed = np.asarray(matched_observed, dtype=float)
    weights = np.asarray(matched_weights, dtype=float)
    denominator = float(np.sum(weights * calc * calc))
    if denominator <= 0:
        return 1.0
    scale = float(np.sum(weights * calc * observed) / denominator)
    return float(np.clip(scale, 0.05, 12.0))

def _nearest_delta(sorted_values: np.ndarray, value: float) -> float:
    delta, _index = _nearest_delta_index(sorted_values, value)
    return delta


def _nearest_delta_index(sorted_values: np.ndarray, value: float) -> tuple[float, int]:
    if len(sorted_values) == 0:
        return 999.0, -1
    index = nearest_index(sorted_values, float(value))
    return abs(float(sorted_values[index]) - float(value)), index
