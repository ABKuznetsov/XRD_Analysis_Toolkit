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


def _fit_peak_grid(x, y, centers, widths, etas, weights, satellites):
    """Solve the unchanged deterministic grid in one batch of SVDs.

    Finalists are checked with the original lstsq/error calculation so close
    numerical ties retain the original grid order and selection rule.
    """
    cc, ww, ee = np.meshgrid(centers, widths, etas, indexing='ij')
    cc, ww, ee = cc.ravel(), ww.ravel(), ee.ravel()
    delta = x[None, :] - cc[:, None]

    def component(offset):
        scaled = (delta - float(offset)) / ww[:, None]
        square = scaled * scaled
        gaussian = np.exp(-4.0 * np.log(2.0) * square)
        lorentzian = 1.0 / (1.0 + 4.0 * square)
        return (1.0-ee[:, None])*gaussian + ee[:, None]*lorentzian

    shape = component(0.)
    for offset, relative_weight in satellites:
        if float(relative_weight) > 0.:
            shape += float(relative_weight)*component(offset)
    design = np.stack((np.ones_like(delta), delta, shape), axis=-1)
    roots = np.sqrt(np.clip(weights, .05, 1.))
    target = y*roots
    weighted = design*roots[None, :, None]
    try:
        u, singular, vh = np.linalg.svd(weighted, full_matrices=False)
        cutoff = np.finfo(float).eps * max(len(x), 3) * singular[:, :1]
        projected = np.einsum('nmk,m->nk', u, target)
        scaled = np.divide(projected, singular, out=np.zeros_like(projected),
                           where=singular > cutoff)
        coefficients = np.einsum('nki,nk->ni', vh, scaled)
        models = np.einsum('nmk,nk->nm', design, coefficients)
        errors = np.sum(weights[None, :]*(y[None, :]-models)**2, axis=1)
        # Near-zero amplitudes can change sign between LAPACK drivers. Keep
        # those trials for the original solver, including baseline-only data.
        amplitude_rounding = 64.*np.finfo(float).eps*np.maximum(
            1., np.max(np.abs(coefficients), axis=1))
        errors[(coefficients[:, 2] < -amplitude_rounding) | ~np.isfinite(errors)] = np.inf
        minimum = float(np.min(errors))
        if not np.isfinite(minimum):
            return None
        rounding = 64.*np.finfo(float).eps*max(1., float(np.sum(weights*y*y)))
        finalists = np.flatnonzero(errors <= minimum+rounding)
    except np.linalg.LinAlgError:
        # Retain the scalar solver's per-trial failure handling on unusual data.
        finalists = range(len(cc))
    best = None
    for index in finalists:
        # Rebuild finalists through the original scalar arithmetic, including
        # satellite-center rounding, before publishing any measurements.
        shape = pseudo_voigt_radiation_profile(x, float(cc[index]), float(ww[index]),
                                               float(ee[index]), satellites)
        trial = np.column_stack((np.ones_like(x), x-float(cc[index]), shape))
        try:
            coefficients, *_ = np.linalg.lstsq(trial*roots[:, None], target, rcond=None)
        except np.linalg.LinAlgError:
            continue
        if float(coefficients[2]) <= 0.:
            continue
        model = trial @ coefficients
        error = float(np.sum(weights*(y-model)**2))
        if best is None or error < best[0][0]:
            best = ((error, float(ww[index]), float(ee[index]), coefficients, model),
                    float(cc[index]))
    return best


