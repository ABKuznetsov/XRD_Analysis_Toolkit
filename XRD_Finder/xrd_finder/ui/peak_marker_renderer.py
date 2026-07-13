from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtGui import QFont

from xrd_finder.ui.plot_style import PlotStyle


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
            phase_assignment_styles=phase_assignment_styles or {},
            show_peak_labels=show_peak_labels,
            style=style,
        )
    if not phase_peak_sets:
        return 0, 0
    peak_positions = observed_peak_positions(x, corrected_y)
    if len(peak_positions) == 0:
        return 0, 0
    y_span = max(float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)), float(np.nanmax(observed_y)), 1.0)
    marker_offset = y_span * 0.045
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
        marker_y = float(observed_y[y_index]) + marker_offset
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
    phase_assignment_styles: dict[str, tuple[str, str]],
    show_peak_labels: bool,
    style: PlotStyle | None = None,
) -> tuple[int, int]:
    style = style or PlotStyle()
    y_span = max(float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)), float(np.nanmax(observed_y)), 1.0)
    marker_offset = y_span * 0.05
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
        marker_y = float(observed_y[y_index]) + marker_offset
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
                    text.setPos(obs_x, marker_y + marker_offset * 0.3)
                    plot.addItem(text)
                    plot_layers["peak_labels"].append(text)
        else:
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
