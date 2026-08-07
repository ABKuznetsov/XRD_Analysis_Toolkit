from __future__ import annotations

import gc
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
import unittest

from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.phase import Phase
from xrd_finder.services.local_phase_cache import LocalPhaseCache

# These focused mixin tests do not use Qt; keep them runnable with the supplied
# Python runtime, which intentionally has no PySide6 installed.
qt = ModuleType("PySide6")
qt_widgets = ModuleType("PySide6.QtWidgets")
qt_widgets.QMessageBox = type("QMessageBox", (), {})
qt_widgets.QTableWidgetItem = type("QTableWidgetItem", (), {})
sys.modules["PySide6"] = qt
sys.modules["PySide6.QtWidgets"] = qt_widgets
element_filter = ModuleType("xrd_finder.ui.element_filter")
element_filter.element_sort_key = lambda element: element
sys.modules["xrd_finder.ui.element_filter"] = element_filter
plot_view_settings = ModuleType("xrd_finder.ui.plot_view_settings")
plot_view_settings.PlotViewSettings = type("PlotViewSettings", (), {})
sys.modules["xrd_finder.ui.plot_view_settings"] = plot_view_settings
from xrd_finder.ui.candidate_structure_actions import PhaseFinderCandidateStructureActionsMixin
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


class CandidatePathCache:
    def __init__(self, paths: dict[tuple[str, str], Path] | None = None) -> None:
        self.paths = paths or {}

    def cif_path(self, source: str, entry_id: str) -> Path | None:
        return self.paths.get((source, entry_id))


class CacheTemporaryDirectory(TemporaryDirectory):
    def __exit__(self, exc_type, exc_value, traceback) -> None:
        gc.collect()
        super().__exit__(exc_type, exc_value, traceback)


class CandidateResolutionHarness(PhaseFinderCandidateStructureActionsMixin):
    def __init__(
        self,
        *,
        saved_paths: dict[str, str] | None = None,
        cache_paths: dict[tuple[str, str], Path] | None = None,
        phases: list[Phase] | None = None,
    ) -> None:
        finder_state = FinderProjectState(candidate_cif_paths=saved_paths or {})
        self.project = type("Project", (), {"finder_state": finder_state, "phases": phases or []})()
        self.local_phase_cache = CandidatePathCache(cache_paths)


class CandidateGainHarness(CandidateResolutionHarness):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cached_peak_calls = 0
        self.cif_peak_paths: list[Path | None] = []

    def _active_pattern(self):
        return None

    def _candidate_cached_json_peaks(self, _candidate: dict[str, str]) -> list[str]:
        self.cached_peak_calls += 1
        return ["cached-peak"]

    def _candidate_cif_peaks_for_gain(self, candidate: dict[str, str]) -> list[str]:
        self.cif_peak_paths.append(self._candidate_local_cif_path(candidate))
        return ["cif-peak"]


class CountingLocalPhaseCache(LocalPhaseCache):
    def __init__(self, root: Path) -> None:
        self.embedded_install_calls = 0
        super().__init__(root)

    def install_embedded_cif(self, cif_path: str | Path, source: str, entry_id: str) -> Path:
        self.embedded_install_calls += 1
        return super().install_embedded_cif(cif_path, source, entry_id)


class CandidateRestoreHarness(PhaseFinderProjectStateActionsMixin):
    def __init__(self, state: FinderProjectState, cache: LocalPhaseCache) -> None:
        self.project = type("Project", (), {"finder_state": state, "phases": []})()
        self.local_phase_cache = cache
        self.tree = type(
            "Tree",
            (),
            {
                "restore_expansion_state": lambda _self, _state: None,
                "set_checked_pattern_ids": lambda _self, _ids: None,
                "set_checked_phase_ids": lambda _self, _ids: None,
                "select_object": lambda _self, _type, _id: None,
            },
        )()
        self.right_tabs = type("Tabs", (), {"count": lambda _self: 0})()
        self.finder_action_bar = None
        self.search_input = None
        self.name_input = None
        self.formula_sum_input = None
        self.ccdc_doi_input = None
        self.inorganics_checkbox = None
        self.organics_checkbox = None
        self.structural_data_checkbox = None
        self.reference_patterns_checkbox = None
        self.rank_by_probability_checkbox = None
        self.match_candidates: list[dict[str, str]] = []

    def _update_element_fields(self) -> None:
        return None

    def _restore_match_state(self, state: FinderProjectState) -> None:
        self.match_candidates = [dict(candidate) for candidate in state.match_candidates]

    def _match_candidates_have_structures(self) -> bool:
        return False

    def _set_grid_visible(self, _visible: bool) -> None:
        return None

    def _refresh_observed_pattern_plot(self) -> None:
        return None

    def _update_match_table(self) -> None:
        return None


