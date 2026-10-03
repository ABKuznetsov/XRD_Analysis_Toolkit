from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import find_peaks, peak_prominences, peak_widths, savgol_filter

from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.instrument.resolution import cristma_tch_profile
from xrd_finder.finder.residual_peak_refinement import refine_residual_peak
from xrd_finder.services.profile_matched_peak_detector import (
    is_broad_rescue_candidate,
    profile_matched_peak_hypotheses,
)


@dataclass(slots=True)
class PhaseAlignmentEstimate:
    zero_shift: float = 0.0
    matched_peaks: int = 0
    total_peaks: int = 0
    score: float = float("inf")
    status: str = "unmatched"


@dataclass(slots=True)
class ObservedLineRecord:
    two_theta: float
    area: float
    fwhm: float
    height: float = 0.0
    prominence: float = 0.0
    area_positive: float = 0.0
    area_signed: float = 0.0
    area_snr: float = 0.0
    curvature: float = 0.0
    fwhm_observed: float = 0.0
    fwhm_sample: float | None = None
    instrument_limited: bool = False
    fit_quality: float = 0.0
    asymmetry: float = 0.0
    broadening_scale: float = 1.0
    profile_match: float = 0.0
    local_snr: float = 0.0
    confidence: float = 0.0
    overlap_flag: bool = False
    delta_chi2: float = 0.0
    width_persistence: int = 0
    evidence_class: str = ""

    def __iter__(self):
        yield self.two_theta
        yield self.area


def nearest_index(sorted_values: np.ndarray, value: float) -> int:
    index = int(np.searchsorted(sorted_values, value, side="left"))
    if index <= 0:
        return 0
    if index >= len(sorted_values):
        return len(sorted_values) - 1
    before = index - 1
    return before if abs(float(sorted_values[before]) - value) <= abs(float(sorted_values[index]) - value) else index


def observed_peak_positions(x, corrected_y, *, distance_scale: float = 1.0) -> np.ndarray:
    y = np.asarray(corrected_y, dtype=float)
    x_values = np.asarray(x, dtype=float)
    if len(y) < 5 or float(np.nanmax(y)) <= 0:
        return np.array([], dtype=float)
    peak_indices, _properties = _observed_peak_indices(
        x_values,
        y,
        prominence_factor=4.2,
        relative_prominence=0.030,
        distance_scale=distance_scale,
    )
    if len(peak_indices) > 80:
        heights = y[peak_indices]
        keep = np.argsort(heights)[-80:]
        peak_indices = peak_indices[keep]
    return np.sort(x_values[peak_indices])


