from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont, QPainterPath

from xrd_finder.ui.plot_style import PlotStyle
from xrd_finder.finder.models import ObservedPeak, PeakAssignment


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


def _positive_grid_step(x: np.ndarray) -> float:
    steps = np.diff(np.asarray(x, dtype=float))
    steps = steps[np.isfinite(steps) & (steps > 0.0)]
    return float(np.median(steps)) if steps.size else 0.0


def _is_significant_peak(
    x: np.ndarray, corrected_y: np.ndarray, y_index: int, sigma: float,
    *, grid_step: float | None = None,
    sensitivity: int = 0,
) -> bool:
    from scipy.signal import peak_prominences
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
    step = _positive_grid_step(x) if grid_step is None else grid_step
    step = step if step > 0.0 else 0.03
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
    # The default five-sigma threshold keeps markers away from ordinary noise.
    # The display slider can reveal weaker already assigned maxima. Cap the
    # local estimate because neighbouring diffraction peaks are structure, not
    # noise, and otherwise they can hide a genuine phase-supported maximum.
    global_sigma = max(float(sigma), 0.0)
    effective_sigma = max(global_sigma, float(local_sigma))
    if global_sigma > 0.0:
        effective_sigma = min(effective_sigma, global_sigma * 1.15)
    threshold = (5.0-4.0*float(np.clip(sensitivity,0,100))/100.) * effective_sigma
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
    *,
    grid_step: float | None = None,
) -> float:
    """Place a marker on the nearby experimental maximum, not above it."""
    if observed_y.size == 0:
        return 0.0
    y_index = max(0, min(int(y_index), observed_y.size - 1))
    if x.size < 2:
        return float(observed_y[y_index])

    step = _positive_grid_step(x) if grid_step is None else grid_step
    step = step if step > 0.0 else 0.01
    half_width = max(step * 2.0, min(0.12, max(float(fwhm or 0.0), 0.0) * 0.30))
    left = int(np.searchsorted(x, obs_x - half_width, side="left"))
    right = int(np.searchsorted(x, obs_x + half_width, side="right"))
    left = max(0, min(left, observed_y.size - 1))
    right = max(left + 1, min(right, observed_y.size))

    local_y = np.asarray(observed_y[left:right], dtype=float)
    local_y = local_y[np.isfinite(local_y)]
    return float(np.max(local_y)) if local_y.size else float(observed_y[y_index])


def _nearby_phase_peak_colors(
    *,
    obs_x: float,
    x: np.ndarray,
    phase_peak_sets: list[tuple[str, str, np.ndarray]] | None,
    fwhm: float = 0.0,
) -> list[str]:
    if not phase_peak_sets:
        return []
    x_values = np.asarray(x, dtype=float)
    if x_values.size >= 2:
        steps = np.diff(x_values)
        steps = steps[np.isfinite(steps) & (steps > 0.0)]
        grid_tolerance = float(np.nanmedian(steps)) * 2.0 if steps.size else 0.0
    else:
        grid_tolerance = 0.0
    tolerance = max(0.22, grid_tolerance, max(float(fwhm or 0.0), 0.0) * 0.75)
    colors: list[str] = []
    for color, _label, phase_positions in phase_peak_sets:
        positions = np.asarray(phase_positions, dtype=float)
        positions = positions[np.isfinite(positions)]
        if positions.size == 0:
            continue
        if float(np.min(np.abs(positions - float(obs_x)))) <= tolerance:
            colors.append(color)
    return colors


def _has_nearby_phase_peak(
    *,
    obs_x: float,
    x: np.ndarray,
    phase_peak_sets: list[tuple[str, str, np.ndarray]] | None,
    fwhm: float = 0.0,
) -> bool:
    return bool(
        _nearby_phase_peak_colors(
            obs_x=obs_x,
            x=x,
            phase_peak_sets=phase_peak_sets,
            fwhm=fwhm,
        )
    )


