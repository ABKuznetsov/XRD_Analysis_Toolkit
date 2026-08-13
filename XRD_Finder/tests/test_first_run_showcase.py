from __future__ import annotations

import json
import unittest
from pathlib import Path


class FirstRunShowcaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]
        cls.showcase_dir = cls.root / "toolkit" / "showcase"
        cls.manifest_path = cls.showcase_dir / "showcase.json"
        cls.module_path = cls.root / "toolkit" / "first_run_showcase.ps1"
        cls.launcher_path = cls.root / "toolkit" / "launch_xrd_finder_preview.ps1"

    def test_assets(self) -> None:
        cards = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [card["title"] for card in cards],
            [
                "Select",
                "Process",
                "Find",
                "Inspect",
                "Compare",
                "Configure",
                "Export and share",
            ],
        )
        for card in cards:
            self.assertTrue((self.showcase_dir / card["image"]).is_file())
            self.assertTrue(card["description"].strip())
        notice = " ".join(str(card.get("notice", "")) for card in cards).lower()
        self.assertIn("window", notice)
        self.assertIn("status bar", notice)

    def test_showcase_module_contract(self) -> None:
        script = self.module_path.read_text(encoding="utf-8")
        for function_name in (
            "Initialize-FirstRunShowcase",
            "Set-ShowcaseMode",
            "Set-ShowcaseInstallationComplete",
            "Save-ShowcaseSeenMarker",
            "Dispose-FirstRunShowcase",
        ):
            self.assertIn(f"function {function_name}", script)
        self.assertIn("Interval = 4500", script)
        self.assertIn("Show-PreviousShowcaseCard", script)
        self.assertIn("Show-NextShowcaseCard", script)
        self.assertIn('$Mode -eq "Ready"', script)
        self.assertIn("showcase-$Version.seen", script)
        self.assertIn("$env:LOCALAPPDATA", script)
        self.assertIn(".Dispose()", script)

    def test_launcher_uses_versioned_ready_showcase(self) -> None:
        launcher = self.launcher_path.read_text(encoding="utf-8")
        self.assertIn("first_run_showcase.ps1", launcher)
        self.assertIn('Test-ShowcaseSeen "1.4.0"', launcher)
        self.assertIn('Initialize-FirstRunShowcase', launcher)
        self.assertIn('-Mode "Ready"', launcher)


if __name__ == "__main__":
    unittest.main()
