from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d, median_filter, percentile_filter
from scipy.optimize import least_squares


@dataclass(frozen=True, slots=True)
class XrdSignalDecomposition:
    """Conservative signal split that never treats broad scattering as baseline."""

    instrument_background: np.ndarray
    broad_scattering: np.ndarray
    crystalline_signal: np.ndarray
    artifact_mask: np.ndarray
    noise_sigma: float
    exponential_terms: int = 0

    @property
    def signal_above_background(self) -> np.ndarray:
        return self.broad_scattering + self.crystalline_signal


@dataclass(frozen=True, slots=True)
class XrdDecompositionSettings:
    support_width_deg: float = 12.0
    support_percentile: float = 7.0
    support_smoothing_deg: float = 3.5
    broad_clip_width_deg: float = 4.5
    broad_smoothing_deg: float = 3.2
    exponential_terms: int = 0


def decompose_xrd_signal(
    x: np.ndarray,
    y: np.ndarray,
    settings: XrdDecompositionSettings | None = None,
) -> XrdSignalDecomposition:
    """Split XRD data into conservative baseline, broad signal, and sharp signal.

    ``broad_scattering`` is deliberately neutral: a single pattern cannot reliably
    distinguish amorphous scattering, nanocrystalline broadening, and holder signal.
    It remains part of the corrected signal and is not subtracted by Auto.
    """

    settings = settings or XrdDecompositionSettings()
    x, y, inverse = _sorted_finite_arrays(x, y)
    if len(y) < 5:
        zeros = np.zeros_like(y)
        return _restore(
            XrdSignalDecomposition(zeros, zeros, y.copy(), np.zeros_like(y, dtype=bool), 1.0, 0),
            inverse,
        )

    step = _median_step(x)
    noise = _robust_noise(y)
    artifacts = _artifact_mask(y, noise)
    working = _replace_artifacts(y, artifacts)

    # A wide, low-percentile envelope follows only the lower support of the
    # pattern. Its scale is intentionally much wider than normal Bragg peaks.
    support_window = _odd_window(
        settings.support_width_deg,
        step,
        41,
        max(41, (len(y) * 2) // 3),
    )
    support = percentile_filter(
        working,
        percentile=float(np.clip(settings.support_percentile, 1.0, 30.0)),
        size=support_window,
        mode="nearest",
    )
    support_sigma = max(_points_for_width(settings.support_smoothing_deg, step), 3.0)
    instrument = gaussian_filter1d(support, sigma=support_sigma, mode="nearest")

    # Keep the baseline below a local noise-aware floor. This is conservative:
    # under-subtraction leaves an offset, while over-subtraction destroys signal.
    local_floor = percentile_filter(
        working,
        percentile=18,
        size=_odd_window(1.2, step, 21, max(21, len(y) // 5)),
        mode="nearest",
    )
    exponential, exponential_error, exponential_terms = _exponential_background(
        x,
        working,
        noise,
        requested_terms=settings.exponential_terms,
    )
    span = max(float(np.nanpercentile(working, 99) - np.nanpercentile(working, 1)), noise)
    edge_count = max(8, len(working) // 12)
    low_angle_excess = (
        float(np.nanmedian(working[:edge_count]) - np.nanmedian(working[-edge_count:])) / span
    )
    force_exponential = int(settings.exponential_terms) in {1, 2, 3}
    if force_exponential or (low_angle_excess > 0.10 and exponential_error < 0.18):
        instrument = exponential
    else:
        exponential_terms = 0
    instrument = np.minimum(instrument, local_floor - 0.40 * noise)
    lower_bound = float(np.nanpercentile(working, 0.2)) - 2.0 * noise
    instrument = np.maximum(instrument, lower_bound)

    above = working - instrument
    # Estimate broad scattering after suppressing narrow positive excursions.
    clip_window = _odd_window(
        settings.broad_clip_width_deg,
        step,
        11,
        max(11, len(y) // 12),
    )
    clipped = percentile_filter(above, percentile=18, size=clip_window, mode="nearest")
    broad_sigma = max(_points_for_width(settings.broad_smoothing_deg, step), 2.0)
    broad = gaussian_filter1d(clipped, sigma=broad_sigma, mode="nearest")
    broad = np.clip(broad, 0.0, None)

    crystalline = working - instrument - broad
    return _restore(
        XrdSignalDecomposition(
            instrument_background=instrument,
            broad_scattering=broad,
            crystalline_signal=crystalline,
            artifact_mask=artifacts,
            noise_sigma=float(noise),
            exponential_terms=exponential_terms,
        ),
        inverse,
    )


def _sorted_finite_arrays(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape:
        raise ValueError("X and Y arrays must have equal shape.")
    finite = np.isfinite(x) & np.isfinite(y)
    if not np.all(finite):
        raise ValueError("XRD decomposition requires finite X and Y values.")
    order = np.argsort(x)
    inverse = np.empty_like(order)
    inverse[order] = np.arange(len(order))
    return x[order], y[order], inverse


def _restore(result: XrdSignalDecomposition, inverse: np.ndarray) -> XrdSignalDecomposition:
    return XrdSignalDecomposition(
        instrument_background=result.instrument_background[inverse],
        broad_scattering=result.broad_scattering[inverse],
        crystalline_signal=result.crystalline_signal[inverse],
        artifact_mask=result.artifact_mask[inverse],
        noise_sigma=result.noise_sigma,
        exponential_terms=result.exponential_terms,
    )


def _artifact_mask(y: np.ndarray, noise: float) -> np.ndarray:
    if len(y) < 7:
        return np.zeros_like(y, dtype=bool)
    local = median_filter(y, size=5, mode="nearest")
    residual = np.abs(y - local)
    threshold = max(10.0 * noise, float(np.nanpercentile(residual, 99.8)))
    return residual > threshold


def _exponential_background(
    x: np.ndarray,
    y: np.ndarray,
    noise: float,
    requested_terms: int = 0,
) -> tuple[np.ndarray, float, int]:
    """Fit one to three exponential decays plus a slow linear component."""

    x0 = float(x[0])
    x_span = max(float(x[-1] - x0), 1.0e-9)
    t = (x - x0) / x_span
    node_count = min(160, max(32, int(round(x_span / 0.55))))
    edges = np.linspace(x0, float(x[-1]), node_count + 1)
    node_x = []
    node_y = []
    for left, right in zip(edges[:-1], edges[1:], strict=False):
        mask = (x >= left) & (x < right)
        if not np.any(mask):
            continue
        local_x = x[mask]
        local_y = y[mask]
        cutoff = float(np.nanpercentile(local_y, 18))
        selected = local_y <= cutoff
        node_x.append(float(np.nanmedian(local_x[selected])))
        node_y.append(float(np.nanmedian(local_y[selected])))
    if len(node_x) < 8:
        return np.full_like(y, float(np.nanpercentile(y, 5))), 1.0, 0
    nx = np.asarray(node_x)
    ny = np.asarray(node_y)
    nt = (nx - x0) / x_span
    y_span = max(float(np.nanpercentile(y, 99) - np.nanpercentile(y, 1)), noise)
    tail = float(np.nanmedian(ny[-max(3, len(ny) // 8) :]))
    amplitude = max(float(np.nanmedian(ny[: max(3, len(ny) // 8)]) - tail), 0.05 * y_span)

    term_options = [int(requested_terms)] if int(requested_terms) in {1, 2, 3} else [1, 2, 3]
    candidates = []
    for term_count in term_options:
        candidate = _fit_exponential_terms(
            nt,
            ny,
            t,
            y,
            y_span,
            noise,
            amplitude,
            tail,
            term_count,
        )
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return np.full_like(y, float(np.nanpercentile(y, 5))), 1.0, 0
    background, error, _criterion, term_count = min(candidates, key=lambda item: item[2])
    return background, error, term_count


def _fit_exponential_terms(
    node_t: np.ndarray,
    node_y: np.ndarray,
    full_t: np.ndarray,
    full_y: np.ndarray,
    y_span: float,
    noise: float,
    amplitude: float,
    tail: float,
    term_count: int,
) -> tuple[np.ndarray, float, float, int] | None:
    initial_decays = np.asarray([2.0, 9.0, 36.0], dtype=float)[:term_count]
    initial_amplitudes = amplitude * np.asarray([0.45, 0.35, 0.20], dtype=float)[:term_count]
    initial_amplitudes *= amplitude / max(float(np.sum(initial_amplitudes)), 1.0e-12)
    initial = np.concatenate([initial_amplitudes, initial_decays, [tail, 0.0]])
    lower = np.concatenate(
        [
            np.zeros(term_count),
            np.full(term_count, 0.05),
            [float(np.nanmin(full_y)) - y_span, -2.0 * y_span],
        ]
    )
    upper = np.concatenate(
        [
            np.full(term_count, 4.0 * y_span),
            np.full(term_count, 120.0),
            [float(np.nanmax(full_y)), 2.0 * y_span],
        ]
    )

    def model(parameters, values):
        amplitudes = parameters[:term_count]
        decays = parameters[term_count : 2 * term_count]
        offset, slope = parameters[-2:]
        exponentials = amplitudes[:, None] * np.exp(-decays[:, None] * values[None, :])
        return np.sum(exponentials, axis=0) + offset + slope * values

    def residual(parameters):
        return (model(parameters, node_t) - node_y) / y_span

    try:
        fit = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            loss="soft_l1",
            f_scale=max(noise / y_span, 0.015),
            max_nfev=650,
        )
    except Exception:
        return None
    normalized_residual = residual(fit.x)
    rss = max(float(np.sum(normalized_residual**2)), 1.0e-12)
    parameter_count = 2 * term_count + 2
    criterion = len(node_y) * np.log(rss / len(node_y)) + parameter_count * np.log(len(node_y))
    background = model(fit.x, full_t)
    node_model = model(fit.x, node_t)
    node_residual = node_y - node_model
    edge_count = max(3, len(node_residual) // 10)
    head_delta = float(np.nanmedian(node_residual[:edge_count]))
    tail_delta = float(np.nanmedian(node_residual[-edge_count:]))
    # Anchor both ends to the lower-support nodes. A global offset tends to
    # undershoot the high-angle tail when the low-angle decay dominates.
    background += head_delta + (tail_delta - head_delta) * full_t
    conservative_shift = float(np.nanpercentile(full_y - background, 4.0))
    if conservative_shift < 0.0:
        background += conservative_shift * (1.0 - full_t)
    error = float(np.nanmedian(np.abs(normalized_residual)))
    return np.asarray(background, dtype=float), error, float(criterion), term_count


def _replace_artifacts(y: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if not np.any(mask):
        return y.copy()
    clean = y.copy()
    indices = np.arange(len(y))
    valid = ~mask
    if np.count_nonzero(valid) >= 2:
        clean[mask] = np.interp(indices[mask], indices[valid], y[valid])
    return clean


def _median_step(x: np.ndarray) -> float:
    diffs = np.diff(x)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    return float(np.nanmedian(diffs)) if len(diffs) else 0.03


def _points_for_width(width: float, step: float) -> float:
    return max(float(width) / max(float(step), 1.0e-6), 1.0)


def _odd_window(width: float, step: float, minimum: int, maximum: int) -> int:
    value = int(round(_points_for_width(width, step)))
    value = max(int(minimum), min(int(maximum), value))
    return value if value % 2 else value + 1


def _robust_noise(y: np.ndarray) -> float:
    diffs = np.diff(y)
    if len(diffs):
        center = float(np.nanmedian(diffs))
        mad = float(np.nanmedian(np.abs(diffs - center)))
        if mad > 0:
            return max(1.4826 * mad / np.sqrt(2.0), 1.0e-12)
    mad = float(np.nanmedian(np.abs(y - np.nanmedian(y))))
    return max(1.4826 * mad, 1.0e-12)
