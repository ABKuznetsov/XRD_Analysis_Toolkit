from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QFont
from scipy.interpolate import PchipInterpolator
from scipy.signal import find_peaks

from xrd_manager.services.calculated_pattern_service import CU_KA1_WAVELENGTH


@dataclass(slots=True)
class CalculatedPlotItems:
    profile_items: list[object] = field(default_factory=list)
    peak_items: list[object] = field(default_factory=list)
    hkl_items: list[object] = field(default_factory=list)


def ensure_right_legend(plot: pg.PlotWidget, clear: bool = False):
    legend = plot.plotItem.legend
    if legend is None:
        legend = plot.addLegend(offset=(-12, 12))
    elif clear:
        legend.clear()
    legend.anchor(itemPos=(1, 0), parentPos=(1, 0), offset=(-12, 12))
    try:
        legend.setLabelTextColor("#111111")
    except Exception:
        pass
    try:
        legend.setLabelTextSize("10pt")
    except Exception:
        pass
    return legend


def calculate_profile_for_structure(service, structure, x_grid, fwhm: float | None = None):
    x_grid = np.asarray(x_grid, dtype=float)
    kwargs = {}
    if fwhm is not None:
        kwargs["fwhm"] = fwhm
    return service.calculate_profile(
        structure,
        x_grid=x_grid,
        two_theta_min=float(np.nanmin(x_grid)),
        two_theta_max=float(np.nanmax(x_grid)),
        wavelength=structure.wavelength or CU_KA1_WAVELENGTH,
        use_lp=True,
        **kwargs,
    )


def scale_profile_to_reference(y, reference_max: float) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    max_y = float(np.nanmax(y)) if len(y) else 0.0
    if max_y <= 0:
        return y
    return y / max_y * max(reference_max, 1.0)


def estimate_background(x, y, degree: int = 10) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(y) < 15:
        return np.full_like(y, float(np.nanpercentile(y, 5)))
    try:
        background = _local_envelope_background(x, y)
    except Exception:
        try:
            background = _chebyshev_background(x, y, degree=degree)
        except Exception:
            background = np.full_like(y, float(np.nanpercentile(y, 15)))
    floor = float(np.nanpercentile(y, 1))
    ceiling = float(np.nanpercentile(y, 99.5))
    return np.clip(background, floor, ceiling)


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


def plot_profile(plot: pg.PlotWidget, x, y, color: str, label: str, width: float = 1.5):
    return plot.plot(x, y, pen=pg.mkPen(color, width=width), name=label)


def hkl_stick_arrays(peaks, baseline: float, height: float):
    stick_x = []
    stick_y = []
    for peak in peaks:
        stick_x.extend([peak.two_theta, peak.two_theta, np.nan])
        stick_y.extend([baseline, baseline + height * max(peak.intensity, 0.0) / 100.0, np.nan])
    return stick_x, stick_y


def hkl_tick_arrays(peaks, baseline: float, height: float):
    tick_x = []
    tick_y = []
    for peak in peaks:
        tick_x.extend([peak.two_theta, peak.two_theta, np.nan])
        tick_y.extend([baseline - height * 0.035, baseline - height * 0.015, np.nan])
    return tick_x, tick_y


def plot_hkl_sticks(
    plot: pg.PlotWidget,
    peaks,
    color: str,
    baseline: float,
    height: float,
    label: str | None = None,
    width: float = 1.6,
):
    stick_x, stick_y = hkl_stick_arrays(peaks, baseline, height)
    return plot.plot(stick_x, stick_y, pen=pg.mkPen(color, width=width), name=label)


def plot_hkl_ticks(plot: pg.PlotWidget, peaks, color: str, baseline: float, height: float):
    tick_x, tick_y = hkl_tick_arrays(peaks, baseline, height)
    return plot.plot(tick_x, tick_y, pen=pg.mkPen(color, width=1.5))


def phase_marker_lane_arrays(peaks, baseline: float, height: float):
    marker_x = []
    marker_y = []
    split_y = baseline + height * 0.5
    for peak in peaks:
        reference_two_theta = float(getattr(peak, "reference_two_theta", peak.two_theta))
        shifted_two_theta = float(peak.two_theta)
        marker_x.extend([reference_two_theta, reference_two_theta, np.nan])
        marker_y.extend([baseline, split_y, np.nan])
        marker_x.extend([shifted_two_theta, shifted_two_theta, np.nan])
        marker_y.extend([split_y, baseline + height, np.nan])
    return marker_x, marker_y


def plot_phase_marker_lane(
    plot: pg.PlotWidget,
    peaks,
    color: str,
    baseline: float,
    height: float,
    label: str,
    x_label: float,
):
    marker_x, marker_y = phase_marker_lane_arrays(peaks, baseline, height)
    marker_item = plot.plot(marker_x, marker_y, pen=pg.mkPen(color, width=1.8))
    label_item = pg.TextItem(label, color=color, anchor=(0.0, 0.5))
    label_font = QFont()
    label_font.setPointSize(9)
    label_font.setWeight(QFont.Weight.DemiBold)
    label_item.setFont(label_font)
    label_item.setPos(x_label, baseline + height * 0.45)
    plot.addItem(label_item)
    return [marker_item, label_item]


def add_hkl_labels(
    plot: pg.PlotWidget,
    peaks,
    color: str,
    y: float,
    height: float | None = None,
    limit: int = 30,
    angle: float = 90,
    above_peaks: bool = False,
):
    labels = []
    display_peaks = sorted(peaks, key=lambda item: getattr(item, "intensity", 0.0), reverse=True)[:limit]
    display_peaks = sorted(display_peaks, key=lambda item: getattr(item, "two_theta", 0.0))
    for peak in display_peaks:
        item = pg.TextItem(f"{peak.h}{peak.k}{peak.l}", color=color, anchor=(0.5, 1.0), angle=angle)
        label_font = QFont()
        label_font.setPointSize(10)
        label_font.setWeight(QFont.Weight.DemiBold)
        item.setFont(label_font)
        if above_peaks and height is not None:
            label_y = y + height * (max(float(peak.intensity), 0.0) / 100.0) + height * 0.09
        else:
            label_y = y
        item.setPos(peak.two_theta, label_y)
        plot.addItem(item)
        labels.append(item)
    return labels


def right_label_y(x, y) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(x) == 0:
        return 0.0
    x_max = float(np.nanmax(x))
    x_min = float(np.nanmin(x))
    right_start = x_min + (x_max - x_min) * 0.86
    mask = x >= right_start
    right_y = y[mask] if np.any(mask) else y
    return float(np.nanmedian(right_y))


def add_right_side_labels(plot: pg.PlotWidget, labels: list[tuple[str, float, float, str]]):
    items = []
    for label, x, y, color in labels:
        item = pg.TextItem(label, color=color, anchor=(1, 0.5))
        item.setPos(x, y)
        plot.addItem(item)
        items.append(item)
    return items