class PortableCandidateStateTest(unittest.TestCase):
    def test_candidate_cif_path_prefers_embedded_copy_over_local_cache_entry(self) -> None:
        """Fails if previews or exports use a machine-specific CIF for an opened project."""
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            embedded_path = tmp_path / "embedded.cif"
            cached_path = tmp_path / "cached.cif"
            embedded_path.write_text("data_embedded\n", encoding="utf-8")
            cached_path.write_text("data_cached\n", encoding="utf-8")
            harness = CandidateResolutionHarness(
                saved_paths={"MP:mp-1": str(embedded_path)},
                cache_paths={("MP", "mp-1"): cached_path},
            )

            self.assertEqual(
                harness._candidate_cif_path({"Source": "MP", "Entry": "mp-1"}),
                embedded_path,
            )

    def test_gain_peaks_bypass_cached_derived_data_for_embedded_candidate(self) -> None:
        """Fails if Gain reuses peaks calculated from a different machine-cache CIF."""
        with TemporaryDirectory() as directory:
            embedded_path = Path(directory) / "embedded.cif"
            embedded_path.write_text("data_embedded\n", encoding="utf-8")
            harness = CandidateGainHarness(saved_paths={"COD:123": str(embedded_path)})
            candidate = {"Source": "COD", "Entry": "123"}

            peaks = harness._candidate_peaks_for_gain(candidate)

            self.assertEqual(peaks, ["cif-peak"])
            self.assertEqual(harness.cached_peak_calls, 0)
            self.assertEqual(harness.cif_peak_paths, [embedded_path])

    def test_gain_peaks_keep_cached_fallback_without_valid_embedded_candidate(self) -> None:
        """Fails if stale or absent embedded mappings disable the existing cache fallback."""
        with TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing.cif"
            harness = CandidateGainHarness(saved_paths={"COD:123": str(missing_path)})

            peaks = harness._candidate_peaks_for_gain({"Source": "COD", "Entry": "123"})

            self.assertEqual(peaks, ["cached-peak"])
            self.assertEqual(harness.cached_peak_calls, 1)
            self.assertEqual(harness.cif_peak_paths, [])

    def test_embedded_candidate_path_is_used_when_local_cache_is_empty(self) -> None:
        """Fails if project-private CIFs are ignored when the machine cache is empty."""
        with TemporaryDirectory() as directory:
            embedded_path = Path(directory) / "embedded.cif"
            embedded_path.write_text("data_embedded\n", encoding="utf-8")
            harness = CandidateResolutionHarness(saved_paths={"MP:mp-1": str(embedded_path)})

            self.assertEqual(
                harness._candidate_local_cif_path({"Source": "MP", "Entry": "mp-1"}),
                embedded_path,
            )

    def test_embedded_candidate_path_takes_priority_over_different_cache_copy(self) -> None:
        """Fails if restoration uses a machine-specific CIF instead of the archived version."""
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            embedded_path = tmp_path / "embedded.cif"
            cached_path = tmp_path / "cached.cif"
            embedded_path.write_text("data_embedded\n", encoding="utf-8")
            cached_path.write_text("data_cached\n", encoding="utf-8")
            harness = CandidateResolutionHarness(
                saved_paths={"COD:123": str(embedded_path)},
                cache_paths={("COD", "123"): cached_path},
            )

            self.assertEqual(
                harness._candidate_local_cif_path({"Source": "COD", "Entry": "123"}),
                embedded_path,
            )

    def test_missing_embedded_path_keeps_existing_cache_and_project_phase_fallbacks(self) -> None:
        """Fails if a stale project mapping disables legacy local resolution."""
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            cached_path = tmp_path / "cached.cif"
            project_path = tmp_path / "project-user.cif"
            cached_path.write_text("data_cached\n", encoding="utf-8")
            project_path.write_text("data_project\n", encoding="utf-8")
            user_phase = Phase.create("Project user phase", str(project_path))
            user_phase.id = "private-user"
            harness = CandidateResolutionHarness(
                saved_paths={
                    "MP:mp-1": str(tmp_path / "missing-mp.cif"),
                    "USER:private-user": str(tmp_path / "missing-user.cif"),
                },
                cache_paths={("MP", "mp-1"): cached_path},
                phases=[user_phase],
            )

            self.assertEqual(
                harness._candidate_local_cif_path({"Source": "MP", "Entry": "mp-1"}),
                cached_path,
            )
            self.assertEqual(
                harness._candidate_local_cif_path({"Source": "USER", "Entry": "private-user"}),
                project_path,
            )

    def test_restore_copies_and_indexes_missing_embedded_candidate(self) -> None:
        """Fails if a loaded CIF is indexed at its temporary extraction path."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            extracted_path = tmp_path / "extracted" / "candidate.cif"
            extracted_path.parent.mkdir()
            extracted_path.write_text("data_portable\n", encoding="utf-8")
            cache = LocalPhaseCache(tmp_path / "cache")
            state = FinderProjectState(candidate_cif_paths={"AFLOW:aflow-1": str(extracted_path)})
            harness = CandidateRestoreHarness(state, cache)

            harness._restore_finder_state_from_project()

            cached_path = cache.cif_path("AFLOW", "aflow-1")
            self.assertIsNotNone(cached_path)
            assert cached_path is not None
            self.assertNotEqual(cached_path, extracted_path)
            self.assertTrue(cached_path.is_relative_to(cache.root))
            self.assertEqual(cached_path.read_text(encoding="utf-8"), "data_portable\n")
            extracted_path.unlink()
            self.assertTrue(cached_path.is_file())
            entry = cache.get("AFLOW", "aflow-1")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.entry_id, "aflow-1")
            self.assertEqual(harness.project.phases, [])

    def test_embedded_install_preserves_key_and_never_overwrites_existing_local_entry(self) -> None:
        """Fails if opening a project replaces a phase already owned by the local library."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            first_path = tmp_path / "first.cif"
            replacement_path = tmp_path / "replacement.cif"
            first_path.write_text("data_local\n", encoding="utf-8")
            replacement_path.write_text("data_embedded\n", encoding="utf-8")
            cache = LocalPhaseCache(tmp_path / "cache")

            installed_path = cache.install_embedded_cif(first_path, "USER", "original-entry")
            second_result = cache.install_embedded_cif(replacement_path, "USER", "original-entry")

            self.assertEqual(second_result, installed_path)
            self.assertEqual(installed_path.read_text(encoding="utf-8"), "data_local\n")
            entry = cache.get("USER", "original-entry")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual((entry.source, entry.entry_id), ("USER", "original-entry"))

    def test_restore_installs_shared_candidate_only_once(self) -> None:
        """Fails if one phase referenced by several pattern states is imported repeatedly."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            extracted_path = tmp_path / "shared.cif"
            extracted_path.write_text("data_shared\n", encoding="utf-8")
            candidate = {"Source": "MP", "Entry": "mp-shared"}
            state = FinderProjectState(
                match_candidates=[candidate],
                candidate_cif_paths={"MP:mp-shared": str(extracted_path)},
                profile_states={
                    "pattern-1": {"candidates": [candidate]},
                    "pattern-2": {"candidates": [candidate]},
                },
            )
            cache = CountingLocalPhaseCache(tmp_path / "cache")
            harness = CandidateRestoreHarness(state, cache)

            harness._restore_finder_state_from_project()

            self.assertEqual(cache.embedded_install_calls, 1)
            self.assertIsNotNone(cache.cif_path("MP", "mp-shared"))

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
