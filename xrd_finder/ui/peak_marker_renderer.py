from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QPainterPath
from scipy.signal import peak_prominences

from xrd_finder.ui.plot_style import PlotStyle


def _half_circle_symbol(side: str) -> QPainterPath:
    path = QPainterPath()
    bounds = QRectF(-0.5, -0.5, 1.0, 1.0)
    if side == "left":
        path.moveTo(0.0, -0.5)
        path.arcTo(bounds, 90.0, 180.0)
    else:
        path.moveTo(0.0, 0.5)
        path.arcTo(bounds, 270.0, 180.0)
    path.closeSubpath()
    return path


_LEFT_HALF_CIRCLE = _half_circle_symbol("left")
_RIGHT_HALF_CIRCLE = _half_circle_symbol("right")


def _unique_colors(colors) -> list[str]:
    unique: list[str] = []
    for color in colors:
        value = str(color or "").strip()
        if value and value not in unique:
            unique.append(value)
    return unique


def _add_colored_phase_marker(
    *,
    plot,
    plot_layers: dict[str, list],
    x: float,
    y: float,
    colors,
    size: int,
    symbol,
) -> None:
    marker_colors = _unique_colors(colors)
    if len(marker_colors) >= 2:
        for color, half_symbol in zip(marker_colors[:2], (_LEFT_HALF_CIRCLE, _RIGHT_HALF_CIRCLE)):
            item = pg.ScatterPlotItem(
                [float(x)],
                [float(y)],
                pen=pg.mkPen("#ffffff", width=0.9),
                brush=pg.mkBrush(color),
                size=size,
                symbol=half_symbol,
            )
            plot.addItem(item)
            plot_layers["coverage_markers"].append(item)
        return
    color = marker_colors[0] if marker_colors else "#d93025"
    item = pg.ScatterPlotItem(
        [float(x)],
        [float(y)],
        pen=pg.mkPen("#ffffff", width=1.0),
        brush=pg.mkBrush(color),
        size=size,
        symbol=symbol,
    )
    plot.addItem(item)
    plot_layers["coverage_markers"].append(item)


