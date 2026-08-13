from __future__ import annotations

import unittest
from pathlib import Path


class EnglishStartupCopyTests(unittest.TestCase):
    def test_windows_startup_resources_expose_english_primary_copy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        showcase = (root / "toolkit" / "first_run_showcase.ps1").read_text(encoding="utf-8")
        runtime = (root / "toolkit" / "sci_runtime_setup_ui.ps1").read_text(encoding="utf-8")
        launcher = (root / "toolkit" / "launch_xrd_finder_preview.ps1").read_text(encoding="utf-8")

        self.assertIn("Welcome to XRD Phase Finder", showcase)
        self.assertIn("Launch XRD Phase Finder", showcase)
        self.assertIn("Update or complete installation", runtime)
        self.assertIn("The scientific environment could not be prepared", runtime)
        self.assertIn("Environment setup required", launcher)
        self.assertIn("Installation was cancelled by the user", launcher)


if __name__ == "__main__":
    unittest.main()
