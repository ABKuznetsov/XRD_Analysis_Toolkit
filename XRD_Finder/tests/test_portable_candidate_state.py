from __future__ import annotations

import gc
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.phase import Phase
from xrd_finder.services.local_phase_cache import LocalPhaseCache

# These focused mixin tests do not use Qt; keep them runnable with the supplied
# Python runtime, which intentionally has no PySide6 installed.
_MODULES_BEFORE_QT_FREE_IMPORTS = dict(sys.modules)
qt = ModuleType("PySide6")
qt_widgets = ModuleType("PySide6.QtWidgets")
qt_widgets.QMessageBox = type("QMessageBox", (), {})
qt_widgets.QTableWidgetItem = type("QTableWidgetItem", (), {})
qt.QtWidgets = qt_widgets
element_filter = ModuleType("xrd_finder.ui.element_filter")
element_filter.element_sort_key = lambda element: element
plot_view_settings = ModuleType("xrd_finder.ui.plot_view_settings")
plot_view_settings.PlotViewSettings = type("PlotViewSettings", (), {})
with patch.dict(
    sys.modules,
    {
        "PySide6": qt,
        "PySide6.QtWidgets": qt_widgets,
        "xrd_finder.ui.element_filter": element_filter,
        "xrd_finder.ui.plot_view_settings": plot_view_settings,
    },
):
    from xrd_finder.ui.candidate_structure_actions import PhaseFinderCandidateStructureActionsMixin
    from xrd_finder.ui.project_state_actions import PhaseFinderProjectStateActionsMixin
_QT_FREE_IMPORTS_RESTORED_SYS_MODULES = sys.modules == _MODULES_BEFORE_QT_FREE_IMPORTS


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


class NetworkGuardCache(CandidatePathCache):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.index_calls = 0

    def index_cif(self, _path: Path, source: str, entry_id: str) -> None:
        self.index_calls += 1


class NetworkDownloadService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.download_calls = 0

    def download_cif(self, entry_id: str, target_dir: Path) -> Path:
        self.download_calls += 1
        return self.path


class CandidateNetworkGuardHarness(PhaseFinderCandidateStructureActionsMixin):
    def __init__(self, root: Path) -> None:
        self.project = type("Project", (), {"finder_state": FinderProjectState(), "phases": []})()
        self.local_phase_cache = NetworkGuardCache(root)
        self.materials_project = NetworkDownloadService(root / "downloaded.cif")
        self._suppress_candidate_network = True


class CountingLocalPhaseCache(LocalPhaseCache):
    def __init__(self, root: Path) -> None:
        self.embedded_install_calls = 0
        super().__init__(root)

    def install_embedded_cif(self, cif_path: str | Path, source: str, entry_id: str) -> Path | None:
        self.embedded_install_calls += 1
        return super().install_embedded_cif(cif_path, source, entry_id)


class ActivationTrackingTable:
    def __init__(self) -> None:
        self.rows: list[list[str]] = []
        self.selected_row = -1
        self.activation_count = 0
        self._signals_blocked = False

    def blockSignals(self, blocked: bool) -> bool:
        previous = self._signals_blocked
        self._signals_blocked = bool(blocked)
        return previous

    def rowCount(self) -> int:
        return len(self.rows)

    def selectRow(self, row: int) -> None:
        self.selected_row = row
        if not self._signals_blocked:
            self.activation_count += 1


class FailingEmbeddedInstallCache:
    def get(self, source: str, entry_id: str):
        return None

    def install_embedded_cif(self, cif_path: str | Path, source: str, entry_id: str) -> Path:
        raise OSError("local phase cache is read-only")


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
        self.candidate_table = ActivationTrackingTable()
        self.project_load_warning_batches: list[list[str]] = []
        self.refresh_count = 0
        self.recalculate_count = 0

    def _set_candidate_rows(self, rows: list[list[str]]) -> None:
        self.candidate_table.rows = rows

    def _update_element_fields(self) -> None:
        return None

    def _restore_match_state(self, state: FinderProjectState) -> None:
        self.match_candidates = [dict(candidate) for candidate in state.match_candidates]

    def _match_candidates_have_structures(self) -> bool:
        return False

    def _set_grid_visible(self, _visible: bool) -> None:
        return None

    def _refresh_observed_pattern_plot(self) -> None:
        self.refresh_count += 1

    def _show_project_load_warnings(self, warnings: list[str]) -> None:
        self.project_load_warning_batches.append(list(warnings))

    def _update_match_table(self) -> None:
        return None

    def _recalculate_match_profile(self, auto_zoom: bool = False) -> None:
        self.recalculate_count += 1


