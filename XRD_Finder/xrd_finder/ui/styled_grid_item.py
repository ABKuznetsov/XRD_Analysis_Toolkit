from __future__ import annotations

import math
from collections.abc import Sequence

import pyqtgraph as pg
from PySide6.QtCore import QLineF, QRectF
from PySide6.QtGui import QColor, QPen


def _unique_visible_values(
    levels: Sequence[Sequence[float]],
    lower: float,
    upper: float,
) -> list[float]:
    span = max(abs(upper - lower), 1.0)
    tolerance = span * 1.0e-9
    values: list[float] = []
    for level in levels[:2]:
        for raw_value in level:
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(value) or value < lower - tolerance or value > upper + tolerance:
                continue
            if any(abs(value - existing) <= tolerance for existing in values):
                continue
            values.append(value)
    return sorted(values)


def build_grid_lines(
    view_rect: QRectF,
    *,
    x_levels: Sequence[Sequence[float]],
    y_levels: Sequence[Sequence[float]],
) -> tuple[list[QLineF], list[QLineF]]:
    """Build de-duplicated major and first-minor grid lines."""

    rect = QRectF(view_rect).normalized()
    if rect.width() <= 0.0 or rect.height() <= 0.0:
        return [], []
    x_values = _unique_visible_values(x_levels, rect.left(), rect.right())
    y_values = _unique_visible_values(y_levels, rect.top(), rect.bottom())
    vertical = [QLineF(value, rect.top(), value, rect.bottom()) for value in x_values]
    horizontal = [QLineF(rect.left(), value, rect.right(), value) for value in y_values]
    return vertical, horizontal


class StyledGridItem(pg.GraphicsObject):
    """Grid synchronized with PlotItem axes but rendered with an exact pen."""

    def __init__(self, view_box, x_axis, y_axis) -> None:
        super().__init__()
        self._view_box = view_box
        self._x_axis = x_axis
        self._y_axis = y_axis
        self._view_rect = QRectF()
        self._vertical_lines: list[QLineF] = []
        self._horizontal_lines: list[QLineF] = []
        self._pen = QPen(QColor("#8f969e"))
        self._pen.setWidthF(0.7)
        self._pen.setCosmetic(True)
        self.setZValue(-1000.0)
        self._view_box.addItem(self, ignoreBounds=True)
        self._view_box.sigRangeChanged.connect(self.refresh)
        self.refresh()

    @property
    def pen(self) -> QPen:
        return QPen(self._pen)

    @property
    def vertical_lines(self) -> tuple[QLineF, ...]:
        return tuple(QLineF(line) for line in self._vertical_lines)

    @property
    def horizontal_lines(self) -> tuple[QLineF, ...]:
        return tuple(QLineF(line) for line in self._horizontal_lines)

    def configure(self, *, color: str, width: float, alpha: float) -> None:
        grid_color = QColor(str(color or "").strip())
        if not grid_color.isValid():
            grid_color = QColor("#8f969e")
        grid_color.setAlphaF(max(0.0, min(float(alpha), 1.0)))
        pen = QPen(grid_color)
        pen.setWidthF(max(float(width), 0.1))
        pen.setCosmetic(True)
        self._pen = pen
        self.update()

    @staticmethod
    def _tick_levels(axis, lower: float, upper: float, pixel_size: float) -> list[list[float]]:
        levels = axis.tickValues(lower, upper, max(float(pixel_size), 1.0))
        return [[float(value) for value in values] for _spacing, values in levels[:2]]

    def refresh(self, *_signal_args) -> None:
        try:
            x_range, y_range = self._view_box.viewRange()
            x_min, x_max = sorted((float(x_range[0]), float(x_range[1])))
            y_min, y_max = sorted((float(y_range[0]), float(y_range[1])))
            rect = QRectF(x_min, y_min, x_max - x_min, y_max - y_min)
            x_levels = self._tick_levels(self._x_axis, x_min, x_max, self._view_box.width())
            y_levels = self._tick_levels(self._y_axis, y_min, y_max, self._view_box.height())
            vertical, horizontal = build_grid_lines(rect, x_levels=x_levels, y_levels=y_levels)
        except Exception:
            rect = QRectF()
            vertical = []
            horizontal = []
        self.prepareGeometryChange()
        self._view_rect = rect
        self._vertical_lines = vertical
        self._horizontal_lines = horizontal
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(self._view_rect)

    def paint(self, painter, _option, _widget=None) -> None:
        if not self.isVisible() or self._pen.color().alpha() <= 0:
            return
        painter.setPen(self._pen)
        for line in self._vertical_lines:
            painter.drawLine(line)
        for line in self._horizontal_lines:
            painter.drawLine(line)
