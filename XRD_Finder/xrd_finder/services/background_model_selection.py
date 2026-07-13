from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d, percentile_filter
from scipy.signal import find_peaks

from xrd_finder.services.preprocessing_service import estimate_amorphous_chebyshev, estimate_background


@dataclass(frozen=True, slots=True)
class BackgroundModelSelection:
    exponential_terms: int
    amorphous_degree: int
    support_width_deg: float
    smoothing_deg: float
    score: float
    physical_background: np.ndarray
    amorphous_component: np.ndarray


def select_background_model(x: np.ndarray, y: np.ndarray) -> BackgroundModelSelection:
    """Select a conservative baseline/halo model using a physical objective."""

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) < 15:
        zeros = np.zeros_like(y)
        return BackgroundModelSelection(1, 2, 5.0, 2.5, float("inf"), zeros, zeros)

    context = _metric_context(x, y)
    best: BackgroundModelSelection | None = None
    backgrounds = {
        terms: estimate_background(x, y, method=f"exponential_{terms}")
        for terms in (1, 2, 3)
    }
    scale_options = ((5.0, 3.0), (7.0, 4.0), (9.0, 5.0))
    for terms, background in backgrounds.items():
        for degree in range(2, 6):
            for support_width, smoothing in scale_options:
                halo = estimate_amorphous_chebyshev(
                    x,
                    y,
                    background,
                    degree=degree,
                    support_width_deg=support_width,
                    smoothing_deg=smoothing,
                )
                score = _background_objective(
                    x,
                    y,
                    background,
                    halo,
                    context,
                    terms,
                    degree,
                )
                candidate = BackgroundModelSelection(
                    terms,
                    degree,
                    support_width,
                    smoothing,
                    score,
                    np.asarray(background, dtype=float),
                    np.asarray(halo, dtype=float),
                )
                if best is None or candidate.score < best.score:
                    best = candidate
    assert best is not None
    return best


def _metric_context(x: np.ndarray, y: np.ndarray) -> dict[str, np.ndarray | float]:
    step = _median_step(x)
    span = max(float(np.nanpercentile(y, 99) - np.nanpercentile(y, 1)), 1.0)
    noise = _robust_noise(y)
    floor_window = _odd_points(1.2, step, len(y))
    broad_window = _odd_points(5.0, step, len(y))
    lower_floor = percentile_filter(y, percentile=12, size=floor_window, mode="nearest")
    lower_floor = gaussian_filter1d(lower_floor, sigma=max(0.6 / step, 2.0), mode="nearest")
    broad_support = percentile_filter(y, percentile=18, size=broad_window, mode="nearest")
    broad_support = gaussian_filter1d(broad_support, sigma=max(2.0 / step, 2.0), mode="nearest")
    peak_indices, _ = find_peaks(y, prominence=max(5.0 * noise, 0.02 * span), distance=max(3, int(0.12 / step)))
    return {
        "span": span,
        "noise": noise,
        "step": step,
        "lower_floor": lower_floor,
        "broad_support": broad_support,
        "peak_indices": peak_indices,
    }


def _background_objective(
    x: np.ndarray,
    y: np.ndarray,
    background: np.ndarray,
    halo: np.ndarray,
    context: dict[str, np.ndarray | float],
    terms: int,
    degree: int,
) -> float:
    span = float(context["span"])
    noise = float(context["noise"])
    floor = np.asarray(context["lower_floor"], dtype=float)
    broad_support = np.asarray(context["broad_support"], dtype=float)
    total = np.asarray(background, dtype=float) + np.asarray(halo, dtype=float)

    floor_error = float(np.median(np.abs(background - floor))) / span
    total_error = float(np.median(np.abs(total - broad_support))) / span
    crossing = float(np.mean(np.clip(total - y - noise, 0.0, None))) / span
    edge_count = max(5, len(y) // 12)
    edge_error = (
        abs(float(np.median(background[:edge_count] - floor[:edge_count])))
        + abs(float(np.median(background[-edge_count:] - floor[-edge_count:])))
    ) / (2.0 * span)
    curvature = _normalized_curvature(total, span)
    peak_base = _peak_base_penalty(
        y,
        total,
        np.asarray(context["peak_indices"], dtype=int),
        float(context["step"]),
        noise,
        span,
    )
    complexity = 0.003 * max(terms - 1, 0) + 0.006 * max(degree - 2, 0)
    return (
        2.2 * floor_error
        + 1.5 * total_error
        + 8.0 * crossing
        + 2.5 * edge_error
        + 6.0 * peak_base
        + 0.8 * curvature
        + complexity
    )


def _peak_base_penalty(
    observed: np.ndarray,
    total: np.ndarray,
    peak_indices: np.ndarray,
    step: float,
    noise: float,
    span: float,
) -> float:
    radius = max(3, int(round(0.55 / max(step, 1.0e-6))))
    penalties = []
    for index in peak_indices[:80]:
        if index - radius < 0 or index + radius >= len(observed):
            continue
        left = float(np.median(observed[max(0, index - radius - 2) : index - radius + 3]))
        right = float(np.median(observed[index + radius - 2 : index + radius + 3]))
        shoulder = 0.5 * (left + right) + noise
        penalties.append(max(float(total[index]) - shoulder, 0.0) / span)
    return float(np.mean(penalties)) if penalties else 0.0


def _normalized_curvature(values: np.ndarray, span: float) -> float:
    if len(values) < 3:
        return 0.0
    return float(np.mean(np.abs(np.diff(values, n=2)))) / max(span, 1.0)


def _median_step(x: np.ndarray) -> float:
    diffs = np.diff(x)
    diffs = diffs[np.isfinite(diffs) & (diffs > 0.0)]
    return float(np.nanmedian(diffs)) if len(diffs) else 0.03


def _odd_points(width: float, step: float, length: int) -> int:
    value = max(9, min(max(9, length // 2), int(round(width / max(step, 1.0e-6)))))
    return value if value % 2 else value + 1


def _robust_noise(y: np.ndarray) -> float:
    differences = np.diff(y)
    if not len(differences):
        return 1.0
    mad = float(np.median(np.abs(differences - np.median(differences))))
    return max(1.4826 * mad / np.sqrt(2.0), 1.0)