def refine_residual_peak(
    x,
    signed_residual,
    seed_two_theta: float,
    *,
    expected_fwhm: float,
    instrument_fwhm: float = 0.0,
    satellite_offsets_weights: Sequence[tuple[float, float]] = (),
    constrain_center: bool = True,
    enforce_instrument_floor: bool = True,
    peak_only_quality: bool = False,
    return_curve: bool = False,
) -> RefinedResidualPeak | tuple[RefinedResidualPeak, np.ndarray, np.ndarray, np.ndarray] | None:
    """Fit a local pseudo-Voigt peak plus a linear baseline to signed residual data.

    The seed is expected to come from a lightly smoothed positive residual.  All
    reported line quantities are fitted against the unsmoothed signed residual.
    A compact deterministic grid is used instead of a nonlinear optimiser so
    this operation stays cheap when it is repeated for many residual lines.
    Residual refinement constrains the center around its seed. The established
    input-measurement path explicitly opts out to preserve accepted-phase fits.
    A supplied instrumental width bounds both width searches unless the legacy
    input-measurement caller explicitly opts out of that constraint as well.
    ``peak_only_quality`` compares the added peak with a linear baseline on
    unweighted data; the opt-in keeps legacy input measurements unchanged.
    ``return_curve`` additionally returns the fitted x, full model and baseline
    arrays for a read-only local inspection, without changing the fit itself.
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
    near_seed = (np.abs(local_x - seed_two_theta) <= center_radius) if constrain_center else np.ones(len(local_x), dtype=bool)
    # The local fitting window also contains neighbours. They must not replace
    # the seeded peak merely because their intensities are higher.
    seed_maxima = local_x[near_seed][np.argsort(local_y[near_seed])[-2:]]
    centers = np.unique(np.concatenate([centers, seed_maxima]))
    instrument_floor = max(float(instrument_fwhm), 0.0) if enforce_instrument_floor else 0.0
    minimum_width = max(step * 2.5, 0.025, expected * 0.35, instrument_floor)
    maximum_width = min(window_radius * 0.90, 1.50, max(expected * 3.5, minimum_width * 1.5))
    if minimum_width > maximum_width:
        return None
    widths = np.geomspace(minimum_width, maximum_width, 11)
    etas = (0.0, 0.33, 0.67, 1.0)

    best: tuple[float, float, float, np.ndarray, np.ndarray] | None = None
    scale = max(float(np.nanpercentile(np.abs(local_y), 90)), 1.0)
    weights = np.ones_like(local_y)
    for robust_pass in range(2):
        if robust_pass:
            center_step = max(step, expected * 0.08)
            centers = np.asarray([best_center - center_step, best_center, best_center + center_step])
            if constrain_center:
                centers = np.unique(np.clip(centers,
                    seed_two_theta - center_radius, seed_two_theta + center_radius))
            widths = np.asarray([best[1] * 0.86, best[1], best[1] * 1.16])
            if instrument_floor > 0.0:
                widths = np.unique(np.maximum(widths, instrument_floor))
            etas = tuple(np.clip([best[2] - 0.18, best[2], best[2] + 0.18], 0.0, 1.0))
            best = None
        fitted = _fit_peak_grid(local_x, local_y, centers, widths, etas,
                                weights, satellite_offsets_weights)
        if fitted is None:
            return None
        best, best_center = fitted
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
    if peak_only_quality:
        # Certify the peak's improvement over the same linear baseline.
        # Robustly downweighting a spike must not by itself improve this
        # quality: both models are compared on the original, unweighted data.
        baseline_design = np.column_stack([np.ones_like(local_x), local_x-best_center])
        baseline_coefficients, *_unused = np.linalg.lstsq(baseline_design, local_y, rcond=None)
        total_variation = float(np.sum((local_y-baseline_design@baseline_coefficients)**2))
        error = float(np.sum((local_y-model)**2))
        # Comparing two least-squares models needs a rounding allowance for
        # both solves, not a single epsilon. Otherwise an exactly linear
        # baseline can earn an arbitrary relative improvement from roundoff.
        precision_floor = (64.*np.finfo(float).eps)**2 * float(np.dot(local_y, local_y))
        fit_quality = (float(np.clip(1.0-error/total_variation, 0.0, 1.0))
            if total_variation > max(precision_floor, np.finfo(float).tiny) else 0.0)
    else:
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
    result = RefinedResidualPeak(
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
    if return_curve:
        return result, local_x.copy(), model.copy(), baseline_curve.copy()
    return result


def refine_residual_peaks(
    x,
    signed_residual,
    seeds: Iterable[object],
    *,
    expected_fwhm: float,
    instrument_fwhm_at: Callable[[float], float] | None = None,
    satellite_components_at: Callable[[float], Sequence[tuple[float, float]]] | None = None,
    refine_peak: Callable | None = None,
    constrain_center: bool = True,
    enforce_instrument_floor: bool = True,
) -> list[RefinedResidualPeak | None]:
    results: list[RefinedResidualPeak | None] = []
    for seed in seeds:
        position = float(getattr(seed, "two_theta", seed))
        instrument_width = float(instrument_fwhm_at(position)) if instrument_fwhm_at is not None else 0.0
        results.append(
            (refine_peak or refine_residual_peak)(
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
                constrain_center=constrain_center,
                enforce_instrument_floor=enforce_instrument_floor,
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