def _robust_noise_sigma(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size < 5:
        return 0.0
    differences = np.diff(finite)
    if differences.size:
        median = float(np.median(differences))
        mad = float(np.median(np.abs(differences - median)))
        sigma = 1.4826 * mad / np.sqrt(2.0)
        if np.isfinite(sigma) and sigma > 0.0:
            return sigma
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    sigma = 1.4826 * mad
    return sigma if np.isfinite(sigma) and sigma > 0.0 else 0.0


def _local_background_sigma(
    local_x: np.ndarray,
    local_y: np.ndarray,
    peak_position: float,
) -> float:
    background_mask = np.abs(local_x - float(peak_position)) >= 0.12
    background_x = np.asarray(local_x[background_mask], dtype=float)
    background_y = np.asarray(local_y[background_mask], dtype=float)
    finite = np.isfinite(background_x) & np.isfinite(background_y)
    background_x = background_x[finite]
    background_y = background_y[finite]
    if background_y.size < 8:
        return 0.0
    centered_x = background_x - float(np.nanmean(background_x))
    try:
        slope, intercept = np.polyfit(centered_x, background_y, 1)
        residual = background_y - (slope * centered_x + intercept)
    except Exception:
        residual = background_y - float(np.nanmedian(background_y))
    median = float(np.nanmedian(residual))
    mad = float(np.nanmedian(np.abs(residual - median)))
    local_sigma = 1.4826 * mad
    return local_sigma if np.isfinite(local_sigma) and local_sigma > 0.0 else 0.0


def _is_significant_peak(x: np.ndarray, corrected_y: np.ndarray, y_index: int, sigma: float) -> bool:
    if sigma <= 0.0 or corrected_y.size == 0:
        return True
    y_index = max(0, min(int(y_index), corrected_y.size - 1))
    position = float(x[y_index])
    left = int(np.searchsorted(x, position - 0.45, side="left"))
    right = int(np.searchsorted(x, position + 0.45, side="right"))
    local_start = max(0, left)
    local_stop = min(len(corrected_y), right)
    local = np.asarray(corrected_y[local_start:local_stop], dtype=float)
    if local.size < 3:
        return False
    local = np.where(np.isfinite(local), local, 0.0)

    # Refinement positions can differ from the sampled experimental maximum by
    # a point or two. Snap only inside a narrow neighbourhood, then require a
    # real local maximum. The wider +/-0.45 degree interval is used solely for
    # measuring its prominence against the surrounding trace.
    steps = np.diff(np.asarray(x, dtype=float))
    steps = steps[np.isfinite(steps) & (steps > 0.0)]
    step = float(np.nanmedian(steps)) if steps.size else 0.03
    snap_radius = max(1, int(round(0.06 / max(step, 1.0e-6))))
    local_index = y_index - local_start
    snap_left = max(0, local_index - snap_radius)
    snap_right = min(local.size, local_index + snap_radius + 1)
    peak_index = snap_left + int(np.argmax(local[snap_left:snap_right]))
    if peak_index <= 0 or peak_index >= local.size - 1:
        return False
    if local[peak_index] <= local[peak_index - 1] or local[peak_index] <= local[peak_index + 1]:
        return False

    baseline = float(np.nanpercentile(local, 20))
    signal = float(local[peak_index]) - baseline
    prominence = float(peak_prominences(local, np.asarray([peak_index], dtype=int))[0][0])
    local_x = np.asarray(x[local_start:local_stop], dtype=float)
    local_sigma = _local_background_sigma(local_x, local, float(x[local_start + peak_index]))
    # Five sigmas keeps publication markers away from ordinary noise. Cap the
    # local estimate because neighbouring diffraction peaks are structure, not
    # noise, and otherwise they can hide a genuine phase-supported maximum.
    global_sigma = max(float(sigma), 0.0)
    effective_sigma = max(global_sigma, float(local_sigma))
    if global_sigma > 0.0:
        effective_sigma = min(effective_sigma, global_sigma * 1.15)
    threshold = 5.0 * effective_sigma
    return bool(
        np.isfinite(signal)
        and np.isfinite(prominence)
        and signal >= threshold
        and prominence >= threshold
    )


def _local_observed_peak_y(
    x: np.ndarray,
    observed_y: np.ndarray,
    obs_x: float,
    y_index: int,
    fwhm: float = 0.0,
) -> float:
    """Place a marker on the nearby experimental maximum, not above it."""
    if observed_y.size == 0:
        return 0.0
    y_index = max(0, min(int(y_index), observed_y.size - 1))
    if x.size < 2:
        return float(observed_y[y_index])

    steps = np.diff(x)
    steps = steps[np.isfinite(steps) & (steps > 0.0)]
    step = float(np.median(steps)) if steps.size else 0.01
    half_width = max(step * 2.0, min(0.12, max(float(fwhm or 0.0), 0.0) * 0.30))
    left = int(np.searchsorted(x, obs_x - half_width, side="left"))
    right = int(np.searchsorted(x, obs_x + half_width, side="right"))
    left = max(0, min(left, observed_y.size - 1))
    right = max(left + 1, min(right, observed_y.size))

    local_y = np.asarray(observed_y[left:right], dtype=float)
    local_y = local_y[np.isfinite(local_y)]
    return float(np.max(local_y)) if local_y.size else float(observed_y[y_index])


def add_peak_coverage_markers(
    *,
    plot,
    plot_layers: dict[str, list],
    observed_peak_positions,
    x: np.ndarray,
    observed_y: np.ndarray,
    corrected_y: np.ndarray,
    phase_peak_sets: list[tuple[str, str, np.ndarray]],
    observed_peak_assignments=None,
    phase_assignment_styles: dict[str, tuple[str, str]] | None = None,
    show_peak_labels: bool = False,
    style: PlotStyle | None = None,
) -> tuple[int, int]:
    style = style or PlotStyle()
    if observed_peak_assignments:
        return add_assignment_markers(
            plot=plot,
            plot_layers=plot_layers,
            x=x,
            observed_y=observed_y,
            corrected_y=corrected_y,
            observed_peaks=observed_peak_assignments,
            phase_peak_sets=phase_peak_sets,
            phase_assignment_styles=phase_assignment_styles or {},
            show_peak_labels=show_peak_labels,
            style=style,
        )
    if not phase_peak_sets:
        return 0, 0
    peak_positions = observed_peak_positions(x, corrected_y)
    if len(peak_positions) == 0:
        return 0, 0
    corrected_strength = np.asarray(corrected_y, dtype=float)
    finite_strength = corrected_strength[np.isfinite(corrected_strength) & (corrected_strength > 0)]
    if len(finite_strength):
        marker_cutoff = float(np.nanpercentile(finite_strength, 72))
        strength_floor = float(np.nanpercentile(finite_strength, 60))
    else:
        marker_cutoff = float(np.nanpercentile(observed_y, 72))
        strength_floor = float(np.nanpercentile(observed_y, 60))
    unknown_limit = 10
    unknown_count = 0
    explained = 0
    y_span = max(
        float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)),
        1.0,
    )
    phase_marker_offset = max(y_span * 0.020, 3.0)
    phase_marker_size = max(int(round(style.marker.size * 1.4)), style.marker.size + 3)
    noise_sigma = _robust_noise_sigma(corrected_strength)
    considered_positions = []
    for obs_x in peak_positions:
        y_index = int(np.argmin(np.abs(x - obs_x)))
        peak_strength = float(corrected_strength[y_index]) if len(corrected_strength) > y_index else float(observed_y[y_index])
        if peak_strength >= strength_floor:
            considered_positions.append(float(obs_x))
    for obs_x in considered_positions:
        y_index = int(np.argmin(np.abs(x - obs_x)))
        marker_y = _local_observed_peak_y(x, observed_y, obs_x, y_index)
        matching_colors = []
        for color, _label, phase_positions in phase_peak_sets:
            if len(phase_positions) == 0:
                continue
            delta = float(np.min(np.abs(phase_positions - obs_x)))
            if delta <= 0.22:
                matching_colors.append(color)
        if matching_colors:
            explained += 1
            if not _is_significant_peak(x, corrected_strength, y_index, noise_sigma):
                continue
            _add_colored_phase_marker(
                plot=plot,
                plot_layers=plot_layers,
                x=float(obs_x),
                y=marker_y + phase_marker_offset,
                colors=matching_colors,
                size=phase_marker_size,
                symbol=style.marker.symbol,
            )
        else:
            peak_strength = float(corrected_strength[y_index]) if len(corrected_strength) > y_index else float(observed_y[y_index])
            if unknown_count >= unknown_limit or peak_strength < marker_cutoff:
                continue
            item = pg.ScatterPlotItem(
                [float(obs_x)],
                [marker_y],
                pen=pg.mkPen("#6f6f6f", width=1.0),
                brush=pg.mkBrush("#ffffff"),
                size=style.marker.size,
                symbol=style.marker.unknown_symbol,
            )
            plot.addItem(item)
            plot_layers["unknown_peaks"].append(item)
            unknown_count += 1
    return explained, int(len(considered_positions))


