from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest

from xrd_finder.core.finder_state import FinderProjectState

# The collection helper does not use Qt; make this focused test runnable with
# the supplied Python runtime, which intentionally has no PySide6 installed.
element_filter = ModuleType("xrd_finder.ui.element_filter")
element_filter.element_sort_key = lambda element: element
sys.modules["xrd_finder.ui.element_filter"] = element_filter
plot_view_settings = ModuleType("xrd_finder.ui.plot_view_settings")
plot_view_settings.PlotViewSettings = type("PlotViewSettings", (), {})
sys.modules["xrd_finder.ui.plot_view_settings"] = plot_view_settings
from xrd_finder.ui.project_state_actions import PhaseFinderProjectStateActionsMixin


class CandidateCollectionHarness(PhaseFinderProjectStateActionsMixin):
    def __init__(self, paths: dict[str, Path | None], saved_paths: dict[str, str] | None = None) -> None:
        self.match_candidates: list[dict[str, str]] = []
        self.profile_states: dict[str, dict[str, object]] = {}
        self.paths = paths
        self.local_path_calls: list[str] = []
        self.project = type("Project", (), {"finder_state": FinderProjectState(candidate_cif_paths=saved_paths or {})})()

    def _candidate_key(self, candidate: dict[str, str]) -> str:
        return f"{candidate.get('Source', '')}:{candidate.get('Entry', '')}"

    def _candidate_local_cif_path(self, candidate: dict[str, str]) -> Path | None:
        candidate_key = self._candidate_key(candidate)
        self.local_path_calls.append(candidate_key)
        return self.paths.get(candidate_key)


class PortableCandidateStateTest(unittest.TestCase):
    def test_collects_active_and_profile_candidates_once_and_drops_stale_paths(self) -> None:
        """Fails if shared profile candidates are resolved repeatedly or stale assets survive."""
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            barium_path = tmp_path / "barium.cif"
            calcium_path = tmp_path / "calcium.cif"
            barium_path.write_text("data_barium\n", encoding="utf-8")
            calcium_path.write_text("data_calcium\n", encoding="utf-8")
            paths = {"USER:BaSiO3": barium_path, "COD:123": calcium_path}
            harness = CandidateCollectionHarness(paths, {"USER:Stale": str(tmp_path / "stale.cif")})
            shared = {"Source": "USER", "Entry": "BaSiO3"}
            harness.match_candidates = [shared]
            harness.profile_states = {
                "first": {"candidates": [shared, {"Source": "COD", "Entry": "123"}]},
                "second": {"candidates": [shared]},
            }

            self.assertEqual(
                harness._collect_project_candidate_cif_paths(),
                {"USER:BaSiO3": str(barium_path), "COD:123": str(calcium_path)},
            )
            self.assertEqual(harness.local_path_calls, ["USER:BaSiO3", "COD:123"])

    def test_uses_existing_extracted_path_when_cache_no_longer_has_candidate(self) -> None:
        """Fails if an extracted asset cannot be reused during a later save."""
        with TemporaryDirectory() as directory:
            extracted_path = Path(directory) / "extracted.cif"
            extracted_path.write_text("data_existing\n", encoding="utf-8")
            harness = CandidateCollectionHarness({}, {"MP:mp-1": str(extracted_path)})
            harness.match_candidates = [{"Source": "MP", "Entry": "mp-1"}]

            self.assertEqual(harness._collect_project_candidate_cif_paths(), {"MP:mp-1": str(extracted_path)})

    def test_referenced_candidate_without_readable_cif_raises_phase_specific_error(self) -> None:
        """Fails if save silently drops a used phase whose CIF cannot be embedded."""
        harness = CandidateCollectionHarness({"AFLOW:aflow-1": None})
        harness.profile_states = {"pattern": {"candidates": [{"Source": "AFLOW", "Entry": "aflow-1"}]}}

        with self.assertRaisesRegex(ValueError, r"AFLOW:aflow-1"):
            harness._collect_project_candidate_cif_paths()


if __name__ == "__main__":
    unittest.main()
