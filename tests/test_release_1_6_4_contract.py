from __future__ import annotations

import json
from pathlib import Path
import tomllib
import unittest

from xrd_finder import __version__
from xrd_finder.finder.fingerprint_matching import MATCH_OBSERVED_LINE_LIMIT
from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY


ROOT = Path(__file__).resolve().parents[1]


class Release164ContractTests(unittest.TestCase):
    def test_release_version_is_consistent(self) -> None:
        self.assertEqual(__version__, "1.6.4")
        self.assertEqual(
            json.loads((ROOT / "app.json").read_text(encoding="utf-8"))["version"],
            "1.6.4",
        )
        with (ROOT / "pyproject.toml").open("rb") as stream:
            self.assertEqual(tomllib.load(stream)["project"]["version"], "1.6.4")

    def test_release_uses_manuscript_match_line_limit(self) -> None:
        self.assertEqual(MATCH_OBSERVED_LINE_LIMIT, 48)

    def test_release_uses_manuscript_gain_combination(self) -> None:
        self.assertEqual(DEFAULT_GAIN_POLICY.evidence_combination, "winner_reliable_direct")
        self.assertEqual(DEFAULT_GAIN_POLICY.winner_overlap_weight, 1.0)
        self.assertEqual(DEFAULT_GAIN_POLICY.corroboration_weight, 0.20)

    def test_windows_update_metadata_points_to_1_6_4_installer(self) -> None:
        metadata = json.loads(
            (ROOT / "launcher" / "updates" / "xrd_finder_windows.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(metadata["version"], "1.6.4")
        self.assertEqual(metadata["platform_versions"]["windows"], "1.6.4")
        self.assertEqual(
            metadata["installer_filename"],
            "XRD_Phase_Finder_Setup_v1_6_4.exe",
        )
        self.assertIn("/v1.6.4/", metadata["installer_url"])

    def test_macos_update_metadata_remains_on_last_built_package(self) -> None:
        metadata = json.loads(
            (ROOT / "launcher" / "updates" / "xrd_finder_macos.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(metadata["version"], "1.6.3")
        self.assertEqual(metadata["platform_versions"]["macos"], "1.6.3")


if __name__ == "__main__":
    unittest.main()
