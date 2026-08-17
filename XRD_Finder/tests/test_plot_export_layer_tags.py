from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6.QtCore import QLineF
from PySide6.QtWidgets import QApplication, QGraphicsLineItem

from xrd_finder.plot_export.metadata import CanvasLayer, canvas_item_tag
from xrd_finder.ui.match_profile_renderer import _tag_plot_item
from xrd_finder.ui.plot_layer_items import sync_plot_export_tags


EXPECTED_LAYER_MAP = {
    "observed": CanvasLayer.OBSERVED,
    "total_profile": CanvasLayer.CALCULATED_TOTAL,
    "phase_profiles": CanvasLayer.PHASE_PROFILES,
    "background": CanvasLayer.PHYSICAL_BACKGROUND,
    "difference": CanvasLayer.DIFFERENCE,
    "calculated_profile": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_profile": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_peak_positions": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_peak_links": CanvasLayer.CANDIDATE_PREVIEW,
    "preview_hkl": CanvasLayer.CANDIDATE_PREVIEW,
    "peak_positions": CanvasLayer.CANDIDATE_PREVIEW,
    "peak_links": CanvasLayer.CANDIDATE_PREVIEW,
    "phase_ticks": CanvasLayer.PHASE_TICKS,
    "coverage_markers": CanvasLayer.ASSIGNMENT_MARKERS,
    "candidate_markers": CanvasLayer.ASSIGNMENT_MARKERS,
    "unknown_peaks": CanvasLayer.UNKNOWN_PEAKS,
    "peak_labels": CanvasLayer.LABELS,
    "hkl": CanvasLayer.LABELS,
    "pattern_legends": CanvasLayer.LEGENDS,
    "legend_info": CanvasLayer.LEGENDS,
}


def _line_item() -> QGraphicsLineItem:
    return QGraphicsLineItem(QLineF(0.0, 0.0, 1.0, 1.0))


class PlotExportLayerTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_current_plot_registry_maps_to_semantic_export_layers(self):
        plot = pg.PlotWidget()
        items = {layer: _line_item() for layer in EXPECTED_LAYER_MAP}
        plot_layers = {layer: [item] for layer, item in items.items()}

        sync_plot_export_tags(plot, plot_layers)

        self.assertEqual(
            {layer: canvas_item_tag(item).layer for layer, item in items.items()},
            EXPECTED_LAYER_MAP,
        )
        plot.close()

    def test_phase_and_candidate_owners_are_nested_below_pattern(self):
        plot = pg.PlotWidget()
        observed = _line_item()
        phase = _line_item()
        preview = _line_item()
        legend = _line_item()
        observed._xrd_pattern_id = "pattern-1"
        phase._xrd_pattern_id = "pattern-1"
        phase._xrd_phase_id = "phase-A"
        preview._xrd_pattern_id = "pattern-1"
        preview._xrd_candidate_id = "candidate-B"
        legend._xrd_pattern_id = "pattern-1"
        plot_layers = {
            "observed": [observed],
            "phase_profiles": [phase],
            "preview_profile": [preview],
            "pattern_legends": [legend],
        }

        sync_plot_export_tags(plot, plot_layers)

        self.assertEqual(canvas_item_tag(observed).owner_id, "pattern-1")
        self.assertEqual(canvas_item_tag(phase).owner_id, "pattern-1/phase-A")
        self.assertEqual(canvas_item_tag(preview).owner_id, "pattern-1/candidate-B")
        self.assertEqual(canvas_item_tag(legend).owner_id, "pattern-1")
        plot.close()

    def test_profile_renderer_retains_stable_phase_and_candidate_ownership(self):
        phase_item = _line_item()
        candidate_item = _line_item()

        _tag_plot_item(
            phase_item,
            "pattern-1",
            phase_id="phase-A",
            object_id="accepted-profile",
        )
        _tag_plot_item(
            candidate_item,
            "pattern-1",
            candidate_id="candidate-B",
            object_id="preview-profile",
        )

        self.assertEqual(phase_item._xrd_pattern_id, "pattern-1")
        self.assertEqual(phase_item._xrd_phase_id, "phase-A")
        self.assertEqual(phase_item._xrd_export_object_id, "accepted-profile")
        self.assertEqual(candidate_item._xrd_candidate_id, "candidate-B")
        self.assertEqual(candidate_item._xrd_export_object_id, "preview-profile")

    def test_registry_fallback_object_ids_are_deterministic(self):
        plot = pg.PlotWidget()
        first = _line_item()
        second = _line_item()
        plot_layers = {"observed": [first, second]}

        sync_plot_export_tags(plot, plot_layers)

        self.assertEqual(canvas_item_tag(first).object_id, "observed-0")
        self.assertEqual(canvas_item_tag(second).object_id, "observed-1")
        plot.close()

    def test_structural_plot_items_receive_export_tags(self):
        plot = pg.PlotWidget()
        grid = _line_item()
        cursor = _line_item()
        legend = _line_item()

        sync_plot_export_tags(
            plot,
            {},
            grid_item=grid,
            cursor_item=cursor,
            legend_item=legend,
        )

        self.assertEqual(canvas_item_tag(grid).layer, CanvasLayer.GRID)
        self.assertEqual(canvas_item_tag(cursor).layer, CanvasLayer.CURSOR)
        self.assertEqual(canvas_item_tag(legend).layer, CanvasLayer.LEGENDS)
        for name in ("bottom", "left", "top", "right"):
            self.assertEqual(canvas_item_tag(plot.getAxis(name)).layer, CanvasLayer.AXES)
        plot.close()


if __name__ == "__main__":
    unittest.main()
