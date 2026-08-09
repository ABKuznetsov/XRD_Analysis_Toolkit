from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from xrd_finder.ui.plot_view_actions import (
    PhaseFinderPlotViewActionsMixin,
    _apply_axis_appearance,
    _axis_label,
    _x_unit_for_scale,
)
from xrd_finder.ui.plot_view_settings import PlotViewSettings, PlotViewSettingsWidget
from xrd_finder.ui.styled_grid_item import StyledGridItem, build_grid_lines


class AxisUnitFormattingTests(unittest.TestCase):
    def test_empty_unit_has_no_brackets(self) -> None:
        self.assertEqual(_axis_label("2theta", ""), "2theta")

    def test_empty_unit_stays_empty_for_either_x_scale(self) -> None:
        self.assertEqual(_x_unit_for_scale("2theta", ""), "")
        self.assertEqual(_x_unit_for_scale("d", ""), "")

    def test_recognized_default_unit_changes_with_scale(self) -> None:
        self.assertEqual(_x_unit_for_scale("d", "deg"), "A")
        self.assertEqual(_x_unit_for_scale("2theta", "A"), "deg")

    def test_custom_unit_is_preserved(self) -> None:
        self.assertEqual(_x_unit_for_scale("d", "custom"), "custom")

    def test_plot_settings_round_trip_preserves_grid_ticks_and_blank_unit(self) -> None:
        original = PlotViewSettings(
            grid_visible=True,
            grid_color="#123456",
            grid_width=1.75,
            grid_alpha=0.4,
            bottom_axis_unit="",
            top_axis_unit="A",
            tick_length=8,
        )
        restored = PlotViewSettings(**asdict(original))
        self.assertEqual(restored, original)


class AxisUnitWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_scale_change_does_not_refill_cleared_unit(self) -> None:
        widget = PlotViewSettingsWidget()
        widget.bottom_unit_input.clear()
        widget.bottom_scale_combo.setCurrentText("d")
        self.assertEqual(widget.bottom_unit_input.text(), "")
        widget.bottom_scale_combo.setCurrentText("2theta")
        self.assertEqual(widget.bottom_unit_input.text(), "")
        widget.deleteLater()


class StyledGridItemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_build_grid_lines_deduplicates_minor_positions(self) -> None:
        vertical, horizontal = build_grid_lines(
            QRectF(0.0, 0.0, 10.0, 20.0),
            x_levels=[[0.0, 5.0, 10.0], [2.5, 5.0, 7.5]],
            y_levels=[[0.0, 10.0, 20.0], [5.0, 10.0, 15.0]],
        )
        self.assertEqual([line.x1() for line in vertical], [0.0, 2.5, 5.0, 7.5, 10.0])
        self.assertEqual([line.y1() for line in horizontal], [0.0, 5.0, 10.0, 15.0, 20.0])

    def test_configure_applies_exact_pen_style(self) -> None:
        plot = pg.PlotWidget()
        item = StyledGridItem(
            plot.getViewBox(),
            plot.getAxis("bottom"),
            plot.getAxis("left"),
        )
        item.configure(color="#123456", width=1.75, alpha=0.4)
        self.assertEqual(item.pen.color().name(), "#123456")
        self.assertAlmostEqual(item.pen.color().alphaF(), 0.4, places=2)
        self.assertAlmostEqual(item.pen.widthF(), 1.75)
        plot.deleteLater()

    def test_grid_does_not_accept_mouse_buttons(self) -> None:
        plot = pg.PlotWidget()
        item = StyledGridItem(
            plot.getViewBox(),
            plot.getAxis("bottom"),
            plot.getAxis("left"),
        )
        self.assertEqual(item.acceptedMouseButtons(), Qt.MouseButton.NoButton)
        plot.deleteLater()

    def test_refresh_uses_axis_tick_spacing(self) -> None:
        plot = pg.PlotWidget()
        plot.resize(600, 400)
        plot.setXRange(0.0, 10.0, padding=0.0)
        plot.setYRange(0.0, 20.0, padding=0.0)
        plot.getAxis("bottom").setTickSpacing(major=5.0, minor=2.5)
        plot.getAxis("left").setTickSpacing(major=10.0, minor=5.0)
        item = StyledGridItem(
            plot.getViewBox(),
            plot.getAxis("bottom"),
            plot.getAxis("left"),
        )
        item.refresh()
        self.assertGreater(len(item.vertical_lines), 1)
        self.assertGreater(len(item.horizontal_lines), 1)
        plot.deleteLater()