def add_assignment_markers(
    *,
    plot,
    plot_layers: dict[str, list],
    x: np.ndarray,
    observed_y: np.ndarray,
    corrected_y: np.ndarray,
    observed_peaks,
    phase_peak_sets: list[tuple[str, str, np.ndarray]] | None = None,
    phase_assignment_styles: dict[str, tuple[str, str]],
    show_peak_labels: bool,
    style: PlotStyle | None = None,
) -> tuple[int, int]:
    style = style or PlotStyle()
    # Use the trace height, not its stacked absolute offset, so marker spacing
    # remains consistent for every pattern in multi mode.
    y_span = max(float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)), 1.0)
    label_offset = max(y_span * 0.008, 1.0)
    phase_marker_offset = max(y_span * 0.020, 3.0)
    phase_marker_size = max(int(round(style.marker.size * 1.4)), style.marker.size + 3)
    corrected_strength = np.asarray(corrected_y, dtype=float)
    noise_sigma = _robust_noise_sigma(corrected_strength)
    peak_strengths = [
        max(float(getattr(observed_peak, "intensity", 0.0)), 0.0)
        for observed_peak in observed_peaks
        if np.isfinite(float(getattr(observed_peak, "intensity", 0.0)))
    ]
    unknown_cutoff = float(np.nanpercentile(peak_strengths, 74)) if peak_strengths else float(np.nanpercentile(observed_y, 74))
    unknown_count = 0
    explained = 0
    legend_marker_names: set[str] = set()
    peak_records = []
    for observed_peak in observed_peaks:
        obs_x = float(observed_peak.two_theta)
        if not np.isfinite(obs_x):
            continue
        y_index = int(np.argmin(np.abs(x - obs_x)))
        peak_height = max(float(getattr(observed_peak, "intensity", 0.0)), 0.0)
        if peak_height <= 0.0:
            peak_height = max(float(observed_y[y_index]) - float(np.nanpercentile(observed_y, 10)), 0.0)
        peak_records.append((peak_height, observed_peak, y_index))
    peak_records = sorted(peak_records, key=lambda item: item[0], reverse=True)[:80]
    peak_records = sorted(peak_records, key=lambda item: float(item[1].two_theta))
    for _peak_height, observed_peak, y_index in peak_records:
        obs_x = float(observed_peak.two_theta)
        marker_y = _local_observed_peak_y(
            x,
            observed_y,
            obs_x,
            y_index,
            float(getattr(observed_peak, "fwhm", 0.0) or 0.0),
        )
        assignments = list(getattr(observed_peak, "assignments", []) or [])
        status = getattr(getattr(observed_peak, "status", ""), "value", getattr(observed_peak, "status", ""))
        if assignments:
            explained += 1
            if not _is_significant_peak(x, corrected_strength, y_index, noise_sigma):
                continue
            assignments_by_strength = sorted(
                assignments,
                key=lambda assignment: float(getattr(assignment, "intensity_ratio", 0.0)),
                reverse=True,
            )
            assignment_colors = [
                phase_assignment_styles.get(
                    str(getattr(assignment, "candidate_key", "")),
                    ("#d93025", ""),
                )[0]
                for assignment in assignments_by_strength
            ]
            _add_colored_phase_marker(
                plot=plot,
                plot_layers=plot_layers,
                x=obs_x,
                y=marker_y + phase_marker_offset,
                colors=assignment_colors,
                size=phase_marker_size,
                symbol="d" if status == "overlapping" else style.marker.symbol,
            )
            if show_peak_labels:
                label = assignment_marker_label(assignments)
                if label:
                    text = pg.TextItem(label, color="#111111", anchor=(0.5, 1.05))
                    font = QFont()
                    font.setPointSize(8)
                    font.setWeight(QFont.Weight.DemiBold)
                    text.setFont(font)
                    text.setPos(obs_x, marker_y + phase_marker_offset + label_offset)
                    plot.addItem(text)
                    plot_layers["peak_labels"].append(text)
        else:
            # Assignment records are authoritative. A merely nearby phase
            # stick must not recolor an unassigned experimental peak, because
            # that produced false phase attribution in multiphase patterns.
            if unknown_count >= 10 or _peak_height < unknown_cutoff:
                continue
            item = pg.ScatterPlotItem(
                [obs_x],
                [marker_y],
                pen=pg.mkPen("#6f6f6f", width=1.2),
                brush=pg.mkBrush("#ffffff"),
                size=style.marker.size,
                symbol=style.marker.unknown_symbol,
                name="unknown peak" if "unknown peak" not in legend_marker_names else None,
            )
            legend_marker_names.add("unknown peak")
            plot.addItem(item)
            plot_layers["unknown_peaks"].append(item)
            unknown_count += 1
    return explained, int(len(peak_records))


def assignment_marker_label(assignments) -> str:
    labels = []
    for assignment in assignments[:2]:
        hkl = "-".join(str(value) for value in getattr(assignment, "hkl", ()) if value is not None)
        if hkl:
            labels.append(f"({hkl})")
    if len(assignments) > 2 and labels:
        labels[-1] = labels[-1] + "+"
    return " / ".join(labels)
