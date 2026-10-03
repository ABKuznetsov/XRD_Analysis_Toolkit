from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class RefinedResidualPeak:
    two_theta: float
    area: float
    height: float
    prominence: float
    fwhm_observed: float
    fwhm_sample: float | None
    instrument_limited: bool
    fit_quality: float
    asymmetry: float
    baseline: float
    baseline_slope: float


def pseudo_voigt_unit_height(x, center: float, fwhm: float, eta: float) -> np.ndarray:
    values = np.asarray(x, dtype=float)
    width = max(float(fwhm), 1.0e-9)
    offset = (values - float(center)) / width
    gaussian = np.exp(-4.0 * np.log(2.0) * offset * offset)
    lorentzian = 1.0 / (1.0 + 4.0 * offset * offset)
    fraction = float(np.clip(eta, 0.0, 1.0))
    return (1.0 - fraction) * gaussian + fraction * lorentzian


def pseudo_voigt_radiation_profile(
    x,
    center: float,
    fwhm: float,
    eta: float,
    satellite_offsets_weights: Sequence[tuple[float, float]] = (),
) -> np.ndarray:
    profile = pseudo_voigt_unit_height(x, center, fwhm, eta)
    for offset, relative_weight in satellite_offsets_weights:
        if float(relative_weight) <= 0.0:
            continue
        profile = profile + float(relative_weight) * pseudo_voigt_unit_height(
            x,
            float(center) + float(offset),
            fwhm,
            eta,
        )
    return profile


def refine_residual_peak(
    x,
    signed_residual,
    seed_two_theta: float,
    *,
    expected_fwhm: float,
    instrument_fwhm: float = 0.0,
    satellite_offsets_weights: Sequence[tuple[float, float]] = (),
) -> RefinedResidualPeak | None:
    """Fit a local pseudo-Voigt peak plus a linear baseline to signed residual data.

    The seed is expected to come from a lightly smoothed positive residual.  All
    reported line quantities are fitted against the unsmoothed signed residual.
    A compact deterministic grid is used instead of a nonlinear optimiser so
    this operation stays cheap when it is repeated for many residual lines.
    """

    x_values = np.asarray(x, dtype=float)
    residual = np.asarray(signed_residual, dtype=float)
    finite = np.isfinite(x_values) & np.isfinite(residual)
    x_values = x_values[finite]
    residual = residual[finite]
    if len(x_values) < 9 or len(x_values) != len(residual):
        return None
    order = np.argsort(x_values)
    x_values = x_values[order]
    residual = residual[order]
    step = _median_step(x_values)
    expected = float(np.clip(expected_fwhm, max(step * 2.0, 0.025), 1.20))
    window_radius = float(np.clip(expected * 4.0, 0.32, 1.60))
    local = (x_values >= seed_two_theta - window_radius) & (x_values <= seed_two_theta + window_radius)
    local_x = x_values[local]
    local_y = residual[local]
    if len(local_x) < 9:
        return None

    center_radius = float(np.clip(expected * 0.65, 0.055, 0.32))
    centers = np.linspace(seed_two_theta - center_radius, seed_two_theta + center_radius, 9)
    centers = np.unique(np.concatenate([centers, local_x[np.argsort(local_y)[-2:]]]))
    minimum_width = max(step * 2.5, 0.025, expected * 0.35)
    maximum_width = min(window_radius * 0.90, 1.50, max(expected * 3.5, minimum_width * 1.5))
    widths = np.geomspace(minimum_width, maximum_width, 11)
    etas = (0.0, 0.33, 0.67, 1.0)

    best: tuple[float, float, float, np.ndarray, np.ndarray] | None = None
    scale = max(float(np.nanpercentile(np.abs(local_y), 90)), 1.0)
    weights = np.ones_like(local_y)
    for robust_pass in range(2):
        if robust_pass:
            center_step = max(step, expected * 0.08)
            centers = np.asarray([best_center - center_step, best_center, best_center + center_step])
            widths = np.asarray([best[1] * 0.86, best[1], best[1] * 1.16])
            etas = tuple(np.clip([best[2] - 0.18, best[2], best[2] + 0.18], 0.0, 1.0))
            best = None
        root_weights = np.sqrt(np.clip(weights, 0.05, 1.0))
        for center in centers:
            delta = local_x - float(center)
            for width in widths:
                for eta in etas:
                    shape = pseudo_voigt_radiation_profile(
                        local_x,
                        float(center),
                        float(width),
                        float(eta),
                        satellite_offsets_weights,
                    )
                    design = np.column_stack([np.ones_like(local_x), delta, shape])
                    try:
                        coefficients, *_unused = np.linalg.lstsq(
                            design * root_weights[:, None],
                            local_y * root_weights,
                            rcond=None,
                        )
                    except np.linalg.LinAlgError:
                        continue
                    if float(coefficients[2]) <= 0.0:
                        continue
                    model = design @ coefficients
                    error = float(np.sum(weights * (local_y - model) ** 2))
                    if best is None or error < best[0]:
                        best = (error, float(width), float(eta), coefficients, model)
                        best_center = float(center)
        if best is None:
            return None
        if robust_pass == 0:
            deviation = local_y - best[4]
            robust_scale = max(1.4826 * float(np.nanmedian(np.abs(deviation - np.nanmedian(deviation)))), scale * 0.005, 1.0e-9)
            weights = np.minimum(1.0, (2.5 * robust_scale) / np.maximum(np.abs(deviation), 1.0e-12))

    error, width, eta, coefficients, model = best
    baseline, slope, amplitude = (float(value) for value in coefficients)
    baseline_curve = baseline + slope * (local_x - best_center)
    peak_signal = np.clip(local_y - baseline_curve, 0.0, None)
    fitted_signal = amplitude * pseudo_voigt_radiation_profile(
        local_x,
        best_center,
        width,
        eta,
        satellite_offsets_weights,
    )
    total_variation = float(np.sum((local_y - np.nanmean(local_y)) ** 2))
    fit_quality = float(np.clip(1.0 - error / max(total_variation, 1.0e-12), 0.0, 1.0))
    asymmetry = _area_asymmetry(local_x, peak_signal, best_center)
    area_factor = (
        (1.0 - eta) * np.sqrt(np.pi) / (2.0 * np.sqrt(np.log(2.0)))
        + eta * np.pi / 2.0
    )
    radiation_weight = 1.0 + sum(max(float(weight), 0.0) for _offset, weight in satellite_offsets_weights)
    area = max(float(amplitude * width * area_factor * radiation_weight), float(np.trapezoid(fitted_signal, local_x)), 0.0)
    instrument_width = max(float(instrument_fwhm), 0.0)
    instrument_limited = bool(instrument_width > 0.0 and width <= instrument_width * 1.15)
    if instrument_limited:
        sample_width = None
    elif instrument_width > 0.0:
        sample_width = float(np.sqrt(max(width * width - instrument_width * instrument_width, 0.0)))
    else:
        sample_width = float(width)
    return RefinedResidualPeak(
        two_theta=best_center,
        area=area,
        height=max(amplitude, 0.0),
        prominence=max(amplitude, 0.0),
        fwhm_observed=float(width),
        fwhm_sample=sample_width,
        instrument_limited=instrument_limited,
        fit_quality=fit_quality,
        asymmetry=asymmetry,
        baseline=baseline,
        baseline_slope=slope,
    )


