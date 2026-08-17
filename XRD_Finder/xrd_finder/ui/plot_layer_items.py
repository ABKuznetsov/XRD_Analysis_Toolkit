from __future__ import annotations

from xrd_finder.plot_export.metadata import CanvasLayer, tag_canvas_item


PLOT_LAYER_EXPORT_MAP: dict[str, CanvasLayer] = {
    "observed": CanvasLayer.OBSERVED,
    "total_profile": CanvasLayer.CALCULATED_TOTAL,
    "phase_profiles": CanvasLayer.PHASE_PROFILES,
    "background": CanvasLayer.PHYSICAL_BACKGROUND,
    "difference": CanvasLayer.DIFFERENCE,
    "calculated_profile": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_profile": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_peak_positions": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_peak_links": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_hkl": CanvasLayer.CANDIDATE_PREVIEW,
    "peak_positions": CanvasLayer.CANDIDATE_PREVIEW,
    "peak_links": CanvasLayer.CANDIDATE_PREVIEW,
    "phase_ticks": CanvasLayer.PHASE_TICKS,
    "coverage_markers": CanvasLayer.ASSIGNMENT_MARKERS,
    "candidate_markers": CanvasLayer.ASSIGNMENT_MARKERS,
    "unknown_peaks": CanvasLayer.UNKNOWN_PEAKS,
    "peak_labels": CanvasLayer.LABELS,
    "hkl": CanvasLayer.LABELS,
    "pattern_legends": CanvasLayer.LEGENDS,
    "legend_info": CanvasLayer.LEGENDS,
}


def _owner_id(
    pattern_id: str | None,
    phase_id: str | None,
    candidate_id: str | None,
) -> str | None:
    owner_parts = [
        str(value)
        for value in (pattern_id, phase_id or candidate_id)
        if value is not None and str(value)
    ]
    return "/".join(owner_parts) or None


def tag_xrd_plot_item(
    item,
    *,
    layer: CanvasLayer | str,
    pattern_id: str | None = None,
    phase_id: str | None = None,
    candidate_id: str | None = None,
    object_id: str | None = None,
    exportable: bool = True,
):
    """Attach export metadata without changing item rendering or ownership."""
    if item is None:
        return None
    resolved_pattern = pattern_id if pattern_id is not None else getattr(item, "_xrd_pattern_id", None)
    resolved_phase = phase_id if phase_id is not None else getattr(item, "_xrd_phase_id", None)
    resolved_candidate = (
        candidate_id
        if candidate_id is not None
        else getattr(item, "_xrd_candidate_id", None)
    )
    resolved_object = (
        object_id
        if object_id is not None
        else getattr(item, "_xrd_export_object_id", None)
    )
    if resolved_pattern is not None:
        item._xrd_pattern_id = str(resolved_pattern)
    if resolved_phase is not None:
        item._xrd_phase_id = str(resolved_phase)
    if resolved_candidate is not None:
        item._xrd_candidate_id = str(resolved_candidate)
    return tag_canvas_item(
        item,
        layer=layer,
        owner_id=_owner_id(resolved_pattern, resolved_phase, resolved_candidate),
        object_id=resolved_object,
        exportable=exportable,
    )


def _tag_item_tree(item, *, layer: CanvasLayer, object_id: str) -> None:
    if item is None:
        return
    tag_xrd_plot_item(item, layer=layer, object_id=object_id)
    try:
        children = list(item.childItems())
    except (AttributeError, RuntimeError):
        children = []
    for index, child in enumerate(children):
        _tag_item_tree(
            child,
            layer=layer,
            object_id=f"{object_id}-child-{index}",
        )


def sync_plot_export_tags(
    plot,
    plot_layers: dict[str, list],
    *,
    grid_item=None,
    cursor_item=None,
    legend_item=None,
) -> None:
    """Synchronize the existing XRD layer registry with export semantics."""
    for registry_name, export_layer in PLOT_LAYER_EXPORT_MAP.items():
        for ordinal, item in enumerate(plot_layers.get(registry_name, ())):
            if item is None:
                continue
            try:
                object_id = getattr(item, "_xrd_export_object_id", None)
                tag_xrd_plot_item(
                    item,
                    layer=export_layer,
                    object_id=object_id or f"{registry_name}-{ordinal}",
                )
            except RuntimeError:
                continue

    for axis_name in ("bottom", "left", "top", "right"):
        try:
            axis = plot.getAxis(axis_name)
        except (AttributeError, KeyError, RuntimeError):
            continue
        _tag_item_tree(axis, layer=CanvasLayer.AXES, object_id=f"axis-{axis_name}")

    plot_item = getattr(plot, "plotItem", None)
    title_item = getattr(plot_item, "titleLabel", None)
    if title_item is not None:
        _tag_item_tree(title_item, layer=CanvasLayer.LABELS, object_id="plot-title")
    if grid_item is not None:
        _tag_item_tree(grid_item, layer=CanvasLayer.GRID, object_id="custom-grid")
    if cursor_item is not None:
        _tag_item_tree(cursor_item, layer=CanvasLayer.CURSOR, object_id="vertical-cursor")
    if legend_item is not None:
        _tag_item_tree(legend_item, layer=CanvasLayer.LEGENDS, object_id="main-legend")


def remove_pattern_layer_items(
    match_plot,
    plot_layers: dict[str, list],
    layers,
    pattern_id: str,
) -> int:
    """Remove plot items owned by one XRD pattern and keep every other item."""
    removed = 0
    for layer in layers:
        kept = []
        for item in list(plot_layers.get(layer, [])):
            if getattr(item, "_xrd_pattern_id", None) != pattern_id:
                kept.append(item)
                continue
            try:
                match_plot.removeItem(item)
            except Exception:
                pass
            removed += 1
        plot_layers[layer] = kept
    return removed
