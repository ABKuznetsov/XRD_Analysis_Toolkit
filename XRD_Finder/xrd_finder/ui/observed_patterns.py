from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from xrd_finder.core.pattern import Pattern
from xrd_finder.io.xy_loader import load_xy


@dataclass(frozen=True)
class ObservedPatternPlotData:
    pattern: Pattern
    name: str
    x: np.ndarray
    y: np.ndarray
    height: float
    offset: float = 0.0
    intensity_scale: float = 1.0

    @property
    def plotted_y(self) -> np.ndarray:
        return self.y + self.offset

    @property
    def context(self) -> dict[str, object]:
        finite_y = self.y[np.isfinite(self.y)]
        raw_min = float(np.nanmin(finite_y)) if finite_y.size else 0.0
        raw_max = float(np.nanmax(finite_y)) if finite_y.size else 1.0
        return {
            "offset": float(self.offset),
            "raw_min": raw_min,
            "raw_max": raw_max,
            "plot_min": raw_min + float(self.offset),
            "plot_max": raw_max + float(self.offset),
            "height": float(self.height),
            "intensity_scale": float(self.intensity_scale),
        }



def normalize_intensity(data: np.ndarray, target_max: float = 100.0) -> np.ndarray:
    values = np.asarray(data, dtype=float)
    if values.ndim != 2 or values.shape[1] < 2 or len(values) == 0:
        return values
    result = np.array(values[:, :2], dtype=float, copy=True)
    y = result[:, 1]
    finite_y = y[np.isfinite(y)]
    if not finite_y.size:
        return result
    scale = float(np.nanmax(finite_y))
    if not np.isfinite(scale) or scale <= 0.0:
        return result
    result[:, 1] = y * (float(target_max) / scale)
    return result

def processed_pattern_data(pattern: Pattern | None) -> np.ndarray | None:
    if pattern is None or not pattern.processed_points:
        return None
    data = np.asarray(pattern.processed_points, dtype=float)
    if data.ndim != 2 or data.shape[1] < 2 or len(data) == 0:
        return None
    return data[:, :2]


def observed_pattern_data(pattern: Pattern | None) -> np.ndarray | None:
    if pattern is None:
        return None
    processed = processed_pattern_data(pattern)
    if processed is not None:
        return processed
    try:
        return load_xy(pattern.source_path)
    except Exception:
        return None


def load_observed_patterns(
    patterns: list[Pattern],
    active_override: tuple[str, np.ndarray, str] | None = None,
    normalize: bool = False,
) -> list[ObservedPatternPlotData]:
    loaded: list[ObservedPatternPlotData] = []
    for pattern in patterns:
        try:
            if active_override is not None and pattern.id == active_override[0]:
                data = np.asarray(active_override[1], dtype=float)
                name = active_override[2]
            else:
                processed = processed_pattern_data(pattern)
                if processed is not None:
                    data = processed
                    name = pattern.processed_label or f"Observed processed: {pattern.name}"
                else:
                    data = load_xy(pattern.source_path)
                    name = f"Observed: {pattern.name}"
        except Exception:
            continue
        if data is None or len(data) == 0:
            continue
        intensity_scale = 1.0
        if normalize:
            finite_y = np.asarray(data[:, 1], dtype=float)
            finite_y = finite_y[np.isfinite(finite_y)]
            maximum = float(np.nanmax(finite_y)) if finite_y.size else 0.0
            if np.isfinite(maximum) and maximum > 0.0:
                intensity_scale = 100.0 / maximum
            data = normalize_intensity(data)
        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)
        finite_y = y[np.isfinite(y)]
        height = float(np.nanmax(finite_y) - np.nanmin(finite_y)) if finite_y.size else 0.0
        loaded.append(
            ObservedPatternPlotData(
                pattern,
                name,
                x,
                y,
                height,
                intensity_scale=intensity_scale,
            )
        )
    return loaded


def apply_pattern_offsets(
    patterns: list[ObservedPatternPlotData],
    stacked: bool,
    offset_percent: int,
) -> list[ObservedPatternPlotData]:
    if not stacked:
        return patterns
    offsets: dict[str, float] = {}
    y_offset = 0.0
    previous_height = 0.0
    for item in reversed(patterns):
        if offsets:
            y_offset += previous_height * (offset_percent / 100.0)
        offsets[item.pattern.id] = y_offset
        previous_height = item.height
    return [
        ObservedPatternPlotData(
            item.pattern,
            item.name,
            item.x,
            item.y,
            item.height,
            offsets.get(item.pattern.id, 0.0),
            item.intensity_scale,
        )
        for item in patterns
    ]
