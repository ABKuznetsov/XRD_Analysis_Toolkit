"""Display-only hkl selection and small vertical label adjustments."""
from __future__ import annotations

import json
import math
import weakref

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt


def primary_hkl_peaks(peaks):
    """Keep one annotation per hkl, at its lowest-angle spectral component.

    Callers supply just one phase. Never merge different hkl at the same angle
    or change the reflection list used for profiles and sticks.
    """
    primary = {}
    for peak in peaks:
        hkl = tuple(getattr(peak, name, None) for name in ('h', 'k', 'l'))
        if any(value in (None, '') for value in hkl) or not any(hkl):
            continue
        position = float(peak.two_theta)
        if not math.isfinite(position):
            continue
        previous = primary.get(hkl)
        if previous is None or position < float(previous.two_theta):
            primary[hkl] = peak
    return list(primary.values())


class HklLabelItem(pg.TextItem):
    MAX_OFFSET_PX = 60.

    def __init__(self, *args, plot, hkl, **kwargs):
        self._plot_ref = weakref.ref(plot)
        self._hkl = tuple(hkl)
        self._pattern_id = None
        self._offset_key = None
        self._offset_px = 0.
        self._base_y = None
        self._drag_start = None
        self._placing = False
        super().__init__(*args, **kwargs)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip('Drag up or down to separate hkl labels')

    def set_label_origin(self, x, y, *, pattern_id=None, phase_id=None):
        self._base_y = float(y)
        self.setPos(float(x), self._base_y)
        self._pattern_id = pattern_id
        self._offset_key = json.dumps([str(phase_id), *self._hkl]) if phase_id else None
        state = self._offset_state()
        if state is not None:
            try:
                saved = float(state.get(self._offset_key, 0.))
            except (ValueError, TypeError):
                saved = 0.
            self._offset_px = max(-self.MAX_OFFSET_PX, min(self.MAX_OFFSET_PX, saved)) if math.isfinite(saved) else 0.
        self._apply_offset()

    def _offset_state(self):
        plot = self._plot_ref()
        provider = getattr(plot, 'hkl_label_offset_state', None)
        return provider(self._pattern_id) if callable(provider) and self._pattern_id and self._offset_key else None

    def _apply_offset(self):
        parent = self.parentItem()
        if self._placing or self._base_y is None or parent is None:
            return
        self._placing = True
        try:
            base = parent.mapToScene(QPointF(self.pos().x(), self._base_y))
            point = parent.mapFromScene(base + QPointF(0., self._offset_px))
            self.setPos(self.pos().x(), point.y())
        finally:
            self._placing = False

    def updateTransform(self, force=False):
        super().updateTransform(force)
        self._apply_offset()

    def hoverEvent(self, event):
        if not event.isExit():
            event.acceptDrags(Qt.MouseButton.LeftButton)

    def mouseDragEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if event.isStart() or self._drag_start is None:
            down = getattr(event, 'buttonDownScenePos', None)
            start_y = down(Qt.MouseButton.LeftButton).y() if callable(down) else event.scenePos().y()
            self._drag_start = (start_y, self._offset_px)
        start_y, start_offset = self._drag_start
        self._offset_px = max(-self.MAX_OFFSET_PX, min(self.MAX_OFFSET_PX,
            start_offset + event.scenePos().y() - start_y))
        self._apply_offset()
        if event.isFinish():
            self._drag_start = None
            state = self._offset_state()
            if state is not None and state.get(self._offset_key) != self._offset_px:
                state[self._offset_key] = self._offset_px
                changed = getattr(self._plot_ref(), 'hkl_label_offset_changed', None)
                if callable(changed):
                    changed()
        event.accept()
