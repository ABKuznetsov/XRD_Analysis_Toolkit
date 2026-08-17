from __future__ import annotations

import os
import unittest
import xml.etree.ElementTree as ET
from xml.dom import minidom

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from xrd_finder.plot_export.metadata import CanvasLayer, tag_canvas_item
from xrd_finder.plot_export.options import PlotExportFormat, PlotExportOptions
from xrd_finder.plot_export.snapshot import freeze_canvas
from xrd_finder.plot_export.svg_exporter import INKSCAPE_NS, LayeredSvgExporter
from xrd_finder.plot_export.svg_items import namespace_svg_fragment


SVG_NS = "http://www.w3.org/2000/svg"
NS = {"svg": SVG_NS}
COREL_LABEL = f"{{{INKSCAPE_NS}}}label"


class PlotExportSvgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _plot(self):
        plot = pg.PlotWidget()
        plot.resize(640, 480)
        plot.setBackground("#ffffff")
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.show()
        for name, axis in plot.plotItem.axes.items():
            tag_canvas_item(
                axis["item"],
                layer=CanvasLayer.AXES,
                object_id=f"axis-{name}",
            )

        layers = (
            CanvasLayer.OBSERVED,
            CanvasLayer.CALCULATED_TOTAL,
            CanvasLayer.PHASE_PROFILES,
            CanvasLayer.PHYSICAL_BACKGROUND,
            CanvasLayer.DIFFERENCE,
            CanvasLayer.CANDIDATE_PREVIEW,
            CanvasLayer.PHASE_TICKS,
            CanvasLayer.ASSIGNMENT_MARKERS,
            CanvasLayer.UNKNOWN_PEAKS,
            CanvasLayer.LABELS,
            CanvasLayer.CURSOR,
            CanvasLayer.LEGENDS,
        )
        for index, layer in enumerate(layers):
            owner = {
                CanvasLayer.OBSERVED: "pattern-a",
                CanvasLayer.PHASE_PROFILES: "pattern-a/phase-1",
                CanvasLayer.CANDIDATE_PREVIEW: "pattern-a/candidate-7",
                CanvasLayer.LEGENDS: "pattern-a",
            }.get(layer)
            curve = plot.plot(
                [10.0, 20.0, 30.0],
                [index * 0.03, 1.0 + index * 0.03, 0.2 + index * 0.03],
                pen=pg.mkPen(pg.intColor(index), width=1.0),
            )
            tag_canvas_item(
                curve,
                layer=layer,
                owner_id=owner,
                object_id=f"item-{index}",
            )
        self.app.processEvents()
        return plot

    def test_svg_has_ordered_named_corel_layers_and_no_raster_images(self):
        plot = self._plot()
        options = PlotExportOptions(
            PlotExportFormat.SVG,
            width_mm=180.0,
            height_mm=135.0,
        )

        with freeze_canvas(plot) as snapshot:
            svg_bytes = LayeredSvgExporter().render(snapshot, options)

        root = ET.fromstring(svg_bytes)
        top_level_layers = [
            child
            for child in root.findall("./svg:g", NS)
            if child.attrib.get(f"{{{INKSCAPE_NS}}}groupmode") == "layer"
        ]
        self.assertEqual(
            [layer.attrib[COREL_LABEL] for layer in top_level_layers],
            [
                "Background",
                "Grid",
                "Axes",
                "Observed",
                "Calculated total",
                "Phase profiles",
                "Physical background",
                "Difference",
                "Candidate preview",
                "Phase ticks",
                "Assignment markers",
                "Unknown peaks",
                "Labels",
                "Cursor",
                "Legends",
            ],
        )
        labels = [
            group.attrib[COREL_LABEL]
            for group in root.findall(".//svg:g", NS)
            if COREL_LABEL in group.attrib
        ]
        self.assertIn("pattern-a", labels)
        self.assertIn("phase-1", labels)
        self.assertIn("candidate-7", labels)
        self.assertEqual(root.attrib["viewBox"], "0 0 640 480")
        self.assertEqual(root.attrib["width"], "180mm")
        self.assertEqual(root.attrib["height"], "135mm")
        self.assertEqual(root.findall(".//svg:image", NS), [])
        self.assertTrue(
            root.findall(".//svg:path", NS) or root.findall(".//svg:polyline", NS)
        )
        plot.close()

    def test_internal_svg_ids_and_references_are_unique(self):
        plot = self._plot()
        options = PlotExportOptions.for_canvas(
            PlotExportFormat.SVG,
            canvas_width_px=640,
            canvas_height_px=480,
        )
        with freeze_canvas(plot) as snapshot:
            root = ET.fromstring(LayeredSvgExporter().render(snapshot, options))
        ids = [element.attrib["id"] for element in root.iter() if "id" in element.attrib]
        self.assertEqual(len(ids), len(set(ids)))
        plot.close()

    def test_fragment_namespace_rewrites_definition_references(self):
        document = minidom.parseString(
            '<svg><defs><clipPath id="clip"><rect width="1" height="1"/></clipPath></defs>'
            '<g id="curve" clip-path="url(#clip)" href="#clip"/></svg>'
        )
        node = document.getElementsByTagName("g")[0]
        definition = document.getElementsByTagName("clipPath")[0]

        namespace_svg_fragment(node, [definition], "pattern-a")

        self.assertEqual(node.getAttribute("id"), "pattern-a-curve")
        self.assertEqual(node.getAttribute("clip-path"), "url(#pattern-a-clip)")
        self.assertEqual(node.getAttribute("href"), "#pattern-a-clip")
        self.assertEqual(definition.getAttribute("id"), "pattern-a-clip")


if __name__ == "__main__":
    unittest.main()
