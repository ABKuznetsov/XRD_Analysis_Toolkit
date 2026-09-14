from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from scipy.ndimage import gaussian_filter1d, percentile_filter
from scipy.interpolate import PchipInterpolator
from scipy.signal import find_peaks, peak_widths, savgol_filter

from xrd_finder.services.auto_parameter_selector import select_decomposition_settings
from xrd_finder.services.xrd_signal_decomposition import XrdDecompositionSettings, decompose_xrd_signal

try:
    from pybaselines import Baseline
except Exception:
    Baseline = None

PYBASELINES_METHODS = {"auto", "arpls", "asls", "snip", "rolling_ball"}


@dataclass(frozen=True, slots=True)
class XrdSignalFeatures:
    point_count: int
    step: float
    intensity_span: float
    noise: float
    noise_ratio: float
    peak_count: int
    peak_density: float
    median_peak_width_deg: float
    broad_peak_fraction: float
    narrow_peak_fraction: float
    baseline_slope_ratio: float
    baseline_curvature_ratio: float
    amorphous_hump_ratio: float
    oversmooth_risk: float


@dataclass(frozen=True, slots=True)
class AutoSmoothingPlan:
    method: str
    window: int
    polyorder: int = 2
    gaussian_sigma: float = 0.2
    passes: int = 1
    features: XrdSignalFeatures | None = None


@dataclass(frozen=True, slots=True)
class AutoBackgroundPlan:
    method: str
    degree: int = 10
    floor_percentile: int = 15
    features: XrdSignalFeatures | None = None


@dataclass(frozen=True, slots=True)
class AutoPreprocessingResult:
    x: np.ndarray
    y: np.ndarray
    background: np.ndarray
    broad_scattering: np.ndarray
    crystalline_signal: np.ndarray
    artifact_mask: np.ndarray
    corrected_y: np.ndarray
    decomposition_settings: XrdDecompositionSettings
    ml_confidence: float
    smoothing: AutoSmoothingPlan
    background_plan: AutoBackgroundPlan
    label: str


def auto_preprocess_for_scoring(x: np.ndarray, y: np.ndarray) -> AutoPreprocessingResult:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    smoothing = auto_smoothing_plan(x, y)
    smooth_y = np.asarray(y, dtype=float)
    for _ in range(max(int(smoothing.passes), 1)):
        smooth_y = smooth_observed_curve(
            smooth_y,
            smoothing.method,
            smoothing.window,
            smoothing.polyorder,
            smoothing.gaussian_sigma,
        )
    background_plan = auto_background_plan(x, smooth_y)
    settings, ml_confidence = select_decomposition_settings(background_plan.features)
    decomposition = decompose_xrd_signal(x, smooth_y, settings=settings)
    background = decomposition.instrument_background
    corrected = smooth_y - background
    label = (
        f"Auto scoring: {smoothing.method} w{smoothing.window}, "
        f"conservative background, broad scattering preserved, confidence {ml_confidence:.0%}"
    )
    return AutoPreprocessingResult(
        x=x,
        y=smooth_y,
        background=background,
        broad_scattering=decomposition.broad_scattering,
        crystalline_signal=decomposition.crystalline_signal,
        artifact_mask=decomposition.artifact_mask,
        corrected_y=corrected,
        decomposition_settings=settings,
        ml_confidence=ml_confidence,
        smoothing=smoothing,
        background_plan=background_plan,
        label=label,
    )


def auto_smoothing_window(x: np.ndarray, y: np.ndarray) -> int:
    return auto_smoothing_plan(x, y).window


