"""Item-level SVG adapter derived from pyqtgraph 0.14.0 SVGExporter.

pyqtgraph is distributed under the MIT license.  This adapter intentionally
uses its private item renderer so XRD Phase Finder can place each existing
scene item in a semantic SVG layer without redrawing or recalculating it.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from functools import partial
from types import FunctionType
from xml.dom import Node

import pyqtgraph
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QTransform
from PySide6.QtWidgets import QGraphicsItem

from .snapshot import CanvasItemSnapshot
from .text_outlines import painter_path_svg_data


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


def _export_mode_states(item):
    pending = [item]
    states = []
    while pending:
        current = pending.pop()
        pending.extend(current.childItems())
        if hasattr(current, "setExportMode"):
            states.append((current, getattr(current, '_exportOpts', False)))
    return states


def _correct_closed_paths(original, node, definitions, item, options):
    """Let the guarded upstream mapper handle closed Qt paths without losing Z.

    pyqtgraph 0.14 assumes every path token contains x,y. Qt also emits a
    standalone Z for filled/custom scatter symbols. Substitute its equivalent
    closing line while coordinates are mapped, then restore the close command
    so line joins, holes and symbol topology remain unchanged.
    """
    closures = []
    for path in node.getElementsByTagName('path'):
        data = path.getAttribute('d')
        if not re.search('[zZ]', data):
            continue
        tokens = re.sub('([zZ])', r' \1 ', data).split()
        start = None
        indices = []
        for index, token in enumerate(tokens):
            if token.startswith('M'):
                start = token[1:]
            elif token in ('Z', 'z'):
                if start is None:
                    raise ValueError('Closed Qt SVG path has no starting point')
                tokens[index] = 'L' + start
                indices.append(index)
        path.setAttribute('d', ' '.join(tokens))
        closures.append((path, indices))
    original(node, definitions, item, options)
    for path, indices in closures:
        tokens = path.getAttribute('d').split()
        for index in indices:
            tokens[index] = 'Z'
        path.setAttribute('d', ' '.join(tokens))


def _item_generator(module):
    # Rebind the pinned adapter's recursive function to private globals rather
    # than monkey-patching pyqtgraph (other exporters may run in this process).
    namespace = vars(module).copy()
    namespace['correctCoordinates'] = partial(_correct_closed_paths, module.correctCoordinates)
    upstream = module._generateItemSvg
    generate = FunctionType(upstream.__code__, namespace, upstream.__name__,
                            upstream.__defaults__, upstream.__closure__)
    namespace['_generateItemSvg'] = generate
    return generate


def _clip_to_ancestors(fragment, item, root_item, canvas_size):
    """Retain ViewBox clipping when exporting tagged descendants separately."""
    parent = item.parentItem()
    bounds = root_item.boundingRect()
    position = root_item.scenePos()
    mapping = QTransform(canvas_size[0]/bounds.width(), 0., 0.,
                         canvas_size[1]/bounds.height(), -position.x(), -position.y())
    index = 0
    while parent is not None:
        if parent.flags() & QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape:
            document = fragment.element.ownerDocument
            identity = f'ancestor-clip-{index}'
            clip = document.createElement('clipPath')
            clip.setAttribute('id', identity)
            clip.setAttribute('clipPathUnits', 'userSpaceOnUse')
            path = document.createElement('path')
            shape = mapping.map(parent.mapToScene(parent.shape()))
            path.setAttribute('d', painter_path_svg_data(shape))
            clip.appendChild(path)
            fragment.definitions.append(clip)
            wrapper = document.createElement('g')
            wrapper.setAttribute('clip-path', f'url(#{identity})')
            wrapper.appendChild(fragment.element)
            fragment.element = wrapper
            index += 1
        parent = parent.parentItem()
    return fragment


def render_item_svg(
    item_snapshot: CanvasItemSnapshot,
    *,
    root_item,
    canvas_size: tuple[int, int],
) -> SvgItemFragment:
    module = _svg_module()
    states = _export_mode_states(item_snapshot.item)
    options = {
        "width": float(canvas_size[0]),
        "height": float(canvas_size[1]),
        "background": QColor("transparent"),
        "scaling stroke": False,
    }
    try:
        try:
            element, definitions = _item_generator(module)(
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
        for item, value in reversed(states):
            item.setExportMode(value is not False, value if value is not False else None)
    fragment = SvgItemFragment(
        element=element,
        definitions=list(definitions),
        source_bounds=QRectF(item_snapshot.item.sceneBoundingRect()),
    )
    return _clip_to_ancestors(fragment, item_snapshot.item, root_item, canvas_size)


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
