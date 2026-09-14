from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

from xrd_finder.ui.project_controls import ProjectControlsWidget


class ProjectControlsCompactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_sidebar_tree_controls_do_not_show_file_actions(self) -> None:
        widget = ProjectControlsWidget()

        buttons = widget.findChildren(QPushButton) + widget.findChildren(QToolButton)
        button_texts = {button.text() for button in buttons if button.text()}

        self.assertIn("Add series", button_texts)
        self.assertIn("Up", button_texts)
        self.assertIn("Down", button_texts)
        self.assertNotIn("New project", button_texts)
        self.assertNotIn("Load project", button_texts)
        self.assertNotIn("Save project", button_texts)
        self.assertNotIn("Save project as...", button_texts)
        self.assertNotIn("Import XRD / CIF", button_texts)


if __name__ == "__main__":
    unittest.main()
