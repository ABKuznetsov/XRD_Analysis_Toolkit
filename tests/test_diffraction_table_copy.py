from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTableWidgetItem

from xrd_finder.ui.compound_card import CopyableTableWidget


class DiffractionTableCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_table(self) -> CopyableTableWidget:
        table = CopyableTableWidget(2, 3)
        table.setHorizontalHeaderLabels(["d [A]", "2theta", "Int."])
        for row, values in enumerate((("1.25", "75.9", "1.5"), ("1.20", "79.8", "0.7"))):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        return table

    def test_copying_a_whole_column_includes_its_header(self):
        table = self.make_table()
        table.selectColumn(1)

        self.assertEqual(table.selected_text(), "2theta\n75.9\n79.8")

    def test_copying_the_whole_table_includes_all_headers(self):
        table = self.make_table()
        table.selectAll()

        self.assertEqual(
            table.selected_text(),
            "d [A]\t2theta\tInt.\n1.25\t75.9\t1.5\n1.20\t79.8\t0.7",
        )

    def test_copy_selection_writes_tsv_to_clipboard(self):
        table = self.make_table()
        table.selectColumn(0)

        table.copy_selection()

        self.assertEqual(QApplication.clipboard().text(), "d [A]\n1.25\n1.20")


if __name__ == "__main__":
    unittest.main()
