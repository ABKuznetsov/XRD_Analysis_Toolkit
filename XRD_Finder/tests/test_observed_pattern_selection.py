from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from xrd_finder.ui.observed_pattern_actions import PhaseFinderObservedPatternActionsMixin


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback

    def emit(self) -> None:
        if self.callback is not None:
            self.callback()


class _Curve:
    def __init__(self) -> None:
        self.curve = self
        self.sigClicked = _Signal()
        self.clickable = False

    def setClickable(self, enabled: bool, width: int) -> None:
        self.clickable = bool(enabled and width)


class _Harness(PhaseFinderObservedPatternActionsMixin):
    def __init__(self) -> None:
        self.selected_pattern_ids: list[str] = []

    def _set_active_pattern_from_plot(self, pattern_id: str) -> None:
        self.selected_pattern_ids.append(pattern_id)


class ObservedPatternSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_curve_selection_is_deferred_until_mouse_event_finishes(self) -> None:
        harness = _Harness()
        curve = _Curve()
        harness._make_observed_curve_selectable(curve, "pattern-1")

        curve.sigClicked.emit()
        self.assertTrue(curve.clickable)
        self.assertEqual(harness.selected_pattern_ids, [])

        self.app.processEvents()
        self.assertEqual(harness.selected_pattern_ids, ["pattern-1"])


if __name__ == "__main__":
    unittest.main()
