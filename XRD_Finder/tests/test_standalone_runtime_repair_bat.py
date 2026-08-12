from __future__ import annotations

import subprocess
import os
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REPAIR_BAT = REPO_ROOT / "repair_xrd_finder_windows_runtime.bat"


def run_bat(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["XRD_REPAIR_TEST_PYTHON"] = sys.executable
    return subprocess.run(
        ["cmd.exe", "/d", "/c", str(REPAIR_BAT), *arguments],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=environment,
        timeout=30,
        check=False,
    )


class StandaloneRuntimeRepairBatTests(unittest.TestCase):
    def test_describe_reports_complete_mandatory_repair_contract(self) -> None:
        result = run_bat("--describe")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = result.stdout
        self.assertIn(r"SCI_ENV=%LocalAppData%\Sci\env", output)
        self.assertIn("gemmi", output)
        self.assertIn("numpy", output)
        self.assertIn("pybaselines", output)
        self.assertIn("pyqtgraph", output)
        self.assertIn("PySide6==6.7.3", output)
        self.assertIn("scipy", output)
        self.assertIn("certifi", output)
        self.assertIn("pandas>=2,<3", output)
        self.assertIn("mp-api", output)
        self.assertIn("pymatgen", output)
        self.assertIn("MAX_REPAIR_ATTEMPTS=2", output)
        self.assertIn(r"LOCK=%LocalAppData%\Sci\locks\xrd_runtime_repair.lock", output)
        self.assertIn(r"COMPLETE=%LocalAppData%\Sci\runtime_complete.flag", output)

    def test_validator_self_test_runs_without_installing_packages(self) -> None:
        result = run_bat("--self-test-validator")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("VALIDATOR_SELF_TEST_OK", result.stdout)
        self.assertNotIn("pip install", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
