from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks, peak_widths, savgol_filter

from xrd_finder.finder.models import FinderInput, ObservedPeak
from xrd_finder.io.xy_loader import load_xy
from xrd_finder.services.preprocessing_service import estimate_background as estimate_xrd_background


@dataclass(slots=True)
class ObservedPatternData:
    x_grid: np.ndarray
    observed_y: np.ndarray
    background: np.ndarray
    target_y: np.ndarray
    fwhm: float
    peaks: list[ObservedPeak]
    peak_positions: np.ndarray


class ObservedPatternProcessor:
    def prepare(self, finder_input: FinderInput) -> ObservedPatternData:
        x_grid, observed_y = self.observed_arrays(finder_input)
        observed_y = self.smooth_y(observed_y, finder_input.smoothing_window)
        if finder_input.subtract_background:
            background = self.custom_background(finder_input, x_grid)
            if background is None:
                background = self.estimate_background(x_grid, observed_y)
        else:
            background = np.zeros_like(observed_y)
        target_y = np.clip(observed_y - background, 0.0, None)
        fwhm = finder_input.fwhm or self.estimate_fwhm(x_grid, target_y)
        peaks = self.observed_peaks(x_grid, target_y, fwhm)
        peak_positions = np.asarray([peak.two_theta for peak in peaks], dtype=float)
        return ObservedPatternData(
            x_grid=x_grid,
            observed_y=observed_y,
            background=background,
            target_y=target_y,
            fwhm=float(fwhm),
            peaks=peaks,
            peak_positions=peak_positions,
        )

    def observed_arrays(self, finder_input: FinderInput) -> tuple[np.ndarray, np.ndarray]:
        if finder_input.observed_x is not None and finder_input.observed_y is not None:
            x = np.asarray(finder_input.observed_x, dtype=float)
            y = np.asarray(finder_input.observed_y, dtype=float)
            if len(x) != len(y) or len(x) == 0:
                raise ValueError("Observed X/Y arrays must be non-empty and have equal length.")
            return x, y
        observed = load_xy(finder_input.pattern_path)
        return np.asarray(observed[:, 0], dtype=float), np.asarray(observed[:, 1], dtype=float)

    def smooth_y(self, y: np.ndarray, window: int) -> np.ndarray:
        if window <= 2 or len(y) < 5:
            return y
        window = min(int(window), len(y) - 1 if len(y) % 2 == 0 else len(y))
        if window % 2 == 0:
            window -= 1
        if window < 5:
            return y
        try:
            return np.asarray(savgol_filter(y, window_length=window, polyorder=2, mode="interp"), dtype=float)
        except Exception:
            kernel = np.ones(window, dtype=float) / float(window)
            return np.convolve(y, kernel, mode="same")

    def estimate_background(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        if len(y) < 5:
            return np.zeros_like(y)
        try:
            return np.asarray(estimate_xrd_background(x, y, method="auto"), dtype=float)
        except Exception:
            return np.full_like(y, float(np.nanpercentile(y, 15)))

    def custom_background(self, finder_input: FinderInput, x_grid: np.ndarray) -> np.ndarray | None:
        if finder_input.background_x is None or finder_input.background_y is None:
            return None
        x = np.asarray(finder_input.background_x, dtype=float)
        y = np.asarray(finder_input.background_y, dtype=float)
        if len(x) != len(y) or len(x) < 2:
            return None
        mask = np.isfinite(x) & np.isfinite(y)
        if np.count_nonzero(mask) < 2:
            return None
        x = x[mask]
        y = y[mask]
        order = np.argsort(x)
        x = x[order]
        y = y[order]
        unique_x, unique_indices = np.unique(x, return_index=True)
        unique_y = y[unique_indices]
        if len(unique_x) < 2:
            return None
        return np.asarray(
            np.interp(x_grid, unique_x, unique_y, left=float(unique_y[0]), right=float(unique_y[-1])),
            dtype=float,
        )

    def estimate_fwhm(self, x: np.ndarray, y: np.ndarray) -> float:
        if len(x) < 5 or float(np.nanmax(y)) <= 0:
            return 0.18
        prominence = max(_robust_noise(y) * 5.0, float(np.nanpercentile(y, 95)) * 0.04, 1.0)
        step = _median_step(x)
        indices, _properties = find_peaks(
            y,
            prominence=prominence,
            distance=max(3, int(round(0.11 / max(step, 1.0e-6)))),
            width=(1, max(5, int(round(1.4 / max(step, 1.0e-6))))),
        )
        if len(indices) == 0:
            return 0.18
        widths = peak_widths(y, indices, rel_height=0.5)[0]
        return float(np.clip(np.nanmedian(widths) * step, 0.05, 0.35))

    def observed_peak_positions(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return np.asarray([peak.two_theta for peak in self.observed_peaks(x, y, 0.18)], dtype=float)

    def observed_peaks(self, x: np.ndarray, y: np.ndarray, fwhm: float) -> list[ObservedPeak]:
        if len(x) < 5 or float(np.nanmax(y)) <= 0:
            return []
        step = _median_step(x)
        prominence = max(_robust_noise(y) * 4.4, float(np.nanpercentile(y, 95)) * 0.035, 1.0)
        indices, properties = find_peaks(
            y,
            prominence=prominence,
            distance=max(3, int(round(0.11 / max(step, 1.0e-6)))),
            width=(1, max(5, int(round(1.4 / max(step, 1.0e-6))))),
        )
        if len(indices) > 150:
            heights = properties.get("prominences", y[indices])
            indices = indices[np.argsort(heights)[-150:]]
        ordered = indices[np.argsort(np.asarray(x, dtype=float)[indices])]
        return [
            ObservedPeak(
                two_theta=float(x[index]),
                intensity=float(y[index]),
                fwhm=float(fwhm),
            )
            for index in ordered
        ]


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
