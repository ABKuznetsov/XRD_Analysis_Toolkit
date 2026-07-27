from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QFont

from xrd_finder.ui.plot_style import PlotStyle


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
    considered_positions = []
    for obs_x in peak_positions:
        y_index = int(np.argmin(np.abs(x - obs_x)))
        peak_strength = float(corrected_strength[y_index]) if len(corrected_strength) > y_index else float(observed_y[y_index])
        if peak_strength >= strength_floor:
            considered_positions.append(float(obs_x))
    for obs_x in considered_positions:
        y_index = int(np.argmin(np.abs(x - obs_x)))
        marker_y = _local_observed_peak_y(x, observed_y, obs_x, y_index)
        best_color = ""
        best_delta = 0.22
        for color, _label, phase_positions in phase_peak_sets:
            if len(phase_positions) == 0:
                continue
            delta = float(np.min(np.abs(phase_positions - obs_x)))
            if delta <= best_delta:
                best_delta = delta
                best_color = color
        if best_color:
            item = pg.ScatterPlotItem(
                [float(obs_x)],
                [marker_y],
                pen=pg.mkPen("#ffffff", width=0.8),
                brush=pg.mkBrush(best_color),
                size=style.marker.size,
                symbol=style.marker.symbol,
            )
            plot.addItem(item)
            plot_layers["coverage_markers"].append(item)
            explained += 1
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
    observed_peaks,
    phase_peak_sets: list[tuple[str, str, np.ndarray]] | None = None,
    phase_assignment_styles: dict[str, tuple[str, str]],
    show_peak_labels: bool,
    style: PlotStyle | None = None,
) -> tuple[int, int]:
    style = style or PlotStyle()
    y_span = max(float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)), float(np.nanmax(observed_y)), 1.0)
    label_offset = max(y_span * 0.008, 1.0)
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
            primary = primary_assignment(assignments)
            color, _phase_label = phase_assignment_styles.get(
                str(getattr(primary, "candidate_key", "")),
                ("#d93025", ""),
            )
            item = pg.ScatterPlotItem(
                [obs_x],
                [marker_y],
                pen=pg.mkPen("#ffffff", width=1.0),
                brush=pg.mkBrush(color),
                size=style.marker.size,
                symbol="d" if status == "overlapping" else style.marker.symbol,
            )
            plot.addItem(item)
            plot_layers["coverage_markers"].append(item)
            if show_peak_labels:
                label = assignment_marker_label(assignments)
                if label:
                    text = pg.TextItem(label, color="#111111", anchor=(0.5, 1.05))
                    font = QFont()
                    font.setPointSize(8)
                    font.setWeight(QFont.Weight.DemiBold)
                    text.setFont(font)
                    text.setPos(obs_x, marker_y + label_offset)
                    plot.addItem(text)
                    plot_layers["peak_labels"].append(text)
        else:
            fallback = _nearest_phase_marker_from_sets(obs_x, getattr(observed_peak, "fwhm", 0.0), phase_peak_sets or [])
            if fallback is not None:
                color, _label = fallback
                explained += 1
                item = pg.ScatterPlotItem(
                    [obs_x],
                    [marker_y],
                    pen=pg.mkPen("#ffffff", width=1.0),
                    brush=pg.mkBrush(color),
                    size=style.marker.size,
                    symbol=style.marker.symbol,
                )
                plot.addItem(item)
                plot_layers["coverage_markers"].append(item)
                continue
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


def _nearest_phase_marker_from_sets(
    obs_x: float,
    observed_fwhm: float,
    phase_peak_sets: list[tuple[str, str, np.ndarray]],
) -> tuple[str, str] | None:
    tolerance = max(0.20, min(0.90, max(float(observed_fwhm or 0.0), 0.12) * 1.55))
    best: tuple[str, str] | None = None
    best_delta = tolerance
    for color, label, phase_positions in phase_peak_sets:
        if len(phase_positions) == 0:
            continue
        delta = float(np.min(np.abs(np.asarray(phase_positions, dtype=float) - float(obs_x))))
        if delta <= best_delta:
            best_delta = delta
            best = (color, label)
    return best


def primary_assignment(assignments):
    return max(
        assignments,
        key=lambda assignment: float(getattr(assignment, "intensity_ratio", 0.0)),
    )


def assignment_marker_label(assignments) -> str:
    labels = []
    for assignment in assignments[:2]:
        hkl = "-".join(str(value) for value in getattr(assignment, "hkl", ()) if value is not None)
        if hkl:
            labels.append(f"({hkl})")
    if len(assignments) > 2 and labels:
        labels[-1] = labels[-1] + "+"
    return " / ".join(labels)