def _marker_merge_tolerance(
    x: np.ndarray, fwhm: float = 0.0, *, grid_step: float | None = None,
) -> float:
    step = _positive_grid_step(x) if grid_step is None else grid_step
    grid_tolerance = step * 3.0
    # Collapse duplicate detections only, not independently resolved maxima.
    return max(0.01, grid_tolerance, min(max(float(fwhm or 0.0), 0.0) * 0.15, 0.04))


def _marker_position_available(
    used_positions: list[float],
    position: float,
    *,
    x: np.ndarray,
    fwhm: float = 0.0,
    grid_step: float | None = None,
) -> bool:
    tolerance = _marker_merge_tolerance(x, fwhm, grid_step=grid_step)
    return all(abs(float(existing) - float(position)) > tolerance for existing in used_positions)


def _phase_marker_offset(plot, y_span: float, size: int, clearance_pixels: float) -> float:
    offset = max(y_span * 0.020, 3.0)
    if clearance_pixels > 0:
        # Symbols have a fixed pixel diameter. In a dense multi-pattern stack,
        # a percentage of just one trace can be smaller than the symbol itself.
        pixel_y = abs(float(plot.getViewBox().viewPixelSize()[1]))
        if np.isfinite(pixel_y):
            offset = max(offset, pixel_y * (size / 2.0 + clearance_pixels))
    return offset


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
    positional_marker_candidate=None,
    weak_marker_candidates=None,
    phase_marker_levels: dict[str, int] | None = None,
    show_peak_labels: bool = False,
    style: PlotStyle | None = None,
    marker_clearance_pixels: float = 0.0,
) -> tuple[int, int]:
    style = style or PlotStyle()
    if observed_peak_assignments is not None:
        return add_assignment_markers(
            plot=plot,
            plot_layers=plot_layers,
            x=x,
            observed_y=observed_y,
            corrected_y=corrected_y,
            observed_peaks=observed_peak_assignments,
            phase_peak_sets=phase_peak_sets,
            phase_assignment_styles=phase_assignment_styles or {},
            positional_marker_candidate=positional_marker_candidate,
            weak_marker_candidates=weak_marker_candidates,
            phase_marker_levels=phase_marker_levels,
            show_peak_labels=show_peak_labels,
            style=style,
            marker_clearance_pixels=marker_clearance_pixels,
        )
    if not phase_peak_sets:
        return 0, 0
    peak_positions = observed_peak_positions(x, corrected_y)
    if len(peak_positions) == 0:
        return 0, 0
    grid_step = _positive_grid_step(x)
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
    phase_marker_size = max(int(round(style.marker.size * 1.4)), style.marker.size + 3)
    phase_marker_offset = _phase_marker_offset(plot, y_span, phase_marker_size, marker_clearance_pixels)
    noise_sigma = _robust_noise_sigma(corrected_strength)
    considered_positions = []
    for obs_x in peak_positions:
        y_index = int(np.argmin(np.abs(x - obs_x)))
        peak_strength = float(corrected_strength[y_index]) if len(corrected_strength) > y_index else float(observed_y[y_index])
        if peak_strength >= strength_floor:
            considered_positions.append(float(obs_x))
    for obs_x in considered_positions:
        y_index = int(np.argmin(np.abs(x - obs_x)))
        marker_y = _local_observed_peak_y(x, observed_y, obs_x, y_index, grid_step=grid_step)
        matching_colors = []
        for color, _label, phase_positions in phase_peak_sets:
            if len(phase_positions) == 0:
                continue
            delta = float(np.min(np.abs(phase_positions - obs_x)))
            if delta <= 0.22:
                matching_colors.append(color)
        if matching_colors:
            explained += 1
            if not _is_significant_peak(x, corrected_strength, y_index, noise_sigma, grid_step=grid_step,
                                        sensitivity=style.marker.weak_peak_sensitivity):
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


