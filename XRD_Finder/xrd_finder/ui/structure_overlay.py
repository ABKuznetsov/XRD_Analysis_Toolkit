from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from xrd_finder.services.calculated_pattern_service import CU_KA1_WAVELENGTH, calculated_profile_from_peaks
from xrd_finder.ui.pattern_plot_helpers import (
    add_hkl_labels,
    calculate_profile_for_structure,
    plot_peak_intensity_sticks,
    plot_phase_marker_lane,
    plot_profile,
    scale_profile_to_reference,
)
from xrd_finder.ui.peak_matching import PhaseAlignmentEstimate
from xrd_finder.plot_export.metadata import CanvasLayer
from xrd_finder.ui.plot_layer_items import tag_xrd_plot_item
from xrd_finder.ui.plot_style import PlotStyle


@dataclass(slots=True)
class StructureOverlayData:
    x_grid: np.ndarray
    x: np.ndarray
    y: np.ndarray
    peaks: list
    background: np.ndarray
    observed_ymax: float | None
    observed_ymin: float | None
    observed_peak_positions: np.ndarray
    profile_fwhm: float
    alignment: PhaseAlignmentEstimate
    has_observed: bool


def shifted_peaks(peaks, zero_shift: float):
    return [replace(peak, two_theta=float(peak.two_theta) + zero_shift) for peak in peaks]


def prepare_structure_overlay(
    *,
    structure,
    observed,
    calculated_pattern_service,
    estimate_background: Callable[..., np.ndarray],
    observed_peak_positions: Callable[..., np.ndarray],
    estimate_profile_fwhm: Callable[..., float],
    estimate_phase_alignment: Callable[..., PhaseAlignmentEstimate],
) -> StructureOverlayData:
    x_grid = None
    observed_ymax = None
    observed_ymin = None
    peak_positions = np.array([], dtype=float)
    background = None
    profile_fwhm = 0.18

    if observed is not None:
        try:
            x_grid = observed[:, 0]
            observed_ymin = float(np.nanmin(observed[:, 1]))
            observed_ymax = float(np.nanmax(observed[:, 1]))
            background = estimate_background(observed[:, 0], observed[:, 1])
            corrected = np.clip(observed[:, 1] - background, 0.0, None)
            peak_positions = observed_peak_positions(observed[:, 0], corrected)
            profile_fwhm = estimate_profile_fwhm(observed[:, 0], corrected)
        except Exception:
            x_grid = None

    if x_grid is None:
        x_grid = np.linspace(5.0, 120.0, 5000)
    if background is None:
        background = np.zeros_like(x_grid)

    x, y, peaks = calculate_profile_for_structure(
        calculated_pattern_service,
        structure,
        x_grid,
        fwhm=profile_fwhm,
    )
    alignment = estimate_phase_alignment(peaks, peak_positions, structure)
    peaks = shifted_peaks(peaks, alignment.zero_shift)
    wavelength = getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH
    x, y = calculated_profile_from_peaks(peaks, x_grid, fwhm=profile_fwhm, wavelength=wavelength)
    if observed_ymax is not None:
        baseline = float(np.nanpercentile(background, 50))
        y = scale_profile_to_reference(y, max(observed_ymax - baseline, 1.0))
    else:
        y = scale_profile_to_reference(y, 100.0)

    return StructureOverlayData(
        x_grid=np.asarray(x_grid, dtype=float),
        x=np.asarray(x, dtype=float),
        y=np.asarray(y, dtype=float),
        peaks=peaks,
        background=np.asarray(background, dtype=float),
        observed_ymax=observed_ymax,
        observed_ymin=observed_ymin,
        observed_peak_positions=peak_positions,
        profile_fwhm=float(profile_fwhm),
        alignment=alignment,
        has_observed=observed is not None,
    )


