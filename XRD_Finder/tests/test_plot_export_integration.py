from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from xrd_finder.plot_export.metadata import CanvasLayer, tag_canvas_item
from xrd_finder.plot_export.options import PlotExportFormat, PlotExportOptions
from xrd_finder.ui.plot_actions import PhaseFinderPlotActionsMixin


class _Host(QWidget, PhaseFinderPlotActionsMixin):
    def __init__(self) -> None:
        super().__init__()
        self.match_plot = pg.PlotWidget()
        self.match_plot.resize(640, 480)
        self.match_plot.show()
        curve = self.match_plot.plot([10.0, 20.0, 30.0], [0.0, 1.0, 0.2])
        tag_canvas_item(
            curve,
            layer=CanvasLayer.OBSERVED,
            owner_id="pattern-1",
            object_id="trace",
        )
        self.remembered_path = ""

    def _sync_current_plot_export_tags(self) -> None:
        return None

    def _last_directory(self) -> str:
        return tempfile.gettempdir()

    def _remember_directory(self, path: str) -> None:
        self.remembered_path = path


class _AcceptedDialog:
    def __init__(self, snapshot, initial_options, parent=None) -> None:
        self.snapshot = snapshot

    def exec(self):
        return QDialog.DialogCode.Accepted

    def options(self):
        return PlotExportOptions(
            PlotExportFormat.SVG,
            width_mm=180.0,
            height_mm=135.0,
        )


class PlotExportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_export_uses_frozen_canvas_without_grab_resize_or_autorange(self):
        host = _Host()
        self.app.processEvents()
        original_size = host.match_plot.size()
        original_range = host.match_plot.plotItem.vb.viewRange()
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = str(Path(temp_dir) / "figure.svg")
            with (
                patch(
                    "xrd_finder.ui.plot_actions.PlotExportDialog",
                    _AcceptedDialog,
                ),
                patch.object(
                    host.match_plot,
                    "grab",
                    side_effect=AssertionError("grab must not be used"),
                ),
                patch(
                    "xrd_finder.ui.plot_actions.QFileDialog.getSaveFileName",
                    return_value=(destination, "SVG"),
                ),
                patch(
                    "xrd_finder.ui.plot_actions.export_frozen_canvas"
                ) as export,
            ):
                host._export_plot_image()

            export.assert_called_once()
            snapshot, options, path = export.call_args.args
            self.assertEqual(snapshot.canvas_size_px, original_size)
            self.assertEqual(options.format, PlotExportFormat.SVG)
            self.assertEqual(Path(path), Path(destination))
            self.assertEqual(host.match_plot.size(), original_size)
            self.assertEqual(host.match_plot.plotItem.vb.viewRange(), original_range)
        host.close()

    def test_analysis_preview_is_directly_rendered_at_current_canvas_size(self):
        host = _Host()
        self.app.processEvents()
        with patch.object(
            host.match_plot,
            "grab",
            side_effect=AssertionError("grab must not be used"),
        ):
            image = host._publication_plot_image()
        self.assertEqual(image.size(), host.match_plot.size())
        host.close()


if __name__ == "__main__":
    unittest.main()