class _PlotViewHarness(PhaseFinderPlotViewActionsMixin):
    def __init__(self) -> None:
        self.match_plot = pg.PlotWidget()
        self._plot_grid_item = None


class PlotAxisGridIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_visible_axis_ticks_point_outward_and_match_axis_pen(self) -> None:
        plot = pg.PlotWidget()
        axis = plot.getAxis("bottom")
        _apply_axis_appearance(
            axis,
            color="#234567",
            width=2.25,
            font=QFont(),
            tick_length=8,
            visible=True,
            values_visible=True,
        )
        self.assertEqual(axis.style["tickLength"], 8)
        self.assertEqual(axis.pen().color().name(), "#234567")
        self.assertAlmostEqual(axis.pen().widthF(), 2.25)
        self.assertEqual(axis.tickPen().color().name(), "#234567")
        self.assertAlmostEqual(axis.tickPen().widthF(), 2.25)
        plot.deleteLater()

    def test_grid_item_is_reused_and_hidden_without_native_grid(self) -> None:
        harness = _PlotViewHarness()
        visible = PlotViewSettings(
            grid_visible=True,
            grid_color="#345678",
            grid_width=1.5,
            grid_alpha=0.35,
        )
        harness._apply_grid_settings(visible)
        first_item = harness._plot_grid_item
        self.assertIsInstance(first_item, StyledGridItem)
        self.assertTrue(first_item.isVisible())
        harness._apply_grid_settings(visible)
        self.assertIs(harness._plot_grid_item, first_item)

        hidden = PlotViewSettings(grid_visible=False)
        harness._apply_grid_settings(hidden)
        self.assertIs(harness._plot_grid_item, first_item)
        self.assertFalse(first_item.isVisible())
        self.assertFalse(harness.match_plot.getAxis("bottom").grid)
        self.assertFalse(harness.match_plot.getAxis("left").grid)
        harness.match_plot.deleteLater()

    def test_custom_grid_is_present_in_offscreen_widget_render(self) -> None:
        plot = pg.PlotWidget()
        plot.resize(640, 420)
        plot.setBackground("#ffffff")
        plot.setXRange(0.0, 10.0, padding=0.0)
        plot.setYRange(0.0, 10.0, padding=0.0)
        plot.getAxis("bottom").setTickSpacing(major=2.0, minor=1.0)
        plot.getAxis("left").setTickSpacing(major=2.0, minor=1.0)
        curve = plot.plot([0.0, 10.0], [0.25, 0.25], pen=pg.mkPen("#000000", width=1.0))
        item = StyledGridItem(plot.getViewBox(), plot.getAxis("bottom"), plot.getAxis("left"))
        item.configure(color="#ff0000", width=2.0, alpha=1.0)
        item.refresh()
        plot.show()
        self.app.processEvents()

        image = QImage(plot.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        plot.render(painter)
        painter.end()

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "grid-smoke.png"
            self.assertTrue(image.save(str(output), "PNG"))
            self.assertGreater(output.stat().st_size, 1000)
        red_pixels = 0
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                color = image.pixelColor(x, y)
                if color.red() > 180 and color.green() < 100 and color.blue() < 100:
                    red_pixels += 1
        self.assertGreater(red_pixels, 20)
        self.assertLess(item.zValue(), curve.zValue())
        plot.close()
        plot.deleteLater()


if __name__ == "__main__":
    unittest.main()
