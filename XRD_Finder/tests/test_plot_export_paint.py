from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QImage
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from xrd_finder.plot_export.metadata import CanvasLayer, tag_canvas_item
from xrd_finder.plot_export.options import PlotExportFormat, PlotExportOptions
from xrd_finder.plot_export.paint_exporter import (
    export_frozen_canvas,
    render_preview,
    render_raster,
    write_vector_pdf,
)
from xrd_finder.plot_export.snapshot import freeze_canvas


class _NoGrabPlotWidget(pg.PlotWidget):
    def grab(self, *args, **kwargs):
        raise AssertionError("publication export must not call QWidget.grab()")


class PlotExportPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _plot(self):
        plot = _NoGrabPlotWidget()
        plot.resize(720, 480)
        plot.setBackground("#ffffff")
        plot.show()
        curve = plot.plot(
            [10.0, 20.0, 30.0, 40.0],
            [0.0, 1.0, 0.2, 0.8],
            pen=pg.mkPen("#151515", width=1.0),
        )
        tag_canvas_item(
            curve,
            layer=CanvasLayer.OBSERVED,
            owner_id="pattern-1",
            object_id="trace",
        )
        self.app.processEvents()
        return plot

    @staticmethod
    def _options(format: PlotExportFormat, *, dpi: int = 600) -> PlotExportOptions:
        return PlotExportOptions(
            format=format,
            width_mm=180.0,
            height_mm=120.0,
            dpi=dpi,
            jpeg_quality=87,
        )

    def test_raster_is_painted_at_final_resolution_with_dpi_metadata(self):
        plot = self._plot()

        with freeze_canvas(plot) as snapshot:
            image = render_raster(snapshot, self._options(PlotExportFormat.PNG))

        self.assertEqual((image.width(), image.height()), (4252, 2835))
        self.assertAlmostEqual(image.dotsPerMeterX(), 600 / 0.0254, delta=1)
        self.assertAlmostEqual(image.dotsPerMeterY(), 600 / 0.0254, delta=1)
        self.assertFalse(image.isNull())
        self.assertEqual(image.pixelColor(0, 0).name(), "#ffffff")
        plot.close()

    def test_preview_is_directly_painted_and_bounded(self):
        plot = self._plot()

        with freeze_canvas(plot) as snapshot:
            preview = render_preview(snapshot, QSize(300, 300))

        self.assertEqual((preview.width(), preview.height()), (300, 200))
        self.assertFalse(preview.isNull())
        plot.close()

    def test_png_tiff_and_jpg_writers_preserve_requested_dimensions(self):
        cases = (
            (PlotExportFormat.PNG, ".png", (b"\x89PNG\r\n\x1a\n",)),
            (PlotExportFormat.TIFF, ".tiff", (b"II*\x00", b"MM\x00*")),
            (PlotExportFormat.JPG, ".jpg", (b"\xff\xd8\xff",)),
        )
        plot = self._plot()
        with tempfile.TemporaryDirectory() as temp_dir:
            for format, suffix, signatures in cases:
                with self.subTest(format=format):
                    destination = Path(temp_dir) / f"figure{suffix}"
                    options = PlotExportOptions(format, 25.4, 12.7, dpi=200, jpeg_quality=87)
                    with freeze_canvas(plot) as snapshot:
                        export_frozen_canvas(snapshot, options, destination)
                    self.assertTrue(destination.read_bytes().startswith(signatures))
                    image = QImage(str(destination))
                    self.assertEqual((image.width(), image.height()), (200, 100))
        plot.close()

    def test_suffix_mismatch_keeps_existing_destination(self):
        plot = self._plot()
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "figure.jpg"
            destination.write_bytes(b"keep-me")

            with freeze_canvas(plot) as snapshot:
                with self.assertRaisesRegex(ValueError, "suffix"):
                    export_frozen_canvas(
                        snapshot,
                        self._options(PlotExportFormat.PNG),
                        destination,
                    )

            self.assertEqual(destination.read_bytes(), b"keep-me")
        plot.close()

    def test_failed_encoder_keeps_existing_destination_and_removes_temporary_file(self):
        plot = self._plot()
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "figure.png"
            destination.write_bytes(b"original")

            with patch(
                "xrd_finder.plot_export.paint_exporter._write_raster_image",
                side_effect=RuntimeError("encode failed"),
            ):
                with freeze_canvas(plot) as snapshot:
                    with self.assertRaisesRegex(RuntimeError, "encode failed"):
                        export_frozen_canvas(
                            snapshot,
                            self._options(PlotExportFormat.PNG),
                            destination,
                        )

            self.assertEqual(destination.read_bytes(), b"original")
            self.assertEqual(list(Path(temp_dir).glob(".figure.png.*.tmp")), [])
        plot.close()

    def test_pdf_uses_exact_page_size_without_page_raster(self):
        plot = self._plot()
        data = QByteArray()
        device = QBuffer(data)
        self.assertTrue(device.open(QIODevice.OpenModeFlag.WriteOnly))

        with freeze_canvas(plot) as snapshot:
            write_vector_pdf(snapshot, self._options(PlotExportFormat.PDF), device)
        device.close()

        pdf_bytes = bytes(data)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertNotIn(b"/Subtype /Image", pdf_bytes)
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "figure.pdf"
            destination.write_bytes(pdf_bytes)
            document = QPdfDocument()
            document.load(str(destination))
            size_points = document.pagePointSize(0)
            self.assertAlmostEqual(size_points.width() * 25.4 / 72.0, 180.0, delta=0.2)
            self.assertAlmostEqual(size_points.height() * 25.4 / 72.0, 120.0, delta=0.2)
            document.close()
            del document
            self.app.processEvents()
        plot.close()


if __name__ == "__main__":
    unittest.main()