def draw_structure_overlay(
    *,
    overlay: StructureOverlayData,
    structure,
    preview: bool,
    match_plot,
    plot_layers: dict[str, list],
    active_plot_context: dict[str, float],
    show_all_selected_patterns: bool,
    show_hkl_labels: bool,
    add_peak_residual_links,
    observed,
    style: PlotStyle | None = None,
    pattern_id: str | None = None,
    candidate_id: str | None = None,
) -> None:
    style = style or PlotStyle()
    color = "#1a73e8" if preview else "#d93025"
    active_plot_offset = float(active_plot_context.get("offset", 0.0))
    marker_top = (
        overlay.observed_ymax + active_plot_offset
        if overlay.observed_ymax is not None
        else float(np.nanmax(overlay.y) if np.nanmax(overlay.y) > 0 else 100.0)
    )
    marker_bottom = (
        overlay.observed_ymin + active_plot_offset
        if overlay.observed_ymin is not None
        else float(np.nanmin(overlay.background) + active_plot_offset)
    )
    y_span = max(marker_top - marker_bottom, float(active_plot_context.get("height", 0.0)), 1.0)

    if overlay.observed_ymax is not None and not preview:
        background_item = plot_profile(
            match_plot,
            overlay.x,
            overlay.background + active_plot_offset,
            style.background.color or "#9aa0a6",
            "background",
            width=max(style.background.width - 0.4, 0.5),
        )
        tag_xrd_plot_item(
            background_item,
            layer=CanvasLayer.CANDIDATE_PREVIEW,
            pattern_id=pattern_id,
            candidate_id=candidate_id,
            object_id="candidate-background",
        )
        plot_layers["calculated_profile"].append(background_item)

    if preview:
        preview_baseline = np.full_like(overlay.x_grid, marker_bottom, dtype=float)
        preview_height = y_span
        stick_item = plot_peak_intensity_sticks(
            match_plot,
            overlay.peaks,
            color,
            overlay.x_grid,
            preview_baseline,
            preview_height,
            f"preview peaks {structure.name}",
            width=style.stick.width,
        )
        tag_xrd_plot_item(
            stick_item,
            layer=CanvasLayer.CANDIDATE_PREVIEW,
            pattern_id=pattern_id,
            candidate_id=candidate_id,
            object_id="candidate-preview-sticks",
        )
        plot_layers["preview_peak_positions"].append(stick_item)
        if show_hkl_labels:
            hkl_items = add_hkl_labels(
                match_plot,
                overlay.peaks,
                color,
                marker_bottom,
                preview_height,
                limit=18,
                above_peaks=True,
            )
            for index, item in enumerate(hkl_items):
                tag_xrd_plot_item(
                    item,
                    layer=CanvasLayer.CANDIDATE_PREVIEW,
                    pattern_id=pattern_id,
                    candidate_id=candidate_id,
                    object_id=f"candidate-preview-hkl-{index}",
                )
            plot_layers["preview_hkl"].extend(hkl_items)
        return

    calc_item = plot_profile(
        match_plot,
        overlay.x,
        overlay.y + overlay.background + active_plot_offset,
        color,
        f"calculated total {structure.name}",
        width=style.calculated.width,
    )
    tag_xrd_plot_item(
        calc_item,
        layer=CanvasLayer.CANDIDATE_PREVIEW,
        pattern_id=pattern_id,
        candidate_id=candidate_id,
        object_id="candidate-calculated-profile",
    )
    plot_layers["calculated_profile"].append(calc_item)
    lane_height = y_span * (0.045 if observed is not None else 0.032)
    lane_baseline = marker_bottom - y_span * (0.13 if observed is not None else 0.18)
    if not show_all_selected_patterns:
        lane_items = plot_phase_marker_lane(
            match_plot,
            overlay.peaks,
            color,
            lane_baseline,
            lane_height,
            None,
            float(np.nanmin(overlay.x) + (np.nanmax(overlay.x) - np.nanmin(overlay.x)) * 0.005),
        )
        for index, item in enumerate(lane_items):
            tag_xrd_plot_item(
                item,
                layer=CanvasLayer.CANDIDATE_PREVIEW,
                pattern_id=pattern_id,
                candidate_id=candidate_id,
                object_id=f"candidate-marker-lane-{index}",
            )
        plot_layers["peak_positions"].extend(lane_items)
    if observed is not None and len(overlay.observed_peak_positions):
        add_peak_residual_links(
            overlay.peaks,
            np.asarray(observed[:, 0], dtype=float),
            np.asarray(observed[:, 1], dtype=float),
            overlay.observed_peak_positions,
            max_delta=0.45,
            limit=36,
            layer="peak_links",
        )
    if show_hkl_labels and not show_all_selected_patterns:
        hkl_items = add_hkl_labels(
            match_plot,
            overlay.peaks,
            color,
            lane_baseline - lane_height * 0.2,
            lane_height,
            limit=18,
        )
        for index, item in enumerate(hkl_items):
            tag_xrd_plot_item(
                item,
                layer=CanvasLayer.LABELS,
                pattern_id=pattern_id,
                candidate_id=candidate_id,
                object_id=f"candidate-hkl-{index}",
            )
        plot_layers["hkl"].extend(hkl_items)
