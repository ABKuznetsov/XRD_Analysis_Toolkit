from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class CanvasLayer(StrEnum):
    BACKGROUND = "background"
    GRID = "grid"
    AXES = "axes"
    OBSERVED = "observed"
    CALCULATED_TOTAL = "calculated_total"
    PHASE_PROFILES = "phase_profiles"
    PHYSICAL_BACKGROUND = "physical_background"
    DIFFERENCE = "difference"
    CANDIDATE_PREVIEW = "candidate_preview"
    PHASE_TICKS = "phase_ticks"
    ASSIGNMENT_MARKERS = "assignment_markers"
    UNKNOWN_PEAKS = "unknown_peaks"
    LABELS = "labels"
    CURSOR = "cursor"
    LEGENDS = "legends"


CANVAS_LAYER_ORDER = (
    CanvasLayer.BACKGROUND,
    CanvasLayer.GRID,
    CanvasLayer.AXES,
    CanvasLayer.OBSERVED,
    CanvasLayer.CALCULATED_TOTAL,
    CanvasLayer.PHASE_PROFILES,
    CanvasLayer.PHYSICAL_BACKGROUND,
    CanvasLayer.DIFFERENCE,
    CanvasLayer.CANDIDATE_PREVIEW,
    CanvasLayer.PHASE_TICKS,
    CanvasLayer.ASSIGNMENT_MARKERS,
    CanvasLayer.UNKNOWN_PEAKS,
    CanvasLayer.LABELS,
    CanvasLayer.CURSOR,
    CanvasLayer.LEGENDS,
)


@dataclass(frozen=True, slots=True)
class CanvasItemTag:
    layer: CanvasLayer
    owner_id: str | None = None
    object_id: str | None = None
    exportable: bool = True


def tag_canvas_item(
    item,
    *,
    layer: CanvasLayer | str,
    owner_id: str | None = None,
    object_id: str | None = None,
    exportable: bool = True,
):
    normalized_layer = layer if isinstance(layer, CanvasLayer) else CanvasLayer(str(layer))
    tag = CanvasItemTag(
        layer=normalized_layer,
        owner_id=None if owner_id is None else str(owner_id),
        object_id=None if object_id is None else str(object_id),
        exportable=bool(exportable),
    )
    item._xrd_export_tag = tag
    item._xrd_export_layer = normalized_layer.value
    item._xrd_export_owner_id = tag.owner_id
    item._xrd_export_object_id = tag.object_id
    return item


def canvas_item_tag(item) -> CanvasItemTag | None:
    tag = getattr(item, "_xrd_export_tag", None)
    return tag if isinstance(tag, CanvasItemTag) else None


def stable_svg_id(*parts: str) -> str:
    identity = "\x1f".join(str(part) for part in parts)
    normalized = unicodedata.normalize("NFKD", identity).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"item-{slug}" if slug else "item"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:52]}-{digest}"