def _positional_marker_lines(candidate, sensitivity, *, all_lines=False):
    """Prepare display-only reflection evidence for a validated single phase."""
    if candidate is None:
        return None
    fields = ('peak_two_theta', 'peak_intensity', 'peak_h', 'peak_k', 'peak_l')
    values = [getattr(candidate, field, []) for field in fields]
    if not values[0] or any(len(value) != len(values[0]) for value in values):
        return None
    # The same slider reveals weak reference reflections as well as weak
    # observed maxima. Its value never changes positional matching tolerance.
    minimum = np.nextafter(0., 1.) if all_lines else 5.0-4.8*float(np.clip(sensitivity, 0, 100))/100.
    rows = sorted((tuple(row) for row in zip(*values, strict=True)
                   if np.isfinite(row[0]) and np.isfinite(row[1]) and row[1] >= minimum),
                  key=lambda row: row[0])
    if not rows:
        return None
    return candidate, rows, np.asarray([row[0] for row in rows], dtype=float)


def _positional_marker_assignment(observed_peak, evidence):
    if evidence is None:
        return []
    candidate, rows, positions = evidence
    angle = float(observed_peak.two_theta)
    index = int(np.searchsorted(positions, angle))
    adjacent = [i for i in (index-1, index) if 0 <= i < len(rows)]
    nearest = min(adjacent, key=lambda i: abs(positions[i]-angle))
    row = rows[nearest]
    delta = angle-float(row[0])
    # Retain the assignment builder's existing positional window. This is
    # annotation evidence, not a change to saved assignments or search scores.
    tolerance = max(.25, min(.75, max(.12, float(getattr(observed_peak, 'fwhm', 0.) or 0.)*1.35)))
    if abs(delta) > tolerance:
        return []
    return [PeakAssignment(candidate_key=candidate.candidate_key,
        phase_name=candidate.name or candidate.formula or candidate.entry_id,
        hkl=tuple(int(value) for value in row[2:]), calc_two_theta=float(row[0]),
        delta_two_theta=delta, intensity_ratio=float(row[1])/100.)]


def phase_marker_level(value) -> int:
    """Read a per-phase display preference; old projects use the standard view."""
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 50


def _marker_maxima_catalogue(x, strength, noise_sigma):
    """Describe experimental maxima throughout the complete angular range.

    Smooth by one sampled point to suppress noise on the sides of large peaks.
    Prominence, rather than absolute height on a peak's tail, orders additions.
    This list is never supplied to the finder or saved as scientific evidence.
    """
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import find_peaks, peak_prominences, peak_widths
    if len(x) < 3 or len(x) != len(strength):
        return [], None
    values = np.where(np.isfinite(strength), strength, 0.)
    step = _positive_grid_step(x)
    if step <= 0.:
        return [], None
    window = max(3, int(round(.9 / step)) | 1)
    raw_indices, _ = find_peaks(values)
    raw_prominences = peak_prominences(values, raw_indices, wlen=window)[0]
    raw_widths = peak_widths(values, raw_indices, rel_height=.5)[0] * step
    raw = (raw_indices, raw_prominences, raw_widths)
    smooth = gaussian_filter1d(values, sigma=1., mode='nearest')
    indices, properties = find_peaks(smooth, prominence=max(2.5 * noise_sigma, np.finfo(float).eps), wlen=window)
    widths = peak_widths(smooth, indices, rel_height=.5)[0] * step
    records = []
    for index, prominence, width in zip(indices, properties['prominences'], widths):
        # A tiny ripple on a high tail is not another diffraction maximum.
        if prominence < max(float(smooth[index]), 0.) * .08:
            continue
        records.append((float(prominence), ObservedPeak(float(x[index]),
            max(float(values[index]), 0.), float(width)), int(index)))
    return records, raw


