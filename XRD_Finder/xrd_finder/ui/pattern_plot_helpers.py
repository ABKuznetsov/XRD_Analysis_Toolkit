from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QFont
from scipy.signal import find_peaks

from xrd_finder.services.calculated_pattern_service import CU_KA1_WAVELENGTH


@dataclass(slots=True)
class CalculatedPlotItems:
    profile_items: list[object] = field(default_factory=list)
    peak_items: list[object] = field(default_factory=list)
    hkl_items: list[object] = field(default_factory=list)


def remove_plot_legend(plot: pg.PlotWidget):
    legend = getattr(plot.plotItem, "legend", None)
    if legend is not None:
        try:
            legend.scene().removeItem(legend)
        except Exception:
            pass
    plot.plotItem.legend = None
    return None


def ensure_right_legend(plot: pg.PlotWidget, clear: bool = False):
    legend = getattr(plot.plotItem, "legend", None)
    if legend is not None and legend.scene() is None:
        plot.plotItem.legend = None
        legend = None
    if legend is None:
        legend = plot.addLegend(offset=(-12, 12))
    elif clear:
        legend.clear()
    legend.setVisible(True)
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


def _set_legend_label(item, label: str | None):
    if label:
        try:
            item._xrd_legend_label = str(label)
        except Exception:
            pass
    return item


def plot_profile(plot: pg.PlotWidget, x, y, color: str, label: str, width: float = 1.5):
    return _set_legend_label(plot.plot(x, y, pen=pg.mkPen(color, width=width)), label)


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
    return _set_legend_label(plot.plot(stick_x, stick_y, pen=pg.mkPen(color, width=width)), label)


def plot_peak_intensity_sticks(
    plot: pg.PlotWidget,
    peaks,
    color: str,
    x_grid,
    baseline,
    height: float,
    label: str | None = None,
    width: float = 1.6,
):
    x_grid = np.asarray(x_grid, dtype=float)
    baseline = np.asarray(baseline, dtype=float)
    if baseline.shape != x_grid.shape:
        baseline = np.full_like(x_grid, float(np.nanmedian(baseline)) if len(baseline) else 0.0)
    stick_x = []
    stick_y = []
    for peak in peaks:
        two_theta = float(getattr(peak, "two_theta", 0.0))
        base_y = float(np.interp(two_theta, x_grid, baseline))
        intensity = max(float(getattr(peak, "intensity", 0.0)), 0.0)
        stick_x.extend([two_theta, two_theta, np.nan])
        stick_y.extend([base_y, base_y + height * intensity / 100.0, np.nan])
    return _set_legend_label(plot.plot(stick_x, stick_y, pen=pg.mkPen(color, width=width)), label)


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
    label: str | None,
    x_label: float,
):
    marker_x, marker_y = phase_marker_lane_arrays(peaks, baseline, height)
    marker_item = plot.plot(marker_x, marker_y, pen=pg.mkPen(color, width=1.8))
    if not label:
        return [marker_item]
    label_item = pg.TextItem(label, color=color, anchor=(0.0, 0.5))
    label_font = QFont()
    label_font.setPointSize(7 if "\n" in label else 8)
    label_font.setWeight(QFont.Weight.DemiBold)
    label_item.setFont(label_font)
    label_item.setPos(x_label, baseline + height * 0.45)
    plot.addItem(label_item)
    return [marker_item, label_item]


def add_hkl_labels(
    plot: pg.PlotWidget,
    peaks,
    color: str,
    y,
    height: float | None = None,
    limit: int = 30,
    angle: float = 90,
    above_peaks: bool = False,
    x_grid=None,
):
    labels = []
    y_values = np.asarray(y, dtype=float)
    x_values = np.asarray(x_grid, dtype=float) if x_grid is not None else None

    def base_y_at(two_theta: float) -> float:
        if y_values.shape == ():
            return float(y_values)
        if x_values is not None and x_values.shape == y_values.shape and y_values.size:
            return float(np.interp(two_theta, x_values, y_values))
        return float(np.nanmedian(y_values)) if y_values.size else 0.0

    display_peaks = sorted(peaks, key=lambda item: getattr(item, "intensity", 0.0), reverse=True)[:limit]
    display_peaks = sorted(display_peaks, key=lambda item: getattr(item, "two_theta", 0.0))
    for peak in display_peaks:
        h = getattr(peak, "h", "")
        k = getattr(peak, "k", "")
        l = getattr(peak, "l", "")
        item = pg.TextItem(f"({h}{k}{l})", color=color, anchor=(0.5, 1.0), angle=angle)
        label_font = QFont()
        label_font.setPointSize(10)
        label_font.setWeight(QFont.Weight.DemiBold)
        item.setFont(label_font)
        two_theta = float(getattr(peak, "two_theta", 0.0))
        if above_peaks and height is not None:
            intensity = max(float(getattr(peak, "intensity", 0.0)), 0.0)
            label_y = base_y_at(two_theta) + float(height) * intensity / 100.0 + float(height) * 0.09
        else:
            label_y = base_y_at(two_theta)
        item.setPos(two_theta, float(label_y))
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
