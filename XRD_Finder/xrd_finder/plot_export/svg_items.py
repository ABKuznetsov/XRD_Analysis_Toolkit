"""Item-level SVG adapter derived from pyqtgraph 0.14.0 SVGExporter.

pyqtgraph is distributed under the MIT license.  This adapter intentionally
uses its private item renderer so XRD Phase Finder can place each existing
scene item in a semantic SVG layer without redrawing or recalculating it.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from xml.dom import Node

import pyqtgraph
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor

from .snapshot import CanvasItemSnapshot


SUPPORTED_PYQTGRAPH_VERSION = "0.14.0"


class UnsupportedPlotExporterError(RuntimeError):
    """Raised when the guarded pyqtgraph item SVG API is unavailable."""


class UnsupportedCanvasItemError(RuntimeError):
    """Raised when a tagged semantic item cannot be represented as SVG."""


@dataclass(slots=True)
class SvgItemFragment:
    element: object
    definitions: list[object]
    source_bounds: QRectF

    @property
    def node(self):
        """Compatibility alias used by the adapted IR/Raman serializer."""
        return self.element


def _svg_module():
    detected = str(pyqtgraph.__version__)
    if detected != SUPPORTED_PYQTGRAPH_VERSION:
        raise UnsupportedPlotExporterError(
            f"Layered SVG export supports pyqtgraph {SUPPORTED_PYQTGRAPH_VERSION}; "
            f"detected {detected}"
        )
    module = importlib.import_module("pyqtgraph.exporters.SVGExporter")
    if not hasattr(module, "_generateItemSvg"):
        raise UnsupportedPlotExporterError(
            f"pyqtgraph {detected} item-level SVG API is unavailable"
        )
    return module


def _reset_export_mode(item) -> None:
    pending = [item]
    while pending:
        current = pending.pop()
        pending.extend(current.childItems())
        if hasattr(current, "setExportMode"):
            current.setExportMode(False)


def render_item_svg(
    item_snapshot: CanvasItemSnapshot,
    *,
    root_item,
    canvas_size: tuple[int, int],
) -> SvgItemFragment:
    module = _svg_module()
    options = {
        "width": float(canvas_size[0]),
        "height": float(canvas_size[1]),
        "background": QColor("transparent"),
        "scaling stroke": False,
    }
    try:
        try:
            element, definitions = module._generateItemSvg(
                item_snapshot.item,
                root=root_item,
                options=options,
            )
        except Exception as exc:
            item_type = (
                f"{type(item_snapshot.item).__module__}."
                f"{type(item_snapshot.item).__qualname__}"
            )
            raise UnsupportedCanvasItemError(
                f"Could not export layer {item_snapshot.tag.layer.value}: {item_type}"
            ) from exc
    finally:
        _reset_export_mode(item_snapshot.item)
    return SvgItemFragment(
        element=element,
        definitions=list(definitions),
        source_bounds=QRectF(item_snapshot.item.sceneBoundingRect()),
    )


def _has_descendant(element, tag_name: str) -> bool:
    return bool(element.getElementsByTagName(tag_name))


def split_axis_fragment(
    fragment: SvgItemFragment,
    *,
    grid_enabled: bool,
) -> tuple[SvgItemFragment, SvgItemFragment | None]:
    axis_root = fragment.element.cloneNode(False)
    grid_root = fragment.element.cloneNode(False)
    elements = [
        child
        for child in fragment.element.childNodes
        if child.nodeType == Node.ELEMENT_NODE
    ]
    text_started = False
    for index, child in enumerate(elements):
        contains_text = _has_descendant(child, "text")
        if contains_text:
            text_started = True
        if grid_enabled and index > 0 and not text_started:
            grid_root.appendChild(child.cloneNode(True))
        else:
            axis_root.appendChild(child.cloneNode(True))
    grid_fragment = (
        SvgItemFragment(
            element=grid_root,
            definitions=[],
            source_bounds=QRectF(fragment.source_bounds),
        )
        if any(
            child.nodeType == Node.ELEMENT_NODE
            for child in grid_root.childNodes
        )
        else None
    )
    return (
        SvgItemFragment(
            element=axis_root,
            definitions=fragment.definitions,
            source_bounds=QRectF(fragment.source_bounds),
        ),
        grid_fragment,
    )


def namespace_svg_fragment(element, definitions: list[object], prefix: str) -> None:
    id_mapping: dict[str, str] = {}
    roots = [element, *definitions]
    all_elements = [
        current
        for root in roots
        for current in [root, *root.getElementsByTagName("*")]
    ]
    for current in all_elements:
        if current.hasAttribute("id"):
            old_id = current.getAttribute("id")
            new_id = f"{prefix}-{old_id}"
            id_mapping[old_id] = new_id
            current.setAttribute("id", new_id)
    if not id_mapping:
        return
    for current in all_elements:
        for attribute_name in list(current.attributes.keys()):
            value = current.getAttribute(attribute_name)
            for old_id, new_id in id_mapping.items():
                value = value.replace(f"url(#{old_id})", f"url(#{new_id})")
                value = re.sub(
                    rf"(?<![\w-])#{re.escape(old_id)}(?![\w-])",
                    f"#{new_id}",
                    value,
                )
            current.setAttribute(attribute_name, value)


def namespace_svg_references(element, prefix: str) -> None:
    namespace_svg_fragment(element, [], prefix)
