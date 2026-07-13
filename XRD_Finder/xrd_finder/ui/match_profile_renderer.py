from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np
from scipy.ndimage import gaussian_filter1d

from xrd_finder.finder import FinderCandidateInput
from xrd_finder.ui.pattern_plot_helpers import add_hkl_labels, plot_peak_intensity_sticks, plot_phase_marker_lane, plot_profile
from xrd_finder.ui.plot_style import PlotStyle



def _tag_plot_item(item, pattern_id: str | None):
    if pattern_id is not None:
        try:
            item._xrd_pattern_id = pattern_id
        except Exception:
            pass
    return item


def _tag_plot_items(items, pattern_id: str | None):
    for item in items:
        _tag_plot_item(item, pattern_id)
    return items


def _tag_new_layer_items(plot_layers: dict[str, list], before_counts: dict[str, int], pattern_id: str | None) -> None:
    for layer, count in before_counts.items():
        _tag_plot_items(plot_layers.get(layer, [])[count:], pattern_id)

def _candidate_iic_value(candidate: dict[str, str], estimate_candidate_iic: Callable[[dict[str, str]], float]) -> float:
    raw_value = candidate.get("I/Ic*", "") or candidate.get("I/Ic", "")
    text = str(raw_value).replace(",", ".").strip()
    if text:
        try:
            value = float(text)
        except ValueError:
            value = 0.0
        if np.isfinite(value) and value > 0.0:
            return value
    return estimate_candidate_iic(candidate)


def _peak_values(value, length: int, default):
    if value is None:
        return [default] * length
    try:
        values = list(value)
    except TypeError:
        values = [value]
    if len(values) < length:
        values.extend([default] * (length - len(values)))
    return values[:length]


def _safe_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, str) and not value.strip():
            return default
        return int(round(float(value)))
    except Exception:
        return default
def build_finder_candidate_inputs(
    candidates: list[dict[str, str]],
    candidate_cif_path: Callable[[dict[str, str]], Path],
    candidate_key: Callable[[dict[str, str]], str],
    candidate_phase_name: Callable[[dict[str, str]], str],
    candidate_source: Callable[[dict[str, str]], str],
) -> tuple[list[FinderCandidateInput], dict[str, dict[str, str]]]:
    finder_candidates = []
    candidate_by_key = {}
    for candidate in candidates:
        try:
            cif_path = candidate_cif_path(candidate)
        except Exception:
            continue
        key = candidate_key(candidate)
        candidate_by_key[key] = candidate
        finder_candidates.append(
            FinderCandidateInput(
                cif_path=str(cif_path),
                entry_id=key,
                name=candidate_phase_name(candidate) or candidate.get("Entry", ""),
                formula=candidate.get("Formula", ""),
                source=candidate_source(candidate),
            )
        )
    return finder_candidates, candidate_by_key


