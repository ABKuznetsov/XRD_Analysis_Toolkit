from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

import numpy as np
from scipy.signal import find_peaks

from xrd_finder.finder.residual_peak_refinement import (
    pseudo_voigt_radiation_profile,
)


@dataclass(frozen=True, slots=True)
class ProfileMatchedPeakHypothesis:
    position: float
    amplitude: float
    area: float
    prominence: float
    area_positive: float
    area_signed: float
    area_snr: float
    broadening_scale: float
    effective_fwhm: float
    profile_match: float
    local_snr: float
    confidence: float
    delta_chi2: float
    width_persistence: int
    evidence_class: str
    overlap_flag: bool = False


def profile_matched_peak_hypotheses(
    x,
    residual,
    *,
    fwhm_at: Callable[[float], float],
    broadening_scales: Sequence[float] = (0.7, 1.0, 1.4, 2.0, 3.0, 4.0),
    eta: float = 0.35,
    sigma_threshold: float = 3.0,
    width_bins: int = 24,
    kernel_hwhm: float = 4.5,
    limit: int = 80,
    satellite_components_at: Callable[[float], Sequence[tuple[float, float]]] | None = None,
) -> tuple[ProfileMatchedPeakHypothesis, ...]:
    """Detect residual peaks with a bank of angle-dependent XRD profiles."""

    x_values = np.asarray(x, dtype=float)
    signal = np.asarray(residual, dtype=float)
    if len(x_values) < 9 or len(signal) != len(x_values):
        return ()
    finite = np.isfinite(x_values) & np.isfinite(signal)
    if np.count_nonzero(finite) < 9:
        return ()
    if not np.all(finite):
        x_values = x_values[finite]
        signal = signal[finite]
    order = np.argsort(x_values)
    x_values = x_values[order]
    signal = signal[order]
    step = _median_step(x_values)
    if step <= 0.0:
        return ()
    signal = signal - float(np.nanmedian(signal))
    noise = _robust_noise(signal)
    scales = tuple(
        sorted(
            {
                float(scale)
                for scale in broadening_scales
                if math.isfinite(float(scale)) and float(scale) > 0.0
            }
        )
    )
    if not scales:
        return ()

    sample_count = min(max(8, int(width_bins) + 1), len(x_values))
    sample_positions = np.linspace(
        float(x_values[0]), float(x_values[-1]), sample_count
    )
    sample_widths = np.asarray(
        [_safe_fwhm(fwhm_at, position, step) for position in sample_positions],
        dtype=float,
    )
    base_widths = np.interp(x_values, sample_positions, sample_widths)
    segment_edges = np.linspace(
        0, len(x_values), min(max(1, int(width_bins)), len(x_values)) + 1
    ).astype(int)

    quality_maps = np.full((len(scales), len(x_values)), -np.inf, dtype=float)
    amplitude_maps = np.zeros_like(quality_maps)
    match_maps = np.zeros_like(quality_maps)
    width_maps = np.zeros_like(quality_maps)
    signal_squared = np.square(signal)
    for scale_index, scale in enumerate(scales):
        for left, right in zip(segment_edges[:-1], segment_edges[1:], strict=True):
            if right <= left:
                continue
            representative_index = min((left + right) // 2, len(x_values) - 1)
            center = float(x_values[representative_index])
            fwhm = max(float(base_widths[representative_index]) * scale, step * 2.5)
            half_points = max(
                2,
                int(math.ceil((kernel_hwhm * 0.5 * fwhm) / step)),
            )
            offsets = np.arange(-half_points, half_points + 1, dtype=float) * step
            satellites = (
                tuple(satellite_components_at(center))
                if satellite_components_at is not None
                else ()
            )
            kernel = pseudo_voigt_radiation_profile(
                offsets,
                0.0,
                fwhm,
                float(np.clip(eta, 0.0, 1.0)),
                satellites,
            )
            baseline_basis = np.column_stack(
                [np.ones(len(offsets), dtype=float), offsets]
            )
            baseline_coefficients, *_unused = np.linalg.lstsq(
                baseline_basis, kernel, rcond=None
            )
            matched_kernel = kernel - baseline_basis @ baseline_coefficients
            kernel_energy = float(np.dot(matched_kernel, matched_kernel))
            if kernel_energy <= 0.0:
                continue
            numerator = np.convolve(signal, matched_kernel[::-1], mode="same")
            local_energy = np.convolve(
                signal_squared,
                np.ones(len(kernel), dtype=float),
                mode="same",
            )
            amplitude = numerator / kernel_energy
            profile_match = numerator / np.sqrt(
                np.maximum(kernel_energy * local_energy, 1.0e-24)
            )
            matched_snr = numerator / max(
                noise * math.sqrt(kernel_energy), 1.0e-12
            )
            match_weight = np.clip(profile_match, 0.0, 1.0)
            # Integrated matched-filter significance rewards a broad peak only
            # when the signal follows the broad kernel across its full support.
            quality = matched_snr * np.square(match_weight)
            quality_maps[scale_index, left:right] = quality[left:right]
            amplitude_maps[scale_index, left:right] = amplitude[left:right]
            match_maps[scale_index, left:right] = profile_match[left:right]
            width_maps[scale_index, left:right] = fwhm
            edge_left = max(left, half_points)
            edge_right = min(right, len(x_values) - half_points)
            if edge_left > left:
                quality_maps[scale_index, left:edge_left] = -np.inf
            if edge_right < right:
                quality_maps[scale_index, edge_right:right] = -np.inf

    minimum_width = max(float(np.nanmin(base_widths)) * min(scales), step * 2.5)
    distance = max(2, int(round((minimum_width * 0.30) / step)))
    threshold = max(float(sigma_threshold), 0.0)
    peak_scale_pairs: list[tuple[float, int, int]] = []
    for scale_index in range(len(scales)):
        scale_quality = np.nan_to_num(
            quality_maps[scale_index], nan=-np.inf, neginf=-np.inf
        )
        scale_peak_indices, _properties = find_peaks(
            scale_quality,
            height=max(threshold * 0.65, 1.0),
            prominence=max(threshold * 0.10, 0.20),
            distance=distance,
        )
        peak_scale_pairs.extend(
            (float(scale_quality[index]), int(index), scale_index)
            for index in scale_peak_indices
        )
    peak_scale_pairs.sort(key=lambda item: (-item[0], item[1], item[2]))

    hypotheses: list[ProfileMatchedPeakHypothesis] = []
    for quality_at_peak, index, scale_index in peak_scale_pairs:
        amplitude = max(float(amplitude_maps[scale_index, index]), 0.0)
        profile_match = float(
            np.clip(match_maps[scale_index, index], 0.0, 1.0)
        )
        local_noise = _local_noise(
            x_values,
            signal,
            float(x_values[index]),
            fallback=noise,
        )
        local_snr = amplitude / max(local_noise, 1.0e-12)
        candidate_width = max(
            float(width_maps[scale_index, index]), step * 2.5
        )
        persistence_radius = max(
            1, int(round(candidate_width * 0.20 / step))
        )
        local_left = max(0, int(index) - persistence_radius)
        local_right = min(len(x_values), int(index) + persistence_radius + 1)
        width_persistence = 0
        for neighbour_scale in range(
            max(0, scale_index - 1), min(len(scales), scale_index + 2)
        ):
            neighbour_quality = float(
                np.nanmax(quality_maps[neighbour_scale, local_left:local_right])
            )
            if neighbour_quality >= max(
                threshold * 0.55, quality_at_peak * 0.22
            ):
                width_persistence += 1
        (
            delta_chi2,
            fitted_amplitude,
            prominence,
            area_positive,
            area_signed,
            area_snr,
        ) = _local_peak_fit_statistics(
            x_values,
            signal,
            index=int(index),
            fwhm=candidate_width,
            eta=float(np.clip(eta, 0.0, 1.0)),
            noise=local_noise,
            kernel_hwhm=kernel_hwhm,
            satellites=(
                tuple(satellite_components_at(float(x_values[index])))
                if satellite_components_at is not None
                else ()
            ),
        )
        amplitude = max(amplitude, fitted_amplitude, 0.0)
        if (
            local_snr < threshold
            or profile_match < 0.35
            or delta_chi2 < 4.0
            or (width_persistence < 2 and local_snr < max(8.0, threshold * 2.5))
        ):
            continue
        fwhm = candidate_width
        area = amplitude * float(
            np.trapezoid(
                pseudo_voigt_radiation_profile(
                    np.arange(
                        -max(2, int(math.ceil((kernel_hwhm * 0.5 * fwhm) / step))),
                        max(2, int(math.ceil((kernel_hwhm * 0.5 * fwhm) / step))) + 1,
                        dtype=float,
                    )
                    * step,
                    0.0,
                    fwhm,
                    float(np.clip(eta, 0.0, 1.0)),
                    (),
                ),
                dx=step,
            )
        )
        if (
            width_persistence >= 3
            and local_snr >= max(4.0, threshold + 1.0)
            and delta_chi2 >= 9.0
        ):
            evidence_class = "strong"
        elif width_persistence >= 2:
            evidence_class = "weak"
        else:
            evidence_class = "tentative"
        confidence = float(
            np.clip(
                profile_match
                * min(local_snr / max(threshold * 2.0, 1.0), 1.0),
                0.0,
                1.0,
            )
        )
        hypotheses.append(
            ProfileMatchedPeakHypothesis(
                position=float(x_values[index]),
                amplitude=amplitude,
                area=max(area, area_positive, amplitude * step),
                prominence=max(float(prominence), 0.0),
                area_positive=max(float(area_positive), 0.0),
                area_signed=float(area_signed),
                area_snr=float(area_snr),
                broadening_scale=float(scales[scale_index]),
                effective_fwhm=fwhm,
                profile_match=profile_match,
                local_snr=float(local_snr),
                confidence=confidence,
                delta_chi2=float(delta_chi2),
                width_persistence=width_persistence,
                evidence_class=evidence_class,
            )
        )

    hypotheses = _deduplicate_hypotheses(hypotheses)
    flagged = [
        replace(
            hypothesis,
            overlap_flag=any(
                other is not hypothesis
                and abs(other.position - hypothesis.position)
                <= 0.65 * (other.effective_fwhm + hypothesis.effective_fwhm)
                for other in hypotheses
            ),
        )
        for hypothesis in hypotheses
    ]
    flagged.sort(key=lambda item: (-item.confidence, -item.local_snr, item.position))
    return tuple(flagged[: max(0, int(limit))])


def _deduplicate_hypotheses(
    hypotheses: Sequence[ProfileMatchedPeakHypothesis],
) -> list[ProfileMatchedPeakHypothesis]:
    selected: list[ProfileMatchedPeakHypothesis] = []
    for hypothesis in sorted(
        hypotheses,
        key=lambda item: (-item.confidence, -item.local_snr, item.position),
    ):
        if any(
            abs(hypothesis.position - previous.position)
            <= max(
                0.025,
                min(
                    hypothesis.effective_fwhm,
                    previous.effective_fwhm,
                )
                * 0.45,
            )
            for previous in selected
        ):
            continue
        selected.append(hypothesis)
    return selected


def _local_peak_fit_statistics(
    x: np.ndarray,
    signal: np.ndarray,
    *,
    index: int,
    fwhm: float,
    eta: float,
    noise: float,
    kernel_hwhm: float,
    satellites: Sequence[tuple[float, float]],
) -> tuple[float, float, float, float, float, float]:
    half_width = max(float(fwhm) * 0.5 * float(kernel_hwhm), 0.06)
    position = float(x[index])
    left = int(np.searchsorted(x, position - half_width, side="left"))
    right = int(np.searchsorted(x, position + half_width, side="right"))
    local_x = x[left:right]
    local_y = signal[left:right]
    if len(local_x) < 5:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    offset = local_x - position
    baseline_design = np.column_stack(
        [np.ones(len(local_x), dtype=float), offset]
    )
    peak = pseudo_voigt_radiation_profile(
        local_x,
        position,
        fwhm,
        eta,
        satellites,
    )
    full_design = np.column_stack([baseline_design, peak])
    try:
        baseline_coefficients, *_unused = np.linalg.lstsq(
            baseline_design, local_y, rcond=None
        )
        full_coefficients, *_unused = np.linalg.lstsq(
            full_design, local_y, rcond=None
        )
    except np.linalg.LinAlgError:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    amplitude = max(float(full_coefficients[-1]), 0.0)
    baseline_residual = local_y - baseline_design @ baseline_coefficients
    fitted_baseline = baseline_design @ full_coefficients[:2]
    full_model = fitted_baseline + amplitude * peak
    full_residual = local_y - full_model
    delta = float(
        np.dot(baseline_residual, baseline_residual)
        - np.dot(full_residual, full_residual)
    ) / max(float(noise) ** 2, 1.0e-24)
    detrended = local_y - fitted_baseline
    area_signed = float(np.trapezoid(detrended, local_x))
    area_positive = float(np.trapezoid(np.maximum(detrended, 0.0), local_x))
    prominence = _local_prominence(local_x, detrended, position, fwhm)
    integration_weights = _trapezoid_weights(local_x)
    area_noise = max(
        float(noise) * math.sqrt(float(np.dot(integration_weights, integration_weights))),
        1.0e-12,
    )
    area_snr = area_signed / area_noise
    return (
        max(delta, 0.0),
        amplitude,
        max(prominence, 0.0),
        max(area_positive, 0.0),
        area_signed,
        area_snr,
    )


def _local_prominence(
    x: np.ndarray,
    detrended: np.ndarray,
    position: float,
    fwhm: float,
) -> float:
    if len(x) < 3:
        return 0.0
    central = np.flatnonzero(np.abs(x - position) <= max(float(fwhm) * 0.65, 1.0e-6))
    if not len(central):
        peak_index = int(np.argmin(np.abs(x - position)))
    else:
        peak_index = int(central[int(np.argmax(detrended[central]))])
    left = detrended[: peak_index + 1]
    right = detrended[peak_index:]
    if not len(left) or not len(right):
        return 0.0
    contour = max(float(np.nanmin(left)), float(np.nanmin(right)))
    return max(float(detrended[peak_index]) - contour, 0.0)


def _trapezoid_weights(x: np.ndarray) -> np.ndarray:
    values = np.asarray(x, dtype=float)
    if len(values) < 2:
        return np.zeros(len(values), dtype=float)
    differences = np.diff(values)
    weights = np.empty(len(values), dtype=float)
    weights[0] = differences[0] * 0.5
    weights[-1] = differences[-1] * 0.5
    if len(values) > 2:
        weights[1:-1] = (differences[:-1] + differences[1:]) * 0.5
    return weights


def _safe_fwhm(
    fwhm_at: Callable[[float], float],
    position: float,
    step: float,
) -> float:
    try:
        value = float(fwhm_at(float(position)))
    except Exception:
        value = 0.0
    if not math.isfinite(value) or value <= 0.0:
        value = max(step * 3.0, 0.08)
    return max(value, step * 2.5)


def _median_step(x: np.ndarray) -> float:
    differences = np.diff(np.asarray(x, dtype=float))
    differences = differences[np.isfinite(differences) & (differences > 0.0)]
    return float(np.nanmedian(differences)) if len(differences) else 0.0


def _robust_noise(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) < 3:
        return 1.0
    differences = np.diff(finite)
    center = float(np.nanmedian(differences))
    mad = float(np.nanmedian(np.abs(differences - center)))
    if mad > 0.0:
        return max(1.4826 * mad / math.sqrt(2.0), 1.0e-12)
    center = float(np.nanmedian(finite))
    return max(
        1.4826 * float(np.nanmedian(np.abs(finite - center))),
        1.0e-12,
    )


def _local_noise(
    x: np.ndarray,
    signal: np.ndarray,
    position: float,
    *,
    fallback: float,
) -> float:
    left = int(np.searchsorted(x, position - 1.0, side="left"))
    right = int(np.searchsorted(x, position + 1.0, side="right"))
    local = signal[left:right]
    if len(local) < 9:
        return max(float(fallback), 1.0e-12)
    value = _robust_noise(local)
    return float(np.clip(value, fallback * 0.65, fallback * 2.5))


__all__ = [
    "ProfileMatchedPeakHypothesis",
    "profile_matched_peak_hypotheses",
]
