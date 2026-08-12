from __future__ import annotations


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
