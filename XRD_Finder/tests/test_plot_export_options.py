from __future__ import annotations

import unittest

from xrd_finder.plot_export.options import (
    PlotExportFormat,
    PlotExportOptions,
    SvgTextMode,
)


class PlotExportOptionsTests(unittest.TestCase):
    def test_supported_formats_include_publication_and_raster_outputs(self):
        self.assertEqual(
            tuple(PlotExportFormat),
            (
                PlotExportFormat.SVG,
                PlotExportFormat.PDF,
                PlotExportFormat.PNG,
                PlotExportFormat.TIFF,
                PlotExportFormat.JPG,
            ),
        )

    def test_requested_width_preserves_canvas_aspect(self):
        options = PlotExportOptions.for_canvas(
            PlotExportFormat.SVG,
            canvas_width_px=1200,
            canvas_height_px=800,
            width_mm=180.0,
        )

        self.assertEqual(options.width_mm, 180.0)
        self.assertEqual(options.height_mm, 120.0)
        self.assertEqual(options.svg_text_mode, SvgTextMode.EDITABLE)

    def test_default_canvas_size_is_one_to_one_at_96_ppi(self):
        options = PlotExportOptions.for_canvas(
            PlotExportFormat.SVG,
            canvas_width_px=960,
            canvas_height_px=480,
        )

        self.assertAlmostEqual(options.width_mm, 254.0)
        self.assertAlmostEqual(options.height_mm, 127.0)

    def test_raster_pixel_size_uses_physical_size_and_dpi(self):
        options = PlotExportOptions(PlotExportFormat.PNG, 180.0, 120.0, dpi=600)

        self.assertEqual(options.pixel_size(), (4252, 2835))

    def test_invalid_dimensions_name_the_rejected_field(self):
        for field_name, values in {
            "width_mm": (0.0, -1.0, float("nan"), float("inf")),
            "height_mm": (0.0, -1.0, float("nan"), float("inf")),
        }.items():
            for value in values:
                kwargs = {"width_mm": 180.0, "height_mm": 120.0}
                kwargs[field_name] = value
                with self.subTest(field=field_name, value=value):
                    with self.assertRaisesRegex(ValueError, field_name):
                        PlotExportOptions(PlotExportFormat.PDF, **kwargs)

    def test_dpi_boundaries_are_enforced(self):
        PlotExportOptions(PlotExportFormat.PNG, 180.0, 120.0, dpi=72)
        PlotExportOptions(PlotExportFormat.TIFF, 180.0, 120.0, dpi=2400)

        for dpi in (71, 2401):
            with self.subTest(dpi=dpi):
                with self.assertRaisesRegex(ValueError, "dpi"):
                    PlotExportOptions(PlotExportFormat.PNG, 180.0, 120.0, dpi=dpi)

    def test_jpeg_quality_boundaries_are_enforced(self):
        PlotExportOptions(PlotExportFormat.JPG, 180.0, 120.0, jpeg_quality=1)
        PlotExportOptions(PlotExportFormat.JPG, 180.0, 120.0, jpeg_quality=100)

        for quality in (0, 101):
            with self.subTest(quality=quality):
                with self.assertRaisesRegex(ValueError, "jpeg_quality"):
                    PlotExportOptions(
                        PlotExportFormat.JPG,
                        180.0,
                        120.0,
                        jpeg_quality=quality,
                    )

    def test_canvas_dimensions_must_be_positive(self):
        for width, height, rejected in ((0, 480, "canvas_width_px"), (960, 0, "canvas_height_px")):
            with self.subTest(width=width, height=height):
                with self.assertRaisesRegex(ValueError, rejected):
                    PlotExportOptions.for_canvas(
                        PlotExportFormat.SVG,
                        canvas_width_px=width,
                        canvas_height_px=height,
                    )


if __name__ == "__main__":
    unittest.main()
