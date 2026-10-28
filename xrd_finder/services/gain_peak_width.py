"""Shared profile-width estimate; numerical implementation unchanged."""
import numpy as np
from scipy.signal import find_peaks


def estimate_profile_fwhm(x, corrected_y) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(corrected_y, dtype=float)
    if len(x) < 5 or float(np.nanmax(y)) <= 0:
        return 0.18
    peak_indices, _properties = find_peaks(
        y,
        prominence=max(float(np.nanpercentile(y, 98)) * 0.02, float(np.nanstd(y)) * 2.0, 1.0),
        distance=max(3, len(y) // 900),
    )
    widths = []
    for index in peak_indices[:120]:
        peak_height = y[index]
        if peak_height <= 0:
            continue
        half_height = peak_height * 0.5
        left = index
        while left > 0 and y[left] > half_height:
            left -= 1
        right = index
        while right < len(y) - 1 and y[right] > half_height:
            right += 1
        width = float(x[right] - x[left])
        if 0.03 <= width <= 1.2:
            widths.append(width)
    if not widths:
        return 0.18
    return float(np.clip(np.nanmedian(widths), 0.06, 0.8))