def observed_peak_records(
    x,
    corrected_y,
    limit: int = 24,
    *,
    distance_scale: float = 1.0,
    instrument_profile: InstrumentProfile | None = None,
    sigma_threshold: float = 3.0,
) -> list[ObservedLineRecord]:
    y = np.asarray(corrected_y, dtype=float)
    x_values = np.asarray(x, dtype=float)
    if len(y) < 5 or float(np.nanmax(y)) <= 0:
        return []
    matched_records: list[ObservedLineRecord] = []
    if instrument_profile is not None:
        hypotheses = profile_matched_peak_hypotheses(
            x_values,
            y,
            fwhm_at=lambda position: instrument_fwhm_at(
                instrument_profile, position
            ),
            broadening_scales=(0.7, 1.0, 1.4, 2.0, 2.5, 3.0, 4.0),
            sigma_threshold=sigma_threshold,
            limit=limit,
            satellite_components_at=lambda position: radiation_satellites_at(
                instrument_profile, position
            ),
        )
        for hypothesis in hypotheses:
            instrument_width = instrument_fwhm_at(
                instrument_profile, hypothesis.position
            )
            fitted = refine_residual_peak(
                x_values,
                y,
                hypothesis.position,
                expected_fwhm=hypothesis.effective_fwhm,
                instrument_fwhm=instrument_width,
                satellite_offsets_weights=radiation_satellites_at(
                    instrument_profile, hypothesis.position
                ),
            )
            use_fit = bool(
                fitted is not None
                and fitted.fit_quality >= 0.20
                and fitted.height > 0.0
            )
            position = fitted.two_theta if use_fit else hypothesis.position
            area = fitted.area if use_fit else hypothesis.area
            observed_fwhm = (
                fitted.fwhm_observed if use_fit else hypothesis.effective_fwhm
            )
            height = fitted.height if use_fit else hypothesis.amplitude
            prominence = fitted.prominence if use_fit else hypothesis.amplitude
            if use_fit:
                sample_fwhm = fitted.fwhm_sample
                instrument_limited = fitted.instrument_limited
            else:
                sample_fwhm, instrument_limited = _sample_fwhm(
                    observed_fwhm,
                    instrument_width,
                )
            matched_records.append(
                ObservedLineRecord(
                    two_theta=position,
                    area=area,
                    fwhm=observed_fwhm,
                    height=height,
                    prominence=prominence,
                    area_positive=hypothesis.area_positive,
                    area_signed=hypothesis.area_signed,
                    area_snr=hypothesis.area_snr,
                    curvature=hypothesis.curvature,
                    fwhm_observed=observed_fwhm,
                    fwhm_sample=sample_fwhm,
                    instrument_limited=instrument_limited,
                    fit_quality=max(
                        hypothesis.profile_match,
                        fitted.fit_quality if use_fit else 0.0,
                    ),
                    asymmetry=fitted.asymmetry if use_fit else 0.0,
                    broadening_scale=hypothesis.broadening_scale,
                    profile_match=hypothesis.profile_match,
                    local_snr=hypothesis.local_snr,
                    confidence=hypothesis.confidence,
                    overlap_flag=hypothesis.overlap_flag,
                    delta_chi2=hypothesis.delta_chi2,
                    width_persistence=hypothesis.width_persistence,
                    evidence_class=hypothesis.evidence_class,
                )
            )
        matched_records.sort(key=lambda item: item.height, reverse=True)
    detection_y = _lightly_smoothed_signal(x_values, y)
    peak_indices, _properties = _observed_peak_indices(
        x_values,
        detection_y,
        prominence_factor=3.4,
        relative_prominence=0.020,
        distance_scale=distance_scale,
    )
    if len(peak_indices) == 0:
        return [
            record for record in matched_records if is_broad_rescue_candidate(record)
        ][:limit]
    step = _median_step(x_values)
    peak_indices = _refine_peak_indices_on_raw(x_values, y, peak_indices)
    prominences = peak_prominences(y, peak_indices)[0]
    width_result = peak_widths(y, peak_indices, rel_height=0.5)
    widths = width_result[0]
    left_ips = width_result[2]
    right_ips = width_result[3]
    records = []
    global_noise = _robust_noise(y)
    for index, prominence, width, left, right in zip(
        peak_indices,
        prominences,
        widths,
        left_ips,
        right_ips,
        strict=False,
    ):
        if not np.isfinite(x_values[index]) or not np.isfinite(y[index]) or y[index] <= 0:
            continue
        local_snr, effective_noise = _peak_local_noise_statistics(
            x_values,
            y,
            int(index),
            global_noise=global_noise,
        )
        if local_snr < max(float(sigma_threshold), 0.0):
            continue
        measured_fwhm = float(np.clip(float(width) * step, 0.05, 0.90))
        sample_fwhm, instrument_limited = _sample_fwhm(
            measured_fwhm,
            instrument_fwhm_at(instrument_profile, float(x_values[index])),
        )
        peak_area = _peak_area(y, float(prominence), float(left), float(right), step)
        area_noise = effective_noise * np.sqrt(max(float(right - left), 1.0)) * step
        records.append(
            ObservedLineRecord(
                two_theta=float(x_values[index]),
                area=peak_area,
                fwhm=measured_fwhm,
                height=max(float(y[index]), float(prominence), 0.0),
                prominence=max(float(prominence), 0.0),
                area_positive=max(float(peak_area), 0.0),
                area_signed=float(peak_area),
                area_snr=float(peak_area) / max(float(area_noise), 1.0e-12),
                fwhm_observed=measured_fwhm,
                fwhm_sample=sample_fwhm,
                instrument_limited=instrument_limited,
                local_snr=float(local_snr),
            )
        )
    records.sort(key=lambda item: item.height, reverse=True)
    for matched in matched_records:
        nearest = min(
            records,
            key=lambda item: abs(item.two_theta - matched.two_theta),
            default=None,
        )
        duplicate_tolerance = (
            max(0.025, min(nearest.fwhm, matched.fwhm) * 0.45)
            if nearest is not None
            else 0.0
        )
        if nearest is None or abs(nearest.two_theta - matched.two_theta) > duplicate_tolerance:
            if is_broad_rescue_candidate(matched):
                records.append(matched)
            continue
        if matched.fit_quality >= nearest.fit_quality:
            nearest.two_theta = matched.two_theta
            nearest.area = matched.area
            nearest.fwhm = matched.fwhm
            nearest.height = matched.height
            nearest.prominence = matched.prominence
            nearest.area_positive = matched.area_positive
            nearest.area_signed = matched.area_signed
            nearest.area_snr = matched.area_snr
            nearest.curvature = matched.curvature
            nearest.fwhm_observed = matched.fwhm_observed
            nearest.fwhm_sample = matched.fwhm_sample
            nearest.instrument_limited = matched.instrument_limited
            nearest.asymmetry = matched.asymmetry
        nearest.broadening_scale = matched.broadening_scale
        nearest.profile_match = matched.profile_match
        nearest.local_snr = matched.local_snr
        nearest.confidence = matched.confidence
        nearest.overlap_flag = matched.overlap_flag
        nearest.delta_chi2 = matched.delta_chi2
        nearest.width_persistence = matched.width_persistence
        nearest.evidence_class = matched.evidence_class
        nearest.fit_quality = max(nearest.fit_quality, matched.fit_quality)
    records.sort(key=lambda item: item.height, reverse=True)
    return records[:limit]


