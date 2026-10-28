"""Temporary device-resolution adjustments; never resize the visible plot."""
from contextlib import contextmanager

import pyqtgraph as pg
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPen, QTransform
from PySide6.QtWidgets import QGraphicsItem


def _scaled_pen(value, factor):
    if not isinstance(value, QPen) or not value.isCosmetic():
        return value
    pen = QPen(value)
    pen.setWidthF((value.widthF() or 1.) * factor)
    return pen


@contextmanager
def export_paint_state(snapshot, painter, logical_scale):
    """Scale pixel-sized content and cosmetic strokes, then restore on errors."""
    items = list(snapshot.scene.items())
    scale = logical_scale * painter.device().devicePixelRatioF()
    modes, dictionaries, attributes, transforms, hidden = [], [], [], [], []
    try:
        for item in items:
            tag = getattr(item, '_xrd_export_tag', None)
            if tag is not None and not tag.exportable and item.isVisible():
                hidden.append(item)
                item.hide()
            if hasattr(item, 'setExportMode'):
                modes.append((item, getattr(item, '_exportOpts', False)))
                # With a high-DPR image resetTransform retains the device
                # scale; applying it here a second time would double symbols.
                item.setExportMode(True, {'antialias': True, 'background': snapshot.background.color(),
                                         'painter': painter, 'resolutionScale': logical_scale})
            options = getattr(item, 'opts', None)
            if isinstance(options, dict):
                for key, value in list(options.items()):
                    if isinstance(value, QPen) and value.isCosmetic():
                        dictionaries.append((options, key, value))
                        options[key] = _scaled_pen(value, scale)
            if isinstance(item, pg.AxisItem):
                attributes.extend((item, name, getattr(item, name))
                                  for name in ('_pen', '_tickPen', 'picture'))
                pen, ticks = item.pen(), item.tickPen()
                item._pen = _scaled_pen(pen, scale)
                item._tickPen = _scaled_pen(ticks, scale)
                item.picture = None
            elif isinstance(getattr(item, '_pen', None), QPen):
                attributes.append((item, '_pen', item._pen))
                item._pen = _scaled_pen(item._pen, scale)

        # PDF has no setDevicePixelRatio. Make transform-independent legend
        # geometry follow the output transform while retaining its screen pose.
        if abs(logical_scale - 1.) > 1.e-9:
            viewport = snapshot.widget.viewportTransform()
            inverse, invertible = viewport.inverted()
            if not invertible:
                raise ValueError('Canvas viewport transformation is not invertible')
            for item in reversed(items):  # parents before children
                flag = QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
                if not item.flags() & flag:
                    continue
                scene_transform = item.deviceTransform(viewport) * inverse
                parent = item.parentItem()
                parent_inverse = parent.sceneTransform().inverted()[0] if parent else QTransform()
                transforms.append((item, item.flags(), item.pos(), item.transform(),
                                   QGraphicsItem.rotation(item), QGraphicsItem.scale(item),
                                   item.transformOriginPoint()))
                item.setFlag(flag, False)
                QGraphicsItem.setPos(item, 0., 0.)
                item.setRotation(0.)
                QGraphicsItem.setScale(item, 1.)
                item.setTransformOriginPoint(QPointF())
                item.setTransform(scene_transform * parent_inverse)
        yield
    finally:
        for item, flags, pos, transform, rotation, scale_value, origin in reversed(transforms):
            item.setFlags(flags)
            QGraphicsItem.setPos(item, pos.x(), pos.y())
            item.setRotation(rotation)
            QGraphicsItem.setScale(item, scale_value)
            item.setTransformOriginPoint(origin)
            item.setTransform(transform)
        for item, name, value in reversed(attributes):
            setattr(item, name, value)
        for options, key, value in reversed(dictionaries):
            options[key] = value
        for item, value in reversed(modes):
            item.setExportMode(value is not False, value if value is not False else None)
        for item in hidden:
            item.show()
