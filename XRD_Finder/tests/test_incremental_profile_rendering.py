from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from xrd_finder.ui.plot_layer_items import remove_pattern_layer_items
from xrd_finder.ui.post_match_pipeline import PostMatchPipeline
from xrd_finder.ui.observed_patterns import (
    clear_observed_file_cache,
    load_observed_file_data,
)


class _PlotItem:
    def __init__(self, pattern_id: str | None) -> None:
        self._xrd_pattern_id = pattern_id


class _Plot:
    def __init__(self) -> None:
        self.removed: list[_PlotItem] = []

    def removeItem(self, item: _PlotItem) -> None:
        self.removed.append(item)


class IncrementalProfileRenderingTests(unittest.TestCase):
    def test_removes_only_items_owned_by_requested_pattern(self) -> None:
        first = _PlotItem("pattern-a")
        second = _PlotItem("pattern-b")
        shared = _PlotItem(None)
        first_marker = _PlotItem("pattern-a")
        layers = {
            "total_profile": [first, second],
            "coverage_markers": [shared, first_marker],
        }
        plot = _Plot()

        removed = remove_pattern_layer_items(
            plot,
            layers,
            ("total_profile", "coverage_markers"),
            "pattern-a",
        )

        self.assertEqual(removed, 2)
        self.assertEqual(plot.removed, [first, first_marker])
        self.assertEqual(layers["total_profile"], [second])
        self.assertEqual(layers["coverage_markers"], [shared])

    def test_post_match_refines_before_single_profile_render(self) -> None:
        calls = []

        def refine(**kwargs):
            calls.append(("cell", kwargs))
            return True

        def profile(**kwargs):
            calls.append(("profile", kwargs))

        pipeline = PostMatchPipeline(
            refresh_selected_profile=profile,
            refine_indexed_cells=refine,
            refresh_gain=lambda: calls.append(("gain", {})),
            should_autozoom=lambda: False,
        )

        pipeline.candidate_added()

        self.assertEqual([name for name, _kwargs in calls], ["cell", "profile", "gain"])
        self.assertFalse(calls[0][1]["recalculate"])
        self.assertTrue(calls[1][1]["active_only"])

    def test_observed_file_cache_survives_source_disconnect(self) -> None:
        clear_observed_file_cache()
        expected = np.asarray([[10.0, 100.0], [11.0, 120.0]])
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "pattern.xy"
            source.write_text("10 100\n11 120\n", encoding="utf-8")
            with patch("xrd_finder.ui.observed_patterns.load_xy", return_value=expected) as loader:
                first = load_observed_file_data(source)
                source.unlink()
                second = load_observed_file_data(source)

        self.assertIs(first, second)
        self.assertEqual(loader.call_count, 1)
        clear_observed_file_cache()


if __name__ == "__main__":
    unittest.main()