def auto_smoothing_plan(x: np.ndarray, y: np.ndarray) -> AutoSmoothingPlan:
    features = describe_xrd_signal(x, y)
    if features.point_count < 9:
        return AutoSmoothingPlan("savgol", 5, features=features)
    max_window = _odd_window(0.22, features.step, minimum=5, maximum=21)
    if features.median_peak_width_deg > 0:
        max_by_peak = _odd_window(features.median_peak_width_deg * 0.45, features.step, minimum=5, maximum=21)
        max_window = min(max_window, max_by_peak)
    base_window = _odd_window(0.08, features.step, minimum=5, maximum=11)
    window = base_window
    if features.noise_ratio > 0.055:
        window += 4
    elif features.noise_ratio > 0.030:
        window += 2
    if features.peak_density > 0.85 or features.narrow_peak_fraction > 0.45:
        window -= 2
    if features.oversmooth_risk > 0.65:
        window -= 2
    window = _odd_int(np.clip(window, 5, max_window))
    method = "savgol"
    passes = 1
    sigma = 0.2
    if features.noise_ratio > 0.085 and features.peak_density < 0.35:
        method = "gaussian"
        sigma = 0.35
    if features.noise_ratio > 0.12 and features.narrow_peak_fraction < 0.35:
        passes = 2
    return AutoSmoothingPlan(method, window, polyorder=2, gaussian_sigma=sigma, passes=passes, features=features)


def auto_background_plan(x: np.ndarray, y: np.ndarray) -> AutoBackgroundPlan:
    features = describe_xrd_signal(x, y)
    return AutoBackgroundPlan(method="auto", degree=10, floor_percentile=15, features=features)


