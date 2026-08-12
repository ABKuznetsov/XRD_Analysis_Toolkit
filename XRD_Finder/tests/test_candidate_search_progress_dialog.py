from __future__ import annotations

import unittest
from pathlib import Path


class CandidateSearchProgressDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        cls.background_runner = (
            repository_root / "XRD_Finder" / "xrd_finder" / "ui" / "analysis_windows.py"
        ).read_text(encoding="utf-8")
        cls.search_actions = (
            repository_root / "XRD_Finder" / "xrd_finder" / "ui" / "candidate_search_actions.py"
        ).read_text(encoding="utf-8")

    def test_background_runner_supports_a_visible_non_cancelable_progress_dialog(self) -> None:
        self.assertIn("show_progress_dialog: bool = False", self.background_runner)
        self.assertIn("progress_dialog = QProgressDialog", self.background_runner)
        self.assertIn("progress_dialog.setCancelButton(None)", self.background_runner)
        self.assertIn("progress_dialog.close()", self.background_runner)

    def test_all_candidate_search_routes_request_the_progress_dialog(self) -> None:
        self.assertEqual(self.search_actions.count("show_progress_dialog=True"), 3)

    def test_candidate_search_routes_have_distinct_diagnostic_operation_names(self) -> None:
        self.assertEqual(self.search_actions.count('operation_name="match.search.auto"'), 1)
        self.assertEqual(self.search_actions.count('operation_name="match.search.text"'), 1)
        self.assertEqual(self.search_actions.count('operation_name="match.search.elements"'), 1)


if __name__ == "__main__":
    unittest.main()
