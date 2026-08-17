from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from xrd_finder.plot_export.metadata import CanvasLayer, tag_canvas_item
from xrd_finder.plot_export.options import (
    PlotExportFormat,
    PlotExportOptions,
    SvgTextMode,
)
from xrd_finder.plot_export.snapshot import freeze_canvas
from xrd_finder.ui.plot_export_dialog import PlotExportDialog


class PlotExportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _plot(self):
        plot = pg.PlotWidget()
        plot.resize(640, 480)
        plot.setBackground("white")
        plot.show()
        curve = plot.plot([10.0, 20.0, 30.0], [0.0, 1.0, 0.2])
        tag_canvas_item(
            curve,
            layer=CanvasLayer.OBSERVED,
            owner_id="pattern-1",
            object_id="trace",
        )
        self.app.processEvents()
        return plot

    def test_dialog_defaults_to_layered_svg_and_direct_preview(self):
        plot = self._plot()
        initial = PlotExportOptions(
            PlotExportFormat.SVG,
            180.0,
            135.0,
            dpi=600,
            svg_text_mode=SvgTextMode.EDITABLE,
        )
        with freeze_canvas(plot) as snapshot:
            dialog = PlotExportDialog(snapshot, initial)
            dialog.resize(900, 680)
            dialog.show()
            self.app.processEvents()
            options = dialog.options()
            preview = dialog.preview.pixmap()

            self.assertEqual(options.format, PlotExportFormat.SVG)
            self.assertEqual(options.svg_text_mode, SvgTextMode.EDITABLE)
            self.assertAlmostEqual(options.width_mm, 180.0)
            self.assertAlmostEqual(options.height_mm, 135.0)
            self.assertFalse(preview.isNull())
            self.assertAlmostEqual(
                preview.width() / preview.height(),
                4.0 / 3.0,
                places=2,
            )
            self.assertTrue(dialog.svg_text_controls.isVisible())
            self.assertFalse(dialog.dpi_controls.isVisible())
            dialog.close()
        plot.close()

    def test_format_controls_and_dimensions_follow_canvas_aspect(self):
        plot = self._plot()
        initial = PlotExportOptions(
            PlotExportFormat.SVG,
            160.0,
            120.0,
            dpi=600,
        )
        with freeze_canvas(plot) as snapshot:
            dialog = PlotExportDialog(snapshot, initial)
            dialog.show()
            index = dialog.format_combo.findData(PlotExportFormat.TIFF)
            dialog.format_combo.setCurrentIndex(index)
            dialog.width_spin.setValue(200.0)
            self.app.processEvents()

            options = dialog.options()
            self.assertEqual(options.format, PlotExportFormat.TIFF)
            self.assertAlmostEqual(options.height_mm, 150.0)
            self.assertTrue(dialog.dpi_controls.isVisible())
            self.assertFalse(dialog.jpeg_controls.isVisible())
            self.assertFalse(dialog.svg_text_controls.isVisible())
            self.assertIn("4724 × 3543 px", dialog.pixel_size_label.text())
            dialog.close()
        plot.close()


if __name__ == "__main__":
    unittest.main()
