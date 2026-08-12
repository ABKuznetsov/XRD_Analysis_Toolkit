from __future__ import annotations

from copy import deepcopy
import math
import unittest

from xrd_finder.io.analysis_summary import compute_result_sha256, scientific_projection


def _summary() -> dict:
    return {
        "schema_version": 1,
        "analysis_id": "ANL-1",
        "revision_id": "REV-1",
        "generated_at": "2026-08-12T10:30:00Z",
        "producer": {"application": "XRD Phase Finder", "version": "1.4.0"},
        "result_sha256": "stale",
        "phase_catalog": [
            {
                "phase_id": "PHASE-B",
                "name": "BaGeO3",
                "formula": "BaGeO3",
                "source": "USER",
                "source_id": "BaGeO3",
            },
            {
                "phase_id": "PHASE-A",
                "name": "BaSiO3",
                "formula": "BaSiO3",
                "source": "USER",
                "source_id": "BaSiO3",
            },
        ],
        "patterns": [
            {
                "pattern_id": "PAT-B",
                "title": "003-00126",
                "sample_ref": {"sample_uid": "SMP-B", "sample_code": "003-00126"},
                "phases": [
                    {"phase_id": "PHASE-B", "fraction_percent": 39.0},
                    {"phase_id": "PHASE-A", "fraction_percent": 61.0},
                ],
                "quantification": {"method": "profile_scale_cell_mass", "is_estimate": True},
                "fit": {"score_percent": 94.0, "explained_peaks": 52, "total_peaks": 58},
                "unknown_peaks": [
                    {"two_theta": 44.2, "intensity": 12.0, "significance": None},
                    {"two_theta": 31.7, "intensity": 20.0, "significance": None},
                ],
                "preview_path": "previews/PAT-B.png",
            },
            {
                "pattern_id": "PAT-A",
                "title": "003-00125",
                "sample_ref": None,
                "phases": [{"phase_id": "PHASE-A", "fraction_percent": 100.0}],
                "quantification": {"method": "profile_scale_cell_mass", "is_estimate": True},
                "fit": {"score_percent": 96.0, "explained_peaks": 11, "total_peaks": 11},
                "unknown_peaks": [],
                "preview_path": None,
            },
        ],
    }


class AnalysisSummaryHashTest(unittest.TestCase):
    def test_excluded_metadata_and_array_order_do_not_change_result_hash(self) -> None:
        first = _summary()
        second = deepcopy(first)
        second.update(
            analysis_id="ANL-OTHER",
            revision_id="REV-OTHER",
            generated_at="2026-08-13T00:00:00Z",
            producer={"application": "XRD Phase Finder", "version": "1.4.1"},
            result_sha256="different-stale-value",
        )
        second["phase_catalog"].reverse()
        second["phase_catalog"].append(
            {
                "phase_id": "PHASE-UNUSED",
                "name": "Unused",
                "formula": "X",
                "source": "USER",
                "source_id": "unused",
            }
        )
        second["patterns"].reverse()
        second["patterns"][0]["preview_path"] = "previews/new.png"
        second["patterns"][0]["sample_ref"] = {
            "project_uid": "PRJ-2",
            "sample_uid": "SMP-2",
            "sample_code": "renamed",
        }
        second["patterns"][1]["phases"].reverse()
        second["patterns"][1]["unknown_peaks"].reverse()

        self.assertEqual(compute_result_sha256(first), compute_result_sha256(second))

    def test_scientific_value_changes_result_hash(self) -> None:
        first = _summary()
        second = deepcopy(first)
        second["patterns"][0]["phases"][0]["fraction_percent"] = 40.0

        self.assertNotEqual(compute_result_sha256(first), compute_result_sha256(second))

    def test_projection_uses_deterministic_array_order(self) -> None:
        projection = scientific_projection(_summary())

        self.assertEqual([item["phase_id"] for item in projection["phase_catalog"]], ["PHASE-A", "PHASE-B"])
        self.assertEqual([item["pattern_id"] for item in projection["patterns"]], ["PAT-A", "PAT-B"])
        pattern_b = projection["patterns"][1]
        self.assertEqual([item["phase_id"] for item in pattern_b["phases"]], ["PHASE-A", "PHASE-B"])
        self.assertEqual([item["two_theta"] for item in pattern_b["unknown_peaks"]], [31.7, 44.2])
        self.assertNotIn("sample_ref", pattern_b)
        self.assertNotIn("preview_path", pattern_b)

    def test_non_finite_numbers_are_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                summary = _summary()
                summary["patterns"][0]["fit"]["score_percent"] = value
                with self.assertRaises(ValueError):
                    compute_result_sha256(summary)


if __name__ == "__main__":
    unittest.main()
