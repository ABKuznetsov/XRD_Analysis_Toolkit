from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np

from xrd_finder.finder import FinderCandidateInput
from xrd_finder.ui.pattern_plot_helpers import plot_phase_marker_lane, plot_profile


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
) -> None:
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
            width=1.5,
        )
        plot_layers["phase_profiles"].append(contribution_item)
        phase_peak_sets.append(
            (
                color,
                phase_label,
                np.asarray(candidate_result.peak_two_theta, dtype=float),
            )
        )
        tick_peaks = [
            SimpleNamespace(
                two_theta=float(peak_two_theta),
                reference_two_theta=float(reference_two_theta),
                intensity=float(peak_intensity),
            )
            for peak_two_theta, reference_two_theta, peak_intensity in zip(
                candidate_result.peak_two_theta,
                candidate_result.peak_reference_two_theta or candidate_result.peak_two_theta,
                candidate_result.peak_intensity or [100.0] * len(candidate_result.peak_two_theta),
            )
        ]
        if not show_all_selected_patterns:
            y_span = max(observed_ymax - observed_ymin, observed_ymax, 1.0)
            lane_height = y_span * 0.038
            lane_gap = lane_height * 0.85
            lane_top = min(observed_ymin_plot, float(np.nanpercentile(background_plot, 5))) - y_span * 0.12
            lane_baseline = lane_top - index * (lane_height + lane_gap)
            lane_items = plot_phase_marker_lane(
                match_plot,
                tick_peaks,
                color,
                lane_baseline,
                lane_height,
                None,
                float(np.nanmin(x) + (np.nanmax(x) - np.nanmin(x)) * 0.005),
            )
            plot_layers["phase_ticks"].extend(lane_items)

    background_item = plot_profile(
        match_plot,
        x,
        background_plot,
        "#9aa0a6",
        "background",
        width=1.2,
    )
    plot_layers["background"].append(background_item)
    fit_quality = profile_fit_quality(observed_y, background, calculated_total)
    explained, total_observed = add_peak_coverage_markers(
        x,
        observed_y_plot,
        np.clip(observed_y - background, 0.0, None),
        phase_peak_sets,
        getattr(result, "observed_peaks", []),
        phase_assignment_styles,
    )
    sum_item = plot_profile(
        match_plot,
        x,
        calculated_total_plot,
        "#0b8043",
        f"calculated total | fit {fit_quality:.0f}% | peaks {explained}/{total_observed}",
        width=1.9,
    )
    plot_layers["total_profile"].append(sum_item)
    match_plot.setTitle("")
