from __future__ import annotations

import os
import unittest
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from xrd_finder.plot_export.metadata import CanvasLayer, tag_canvas_item
from xrd_finder.plot_export.options import (
    PlotExportFormat,
    PlotExportOptions,
    SvgTextMode,
)
from xrd_finder.plot_export.snapshot import freeze_canvas
from xrd_finder.plot_export.svg_exporter import LayeredSvgExporter


SVG_NS = "http://www.w3.org/2000/svg"
NS = {"svg": SVG_NS}


class PlotExportTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _plot(self):
        plot = pg.PlotWidget()
        plot.resize(640, 480)
        plot.setBackground("white")
        plot.setTitle("BaSiO₃ — 900 °C")
        plot.setLabel("bottom", "2theta", units="deg")
        plot.setLabel("left", "I rel.")
        plot.show()
        for name, axis in plot.plotItem.axes.items():
            tag_canvas_item(
                axis["item"],
                layer=CanvasLayer.AXES,
                object_id=f"axis-{name}",
            )
        title = plot.plotItem.titleLabel
        tag_canvas_item(title, layer=CanvasLayer.LABELS, object_id="title")
        curve = plot.plot(
            [10.0, 20.0, 30.0],
            [0.0, 1.0, 0.2],
            pen=pg.mkPen("#111111"),
        )
        tag_canvas_item(
            curve,
            layer=CanvasLayer.OBSERVED,
            owner_id="pattern-1",
            object_id="trace",
        )
        self.app.processEvents()
        return plot

    def _export(self, mode: SvgTextMode):
        plot = self._plot()
        options = PlotExportOptions(
            PlotExportFormat.SVG,
            180.0,
            135.0,
            svg_text_mode=mode,
        )
        with freeze_canvas(plot) as snapshot:
            root = ET.fromstring(LayeredSvgExporter().render(snapshot, options))
        plot.close()
        return root

    def test_editable_mode_preserves_text_and_font_metadata(self):
        root = self._export(SvgTextMode.EDITABLE)
        self.assertEqual(root.attrib["data-text-mode"], "editable")
        self.assertTrue(root.attrib["data-font-families"])
        text = " ".join("".join(element.itertext()) for element in root.findall(".//svg:text", NS))
        self.assertIn("BaSiO", text)
        self.assertIn("2theta", text)

    def test_curve_mode_replaces_text_with_named_vector_paths(self):
        root = self._export(SvgTextMode.CURVES)
        self.assertEqual(root.attrib["data-text-mode"], "curves")
        self.assertEqual(root.findall(".//svg:text", NS), [])
        paths = [
            path
            for path in root.findall(".//svg:path", NS)
            if path.attrib.get("data-source") == "text"
        ]
        self.assertTrue(paths)
        self.assertTrue(
            all(path.attrib.get("id", "").startswith("text-curve-") for path in paths)
        )
        self.assertTrue(all(path.attrib.get("d") for path in paths))


if __name__ == "__main__":
    unittest.main()
