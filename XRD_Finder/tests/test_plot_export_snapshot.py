from __future__ import annotations

import copy
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6.QtCore import QLineF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QApplication, QGraphicsLineItem

from xrd_finder.plot_export.metadata import CanvasLayer, tag_canvas_item
from xrd_finder.plot_export.snapshot import UnmarkedCanvasItemError, freeze_canvas


def _transform_values(transform: QTransform) -> tuple[float, ...]:
    return (
        transform.m11(),
        transform.m12(),
        transform.m13(),
        transform.m21(),
        transform.m22(),
        transform.m23(),
        transform.m31(),
        transform.m32(),
        transform.m33(),
    )


class PlotExportSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _plot_with_two_tagged_items(self):
        plot = pg.PlotWidget()
        plot.resize(640, 480)
        plot.setXRange(12.0, 88.0, padding=0.0)
        plot.setYRange(-0.25, 1.75, padding=0.0)
        first = QGraphicsLineItem(QLineF(0.0, 0.0, 1.0, 1.0))
        second = QGraphicsLineItem(QLineF(0.0, 1.0, 1.0, 0.0))
        tag_canvas_item(
            first,
            layer=CanvasLayer.OBSERVED,
            owner_id="pattern-1",
            object_id="trace",
        )
        tag_canvas_item(
            second,
            layer=CanvasLayer.PHASE_PROFILES,
            owner_id="pattern-1/phase-1",
            object_id="trace",
        )
        plot.addItem(first)
        plot.addItem(second)
        first.setPos(2.5, -3.0)
        first.setRotation(7.0)
        second.setVisible(False)
        self.app.processEvents()
        return plot, first, second

    def _capture_state(self, plot, first, second):
        view_box = plot.plotItem.vb
        return {
            "size": plot.size(),
            "range": copy.deepcopy(view_box.viewRange()),
            "auto_range": copy.deepcopy(view_box.state["autoRange"]),
            "updates": plot.updatesEnabled(),
            "first_visible": first.isVisible(),
            "second_visible": second.isVisible(),
            "first_position": first.pos(),
            "first_rotation": first.rotation(),
            "first_scale": first.scale(),
            "first_transform": _transform_values(first.transform()),
        }

    def test_freeze_canvas_restores_state_after_normal_exit(self):
        plot, first, second = self._plot_with_two_tagged_items()
        before = self._capture_state(plot, first, second)

        with freeze_canvas(plot) as snapshot:
            self.assertEqual(snapshot.canvas_size_px.width(), 640)
            self.assertEqual(snapshot.canvas_size_px.height(), 480)
            self.assertEqual(
                snapshot.view_range,
                (tuple(before["range"][0]), tuple(before["range"][1])),
            )
            self.assertEqual(
                {entry.tag.owner_id for entry in snapshot.export_items()},
                {"pattern-1"},
            )
            plot.resize(320, 240)
            plot.plotItem.vb.setRange(
                xRange=(1.0, 2.0),
                yRange=(3.0, 4.0),
                padding=0.0,
            )
            first.setVisible(False)
            second.setVisible(True)
            first.setPos(100.0, 200.0)
            first.setRotation(90.0)
            first.setScale(2.0)
            first.setTransform(QTransform().shear(0.25, 0.0))

        self.assertEqual(self._capture_state(plot, first, second), before)
        plot.close()

    def test_freeze_canvas_restores_state_after_render_failure(self):
        plot, first, second = self._plot_with_two_tagged_items()
        before = self._capture_state(plot, first, second)

        with self.assertRaisesRegex(RuntimeError, "render failed"):
            with freeze_canvas(plot):
                plot.plotItem.vb.setXRange(200.0, 300.0, padding=0.0)
                first.setVisible(False)
                second.setVisible(True)
                first.setPos(-50.0, 75.0)
                first.setRotation(-33.0)
                raise RuntimeError("render failed")

        self.assertEqual(self._capture_state(plot, first, second), before)
        plot.close()

    def test_export_items_reject_visible_unmarked_plot_content(self):
        plot = pg.PlotWidget()
        unmarked = QGraphicsLineItem(QLineF(0.0, 0.0, 1.0, 1.0))
        plot.addItem(unmarked)

        with freeze_canvas(plot) as snapshot:
            with self.assertRaisesRegex(UnmarkedCanvasItemError, "QGraphicsLineItem"):
                snapshot.export_items()

        plot.close()


if __name__ == "__main__":
    unittest.main()