def refine_residual_peaks(
    x,
    signed_residual,
    seeds: Iterable[object],
    *,
    expected_fwhm: float,
    instrument_fwhm_at: Callable[[float], float] | None = None,
    satellite_components_at: Callable[[float], Sequence[tuple[float, float]]] | None = None,
) -> list[RefinedResidualPeak | None]:
    results: list[RefinedResidualPeak | None] = []
    for seed in seeds:
        position = float(getattr(seed, "two_theta", seed))
        instrument_width = float(instrument_fwhm_at(position)) if instrument_fwhm_at is not None else 0.0
        results.append(
            refine_residual_peak(
                x,
                signed_residual,
                position,
                expected_fwhm=max(float(getattr(seed, "fwhm", 0.0) or 0.0), float(expected_fwhm)),
                instrument_fwhm=instrument_width,
                satellite_offsets_weights=(
                    satellite_components_at(position)
                    if satellite_components_at is not None
                    else ()
                ),
            )
        )
    return results


def _area_asymmetry(x: np.ndarray, signal: np.ndarray, center: float) -> float:
    left = x <= center
    right = x >= center
    left_area = float(np.trapezoid(signal[left], x[left])) if np.count_nonzero(left) >= 2 else 0.0
    right_area = float(np.trapezoid(signal[right], x[right])) if np.count_nonzero(right) >= 2 else 0.0
    return float(np.clip(abs(left_area - right_area) / max(left_area + right_area, 1.0e-12), 0.0, 1.0))


def _median_step(x: np.ndarray) -> float:
    differences = np.diff(np.asarray(x, dtype=float))
    differences = differences[np.isfinite(differences) & (differences > 0.0)]
    return float(np.nanmedian(differences)) if len(differences) else 0.03


__all__ = [
    "RefinedResidualPeak",
    "pseudo_voigt_unit_height",
    "pseudo_voigt_radiation_profile",
    "refine_residual_peak",
    "refine_residual_peaks",
]