def _complete_marker_catalogue(*, x, strength, noise_sigma, peak_records,
                               prepared, evidence):
    """Describe all phase-supported experimental maxima before filtering.

    One catalogue entry represents one actual local maximum, even when several
    reflections/phases coincide. Slider values never participate in detection.
    """
    detected, raw = _marker_maxima_catalogue(x, strength, noise_sigma)
    if raw is None:
        return {}, {}
    indices, prominences, widths = raw
    step = _positive_grid_step(x)
    positions = x[indices]
    proposals = []
    def measured_maximum(angle):
        if not len(indices):
            return None
        offset = int(np.searchsorted(positions, angle))
        adjacent = [i for i in (offset - 1, offset) if 0 <= i < len(indices)]
        nearest = min(adjacent, key=lambda i: abs(float(positions[i]) - angle))
        index = int(indices[nearest])
        prominence = float(prominences[nearest])
        if (abs(float(x[index]) - angle) > max(.04, step * 2.) or prominence <= 0.
                or prominence < max(float(strength[index]), 0.) * .08):
            return None
        return index, prominence, float(widths[nearest])
    original_by_maximum = {}
    for original_index, ((_, peak, _), assignments) in enumerate(zip(peak_records, prepared)):
        maximum = measured_maximum(peak.two_theta)
        if maximum is None:
            continue
        index, prominence, width = maximum
        original_by_maximum.setdefault(index, original_index)
        if assignments:
            proposals.append((index, prominence, width, assignments))
    # Include weaker maxima missing from the capped identification peak list.
    # In a mixture coincident references remain coincident annotations; no
    # scientific assignment or phase fraction is inferred or modified here.
    for _prominence, peak, _index in detected:
        maximum = measured_maximum(peak.two_theta)
        if maximum is None:
            continue
        index, prominence, width = maximum
        measured_peak = ObservedPeak(float(x[index]), max(float(strength[index]), 0.), width)
        assignments = {}
        for item in evidence:
            for assignment in _positional_marker_assignment(measured_peak, item):
                assignments[assignment.candidate_key] = assignment
        if assignments:
            proposals.append((index, prominence, width, assignments))
    catalogue, strengths, targets = {}, {}, {}
    for index, prominence, width, assignments in sorted(proposals, key=lambda row: row[1], reverse=True):
        target = targets.get(index)
        if target is None:
            target = original_by_maximum.get(index)
            measured_peak = ObservedPeak(float(x[index]), max(float(strength[index]), 0.), width)
            record = (measured_peak.intensity, measured_peak, index)
            if target is None:
                target = len(peak_records)
                peak_records.append(record)
                prepared.append({})
            else:
                # Replace a local display record, never the saved ObservedPeak.
                peak_records[target] = record
            targets[index] = target
            strengths[target] = prominence
        for key, assignment in assignments.items():
            prepared[target].setdefault(key, assignment)
            if target not in catalogue.setdefault(key, []):
                catalogue[key].append(target)
    return catalogue, strengths


