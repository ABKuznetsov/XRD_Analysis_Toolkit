from __future__ import annotations

import unittest
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
import hashlib

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.io.analysis_summary_builder import build_analysis_summary, result_snapshot


class AnalysisSummaryBuilderTest(unittest.TestCase):
    def test_result_snapshot_identifies_the_actual_cif_content(self) -> None:
        with TemporaryDirectory() as directory:
            cif_path = Path(directory) / "phase.cif"
            cif_path.write_bytes(b"data_phase\n_cell_length_a 8.1\n")
            candidate = {
                "Source": "USER",
                "Entry": "BaSiO3",
                "Phase": "BaSiO3",
                "Formula": "Ba Si O3",
                "_CifPath": str(cif_path),
            }
            result = SimpleNamespace(
                candidates=[SimpleNamespace(entry_id="USER:BaSiO3", quantity_percent=100.0)],
                observed_peaks=[],
            )

            snapshot = result_snapshot(
                result,
                {"USER:BaSiO3": candidate},
                fit_score_percent=100.0,
                explained_peaks=1,
                total_peaks=1,
            )

            self.assertEqual(
                snapshot["phases"][0]["structure_sha256"],
                hashlib.sha256(cif_path.read_bytes()).hexdigest(),
            )

    def test_result_snapshot_uses_calculated_quantities_and_unassigned_peaks(self) -> None:
        candidate = {
            "Source": "USER",
            "Entry": "BaSiO3",
            "Phase": "BaO3Si",
            "_DisplayName": "BaSiO3",
            "Formula": "Ba Si O3",
        }
        result = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    entry_id="USER:BaSiO3",
                    quantity_percent=61.0,
                )
            ],
            observed_peaks=[
                SimpleNamespace(two_theta=31.7, intensity=20.0, assignments=[]),
                SimpleNamespace(two_theta=29.1, intensity=100.0, assignments=[SimpleNamespace()]),
            ],
        )

        snapshot = result_snapshot(
            result,
            {"USER:BaSiO3": candidate},
            fit_score_percent=94.0,
            explained_peaks=52,
            total_peaks=58,
        )

        self.assertEqual(snapshot["phases"][0]["name"], "BaSiO3")
        self.assertEqual(snapshot["phases"][0]["fraction_percent"], 61.0)
        self.assertEqual(snapshot["fit"]["unknown_peak_count"], 1)
        self.assertEqual(snapshot["unknown_peaks"], [
            {"two_theta": 31.7, "intensity": 20.0, "significance": None}
        ])

    def test_shared_phase_is_catalogued_once_and_referenced_by_each_pattern(self) -> None:
        first = Pattern.create("003-00125")
        second = Pattern.create("003-00126")
        project = Project(name="Series", patterns=[first, second])
        shared_phase = {
            "phase_id": "PHASE-1",
            "name": "BaSiO3",
            "formula": "BaSiO3",
            "source": "USER",
            "source_id": "BaSiO3",
            "fraction_percent": 100.0,
        }
        project.finder_state.profile_states = {
            first.id: {"result_snapshot": _snapshot([shared_phase])},
            second.id: {"result_snapshot": _snapshot([shared_phase | {"fraction_percent": None}])},
        }
        project.finder_state.pattern_sample_refs = {
            first.id: {
                "project_uid": "PRJ-1",
                "sample_uid": "SMP-1",
                "sample_code": "003-00125",
            }
        }

        summary = build_analysis_summary(
            project,
            "1.4.0",
            generated_at="2026-08-12T10:30:00Z",
            revision_id="REV-1",
        )

        self.assertEqual(len(summary["phase_catalog"]), 1)
        self.assertEqual(summary["phase_catalog"][0]["phase_id"], "PHASE-1")
        self.assertEqual([item["pattern_id"] for item in summary["patterns"]], sorted([first.id, second.id]))
        by_id = {item["pattern_id"]: item for item in summary["patterns"]}
        self.assertEqual(by_id[first.id]["sample_ref"]["sample_uid"], "SMP-1")
        self.assertIsNone(by_id[second.id]["sample_ref"])
        self.assertEqual(by_id[first.id]["phases"], [{"phase_id": "PHASE-1", "fraction_percent": 100.0}])
        self.assertIsNone(by_id[second.id]["phases"][0]["fraction_percent"])
        self.assertEqual(len(summary["result_sha256"]), 64)

    def test_extracted_preview_mapping_overrides_stale_snapshot_path(self) -> None:
        pattern = Pattern.create("003-00125")
        project = Project(name="Series", patterns=[pattern])
        project.finder_state.profile_states = {
            pattern.id: {
                "result_snapshot": _snapshot([]) | {"preview_path": "old-machine.png"}
            }
        }
        project.finder_state.analysis_preview_paths = {
            pattern.id: "C:/restored/previews/pattern.png"
        }

        summary = build_analysis_summary(
            project,
            "1.4.0",
            generated_at="2026-08-12T10:30:00Z",
            revision_id="REV-1",
        )

        self.assertEqual(
            summary["patterns"][0]["preview_path"],
            "C:/restored/previews/pattern.png",
        )

    def test_same_scientific_state_keeps_revision_but_changed_fraction_creates_one(self) -> None:
        pattern = Pattern.create("Sample")
        project = Project(name="Revision project", patterns=[pattern])
        project.finder_state.profile_states = {
            pattern.id: {
                "result_snapshot": _snapshot(
                    [
                        {
                            "phase_id": "PHASE-1",
                            "name": "BaSiO3",
                            "formula": "BaSiO3",
                            "source": "USER",
                            "source_id": "BaSiO3",
                            "fraction_percent": 100.0,
                        }
                    ]
                )
            }
        }
        first = build_analysis_summary(
            project,
            "1.4.0",
            generated_at="2026-08-12T10:30:00Z",
            revision_id="REV-1",
        )
        project.analysis_summary = first

        unchanged = build_analysis_summary(
            project,
            "1.4.1",
            generated_at="2026-08-12T11:00:00Z",
            revision_id="REV-2",
        )
        self.assertEqual(unchanged["analysis_id"], first["analysis_id"])
        self.assertEqual(unchanged["revision_id"], "REV-1")
        self.assertEqual(unchanged["generated_at"], "2026-08-12T10:30:00Z")

        project.finder_state.profile_states[pattern.id]["result_snapshot"]["phases"][0][
            "fraction_percent"
        ] = 99.0
        changed = build_analysis_summary(
            project,
            "1.4.1",
            generated_at="2026-08-12T11:00:00Z",
            revision_id="REV-2",
        )
        self.assertEqual(changed["analysis_id"], first["analysis_id"])
        self.assertEqual(changed["revision_id"], "REV-2")
        self.assertNotEqual(changed["result_sha256"], first["result_sha256"])


def _snapshot(phases: list[dict]) -> dict:
    return {
        "phases": phases,
        "quantification": {"method": "profile_scale_cell_mass", "is_estimate": True},
        "fit": {"score_percent": 94.0, "explained_peaks": 52, "total_peaks": 58},
        "unknown_peaks": [
            {"two_theta": 31.7, "intensity": 20.0, "significance": None}
        ],
        "preview_path": None,
    }


if __name__ == "__main__":
    unittest.main()