def _peak_exceeds_local_noise(
    x: np.ndarray,
    y: np.ndarray,
    index: int,
    *,
    global_noise: float,
    sigma_threshold: float,
) -> bool:
    threshold_factor = max(float(sigma_threshold), 0.0)
    if threshold_factor <= 0.0:
        return True
    local_snr, _effective_noise = _peak_local_noise_statistics(
        x,
        y,
        index,
        global_noise=global_noise,
    )
    return bool(local_snr >= threshold_factor)


def _peak_local_noise_statistics(
    x: np.ndarray,
    y: np.ndarray,
    index: int,
    *,
    global_noise: float,
) -> tuple[float, float]:
    position = float(x[index])
    half_width = 1.0
    left = int(np.searchsorted(x, position - half_width, side="left"))
    right = int(np.searchsorted(x, position + half_width, side="right"))
    local = np.asarray(y[left:right], dtype=float)
    local = local[np.isfinite(local)]
    if len(local) < 7:
        local_noise = float(global_noise)
        baseline = 0.0
    else:
        local_noise = _robust_noise(local)
        baseline = float(np.nanmedian(local))
    effective_noise = max(local_noise, float(global_noise) * 0.65, 1.0e-9)
    signal_height = float(y[index]) - baseline
    return max(signal_height / effective_noise, 0.0), effective_noise