def _visible_phase_maxima(indices, strengths, level, noise_sigma):
    """Apply a common height-above-background threshold across the whole scan.

    The logarithmic scale keeps useful control when the strongest peak is
    orders of magnitude higher than weak lines. 50 retains the standard
    five-sigma sensitivity; 1 leaves the strongest, 0 hides all, 100 shows all.
    """
    level = phase_marker_level(level)
    if level == 0 or not indices:
        return set()
    if level == 100:
        return set(indices)
    maximum = max(strengths[index] for index in indices)
    minimum = min(strengths[index] for index in indices)
    standard = min(maximum, max(5. * noise_sigma, np.finfo(float).eps))
    if level < 50:
        if level == 1:
            threshold = maximum
        else:
            weight = (50. - level) / 49.
            threshold = float(np.exp((1. - weight) * np.log(standard) + weight * np.log(maximum)))
    else:
        weight = (level - 50.) / 50.
        lower = min(minimum, standard)
        threshold = float(np.exp((1. - weight) * np.log(standard) + weight * np.log(lower)))
    threshold = min(threshold, maximum)
    return {index for index in indices if strengths[index] >= threshold}


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
    positional_marker_candidate=None,
    weak_marker_candidates=None,
    phase_marker_levels: dict[str, int] | None = None,
    style: PlotStyle | None = None,
    marker_clearance_pixels: float = 0.0,
) -> tuple[int, int]:
    style = style or PlotStyle()
    positional_evidence = _positional_marker_lines(positional_marker_candidate, style.marker.weak_peak_sensitivity)
    weak_candidates = weak_marker_candidates if weak_marker_candidates is not None else [positional_marker_candidate]
    all_evidence = [item for candidate in weak_candidates
                    if (item := _positional_marker_lines(candidate, 0, all_lines=True)) is not None]
    # Use the trace height, not its stacked absolute offset, so marker spacing
    # remains consistent for every pattern in multi mode.
    y_span = max(float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)), 1.0)
    label_offset = max(y_span * 0.008, 1.0)
    phase_marker_size = max(int(round(style.marker.size * 1.4)), style.marker.size + 3)
    phase_marker_offset = _phase_marker_offset(plot, y_span, phase_marker_size, marker_clearance_pixels)
    corrected_strength = np.asarray(corrected_y, dtype=float)
    noise_sigma = _robust_noise_sigma(corrected_strength)
    grid_step = _positive_grid_step(x)
    peak_strengths = [
        max(float(getattr(observed_peak, "intensity", 0.0)), 0.0)
        for observed_peak in observed_peaks
        if np.isfinite(float(getattr(observed_peak, "intensity", 0.0)))
    ]
    unknown_cutoff = float(np.nanpercentile(peak_strengths, 74)) if peak_strengths else float(np.nanpercentile(observed_y, 74))
    unknown_count = 0
    explained = 0
    unknown_marker_positions: list[float] = []
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
    peak_records = sorted(peak_records, key=lambda item: item[0], reverse=True)
    # Build the entire experimental-maxima catalogue independently of sliders.
    # Scientific assignments/counts remain those of the saved result.
    prepared = []
    scientific_peak_count = len(peak_records)
    for _height, peak, _y_index in peak_records:
        actual = list(getattr(peak, "assignments", []) or [])
        explained += bool(actual)
        standard = actual or _positional_marker_assignment(peak, positional_evidence)
        prepared.append({str(a.candidate_key): a for a in standard})
    # Zero-clipping lowers apparent noise. Use the unclipped trace as well so
    # the catalogue floor and automatic threshold do not follow that artefact.
    catalogue_noise = max(noise_sigma, _robust_noise_sigma(observed_y))
    catalogue, strengths = _complete_marker_catalogue(x=x, strength=corrected_strength,
        noise_sigma=catalogue_noise, peak_records=peak_records,
        prepared=prepared, evidence=all_evidence)
    visible = {key: _visible_phase_maxima(indices, strengths,
                (phase_marker_levels or {}).get(key, 50), catalogue_noise)
               for key, indices in catalogue.items()}
    for record_index, (_peak_height, observed_peak, y_index) in enumerate(peak_records):
        obs_x = float(observed_peak.two_theta)
        marker_y = _local_observed_peak_y(
            x,
            observed_y,
            obs_x,
            y_index,
            float(getattr(observed_peak, "fwhm", 0.0) or 0.0),
            grid_step=grid_step,
        )
        supported = list(prepared[record_index].values())
        assignments = [a for a in supported
                       if record_index in visible.get(str(a.candidate_key), set())]
        status = getattr(getattr(observed_peak, "status", ""), "value", getattr(observed_peak, "status", ""))
        if assignments:
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
                symbol="d" if status == "overlapping" and len(assignments) == len(supported) else style.marker.symbol,
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
        elif not supported:
            # Without an accepted, validated single-phase positional model,
            # retain the scientific assignment's unknown display unchanged.
            if unknown_count >= 10 or _peak_height < unknown_cutoff:
                continue
            if not _marker_position_available(
                unknown_marker_positions,
                obs_x,
                x=x,
                fwhm=float(getattr(observed_peak, "fwhm", 0.0) or 0.0),
                grid_step=grid_step,
            ):
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
            unknown_marker_positions.append(obs_x)
            unknown_count += 1
    return explained, scientific_peak_count


def assignment_marker_label(assignments) -> str:
    labels = []
    for assignment in assignments[:2]:
        hkl = "-".join(str(value) for value in getattr(assignment, "hkl", ()) if value is not None)
        if hkl:
            labels.append(f"({hkl})")
    if len(assignments) > 2 and labels:
        labels[-1] = labels[-1] + "+"
    return " / ".join(labels)