class LegacyCandidateRestoreHarness(CandidateRestoreHarness):
    def __init__(
        self,
        state: FinderProjectState,
        cache: LocalPhaseCache,
        paths: dict[str, Path | None],
        stored_structures: dict[str, object] | None = None,
    ) -> None:
        super().__init__(state, cache)
        self.paths = paths
        self.stored_structures = stored_structures or {}
        self.match_structures: dict[str, object] = {}
        self.match_table = ActivationTrackingTable()
        self.recalculate_count = 0

    def _restore_match_state(self, state: FinderProjectState) -> None:
        PhaseFinderProjectStateActionsMixin._restore_match_state(self, state)

    def _match_candidates_have_structures(self) -> bool:
        return PhaseFinderProjectStateActionsMixin._match_candidates_have_structures(self)

    def _active_pattern(self):
        return None

    def _finder_candidate_structure_overrides(self, _pattern, _candidates) -> dict[str, object]:
        return self.stored_structures

    def _candidate_key(self, candidate: dict[str, str]) -> str:
        return f"{candidate.get('Source', '')}:{candidate.get('Entry', '')}"

    def _candidate_phase_name(self, candidate: dict[str, str]) -> str:
        return candidate.get("_DisplayName", "") or candidate.get("Phase", "")

    def _candidate_local_cif_path(self, candidate: dict[str, str]) -> Path | None:
        return self.paths.get(self._candidate_key(candidate))

    def _update_match_table(self) -> None:
        self.match_table.rows = [[self._candidate_key(candidate)] for candidate in self.match_candidates]

    def _recalculate_match_profile(self, auto_zoom: bool = False) -> None:
        self.recalculate_count += 1


