from __future__ import annotations

import copy
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSize
from PySide6.QtGui import QBrush, QTransform
from PySide6.QtWidgets import QApplication

from .metadata import CanvasItemTag, canvas_item_tag


class UnmarkedCanvasItemError(RuntimeError):
    """Raised when visible plot content has no semantic export tag."""


@dataclass(frozen=True, slots=True)
class CanvasItemSnapshot:
    item: object
    tag: CanvasItemTag
    visible: bool
    z_value: float
    scene_transform: QTransform
    scene_index: int


@dataclass(frozen=True, slots=True)
class _ItemState:
    item: object
    visible: bool
    transform: QTransform
    position: QPointF
    rotation: float
    scale: float
    transform_origin: QPointF


class FrozenCanvas:
    """A read-only view of the current canvas with exact state restoration."""

    def __init__(self, widget) -> None:
        self.widget = widget
        self.plot_item = widget.plotItem
        self.view_box = self.plot_item.vb
        self.scene = widget.scene()
        self.source_rect = QRectF()
        self.plot_item_rect = QRectF()
        self.canvas_size_px = QSize()
        self.view_range: tuple[tuple[float, float], tuple[float, float]] = (
            (0.0, 1.0),
            (0.0, 1.0),
        )
        self.device_pixel_ratio = 1.0
        self.logical_dpi_x = 96
        self.logical_dpi_y = 96
        self.background = QBrush()
        self.items: tuple[CanvasItemSnapshot, ...] = ()
        self._unmarked_visible_items: tuple[object, ...] = ()
        self._original_size = QSize()
        self._original_view_range: list[list[float]] = []
        self._original_auto_range: list[object] = []
        self._original_updates_enabled = True
        self._original_item_states: tuple[_ItemState, ...] = ()
        self._entered = False

    def __enter__(self) -> FrozenCanvas:
        if self._entered:
            raise RuntimeError("FrozenCanvas cannot be entered twice")
        application = QApplication.instance()
        if application is not None:
            application.processEvents()

        self._entered = True
        try:
            self._capture_state()
            self.view_box.disableAutoRange()
            self.widget.setUpdatesEnabled(False)
            return self
        except BaseException:
            self._restore_state()
            self._entered = False
            raise

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            self._restore_state()
        finally:
            self._entered = False
        return False

    def _capture_state(self) -> None:
        self._original_size = QSize(self.widget.size())
        self._original_view_range = copy.deepcopy(self.view_box.viewRange())
        self._original_auto_range = copy.deepcopy(self.view_box.state["autoRange"])
        self._original_updates_enabled = bool(self.widget.updatesEnabled())
        self.canvas_size_px = QSize(self.widget.size())
        self.source_rect = self.widget.mapToScene(self.widget.rect()).boundingRect()
        self.plot_item_rect = QRectF(self.plot_item.boundingRect())
        self.view_range = (
            tuple(float(value) for value in self._original_view_range[0]),
            tuple(float(value) for value in self._original_view_range[1]),
        )
        self.device_pixel_ratio = float(self.widget.devicePixelRatioF())
        self.logical_dpi_x = int(self.widget.logicalDpiX())
        self.logical_dpi_y = int(self.widget.logicalDpiY())
        background_brush = (
            self.widget.backgroundBrush()
            if hasattr(self.widget, "backgroundBrush")
            else self.scene.backgroundBrush()
        )
        self.background = QBrush(background_brush)

        snapshots: list[CanvasItemSnapshot] = []
        item_states: list[_ItemState] = []
        for scene_index, item in enumerate(self.scene.items()):
            tag = canvas_item_tag(item)
            if tag is None:
                continue
            visible = bool(item.isVisible())
            item_states.append(
                _ItemState(
                    item=item,
                    visible=visible,
                    transform=QTransform(item.transform()),
                    position=QPointF(item.pos()),
                    rotation=float(item.rotation()),
                    scale=float(item.scale()),
                    transform_origin=QPointF(item.transformOriginPoint()),
                )
            )
            snapshots.append(
                CanvasItemSnapshot(
                    item=item,
                    tag=tag,
                    visible=visible,
                    z_value=float(item.zValue()),
                    scene_transform=QTransform(item.sceneTransform()),
                    scene_index=scene_index,
                )
            )
        self.items = tuple(snapshots)
        self._original_item_states = tuple(item_states)
        self._unmarked_visible_items = tuple(
            item
            for item in self.view_box.addedItems
            if canvas_item_tag(item) is None and bool(item.isVisible())
        )

    def _restore_state(self) -> None:
        if not self._entered:
            return
        try:
            for state in self._original_item_states:
                try:
                    state.item.setTransform(QTransform(state.transform))
                    state.item.setTransformOriginPoint(QPointF(state.transform_origin))
                    # pyqtgraph's PlotDataItem narrows the Qt overload to
                    # ``setPos(x, y)``; passing QPointF fails for those items.
                    state.item.setPos(state.position.x(), state.position.y())
                    state.item.setRotation(state.rotation)
                    state.item.setScale(state.scale)
                    state.item.setVisible(state.visible)
                except RuntimeError:
                    continue
            if self._original_view_range:
                self.view_box.setRange(
                    xRange=self._original_view_range[0],
                    yRange=self._original_view_range[1],
                    padding=0.0,
                    update=False,
                    disableAutoRange=False,
                )
            for axis, state in enumerate(self._original_auto_range):
                if state is False:
                    self.view_box.disableAutoRange(axis)
                else:
                    self.view_box.enableAutoRange(axis, enable=state)
            self.widget.resize(self._original_size)
            self.widget.setUpdatesEnabled(self._original_updates_enabled)
            application = QApplication.instance()
            if application is not None:
                application.processEvents()
        finally:
            self._entered = False

    def export_items(self) -> tuple[CanvasItemSnapshot, ...]:
        if self._unmarked_visible_items:
            item = self._unmarked_visible_items[0]
            item_type = f"{type(item).__module__}.{type(item).__qualname__}"
            raise UnmarkedCanvasItemError(f"Unmarked export item: {item_type}")
        return tuple(
            item
            for item in self.items
            if item.visible and item.tag.exportable
        )


def freeze_canvas(widget) -> FrozenCanvas:
    return FrozenCanvas(widget)