def _lightly_smoothed_signal(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    step = _median_step(x)
    window = int(round(0.05 / max(step, 1.0e-6)))
    window = min(11, max(5, window))
    if window % 2 == 0:
        window += 1
    if len(y) < window:
        return y
    try:
        return np.asarray(savgol_filter(y, window, 2, mode="interp"), dtype=float)
    except Exception:
        return y


def _refine_peak_indices_on_raw(
    x: np.ndarray,
    y: np.ndarray,
    detected_indices: np.ndarray,
) -> np.ndarray:
    step = _median_step(x)
    radius = max(1, int(round(0.06 / max(step, 1.0e-6))))
    refined = []
    for detected in detected_indices:
        left = max(0, int(detected) - radius)
        right = min(len(y), int(detected) + radius + 1)
        if right <= left:
            continue
        refined.append(left + int(np.nanargmax(y[left:right])))
    return np.asarray(sorted(set(refined)), dtype=int)


def _peak_area(y: np.ndarray, prominence: float, left_ip: float, right_ip: float, step: float) -> float:
    left = max(0, int(np.floor(left_ip)))
    right = min(len(y) - 1, int(np.ceil(right_ip)))
    if right <= left:
        return max(float(prominence), 0.0)
    baseline = max(float(y[left]), float(y[right]), 0.0)
    values = np.clip(np.asarray(y[left : right + 1], dtype=float) - baseline, 0.0, None)
    return max(float(np.trapezoid(values, dx=step)), float(prominence) * step, 0.0)


def instrument_fwhm_at(profile: InstrumentProfile | None, two_theta: float) -> float:
    if profile is None:
        return 0.0
    resolution = profile.resolution
    if resolution.model == "constant_fwhm":
        return max(float(resolution.constant_fwhm_deg), 0.0)
    try:
        model = cristma_tch_profile(resolution)
        return max(float(model.fwhm_deg_at(float(two_theta))), 0.0)
    except Exception:
        return 0.0


def radiation_satellites_at(
    profile: InstrumentProfile | None,
    two_theta: float,
) -> tuple[tuple[float, float], ...]:
    if profile is None or profile.radiation.mode != "kalpha_doublet":
        return ()
    components = tuple(profile.radiation.components)
    if len(components) < 2:
        return ()
    primary = components[0]
    theta = math.radians(float(two_theta) * 0.5)
    sine = math.sin(theta)
    if sine <= 0.0:
        return ()
    d_spacing = float(primary.wavelength_angstrom) / (2.0 * sine)
    primary_lp = _local_lp_factor(profile, float(two_theta))
    satellites = []
    for component in components[1:]:
        argument = float(component.wavelength_angstrom) / (2.0 * d_spacing)
        if not 0.0 < argument < 1.0:
            continue
        component_two_theta = 2.0 * math.degrees(math.asin(argument))
        relative_weight = float(component.weight) / max(float(primary.weight), 1.0e-12)
        relative_weight *= _local_lp_factor(profile, component_two_theta) / max(primary_lp, 1.0e-12)
        satellites.append((component_two_theta - float(two_theta), relative_weight))
    return tuple(satellites)


def _local_lp_factor(profile: InstrumentProfile, two_theta: float) -> float:
    if not profile.geometry.apply_lorentz_polarization:
        return 1.0
    theta = math.radians(float(two_theta) * 0.5)
    angle = math.radians(float(two_theta))
    sine = max(math.sin(theta), 1.0e-6)
    cosine = max(math.cos(theta), 1.0e-6)
    perpendicular = float(np.clip(profile.geometry.polarization_fraction, 0.0, 1.0))
    polarization = perpendicular + (1.0 - perpendicular) * math.cos(angle) ** 2
    return polarization / (sine * sine * cosine)


def _sample_fwhm(observed_fwhm: float, instrument_fwhm: float) -> tuple[float | None, bool]:
    # Effective Gaussian estimate used as a cheap grouping feature.  Full
    # profile fitting still uses the instrument model directly.
    observed = max(float(observed_fwhm), 0.0)
    instrument = max(float(instrument_fwhm), 0.0)
    instrument_limited = bool(instrument > 0.0 and observed <= instrument * 1.15)
    if instrument_limited:
        return None, True
    if instrument <= 0.0:
        return observed, False
    return float(np.sqrt(max(observed**2 - instrument**2, 0.0))), False


def _observed_peak_indices(
    x: np.ndarray,
    y: np.ndarray,
    *,
    prominence_factor: float,
    relative_prominence: float,
    distance_scale: float = 1.0,
) -> tuple[np.ndarray, dict]:
    step = _median_step(x)
    noise = _robust_noise(y)
    finite = y[np.isfinite(y)]
    p95 = float(np.nanpercentile(finite, 95)) if len(finite) else 0.0
    prominence = max(noise * float(prominence_factor), p95 * float(relative_prominence), 1.0)
    scale = max(float(distance_scale), 0.05)
    distance = max(3, int(round((0.11 * scale) / max(step, 1.0e-6))))
    max_width = max(5, int(round(1.4 / max(step, 1.0e-6))))
    indices, properties = find_peaks(
        y,
        prominence=prominence,
        distance=distance,
        width=(1, max_width),
    )
    height_floor = max(noise * 2.2, float(np.nanpercentile(finite, 65)) if len(finite) else 0.0)
    height_distance = max(2, int(round((0.045 * scale) / max(step, 1.0e-6))))
    height_indices, _height_properties = find_peaks(
        y,
        height=height_floor,
        distance=height_distance,
    )
    if len(height_indices):
        top_height = height_indices[np.argsort(y[height_indices])[-160:]]
        combined = np.unique(np.concatenate([indices, top_height])).astype(int)
        if len(combined):
            combined_prominences = peak_prominences(y, combined)[0]
            combined_widths = peak_widths(y, combined, rel_height=0.5)[0]
            keep = (
                np.isfinite(combined_prominences)
                & np.isfinite(combined_widths)
                & (combined_prominences >= max(noise * 1.15, 1.0))
                & (combined_widths <= max_width)
            )
            indices = combined[keep]
            properties = {
                "prominences": combined_prominences[keep],
                "widths": combined_widths[keep],
            }
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
