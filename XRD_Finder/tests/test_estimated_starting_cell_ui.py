from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from xrd_finder.ui import match_profile_renderer
from xrd_finder.ui.compound_card import CompoundCardWidget


class EstimatedStartingCellUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_renderer_stores_structured_estimate_on_candidate(self) -> None:
        store = getattr(match_profile_renderer, "_store_estimated_cell_state", None)
        self.assertIsNotNone(store)

        candidate: dict[str, object] = {}
        result = SimpleNamespace(
            estimated_cell={
                "a": 5.12345,
                "b": 5.23456,
                "c": 7.34567,
                "alpha": 90.0,
                "beta": 91.25,
                "gamma": 120.0,
            },
            cell_fit_peaks=9,
            cell_fit_initial_rms_deg=0.148,
            cell_fit_rms_deg=0.031,
        )

        store(candidate, result)

        self.assertEqual(candidate["_EstimatedCell"]["a"], 5.12345)
        self.assertEqual(candidate["_CellFitPeaks"], 9)
        self.assertEqual(candidate["_CellFitRmsDeg"], 0.031)

    def test_reference_card_distinguishes_source_and_estimated_cells(self) -> None:
        card = CompoundCardWidget()
        card.set_candidate(
            {
                "Phase": "Test phase",
                "Cell": "a 5.0; b 5.0; c 7.0; alpha 90; beta 90; gamma 120",
                "_EstimatedCell": {
                    "a": 5.12345,
                    "b": 5.23456,
                    "c": 7.34567,
                    "alpha": 90.0,
                    "beta": 91.25,
                    "gamma": 120.0,
                },
                "_CellFitPeaks": 9,
                "_CellFitInitialRmsDeg": 0.148,
                "_CellFitRmsDeg": 0.031,
            }
        )

        self.assertIn("5.12345", card.labels["Estimated starting cell"].text())
        self.assertIn("9 indexed peaks", card.labels["Cell fit"].text())
        self.assertIn("0.148", card.labels["Cell fit"].text())
        self.assertIn("0.031", card.labels["Cell fit"].text())


if __name__ == "__main__":
    unittest.main()
