from __future__ import annotations

import re
import unittest
from pathlib import Path


class EnglishStartupCopyTests(unittest.TestCase):
    def test_windows_startup_resources_do_not_contain_cyrillic_copy(self) -> None:
        root = Path(__file__).resolve().parents[2]
        resources = (
            root / "toolkit" / "first_run_showcase.ps1",
            root / "toolkit" / "showcase" / "showcase.json",
            root / "toolkit" / "sci_runtime_setup_ui.ps1",
            root / "toolkit" / "launch_xrd_finder_preview.ps1",
        )

        offenders = []
        for path in resources:
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if re.search(r"[\u0400-\u04ff]", line):
                    offenders.append(f"{path.name}:{line_number}: {line.strip()}")

        self.assertEqual([], offenders, "Cyrillic startup copy remains:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
