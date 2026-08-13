from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "toolkit" / "setup_sci_env.bat"


class SciRuntimeSetupPolicyTests(unittest.TestCase):
    def test_repair_does_not_delete_or_upgrade_working_packages(self) -> None:
        setup = SETUP_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("repair_sci_metadata.py", setup)
        self.assertNotIn("Remove-Item -LiteralPath '%SCI_ENV%' -Recurse", setup)
        install_line = next(
            line
            for line in setup.splitlines()
            if 'pip install' in line and '"!REQ!"' in line
        )
        self.assertNotIn(" --upgrade ", install_line)

    def test_pip_check_is_diagnostic_after_runtime_self_test_passes(self) -> None:
        setup = SETUP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('"%PYTHON_EXE%" -m pip check >> "%LOG_FILE%" 2>&1', setup)
        self.assertIn("pip check reported metadata or dependency warnings", setup)
        pip_check_tail = setup.split('"%PYTHON_EXE%" -m pip check', 1)[1].splitlines()[:3]
        self.assertFalse(any("goto validation_failed" in line for line in pip_check_tail))


if __name__ == "__main__":
    unittest.main()
