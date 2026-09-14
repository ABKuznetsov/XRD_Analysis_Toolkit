from __future__ import annotations

import numpy as np

from xrd_finder.ui.pattern_plot_helpers import add_hkl_labels, plot_peak_intensity_sticks, plot_profile, scale_profile_to_reference
from xrd_finder.plot_export.metadata import CanvasLayer
from xrd_finder.ui.plot_layer_items import tag_xrd_plot_item
from xrd_finder.ui.plot_style import PlotStyle


def draw_rruff_reference(
    *,
    plot,
    plot_layers: dict[str, list],
    data: np.ndarray,
    observed,
    label: str,
    style: PlotStyle | None = None,
    pattern_id: str | None = None,
    candidate_id: str | None = None,
) -> None:
    style = style or PlotStyle()
    reference_color = style.reference.color or "#1a73e8"
    y = np.asarray(data[:, 1], dtype=float)
    if observed is not None and len(observed):
        observed_max = max(float(np.nanmax(observed[:, 1])), 1.0)
        y = scale_profile_to_reference(y, observed_max * 0.92)
    item = plot_profile(
        plot,
        np.asarray(data[:, 0], dtype=float),
        y,
        reference_color,
        f"RRUFF reference {label}",
        width=style.reference.width,
    )
    tag_xrd_plot_item(
        item,
        layer=CanvasLayer.CANDIDATE_PREVIEW,
        pattern_id=pattern_id,
        candidate_id=candidate_id,
        object_id="rruff-reference-profile",
    )
    plot_layers["calculated_profile"].append(item)


def draw_pdf2_reference(
    *,
    plot,
    plot_layers: dict[str, list],
    peaks,
    observed,
    active_plot_context: dict[str, float],
    label: str,
    show_hkl_labels: bool,
    style: PlotStyle | None = None,
    pattern_id: str | None = None,
    candidate_id: str | None = None,
) -> None:
    style = style or PlotStyle()
    reference_color = style.reference.color or "#1a73e8"
    if observed is not None and len(observed):
        x_grid = np.asarray(observed[:, 0], dtype=float)
        active_plot_offset = float(active_plot_context.get("offset", 0.0))
        baseline_value = float(np.nanmin(observed[:, 1])) + active_plot_offset
        top_value = float(np.nanmax(observed[:, 1])) + active_plot_offset
        height = max(top_value - baseline_value, float(active_plot_context.get("height", 0.0)), 1.0)
    else:
        x_grid = np.linspace(5.0, 120.0, 5000)
        baseline_value = 0.0
        height = 100.0

    baseline = np.full_like(x_grid, baseline_value, dtype=float)
    stick_item = plot_peak_intensity_sticks(
        plot,
        peaks,
        reference_color,
        x_grid,
        baseline,
        height,
        f"PDF-2 reference {label}",
        width=style.stick.width,
    )
    tag_xrd_plot_item(
        stick_item,
        layer=CanvasLayer.CANDIDATE_PREVIEW,
        pattern_id=pattern_id,
        candidate_id=candidate_id,
        object_id="pdf2-reference-sticks",
    )
    plot_layers["preview_peak_positions"].append(stick_item)
    hkl_peaks = [peak for peak in peaks if getattr(peak, "h", "") or getattr(peak, "k", "") or getattr(peak, "l", "")]
    if show_hkl_labels and hkl_peaks:
        hkl_items = add_hkl_labels(
            plot,
            hkl_peaks,
            reference_color,
            baseline_value,
            height,
            limit=18,
            above_peaks=True,
        )
        for index, item in enumerate(hkl_items):
            tag_xrd_plot_item(
                item,
                layer=CanvasLayer.CANDIDATE_PREVIEW,
                pattern_id=pattern_id,
                candidate_id=candidate_id,
                object_id=f"pdf2-reference-hkl-{index}",
            )
        plot_layers["preview_hkl"].extend(hkl_items)
