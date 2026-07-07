from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtGui import QFont


class XrdViewBox(pg.ViewBox):
    def __init__(self) -> None:
        super().__init__(enableMenu=False)
        self.setMouseMode(pg.ViewBox.RectMode)
        self.setMouseEnabled(x=True, y=True)

    def wheelEvent(self, event, axis=None) -> None:
        delta = event.delta() if hasattr(event, "delta") else event.angleDelta().y()
        factor = 0.9 if delta > 0 else 1.1
        center = self.mapSceneToView(event.scenePos())
        self.scaleBy(x=factor, y=1.0, center=center)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        self.autoRange(padding=0.02)
        event.accept()


def create_xrd_plot_widget() -> pg.PlotWidget:
    plot = pg.PlotWidget(viewBox=XrdViewBox())
    plot.setBackground("w")
    plot.showGrid(x=True, y=True, alpha=0.18)
    plot.setMenuEnabled(False)
    plot.setTitle("", color="#111111", size="13pt")
    for axis_name in ("bottom", "left"):
        axis = plot.getAxis(axis_name)
        axis.setPen(pg.mkPen("#111111", width=1.2))
        axis.setTextPen(pg.mkPen("#111111"))
        axis_font = QFont()
        axis_font.setPointSize(10)
        axis.setTickFont(axis_font)
        axis.setStyle(tickTextOffset=8)
    plot.setLabel("bottom", "2theta", color="#111111", **{"font-size": "12pt"})
    plot.setLabel("left", "I rel.", color="#111111", **{"font-size": "12pt"})
    return plot
