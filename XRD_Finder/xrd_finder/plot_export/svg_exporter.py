from __future__ import annotations

from collections import defaultdict
from xml.dom import minidom

import pyqtgraph as pg

from .metadata import CANVAS_LAYER_ORDER, CanvasLayer, stable_svg_id
from .options import PlotExportFormat, PlotExportOptions
from .snapshot import CanvasItemSnapshot, FrozenCanvas
from .svg_items import (
    namespace_svg_fragment,
    render_item_svg,
    split_axis_fragment,
)


SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"


_LAYER_LABELS = {
    CanvasLayer.BACKGROUND: "Background",
    CanvasLayer.GRID: "Grid",
    CanvasLayer.AXES: "Axes",
    CanvasLayer.OBSERVED: "Observed",
    CanvasLayer.CALCULATED_TOTAL: "Calculated total",
    CanvasLayer.PHASE_PROFILES: "Phase profiles",
    CanvasLayer.PHYSICAL_BACKGROUND: "Physical background",
    CanvasLayer.DIFFERENCE: "Difference",
    CanvasLayer.CANDIDATE_PREVIEW: "Candidate preview",
    CanvasLayer.PHASE_TICKS: "Phase ticks",
    CanvasLayer.ASSIGNMENT_MARKERS: "Assignment markers",
    CanvasLayer.UNKNOWN_PEAKS: "Unknown peaks",
    CanvasLayer.LABELS: "Labels",
    CanvasLayer.CURSOR: "Cursor",
    CanvasLayer.LEGENDS: "Legends",
}


def _number(value: float) -> str:
    rounded = round(float(value), 8)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:g}"


class LayeredSvgExporter:
    """Serialize the frozen XRD canvas into named editable vector layers."""

    def render(self, snapshot: FrozenCanvas, options: PlotExportOptions) -> bytes:
        if options.format is not PlotExportFormat.SVG:
            raise ValueError("LayeredSvgExporter requires SVG options")
        width = int(snapshot.canvas_size_px.width())
        height = int(snapshot.canvas_size_px.height())
        if width <= 0 or height <= 0:
            raise ValueError("Frozen canvas dimensions must be positive")

        document = minidom.Document()
        root = document.createElement("svg")
        root.setAttribute("xmlns", SVG_NS)
        root.setAttribute("xmlns:inkscape", INKSCAPE_NS)
        root.setAttribute("width", f"{_number(options.width_mm)}mm")
        root.setAttribute("height", f"{_number(options.height_mm)}mm")
        root.setAttribute("viewBox", f"0 0 {width} {height}")
        root.setAttribute("version", "1.1")
        root.setAttribute("data-text-mode", options.svg_text_mode.value)
        document.appendChild(root)
        definitions = document.createElement("defs")
        root.appendChild(definitions)

        rendered: dict[
            CanvasLayer,
            list[tuple[CanvasItemSnapshot | None, object]],
        ] = defaultdict(list)
        background = document.createElement("rect")
        background.setAttribute("x", "0")
        background.setAttribute("y", "0")
        background.setAttribute("width", str(width))
        background.setAttribute("height", str(height))
        color = snapshot.background.color()
        background.setAttribute("fill", color.name())
        background.setAttribute("fill-opacity", _number(color.alphaF()))
        rendered[CanvasLayer.BACKGROUND].append((None, background))

        items = self._top_level_items(snapshot.export_items())
        for item_snapshot in sorted(
            items,
            key=lambda item: (item.z_value, item.scene_index),
        ):
            fragment = render_item_svg(
                item_snapshot,
                root_item=snapshot.plot_item,
                canvas_size=(width, height),
            )
            prefix = stable_svg_id(
                item_snapshot.tag.layer.value,
                item_snapshot.tag.owner_id or "",
                item_snapshot.tag.object_id or type(item_snapshot.item).__name__,
            )
            if isinstance(item_snapshot.item, pg.AxisItem):
                axis_fragment, grid_fragment = split_axis_fragment(
                    fragment,
                    grid_enabled=item_snapshot.item.grid is not False,
                )
                self._register_fragment(
                    document,
                    definitions,
                    rendered,
                    CanvasLayer.AXES,
                    item_snapshot,
                    axis_fragment,
                    f"{prefix}-axis",
                )
                if grid_fragment is not None:
                    self._register_fragment(
                        document,
                        definitions,
                        rendered,
                        CanvasLayer.GRID,
                        item_snapshot,
                        grid_fragment,
                        f"{prefix}-grid",
                    )
                continue
            self._register_fragment(
                document,
                definitions,
                rendered,
                item_snapshot.tag.layer,
                item_snapshot,
                fragment,
                prefix,
            )

        for layer in CANVAS_LAYER_ORDER:
            entries = rendered.get(layer, [])
            if not entries:
                continue
            group = self._group(document, _LAYER_LABELS[layer], layer.value)
            for item_snapshot, node in entries:
                if item_snapshot is None or not item_snapshot.tag.owner_id:
                    group.appendChild(document.importNode(node, True))
                    continue
                self._append_owned_node(
                    document,
                    group,
                    layer,
                    item_snapshot.tag.owner_id,
                    node,
                )
            root.appendChild(group)
        return document.toxml(encoding="utf-8")

    @staticmethod
    def _top_level_items(
        items: tuple[CanvasItemSnapshot, ...],
    ) -> list[CanvasItemSnapshot]:
        by_item = {item.item: item for item in items}
        top_level: list[CanvasItemSnapshot] = []
        for item_snapshot in items:
            parent = item_snapshot.item.parentItem()
            nested = False
            while parent is not None:
                if parent in by_item:
                    nested = True
                    break
                parent = parent.parentItem()
            if not nested:
                top_level.append(item_snapshot)
        return top_level

    @staticmethod
    def _register_fragment(
        document,
        definitions,
        rendered,
        layer,
        item_snapshot,
        fragment,
        prefix: str,
    ) -> None:
        namespace_svg_fragment(fragment.element, fragment.definitions, prefix)
        for definition in fragment.definitions:
            definitions.appendChild(document.importNode(definition.cloneNode(True), True))
        rendered[layer].append((item_snapshot, fragment.element))

    @staticmethod
    def _group(document, label: str, *identity: str, as_layer: bool = True):
        group = document.createElement("g")
        group.setAttribute("id", stable_svg_id(*identity, label))
        if as_layer:
            group.setAttribute("inkscape:groupmode", "layer")
        group.setAttribute("inkscape:label", label)
        return group

    def _append_owned_node(
        self,
        document,
        layer_group,
        layer: CanvasLayer,
        owner_id: str,
        node,
    ) -> None:
        parent = layer_group
        path: list[str] = []
        for owner_part in (part for part in owner_id.split("/") if part):
            path.append(owner_part)
            identity = stable_svg_id(layer.value, *path, "owner")
            owner_group = next(
                (
                    child
                    for child in parent.childNodes
                    if child.nodeType == child.ELEMENT_NODE
                    and child.getAttribute("data-owner-path") == "/".join(path)
                ),
                None,
            )
            if owner_group is None:
                owner_group = self._group(
                    document,
                    owner_part,
                    identity,
                    as_layer=False,
                )
                owner_group.setAttribute("data-owner-path", "/".join(path))
                parent.appendChild(owner_group)
            parent = owner_group
        parent.appendChild(document.importNode(node, True))