def describe_xrd_signal(x: np.ndarray, y: np.ndarray) -> XrdSignalFeatures:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    x = x[finite]
    y = y[finite]
    if len(y) < 3:
        return XrdSignalFeatures(len(y), 0.03, 1.0, 1.0, 1.0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    order = np.argsort(x)
    x = x[order]
    y = y[order]
    step = _median_step(x)
    span = max(float(np.nanpercentile(y, 99)) - float(np.nanpercentile(y, 1)), 1.0)
    noise = _robust_noise(y)
    noise_ratio = float(np.clip(noise / span, 0.0, 1.0))
    smooth_width = _odd_window(1.4, step, minimum=9, maximum=max(9, len(y) // 3))
    smooth = gaussian_filter1d(y, sigma=max(smooth_width / 7.0, 1.0), mode="nearest")
    residual = y - smooth
    peak_indices, properties = _feature_peak_indices(x, residual, noise, span)
    widths_deg = np.array([], dtype=float)
    if len(peak_indices):
        try:
            widths_deg = peak_widths(np.maximum(residual, 0.0), peak_indices, rel_height=0.5)[0] * step
        except Exception:
            widths_deg = np.array([], dtype=float)
    median_width = float(np.nanmedian(widths_deg)) if len(widths_deg) else 0.0
    broad_fraction = float(np.mean(widths_deg > 0.55)) if len(widths_deg) else 0.0
    narrow_fraction = float(np.mean(widths_deg < 0.16)) if len(widths_deg) else 0.0
    x_span = max(float(x[-1] - x[0]), step)
    peak_density = float(len(peak_indices) / max(x_span / 10.0, 1.0))
    lower = percentile_filter(y, percentile=22, size=_odd_window(0.7, step, minimum=9, maximum=max(9, len(y) // 4)), mode="nearest")
    baseline = gaussian_filter1d(lower, sigma=max(_odd_window(3.0, step, minimum=21, maximum=max(21, len(y) // 2)) / 8.0, 2.0), mode="nearest")
    slope_ratio = float((np.nanpercentile(np.abs(np.gradient(baseline)), 95) * x_span) / span)
    curvature_ratio = float((np.nanpercentile(np.abs(np.gradient(np.gradient(baseline))), 95) * x_span * x_span) / span)
    hump = np.maximum(baseline - np.nanpercentile(baseline, 10), 0.0)
    hump_ratio = float(np.nanmax(hump) / span) if len(hump) else 0.0
    oversmooth_risk = float(np.clip(narrow_fraction * 0.55 + min(peak_density / 1.4, 1.0) * 0.35 + (1.0 - noise_ratio) * 0.10, 0.0, 1.0))
    return XrdSignalFeatures(
        point_count=len(y),
        step=step,
        intensity_span=span,
        noise=noise,
        noise_ratio=noise_ratio,
        peak_count=int(len(peak_indices)),
        peak_density=peak_density,
        median_peak_width_deg=median_width,
        broad_peak_fraction=broad_fraction,
        narrow_peak_fraction=narrow_fraction,
        baseline_slope_ratio=slope_ratio,
        baseline_curvature_ratio=curvature_ratio,
        amorphous_hump_ratio=hump_ratio,
        oversmooth_risk=oversmooth_risk,
    )


def _feature_peak_indices(x: np.ndarray, y: np.ndarray, noise: float, span: float) -> tuple[np.ndarray, dict]:
    step = _median_step(x)
    positive = np.maximum(np.asarray(y, dtype=float), 0.0)
    prominence = max(noise * 4.0, span * 0.018, 1.0)
    return find_peaks(
        positive,
        prominence=prominence,
        distance=max(3, int(round(0.10 / max(step, 1.0e-6)))),
        width=(1, max(5, int(round(2.0 / max(step, 1.0e-6))))),
    )


def smooth_observed_curve(
    y: np.ndarray,
    method: str,
    window: int,
    polyorder: int = 2,
    gaussian_sigma: float = 0.2,
) -> np.ndarray:
    if window <= 2 or len(y) < 5:
        return np.asarray(y, dtype=float)
    window = min(int(window), len(y) - 1 if len(y) % 2 == 0 else len(y))
    if window % 2 == 0:
        window -= 1
    if window < 3:
        return np.asarray(y, dtype=float)
    values = np.asarray(y, dtype=float)
    if method == "moving":
        kernel = np.ones(window, dtype=float) / float(window)
        return np.convolve(values, kernel, mode="same")
    if method == "gaussian":
        sigma = max(0.1, float(gaussian_sigma))
        radius = max(1, int(round(sigma * 4)))
        grid = np.arange(-radius, radius + 1, dtype=float)
        kernel = np.exp(-0.5 * (grid / sigma) ** 2)
        kernel /= float(np.sum(kernel))
        padded = np.pad(values, (radius, radius), mode="edge")
        return np.convolve(padded, kernel, mode="same")[radius:-radius]
    order = max(1, min(int(polyorder), window - 2))
    try:
        return np.asarray(savgol_filter(values, window_length=window, polyorder=order, mode="interp"), dtype=float)
    except Exception:
        kernel = np.ones(window, dtype=float) / float(window)
        return np.convolve(values, kernel, mode="same")


def estimate_background(x, y, degree: int = 10, method: str = "auto") -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) < 15:
        return np.full_like(y, float(np.nanpercentile(y, 5)))
    try:
        if method == "auto":
            background = _xrd_hybrid_background(x, y)
        elif method == "auto_with_broad":
            background = _xrd_hybrid_background(x, y)
            background = background + estimate_amorphous_chebyshev(x, y, background)
        elif method.startswith("exponential_"):
            remove_broad = method.endswith("_with_broad")
            base_method = method.removesuffix("_with_broad")
            term_count = int(base_method.rsplit("_", 1)[-1])
            features = describe_xrd_signal(x, y)
            settings, _confidence = select_decomposition_settings(features)
            settings = replace(settings, exponential_terms=term_count)
            decomposition = decompose_xrd_signal(x, y, settings=settings)
            background = decomposition.instrument_background
            if remove_broad:
                background = background + decomposition.broad_scattering
        elif method == "polynomial":
            background = _chebyshev_background(x, y, degree=degree)
        elif method.startswith("snip_"):
            half_window = int(method.rsplit("_", 1)[-1])
            background = _pybaselines_background(x, y, method="snip", half_window=half_window)
        elif method in PYBASELINES_METHODS:
            background = _pybaselines_background(x, y, method=method)
        else:
            background = _local_envelope_background(x, y)
    except Exception:
        try:
            background = _chebyshev_background(x, y, degree=degree)
        except Exception:
            background = np.full_like(y, float(np.nanpercentile(y, 15)))
    background = _stabilize_background_edges(x, y, background)
    floor = 0.0 if float(np.nanmin(y)) >= 0.0 else float(np.nanpercentile(y, 1))
    ceiling = float(np.nanpercentile(y, 99.5))
    return np.clip(background, floor, ceiling)

def estimate_amorphous_chebyshev(
    x: np.ndarray,
    y: np.ndarray,
    physical_background: np.ndarray,
    degree: int = 3,
    support_width_deg: float = 7.0,
    smoothing_deg: float = 4.0,
) -> np.ndarray:
    """Estimate a smooth amorphous contribution above a physical baseline."""

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    background = np.asarray(physical_background, dtype=float)
    if len(y) < 15 or x.shape != y.shape or background.shape != y.shape:
        return np.zeros_like(y)
    diffs = np.diff(x)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
    step = float(np.nanmedian(diffs)) if len(diffs) else 0.03
    window = max(21, int(round(float(support_width_deg) / max(step, 1.0e-6))))
    window = window if window % 2 else window + 1
    residual = np.clip(y - background, 0.0, None)
    support = percentile_filter(residual, percentile=8, size=window, mode="nearest")
    support = gaussian_filter1d(
        support,
        sigma=max(float(smoothing_deg) / max(step, 1.0e-6), 2.0),
        mode="nearest",
    )
    halo = _chebyshev_background(x, support, degree=int(np.clip(degree, 2, 10)))
    return np.clip(np.asarray(halo, dtype=float), 0.0, None)


def _xrd_hybrid_background(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Whole-pattern conservative baseline for XRD traces.

    Auto mode should describe the physical baseline, not every local valley.
    We therefore combine several low-support estimates and smooth the result
    over the full range before applying a local cap under the measured signal.
    """

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    envelope = _adaptive_xrd_envelope(x, y)
    candidates = [envelope]
    if Baseline is not None:
        for method in ("arpls", "snip", "asls"):
            try:
                candidates.append(_pybaselines_background(x, y, method=method))
            except Exception:
                pass
    try:
        candidates.append(_chebyshev_background(x, y, degree=6))
    except Exception:
        pass
    noise = _robust_noise(y)
    stack = np.vstack([np.asarray(candidate, dtype=float) for candidate in candidates])
    # Use a lower percentile rather than a median so broad crystalline clusters
    # do not pull the baseline into the peaks.
    combined = np.nanpercentile(stack, 35.0, axis=0)
    combined = _smooth_background_curve(x, combined, width_deg=2.2)
    combined = np.minimum(combined, envelope + max(noise * 1.5, 1.0))
    return _cap_background_to_local_signal(x, y, combined, noise)


def _smooth_background_curve(x: np.ndarray, background: np.ndarray, width_deg: float) -> np.ndarray:
    order = np.argsort(x)
    xs = np.asarray(x[order], dtype=float)
    bg = np.asarray(background[order], dtype=float)
    step = _median_step(xs)
    sigma = max(float(width_deg) / max(step, 1.0e-6), 2.0)
    smoothed = gaussian_filter1d(bg, sigma=sigma, mode="nearest")
    restored = np.empty_like(smoothed)
    restored[order] = smoothed
    return restored


def _adaptive_xrd_envelope(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    order = np.argsort(x)
    xs = np.asarray(x[order], dtype=float)
    ys = np.asarray(y[order], dtype=float)
    step = _median_step(xs)
    small_window = _odd_window(0.45, step, minimum=9, maximum=max(9, len(ys) // 8))
    broad_window = _odd_window(2.8, step, minimum=31, maximum=max(31, len(ys) // 2))
    lower = percentile_filter(ys, percentile=18, size=small_window, mode="nearest")
    broad = percentile_filter(ys, percentile=32, size=broad_window, mode="nearest")
    sigma = max(broad_window / 8.0, 2.0)
    smooth = gaussian_filter1d(broad, sigma=sigma, mode="nearest")
    noise = _robust_noise(ys)
    cap = percentile_filter(ys, percentile=48, size=small_window, mode="nearest") + max(noise * 1.8, 1.0)
    background_sorted = np.minimum(smooth, cap)
    background_sorted = np.maximum(background_sorted, lower - max(noise * 2.0, 1.0))
    background_sorted = _smooth_nodes(background_sorted, window=min(21, max(7, broad_window // 5)))
    background = np.empty_like(background_sorted)
    background[order] = background_sorted
    return _cap_background_to_local_signal(x, y, background, noise)


def _cap_background_to_local_signal(x: np.ndarray, y: np.ndarray, background: np.ndarray, noise: float) -> np.ndarray:
    order = np.argsort(x)
    ys = np.asarray(y[order], dtype=float)
    bg_sorted = np.asarray(background[order], dtype=float)
    step = _median_step(np.asarray(x[order], dtype=float))
    cap_window = _odd_window(0.65, step, minimum=9, maximum=max(9, len(ys) // 6))
    local_cap = percentile_filter(ys, percentile=62, size=cap_window, mode="nearest") + max(noise * 2.0, 1.0)
    bg_sorted = np.minimum(bg_sorted, local_cap)
    floor = 0.0 if float(np.nanmin(y)) >= 0.0 else float(np.nanpercentile(y, 0.5))
    bg_sorted = np.maximum(bg_sorted, floor)
    capped = np.empty_like(bg_sorted)
    capped[order] = bg_sorted
    return capped


def _stabilize_background_edges(x: np.ndarray, y: np.ndarray, background: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    background = np.asarray(background, dtype=float)
    if len(y) < 25 or x.shape != y.shape or background.shape != y.shape:
        return background

    order = np.argsort(x)
    xs = np.asarray(x[order], dtype=float)
    ys = np.asarray(y[order], dtype=float)
    bg = np.asarray(background[order], dtype=float)
    step = _median_step(xs)
    span = max(float(xs[-1] - xs[0]), step)
    edge_width = float(np.clip(span * 0.16, 6.0, 12.0))
    support_window = _odd_window(1.2, step, minimum=9, maximum=max(9, len(ys) // 5))
    smooth_width = _odd_window(3.0, step, minimum=21, maximum=max(21, len(ys) // 3))
    support = percentile_filter(ys, percentile=26, size=support_window, mode="reflect")
    support = gaussian_filter1d(support, sigma=max(smooth_width / 7.0, 2.0), mode="reflect")
    support = np.minimum(support, ys + max(_robust_noise(ys) * 1.5, 1.0))

    left_end = xs[0] + edge_width
    right_start = xs[-1] - edge_width
    left = xs <= left_end
    right = xs >= right_start
    stabilized = np.copy(bg)
    if np.any(left):
        t = np.clip((xs[left] - xs[0]) / max(edge_width, step), 0.0, 1.0)
        weight = 1.0 - (t * t * (3.0 - 2.0 * t))
        stabilized[left] = bg[left] * (1.0 - weight) + support[left] * weight
    if np.any(right):
        t = np.clip((xs[-1] - xs[right]) / max(edge_width, step), 0.0, 1.0)
        weight = 1.0 - (t * t * (3.0 - 2.0 * t))
        stabilized[right] = bg[right] * (1.0 - weight) + support[right] * weight

    restored = np.empty_like(stabilized)
    restored[order] = stabilized
    return restored


def _median_step(x: np.ndarray) -> float:
    diffs = np.diff(np.asarray(x, dtype=float))
    diffs = diffs[np.isfinite(diffs) & (diffs > 0)]
    return float(np.nanmedian(diffs)) if len(diffs) else 0.03


def _odd_window(width: float, step: float, *, minimum: int, maximum: int) -> int:
    size = int(round(float(width) / max(float(step), 1.0e-6)))
    size = max(int(minimum), min(int(maximum), size))
    return size if size % 2 else size + 1


def _odd_int(value: float | int) -> int:
    integer = max(3, int(round(float(value))))
    return integer if integer % 2 else integer + 1


def _robust_noise(y: np.ndarray) -> float:
    values = np.asarray(y, dtype=float)
    diffs = np.diff(values[np.isfinite(values)])
    if len(diffs):
        mad = float(np.nanmedian(np.abs(diffs - np.nanmedian(diffs))))
        if mad > 0:
            return max(1.4826 * mad / np.sqrt(2.0), 1.0)
    finite = values[np.isfinite(values)]
    if not len(finite):
        return 1.0
    mad = float(np.nanmedian(np.abs(finite - np.nanmedian(finite))))
    return max(1.4826 * mad, 1.0)


def _pybaselines_background(x: np.ndarray, y: np.ndarray, method: str = "auto", half_window: int | None = None) -> np.ndarray:
    if Baseline is None:
        return _local_envelope_background(x, y)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.all(np.diff(x) >= 0):
        order = None
        xs = x
        ys = y
    else:
        order = np.argsort(x)
        xs = x[order]
        ys = y[order]
    if len(xs) < 15:
        return np.full_like(y, float(np.nanpercentile(y, 5)))

    baseline = Baseline(x_data=xs, check_finite=False)
    lam = float(np.clip(len(ys) ** 2.15, 1.0e4, 1.0e8))
    if method in {"auto", "arpls"}:
        background_sorted, _params = baseline.arpls(ys, lam=lam)
    elif method == "asls":
        background_sorted, _params = baseline.asls(ys, lam=lam, p=0.01)
    elif method == "snip":
        max_half_window = int(np.clip(half_window if half_window is not None else max(8, len(ys) // 90), 8, 240))
        background_sorted, _params = baseline.snip(ys, max_half_window=max_half_window)
    elif method == "rolling_ball":
        ball_window = max(8, min(120, len(ys) // 60))
        background_sorted, _params = baseline.rolling_ball(ys, half_window=ball_window)
    else:
        return _local_envelope_background(x, y)

    background_sorted = np.asarray(background_sorted, dtype=float)
    background_sorted = np.minimum(background_sorted, ys + max(float(np.nanstd(ys)) * 0.05, 1.0))
    if order is None:
        return background_sorted
    background = np.empty_like(background_sorted)
    background[order] = background_sorted
    return background


def _local_envelope_background(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    order = np.argsort(x)
    xs = np.asarray(x[order], dtype=float)
    ys = np.asarray(y[order], dtype=float)
    xmin = float(xs[0])
    xmax = float(xs[-1])
    if xmax <= xmin:
        return np.full_like(y, float(np.nanpercentile(y, 15)))

    bin_count = min(140, max(30, len(ys) // 55))
    edges = np.linspace(xmin, xmax, bin_count + 1)
    node_x = []
    node_y = []

    edge_points = max(8, len(ys) // 120)
    node_x.append(float(xs[0]))
    node_y.append(float(np.nanmedian(ys[:edge_points])))

    for left, right in zip(edges[:-1], edges[1:]):
        mask = (xs >= left) & (xs < right)
        if not np.any(mask):
            continue
        local_x = xs[mask]
        local_y = ys[mask]
        peak_cut = float(np.nanpercentile(local_y, 72))
        local_y = local_y[local_y <= peak_cut]
        if len(local_y) == 0:
            continue
        node_x.append(float(np.nanmean(local_x)))
        node_y.append(float(np.nanpercentile(local_y, 55)))

    node_x.append(float(xs[-1]))
    node_y.append(float(np.nanmedian(ys[-edge_points:])))

    node_x = np.asarray(node_x, dtype=float)
    node_y = np.asarray(node_y, dtype=float)
    if len(node_x) < 4:
        return np.full_like(y, float(np.nanpercentile(y, 15)))

    unique_x, unique_indices = np.unique(node_x, return_index=True)
    node_y = node_y[unique_indices]
    if len(unique_x) < 4:
        return np.full_like(y, float(np.nanpercentile(y, 15)))

    node_y = _smooth_nodes(node_y, window=7)
    interpolator = PchipInterpolator(unique_x, node_y, extrapolate=True)
    background_sorted = np.asarray(interpolator(xs), dtype=float)
    background_sorted = np.minimum(background_sorted, ys + max(float(np.nanstd(ys)) * 0.08, 1.0))

    background = np.empty_like(background_sorted)
    background[order] = background_sorted
    return background


def _smooth_nodes(values: np.ndarray, window: int = 7) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) < window:
        return values
    half = window // 2
    smoothed = np.copy(values)
    for index in range(1, len(values) - 1):
        left = max(0, index - half)
        right = min(len(values), index + half + 1)
        smoothed[index] = float(np.nanmedian(values[left:right]))
    smoothed[0] = values[0]
    smoothed[-1] = values[-1]
    return smoothed


def _chebyshev_background(x: np.ndarray, y: np.ndarray, degree: int = 10) -> np.ndarray:
    xmin = float(np.nanmin(x))
    xmax = float(np.nanmax(x))
    if xmax <= xmin:
        return np.full_like(y, float(np.nanpercentile(y, 15)))
    xn = 2.0 * (x - xmin) / (xmax - xmin) - 1.0
    bin_count = min(90, max(18, len(y) // 80))
    edges = np.linspace(xmin, xmax, bin_count + 1)
    node_x = []
    node_y = []
    node_weights = []
    edge_points = max(8, len(y) // 40)
    anchor_points = max(5, len(y) // 180)
    left_anchor = float(np.nanmedian(y[:anchor_points]))
    right_anchor = float(np.nanmedian(y[-anchor_points:]))
    node_x.append(float(x[0]))
    node_y.append(left_anchor)
    node_weights.append(25.0)
    node_x.append(float(np.nanmean(x[:edge_points])))
    node_y.append(float(np.nanpercentile(y[:edge_points], 55)))
    node_weights.append(8.0)
    for left, right in zip(edges[:-1], edges[1:]):
        mask = (x >= left) & (x < right)
        if not np.any(mask):
            continue
        node_x.append(float(np.nanmean(x[mask])))
        node_y.append(float(np.nanpercentile(y[mask], 38)))
        node_weights.append(1.0)
    node_x.append(float(np.nanmean(x[-edge_points:])))
    node_y.append(float(np.nanpercentile(y[-edge_points:], 55)))
    node_weights.append(8.0)
    node_x.append(float(x[-1]))
    node_y.append(right_anchor)
    node_weights.append(25.0)
    if len(node_x) <= 3:
        return np.full_like(y, float(np.nanpercentile(y, 15)))
    node_x = np.asarray(node_x, dtype=float)
    node_y = np.asarray(node_y, dtype=float)
    node_weights = np.asarray(node_weights, dtype=float)
    node_xn = 2.0 * (node_x - xmin) / (xmax - xmin) - 1.0
    fit_degree = min(degree, len(node_x) - 2)
    vandermonde = np.polynomial.chebyshev.chebvander(node_xn, fit_degree)
    hard_anchor_mask = node_weights >= 20.0
    weights = np.copy(node_weights)
    coeffs = np.zeros(fit_degree + 1)
    for _iteration in range(8):
        coeffs, *_rest = np.linalg.lstsq(vandermonde * weights[:, None], node_y * weights, rcond=None)
        residual = node_y - vandermonde @ coeffs
        sigma = max(float(np.nanmedian(np.abs(residual))) * 1.4826, 1.0)
        robust_weights = np.where(residual > sigma * 0.8, 0.35, 1.0)
        robust_weights = np.where(residual < -sigma * 2.0, 0.65, robust_weights)
        robust_weights = np.where(hard_anchor_mask, 1.0, robust_weights)
        weights = node_weights * robust_weights
    return np.asarray(np.polynomial.chebyshev.chebval(xn, coeffs), dtype=float)