class PortableCandidateStateTest(unittest.TestCase):
    def test_qt_free_import_stubs_restore_sys_modules_exactly(self) -> None:
        """Fails if this focused module poisons modules imported by later tests."""
        self.assertTrue(_QT_FREE_IMPORTS_RESTORED_SYS_MODULES)

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

    def test_project_restore_network_guard_blocks_uncached_database_download(self) -> None:
        """Fails if automatic restoration can download an unreferenced search result."""
        with TemporaryDirectory() as directory:
            harness = CandidateNetworkGuardHarness(Path(directory))

            with self.assertRaisesRegex(ValueError, r"project load"):
                harness._candidate_cif_path({"Source": "MP", "Entry": "mp-remote"})

            self.assertEqual(harness.materials_project.download_calls, 0)
            self.assertEqual(harness.local_phase_cache.index_calls, 0)

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

    def test_embedded_install_does_not_replace_metadata_only_record(self) -> None:
        """Fails if an existing key without a CIF path is treated as unowned."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            embedded_path = tmp_path / "embedded.cif"
            embedded_path.write_text("data_embedded\n", encoding="utf-8")
            cache = LocalPhaseCache(tmp_path / "cache")
            cache.upsert_computational_entries(
                [
                    SimpleNamespace(
                        source="MP",
                        entry_id="mp-metadata",
                        formula="BaSiO3",
                        name="Existing metadata",
                        spacegroup="P1",
                        note="search result",
                    )
                ]
            )

            result = cache.install_embedded_cif(embedded_path, "MP", "mp-metadata")

            self.assertIsNone(result)
            entry = cache.get("MP", "mp-metadata")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(entry.name, "Existing metadata")
            self.assertEqual(entry.cif_path, "")
            self.assertFalse((cache.root / "embedded_cif" / "MP").exists())

    def test_embedded_install_does_not_replace_record_whose_file_is_missing(self) -> None:
        """Fails if file disappearance changes install-only-if-key-absent semantics."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            original_path = tmp_path / "original.cif"
            replacement_path = tmp_path / "replacement.cif"
            original_path.write_text("data_original\n", encoding="utf-8")
            replacement_path.write_text("data_replacement\n", encoding="utf-8")
            cache = LocalPhaseCache(tmp_path / "cache")
            installed_path = cache.install_embedded_cif(original_path, "AFLOW", "aflow-missing-file")
            assert installed_path is not None
            installed_path.unlink()

            result = cache.install_embedded_cif(replacement_path, "AFLOW", "aflow-missing-file")

            self.assertEqual(result, installed_path)
            self.assertFalse(installed_path.exists())
            entry = cache.get("AFLOW", "aflow-missing-file")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(Path(entry.cif_path), installed_path)

    def test_embedded_install_loses_race_without_overwriting_concurrent_entry(self) -> None:
        """Fails if a cache row created after the preflight check can be overwritten."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            embedded_path = tmp_path / "embedded.cif"
            concurrent_path = tmp_path / "concurrent.cif"
            embedded_path.write_text("data_embedded\n", encoding="utf-8")
            concurrent_path.write_text("data_concurrent\n", encoding="utf-8")
            cache = LocalPhaseCache(tmp_path / "cache")
            cache_shutil = LocalPhaseCache.install_embedded_cif.__globals__["shutil"]
            copy2 = cache_shutil.copy2

            def copy_then_win_race(source: Path, target: Path):
                result = copy2(source, target)
                cache.index_cif(concurrent_path, source="MP", entry_id="mp-race")
                return result

            with patch.object(cache_shutil, "copy2", side_effect=copy_then_win_race):
                result = cache.install_embedded_cif(embedded_path, "MP", "mp-race")

            self.assertEqual(result, concurrent_path)
            entry = cache.get("MP", "mp-race")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(Path(entry.cif_path), concurrent_path)
            embedded_root = cache.root / "embedded_cif"
            self.assertEqual(list(embedded_root.rglob("*.cif")) if embedded_root.exists() else [], [])

    def test_clearing_source_removes_only_its_embedded_cif_directory(self) -> None:
        """Fails if source clearing leaves durable project-installed files behind."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            user_path = tmp_path / "user.cif"
            aflow_path = tmp_path / "aflow.cif"
            user_path.write_text("data_user\n", encoding="utf-8")
            aflow_path.write_text("data_aflow\n", encoding="utf-8")
            cache = LocalPhaseCache(tmp_path / "cache")
            user_installed = cache.install_embedded_cif(user_path, "USER", "user-entry")
            aflow_installed = cache.install_embedded_cif(aflow_path, "AFLOW", "aflow-entry")
            assert user_installed is not None
            assert aflow_installed is not None

            cache.clear_user_library()

            self.assertFalse(user_installed.parent.exists())
            self.assertTrue(aflow_installed.parent.is_dir())
            self.assertIsNone(cache.get("USER", "user-entry"))
            self.assertIsNotNone(cache.get("AFLOW", "aflow-entry"))

    def test_clearing_source_does_not_delete_colliding_source_directory(self) -> None:
        """Fails if distinct source names share one sanitized durable directory."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            user_path = tmp_path / "user.cif"
            other_path = tmp_path / "other.cif"
            user_path.write_text("data_user\n", encoding="utf-8")
            other_path.write_text("data_other\n", encoding="utf-8")
            cache = LocalPhaseCache(tmp_path / "cache")
            user_installed = cache.install_embedded_cif(user_path, "USER", "user-entry")
            other_installed = cache.install_embedded_cif(other_path, "USER!", "other-entry")
            assert user_installed is not None
            assert other_installed is not None

            self.assertNotEqual(user_installed.parent, other_installed.parent)
            cache.clear_user_library()

            self.assertFalse(user_installed.exists())
            self.assertTrue(other_installed.is_file())
            self.assertEqual(cache.cif_path("USER!", "other-entry"), other_installed)

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

    def test_cache_install_failure_warns_and_does_not_abort_embedded_restore(self) -> None:
        """Fails if optional local-library installation aborts a self-contained load."""
        with TemporaryDirectory() as directory:
            embedded_path = Path(directory) / "embedded.cif"
            embedded_path.write_text("data_embedded\n", encoding="utf-8")
            candidate = {"Source": "MP", "Entry": "mp-read-only", "Phase": "Portable phase"}
            state = FinderProjectState(
                match_candidates=[candidate],
                candidate_cif_paths={"MP:mp-read-only": str(embedded_path)},
            )
            harness = CandidateRestoreHarness(state, FailingEmbeddedInstallCache())  # type: ignore[arg-type]

            try:
                harness._restore_finder_state_from_project()
            except OSError as exc:
                self.fail(f"cache installation escaped project restoration: {exc}")

            self.assertEqual(harness.match_candidates, [candidate])
            self.assertEqual(state.candidate_cif_paths, {"MP:mp-read-only": str(embedded_path)})
            self.assertEqual(harness.refresh_count, 1)
            self.assertEqual(harness.recalculate_count, 1)
            self.assertEqual(len(harness.project_load_warning_batches), 1)
            warning = "\n".join(harness.project_load_warning_batches[0])
            self.assertRegex(warning, r"MP:mp-read-only.*read-only")

    def test_restore_candidate_selection_does_not_activate_or_request_network(self) -> None:
        """Fails if restoring the saved row emits the normal preview activation."""
        with CacheTemporaryDirectory() as directory:
            state = FinderProjectState(
                candidate_rows=[
                    {
                        "Source": "COD",
                        "Entry": "1000000",
                        "Formula": "BaSiO3",
                        "Phase": "Legacy remote result",
                    }
                ],
                candidate_current_row=0,
            )
            harness = CandidateRestoreHarness(state, LocalPhaseCache(Path(directory) / "cache"))

            harness._restore_finder_state_from_project()

            self.assertEqual(harness.candidate_table.selected_row, 0)
            self.assertEqual(harness.candidate_table.activation_count, 0)

    def test_unresolved_legacy_phase_warns_without_suppressing_valid_recalculation(self) -> None:
        """Fails if one missing legacy CIF hides the problem and blocks valid phases."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            valid_path = tmp_path / "valid.cif"
            valid_path.write_text("data_valid\n", encoding="utf-8")
            valid = {"Source": "USER", "Entry": "valid", "_DisplayName": "Valid phase"}
            missing = {"Source": "USER", "Entry": "missing", "_DisplayName": "Missing legacy phase"}
            state = FinderProjectState(match_candidates=[valid, missing])
            harness = LegacyCandidateRestoreHarness(
                state,
                LocalPhaseCache(tmp_path / "cache"),
                {"USER:valid": valid_path, "USER:missing": None},
            )

            def parse_valid_cif(path: Path):
                self.assertEqual(path, valid_path)
                return SimpleNamespace(), SimpleNamespace(name="Parsed phase")

            restore_globals = PhaseFinderProjectStateActionsMixin._restore_match_state.__globals__
            with patch.dict(restore_globals, {"create_phase_from_cif": parse_valid_cif}):
                harness._restore_finder_state_from_project()

            self.assertIn("USER:valid", harness.match_structures)
            self.assertNotIn("USER:missing", harness.match_structures)
            self.assertEqual(harness.recalculate_count, 1)
            self.assertEqual(len(harness.project_load_warning_batches), 1)
            warning = "\n".join(harness.project_load_warning_batches[0])
            self.assertRegex(warning, r"Missing legacy phase.*USER:missing")

    def test_legacy_phase_warning_explains_when_saved_structure_is_used(self) -> None:
        """Fails if a successful structure fallback is reported as a wholly unrestored phase."""
        with CacheTemporaryDirectory() as directory:
            tmp_path = Path(directory)
            candidate = {
                "Source": "USER",
                "Entry": "missing",
                "_DisplayName": "Saved legacy phase",
            }
            saved_structure = SimpleNamespace(name="Saved structure")
            state = FinderProjectState(match_candidates=[candidate])
            harness = LegacyCandidateRestoreHarness(
                state,
                LocalPhaseCache(tmp_path / "cache"),
                {"USER:missing": None},
                {"USER:missing": saved_structure},
            )

            harness._restore_finder_state_from_project()

            self.assertIs(harness.match_structures["USER:missing"], saved_structure)
            warning = "\n".join(harness.project_load_warning_batches[0])
            self.assertRegex(
                warning,
                r"Saved legacy phase.*USER:missing.*using saved structure",
            )

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
        harness.profile_states = {
            "pattern": {
                "candidates": [
                    {"Source": "AFLOW", "Entry": "aflow-1", "_DisplayName": "Barium silicate"}
                ]
            }
        }

        with self.assertRaisesRegex(ValueError, r"Barium silicate.*AFLOW:aflow-1"):
            harness._collect_project_candidate_cif_paths()


if __name__ == "__main__":
    unittest.main()
