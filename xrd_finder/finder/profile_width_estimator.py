from __future__ import annotations

import numpy as np


def estimate_phase_fwhm_from_signal(
    peaks,
    x_grid,
    target_y,
    *,
    base_fwhm: float,
) -> float:
    """Estimate one phase width from isolated, one-to-one peak matches."""
    x = np.asarray(x_grid, dtype=float)
    y = np.asarray(target_y, dtype=float)
    fallback = float(np.clip(base_fwhm, 0.04, 0.80))
    if not peaks or len(x) < 8 or len(x) != len(y) or float(np.nanmax(y)) <= 0.0:
        return fallback

    usable = sorted(
        (peak for peak in peaks if float(getattr(peak, "intensity", 0.0) or 0.0) >= 1.0),
        key=lambda peak: float(getattr(peak, "two_theta", 0.0) or 0.0),
    )[:120]
    isolation_radius = max(0.22, min(0.55, fallback * 1.8))
    isolated = []
    for index, peak in enumerate(usable):
        position = float(peak.two_theta)
        left_gap = position - float(usable[index - 1].two_theta) if index else float("inf")
        right_gap = float(usable[index + 1].two_theta) - position if index + 1 < len(usable) else float("inf")
        if min(left_gap, right_gap) >= isolation_radius:
            isolated.append(peak)
    strong = sorted(
        (peak for peak in isolated if float(getattr(peak, "intensity", 0.0) or 0.0) >= 4.0),
        key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0),
        reverse=True,
    )[:24]

    widths: list[float] = []
    used_maxima: set[int] = set()
    search_radius = max(0.18, min(0.65, fallback * 2.4))
    window_radius = max(0.45, min(1.4, fallback * 6.0))
    for peak in strong:
        result = _local_signal_fwhm(
            x,
            y,
            float(peak.two_theta),
            search_radius=search_radius,
            window_radius=window_radius,
        )
        if result is None:
            continue
        maximum_index, width = result
        if maximum_index in used_maxima:
            continue
        used_maxima.add(maximum_index)
        widths.append(width)
    if len(widths) < 2:
        return fallback
    # A remaining unresolved overlap can still produce a long upper tail.
    # The lower-middle quantile represents the instrumental/sample width of
    # clean reflections without being controlled by the single narrowest one.
    return float(np.clip(np.nanpercentile(np.asarray(widths, dtype=float), 35), 0.04, 0.80))


def _local_signal_fwhm(
    x: np.ndarray,
    y: np.ndarray,
    center: float,
    *,
    search_radius: float,
    window_radius: float,
) -> tuple[int, float] | None:
    search_indices = np.flatnonzero((x >= center - search_radius) & (x <= center + search_radius))
    if len(search_indices) < 3:
        return None
    peak_index = int(search_indices[int(np.nanargmax(y[search_indices]))])
    window_indices = np.flatnonzero(
        (x >= float(x[peak_index]) - window_radius)
        & (x <= float(x[peak_index]) + window_radius)
    )
    if len(window_indices) < 5:
        return None
    local_y = y[window_indices]
    edge_count = max(2, min(8, len(local_y) // 5))
    edge_values = np.concatenate([local_y[:edge_count], local_y[-edge_count:]])
    baseline = float(np.nanpercentile(edge_values, 35))
    height = float(y[peak_index]) - baseline
    if height <= max(float(np.nanpercentile(y, 95)) * 0.015, 1.0):
        return None
    half = baseline + 0.5 * height
    left = peak_index
    while left > 0 and y[left] > half and x[left] >= x[peak_index] - window_radius:
        left -= 1
    right = peak_index
    while right < len(y) - 1 and y[right] > half and x[right] <= x[peak_index] + window_radius:
        right += 1
    if left == peak_index or right == peak_index:
        return None
    left_x = _interpolated_crossing_x(x, y, left, left + 1, half)
    right_x = _interpolated_crossing_x(x, y, right, right - 1, half)
    width = abs(float(right_x) - float(left_x))
    if not np.isfinite(width):
        return None
    return peak_index, float(np.clip(width, 0.04, 0.90))


def _interpolated_crossing_x(
    x: np.ndarray,
    y: np.ndarray,
    index_a: int,
    index_b: int,
    level: float,
) -> float:
    xa = float(x[index_a])
    xb = float(x[index_b])
    ya = float(y[index_a])
    yb = float(y[index_b])
    denominator = yb - ya
    if abs(denominator) < 1.0e-12:
        return xa
    fraction = (float(level) - ya) / denominator
    return xa + float(np.clip(fraction, 0.0, 1.0)) * (xb - xa)


__all__ = ["estimate_phase_fwhm_from_signal"]