def draw_match_profile_result(
    *,
    result,
    candidate_by_key: dict[str, dict[str, str]],
    match_plot,
    plot_layers: dict[str, list],
    show_all_selected_patterns: bool,
    active_plot_context: dict[str, float],
    pattern_id: str | None = None,
    phase_color: Callable[[dict[str, str], int], str],
    phase_legend_label: Callable[[dict[str, str]], str],
    candidate_key: Callable[[dict[str, str]], str],
    estimate_candidate_iic: Callable[[dict[str, str]], float],
    profile_fit_quality: Callable[[np.ndarray, np.ndarray, np.ndarray], float],
    add_peak_coverage_markers: Callable[..., tuple[int, int]],
    match_scales: dict[str, float],
    match_quantities: dict[str, float],
    match_iic: dict[str, float],
    match_zero_shifts: dict[str, float],
    match_cell_scales: dict[str, float],
    match_alignment_scores: dict[str, str],
    style: PlotStyle | None = None,
    show_hkl_labels: bool = False,
    show_peak_labels: bool = False,
) -> None:
    style = style or PlotStyle()
    x = np.asarray(result.pattern_x, dtype=float)
    background = np.asarray(result.background, dtype=float)
    calculated_total = np.asarray(result.calculated_total, dtype=float)
    observed_y = np.asarray(result.pattern_y, dtype=float)
    observed_ymax = float(np.nanmax(result.pattern_y)) if result.pattern_y else 100.0
    observed_ymin = float(np.nanmin(result.pattern_y)) if result.pattern_y else 0.0
    active_plot_offset = float(active_plot_context.get("offset", 0.0))
    observed_y_plot = observed_y + active_plot_offset
    observed_ymin_plot = observed_ymin + active_plot_offset
    background_plot = background + active_plot_offset
    calculated_total_plot = calculated_total + active_plot_offset
    residual = observed_y - calculated_total
    if len(x) > 2 and len(residual):
        step = float(np.nanmedian(np.diff(x)))
        sigma = max(1.0, min(14.0, float(getattr(result, "fwhm", 0.18) or 0.18) / max(abs(step), 1.0e-6) / 4.0))
        residual = gaussian_filter1d(residual, sigma=sigma, mode="nearest")
    phase_peak_sets: list[tuple[str, str, np.ndarray]] = []
    phase_assignment_styles: dict[str, tuple[str, str]] = {}

    match_scales.clear()
    match_quantities.clear()
    match_iic.clear()
    match_zero_shifts.clear()
    match_cell_scales.clear()
    match_alignment_scores.clear()

    for index, candidate_result in enumerate(result.candidates):
        candidate = candidate_by_key.get(candidate_result.entry_id)
        if candidate is None:
            continue
        key = candidate_key(candidate)
        color = phase_color(candidate, index)
        phase_label = phase_legend_label(candidate)
        phase_assignment_styles[str(candidate_result.candidate_key)] = (color, phase_label)
        profile = np.asarray(candidate_result.profile, dtype=float)
        match_scales[key] = float(candidate_result.scale)
        match_quantities[key] = float(candidate_result.quantity_percent)
        match_iic[key] = _candidate_iic_value(candidate, estimate_candidate_iic)
        match_zero_shifts[key] = float(result.global_zero_shift)
        match_cell_scales[key] = float(candidate_result.cell_scale)
        match_alignment_scores[key] = (
            f"{candidate_result.status} {candidate_result.matched_peaks}/{candidate_result.total_peaks}"
        )
        contribution_item = plot_profile(
            match_plot,
            x,
            background_plot + profile,
            color,
            f"phase {phase_label}",
            width=style.phase.width,
        )
        _tag_plot_item(contribution_item, pattern_id)
        plot_layers["phase_profiles"].append(contribution_item)
        phase_peak_sets.append(
            (
                color,
                phase_label,
                np.asarray(candidate_result.peak_two_theta, dtype=float),
            )
        )
        peak_two_theta_values = _peak_values(candidate_result.peak_two_theta, len(candidate_result.peak_two_theta), 0.0)
        peak_count = len(peak_two_theta_values)
        reference_two_theta_values = _peak_values(
            getattr(candidate_result, "peak_reference_two_theta", None),
            peak_count,
            None,
        )
        intensity_values = _peak_values(getattr(candidate_result, "peak_intensity", None), peak_count, 100.0)
        h_values = _peak_values(getattr(candidate_result, "peak_h", None), peak_count, 0)
        k_values = _peak_values(getattr(candidate_result, "peak_k", None), peak_count, 0)
        l_values = _peak_values(getattr(candidate_result, "peak_l", None), peak_count, 0)
        tick_peaks = []
        for peak_two_theta, reference_two_theta, peak_intensity, h, k, l in zip(
            peak_two_theta_values,
            reference_two_theta_values,
            intensity_values,
            h_values,
            k_values,
            l_values,
        ):
            try:
                two_theta = float(peak_two_theta)
                if not np.isfinite(two_theta):
                    continue
            except Exception:
                continue
            try:
                reference_two_theta = two_theta if reference_two_theta is None else float(reference_two_theta)
            except Exception:
                reference_two_theta = two_theta
            try:
                intensity = float(peak_intensity)
            except Exception:
                intensity = 100.0
            tick_peaks.append(
                SimpleNamespace(
                    two_theta=two_theta,
                    reference_two_theta=reference_two_theta,
                    intensity=max(intensity, 0.0),
                    h=_safe_int(h),
                    k=_safe_int(k),
                    l=_safe_int(l),
                )
            )
        y_span = max(observed_ymax - observed_ymin, observed_ymax, float(active_plot_context.get("height", 0.0)), 1.0)
        profile_height = max(float(np.nanmax(profile)) if len(profile) else 0.0, y_span * 0.035)
        if show_all_selected_patterns:
            preview_baseline = background_plot + index * y_span * 0.025
            preview_height = profile_height
            label_y = preview_baseline
        else:
            preview_baseline = background_plot
            preview_height = profile_height
            shift_lane_height = y_span * 0.045
            shift_lane_gap = shift_lane_height * 0.85
            shift_lane_top = min(observed_ymin_plot, float(np.nanpercentile(background_plot, 5))) - y_span * 0.12
            shift_lane_baseline = shift_lane_top - index * (shift_lane_height + shift_lane_gap)
            shift_items = plot_phase_marker_lane(
                match_plot,
                tick_peaks,
                color,
                shift_lane_baseline,
                shift_lane_height,
                None,
                float(np.nanmin(x) + (np.nanmax(x) - np.nanmin(x)) * 0.005),
            )
            _tag_plot_items(shift_items, pattern_id)
            plot_layers["phase_ticks"].extend(shift_items)
            label_y = preview_baseline
        stick_item = plot_peak_intensity_sticks(
            match_plot,
            tick_peaks,
            color,
            x,
            preview_baseline,
            preview_height,
            f"preview peaks {phase_label}",
            width=style.stick.width,
        )
        _tag_plot_item(stick_item, pattern_id)
        plot_layers["preview_peak_positions"].append(stick_item)
        if show_hkl_labels:
            hkl_items = add_hkl_labels(
                match_plot,
                tick_peaks,
                color,
                label_y,
                preview_height,
                limit=18,
                above_peaks=True,
                x_grid=x,
            )
            _tag_plot_items(hkl_items, pattern_id)
            plot_layers["hkl"].extend(hkl_items)

    background_item = plot_profile(
        match_plot,
        x,
        background_plot,
        style.background.color or "#9aa0a6",
        "background",
        width=style.background.width,
    )
    _tag_plot_item(background_item, pattern_id)
    plot_layers["background"].append(background_item)
    residual_peak = float(np.nanmax(np.abs(residual))) if len(residual) else 0.0
    if residual_peak > 0.0:
        difference_height = y_span * 0.24
        difference_scale = min(1.0, difference_height / max(residual_peak, 1.0e-9))
        difference_baseline = min(observed_ymin_plot, float(np.nanpercentile(background_plot, 5))) - y_span * 0.24
        difference_y = difference_baseline + residual * difference_scale
        difference_item = plot_profile(
            match_plot,
            x,
            difference_y,
            "#6f45a3",
            "difference",
            width=max(style.background.width + 0.4, 1.4),
        )
        _tag_plot_item(difference_item, pattern_id)
        plot_layers["difference"].append(difference_item)
    fit_quality = profile_fit_quality(observed_y, background, calculated_total)
    marker_layer_counts = {layer: len(plot_layers.get(layer, [])) for layer in ("coverage_markers", "peak_labels", "unknown_peaks")}
    explained, total_observed = add_peak_coverage_markers(
        x,
        observed_y_plot,
        np.clip(observed_y - background, 0.0, None),
        phase_peak_sets,
        getattr(result, "observed_peaks", []),
        phase_assignment_styles,
        show_peak_labels=show_peak_labels,
    )
    _tag_new_layer_items(plot_layers, marker_layer_counts, pattern_id)
    sum_item = plot_profile(
        match_plot,
        x,
        calculated_total_plot,
        style.calculated.color or "#0b8043",
        f"calculated total | fit {fit_quality:.0f}% | peaks {explained}/{total_observed}",
        width=style.calculated.width,
    )
    _tag_plot_item(sum_item, pattern_id)
    plot_layers["total_profile"].append(sum_item)
