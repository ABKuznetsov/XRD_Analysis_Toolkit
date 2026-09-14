from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from xrd_finder.core.project import Project
from xrd_finder.ui.analysis_windows import PhaseFinderWindow
from xrd_finder.ui.visible_profile_calculation_queue import VisibleProfileCalculationQueue


class VisibleProfileCalculationQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_calculates_each_visible_pattern_once_in_display_order(self) -> None:
        calculated: list[str] = []
        queue = VisibleProfileCalculationQueue(calculated.append)

        queue.schedule(["pattern-a", "pattern-b", "pattern-a", "pattern-c"])
        while queue.is_busy:
            self.app.processEvents()

        self.assertEqual(calculated, ["pattern-a", "pattern-b", "pattern-c"])

    def test_new_patterns_can_be_added_while_queue_is_running(self) -> None:
        calculated: list[str] = []
        queue: VisibleProfileCalculationQueue

        def calculate(pattern_id: str) -> None:
            calculated.append(pattern_id)
            if pattern_id == "pattern-a":
                queue.schedule(["pattern-b", "pattern-c"])

        queue = VisibleProfileCalculationQueue(calculate)
        queue.schedule(["pattern-a", "pattern-b"])
        while queue.is_busy:
            self.app.processEvents()

        self.assertEqual(calculated, ["pattern-a", "pattern-b", "pattern-c"])

    def test_window_queue_calculates_every_displayed_pattern_without_network(self) -> None:
        window = PhaseFinderWindow(Project("Queue test"), defer_initial_plot=True)
        patterns = [
            SimpleNamespace(id="pattern-a", name="A"),
            SimpleNamespace(id="pattern-b", name="B"),
        ]
        calculations: list[tuple[str, bool, bool]] = []
        redraws: list[bool] = []
        window.show_all_selected_patterns = True
        window._patterns_to_display = lambda: patterns
        window._profile_candidates_for_pattern = lambda pattern: [{"Entry": pattern.id}]

        def calculate(pattern, _candidates, *, cache_only=False):
            calculations.append(
                (pattern.id, bool(cache_only), bool(window._suppress_candidate_network))
            )
            return object(), {}

        window._finder_result_for_pattern = calculate
        window._recalculate_match_profile = lambda **kwargs: redraws.append(
            bool(kwargs.get("active_only"))
        )

        window.visible_profile_calculation_queue.schedule(pattern.id for pattern in patterns)
        while window.visible_profile_calculation_queue.is_busy:
            self.app.processEvents()

        self.assertEqual(
            calculations,
            [("pattern-a", False, True), ("pattern-b", False, True)],
        )
        self.assertEqual(redraws, [False, False])
        window.close()


if __name__ == "__main__":
    unittest.main()
