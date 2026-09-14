from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from xrd_finder.ui.candidate_tables import (
    CandidateTableWidget,
    SelectedCandidatesTableWidget,
)


def _row(source: str, entry_id: str, phase: str) -> list[str]:
    return [source, entry_id, "Al2 O3", phase, "R -3 c", "50%", "", ""]


class CandidateTableContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_refresh_preserves_selected_candidate_by_source_and_entry(self) -> None:
        table = CandidateTableWidget(
            [_row("COD", "100", "First"), _row("RRUFF", "R200", "Second")]
        )
        table.selectRow(1)

        table.set_rows(
            [_row("RRUFF", "R200", "Second"), _row("COD", "100", "First")],
            lambda row: row,
        )

        selected = table.selected_row_values()
        self.assertIsNotNone(selected)
        self.assertEqual((selected["Source"], selected["Entry"]), ("RRUFF", "R200"))

    def test_missing_candidate_can_fall_back_to_first_row(self) -> None:
        table = CandidateTableWidget([_row("COD", "100", "First")])
        table.selectRow(0)

        table.set_rows(
            [_row("COD", "200", "Replacement")],
            lambda row: row,
            select_first_if_missing=True,
        )

        self.assertEqual(table.currentRow(), 0)
        self.assertEqual(table.selected_row_values()["Entry"], "200")

    def test_refresh_preserves_scroll_positions(self) -> None:
        rows = [_row("COD", str(index), f"Phase {index}") for index in range(40)]
        table = CandidateTableWidget(rows)
        table.horizontalScrollBar().setRange(0, 500)
        table.verticalScrollBar().setRange(0, 500)
        table.horizontalScrollBar().setValue(73)
        table.verticalScrollBar().setValue(211)

        table.set_rows(list(reversed(rows)), lambda row: row)

        self.assertEqual(table.horizontalScrollBar().value(), 73)
        self.assertEqual(table.verticalScrollBar().value(), 211)

    def test_selected_phase_name_remains_visible_in_narrow_right_panel(self) -> None:
        table = SelectedCandidatesTableWidget()
        table.resize(390, 220)
        table.set_rows(
            [["#d93025", "Strontium boron oxide", "fit 55.9%", "100.0", "3.86"]]
        )
        table.show()
        self.app.processEvents()

        self.assertGreaterEqual(table.columnWidth(1), 80)
        table.close()


if __name__ == "__main__":
    unittest.main()
