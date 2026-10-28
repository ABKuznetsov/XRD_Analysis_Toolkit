from __future__ import annotations
from xrd_finder.ui.interface_scaling import InterfaceScalingMixin
from xrd_finder.ui.menu_actions import PhaseFinderMenuActionsMixin
from xrd_finder.ui.peak_information_actions import PeakInformationActionsMixin
from xrd_finder.ui.find_peaks_actions import FindPeaksActionsMixin
from xrd_finder.ui.manual_peak_actions import ManualPeakActionsMixin
from xrd_finder.ui.manual_calibration_actions import ManualCalibrationActionsMixin
from xrd_finder.ui.preview_observation_job import PreviewObservationController
from xrd_finder.ui.structure_overlay import OverlayObservationCache, overlay_observation_key
from xrd_finder.services.peak_cell_alignment import apply_peak_cell
from xrd_finder.ui.match_profile_renderer import resolve_candidate_initial_cell, store_accepted_cell_results
from dataclasses import replace

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDialog,
)
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import nnls
import numpy as np
import pyqtgraph as pg
from scipy.signal import find_peaks
from pathlib import Path

from xrd_finder.services.gain_lines import GainLineMixin, candidate_cif_fingerprint
from xrd_finder.services.gain_calculation import GainCalculationMixin
from xrd_finder import __version__
from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.series import SeriesAnalysis
from xrd_finder.core.reference_structures import create_corundum_reference_structure
from xrd_finder.core.structure import CellParameters, Structure
from xrd_finder.finder import FinderInput, FinderService
from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.models import ObservedPeak, candidate_structure_override
from xrd_finder.finder.quantification import quantification_source_signature
from xrd_finder.finder.fingerprint_matching import fingerprint_match_score
from xrd_finder.finder.gain_evidence import phase_signal_to_noise
from xrd_finder.finder.profile_backend import FinderPeakProfileBackend
from xrd_finder.finder.profile_calculator import array_fingerprint
from xrd_finder.ui.plot_layer_items import restore_profile_layer_stacking
from xrd_finder.instrument.library import BUILTIN_PROFILE_ID, InstrumentProfileLibrary
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.scientific_folder_import import collect_scientific_folder_groups, unique_series_name
from xrd_finder.io.xy_loader import load_xy
from xrd_finder.io.project_io import PORTABLE_PROJECT_SUFFIX, load_project_manifest, save_project_manifest
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    CalculatedPatternService,
    HKLPeak,
    calculated_profile_from_peaks,
)
from xrd_finder.services.candidate_search_service import (
    CandidateSearchService,
    normalize_candidate_row,
)
from xrd_finder.services.ccdc_service import CcdcService
from xrd_finder.services.cod_online_service import CodOnlineService, formula_elements
from xrd_finder.services.computational_database_service import AflowService, OqmdService
from xrd_finder.services.local_phase_cache import LocalPhaseCache, LocalPhaseSearchError
from xrd_finder.services.match_pdf2_service import MatchPdf2Service
from xrd_finder.services.materials_project_service import MaterialsProjectService
from xrd_finder.services.preprocessing_service import estimate_background
from xrd_finder.services.refinement_service import RefinementService
from xrd_finder.services.gain_shortlist import (
    common_zero_shift,
    estimate_matched_profile_fwhm,
    residual_peak_is_explained,
    select_profile_candidate_indices,
    summarize_combined_residual_evidence,
)
from xrd_finder.services.runtime_diagnostics import traced_operation
from xrd_finder.services.phase_pattern_equivalence import compare_phase_patterns
from xrd_finder.services.security_mode import (
    env_offline_mode_enabled,
    offline_mode_enabled,
    security_settings_path,
    set_saved_offline_mode_enabled,
)
from xrd_finder.tools.secure_macos_installer import build_secure_macos_pkg
from xrd_finder.tools.secure_windows_package import build_secure_windows_installer
from xrd_finder.services.indexed_cell_matching import IndexedCellMatchingService
from xrd_finder.services.rruff_service import RruffService
from xrd_finder.ui.pattern_plot_helpers import (
    ensure_right_legend,
    estimate_profile_fwhm,
)
from xrd_finder.ui.phase_finder_menu import build_phase_finder_menu_bar
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.gain_job import GainJobController, accepted_profile_snapshot
from xrd_finder.ui.candidate_info_actions import PhaseFinderCandidateInfoActionsMixin
from xrd_finder.ui.candidate_search_actions import PhaseFinderCandidateSearchActionsMixin
from xrd_finder.ui.candidate_structure_actions import PhaseFinderCandidateStructureActionsMixin
from xrd_finder.ui.candidate_tables import CandidateTableWidget, SelectedCandidatesTableWidget
from xrd_finder.ui.compound_card import CompoundCardWidget
from xrd_finder.ui.composition_panel import CompositionPanel
from xrd_finder.ui.peak_selection_actions import PhaseFinderPeakSelectionActionsMixin
from xrd_finder.ui.database_actions import PhaseFinderDatabaseActionsMixin
from xrd_finder.ui.database_panel import DatabasePanelWidget
from xrd_finder.ui.element_filter import PeriodicTableWidget, element_sort_key
from xrd_finder.ui.finder_action_bar import FinderActionBar
from xrd_finder.ui.finder_plot_control_bar import FinderPlotControlBar
from xrd_finder.ui.finder_top_toolbar import FinderTopToolBar
from xrd_finder.ui.gain_scoring import (
    DEFAULT_GAIN_POLICY,
    GainIndexedEvidence,
    GainStage,
    build_gain_indexed_evidence,
    fit_residual_candidate_scale,
    profile_residual_gain,
)
from xrd_finder.ui.help_text import PHASE_FINDER_HELP_TEXT, PHASE_FINDER_HELP_TITLE
from xrd_finder.ui.instrument_profile_actions import PhaseFinderInstrumentProfileActionsMixin
from xrd_finder.ui.layout_state import SplitterLayoutState
from xrd_finder.ui.match_profile_renderer import build_finder_candidate_inputs, draw_match_profile_result
from xrd_finder.ui.candidate_line_provider import CandidateLineProvider
from xrd_finder.ui.observed_pattern_actions import (
    PhaseFinderObservedPatternActionsMixin,
    _processed_amorphous_background_data,
)
from xrd_finder.ui.peak_marker_renderer import (
    add_peak_coverage_markers,
)
from xrd_finder.ui.peak_matching import (
    ObservedLineRecord,
    PhaseAlignmentEstimate,
    estimate_phase_alignment,
    nearest_index as nearest_peak_index,
    observed_peak_positions,
    observed_peak_records,
    peak_presence_probability,
    instrument_fwhm_at,
    radiation_satellites_at,
)
from xrd_finder.io.cif_powder_pattern import extract_cif_powder_peaks
from xrd_finder.finder.residual_peak_refinement import refine_residual_peaks
from xrd_finder.finder.phase_width_model import (
    fit_phase_width_model,
    match_clean_phase_records,
    width_difference_corroboration,
)
from xrd_finder.ui.plot_actions import PhaseFinderPlotActionsMixin
from xrd_finder.ui.plot_view_actions import PhaseFinderPlotViewActionsMixin
from xrd_finder.ui.plot_view_settings import PlotViewSettings, PlotViewSettingsWidget
from xrd_finder.ui.post_match_pipeline import PostMatchPipeline
from xrd_finder.ui.preprocessing_actions import PhaseFinderPreprocessingActionsMixin
from xrd_finder.ui.project_state_actions import PhaseFinderProjectStateActionsMixin
from xrd_finder.ui.project_tree_actions import PhaseFinderProjectTreeActionsMixin
from xrd_finder.ui.project_controls import ProjectControlsWidget
from xrd_finder.ui.project_tree import ProjectTree
from xrd_finder.ui.reference_preview_renderer import draw_pdf2_reference, draw_rruff_reference
from xrd_finder.ui.selected_phases_actions import PhaseFinderSelectedPhasesActionsMixin
from xrd_finder.ui.structure_overlay import draw_structure_overlay, prepare_structure_overlay
from xrd_finder.ui.theme import is_dark_theme, window_style
from xrd_finder.ui.visible_profile_calculation_queue import VisibleProfileCalculationQueue
from xrd_finder.ui.xrd_plot import create_xrd_plot_widget
from xrd_finder.ui.analysis_preview import capture_analysis_preview
from xrd_finder.ui.app_settings import app_settings
from xrd_finder.ui.database_state import source_states
from xrd_finder.ui.settings_transfer import export_user_settings_bundle, import_user_settings_bundle


class AnalysisWindow(QDialog):
    project_changed = Signal()
    background_status_changed = Signal(str)
    cod_server_alert = Signal(str)
    candidate_prepared = Signal(object)
    candidate_preparation_progress = Signal(object)
    IMPORT_SUFFIXES = {".xy", ".txt", ".dat", ".csv", ".xye", ".cif"}

    def __init__(self, project: Project, title: str) -> None:
        super().__init__()
        self.project = project
        self._base_title = title
        self._project_read_only_example = False
        self._saved_project_snapshot: str | None = None
        self.setWindowTitle(f"{title} - {project.name}")
        self._layout_state = SplitterLayoutState(app_settings())
        self.setStyleSheet(window_style(self._is_dark_theme()))
        self.setAcceptDrops(True)
        self._drop_targets: list[QWidget] = []
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.resize(1300, 820)

        self.tree = ProjectTree()
        self._register_drop_target(self.tree)
        self.tree.set_project(project)
        self.tree.object_open_requested.connect(self._open_project_object)
        self.tree.object_rename_requested.connect(self._rename_project_object)
        self.tree.object_delete_requested.connect(self._delete_project_object)
        self.tree.series_create_requested.connect(self._create_project_series)
        self.tree.object_move_to_series_requested.connect(self._move_project_object_to_series)
        self.tree.pattern_copy_to_series_requested.connect(self._copy_pattern_to_series)
        self.tree.itemSelectionChanged.connect(self._on_project_tree_selection_changed)
        self.tree.pattern_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())
        self.tree.phase_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())

        self.sidebar = QWidget()
        self.sidebar.setObjectName('projectSidebar')
        self.sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.sidebar.setMinimumWidth(170)
        self.sidebar.setMaximumWidth(360)
        self._register_drop_target(self.sidebar)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)
        self.project_controls = ProjectControlsWidget()
        self.project_controls.newProjectRequested.connect(self._new_project)
        self.project_controls.loadProjectRequested.connect(self._load_project)
        self.project_controls.saveProjectRequested.connect(self._save_project)
        self.project_controls.saveProjectAsRequested.connect(self._save_project_as)
        self.project_controls.addSeriesRequested.connect(self._create_project_series)
        self.project_controls.importRequested.connect(self._import_scientific_files)
        self.project_controls.moveRequested.connect(self._move_current_tree_object)
        self._register_drop_target(self.project_controls)
        sidebar_layout.addWidget(self.project_controls)
        sidebar_layout.addWidget(self.tree, 1)

        self.center = QWidget()
        self._register_drop_target(self.center)
        self.center_layout = QVBoxLayout(self.center)
        self.center_layout.setContentsMargins(0, 0, 0, 0)

        self.right_tabs = QTabWidget()
        self._register_drop_target(self.right_tabs)
        self.right_tabs.setMinimumWidth(280)
        self.right_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._layout_state.register("main_splitter", self.main_splitter)
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.addWidget(self.center)
        self.main_splitter.addWidget(self.right_tabs)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 1)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.setSizes([190, 920, 390])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 4)
        layout.setSpacing(6)
        layout.addWidget(self.main_splitter)
        self.background_status_label = QLabel("Ready")
        self.background_status_label.setObjectName('backgroundStatus')
        self.background_status_label.setFixedHeight(26)
        self.background_status_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.background_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.background_status_label)
        self.background_status_changed.connect(self._set_background_status)
        self._cod_server_alert_box: QMessageBox | None = None
        self.cod_server_alert.connect(self._show_cod_server_alert)

    def _set_background_status(self, message: str) -> None:
        text = str(message or "Ready")
        self.background_status_label.setText(text)
        self.background_status_label.setToolTip(text)

    def _show_cod_server_alert(self, message: str) -> None:
        if self._cod_server_alert_box is not None and self._cod_server_alert_box.isVisible():
            self._cod_server_alert_box.setText(message)
            self._cod_server_alert_box.raise_()
            return

        alert = QMessageBox(self)
        alert.setIcon(QMessageBox.Icon.Warning)
        alert.setWindowTitle("Online database connection unavailable")
        alert.setText(message)
        alert.setInformativeText(
            "Local database results remain available. Check VPN/proxy settings if online COD, Materials Project, AFLOW or OQMD should be reachable."
        )
        alert.setStandardButtons(QMessageBox.StandardButton.Ok)
        alert.setModal(False)
        alert.finished.connect(self._clear_cod_server_alert)
        self._cod_server_alert_box = alert
        alert.open()

    def _clear_cod_server_alert(self, _result: int) -> None:
        self._cod_server_alert_box = None

    def _is_dark_theme(self) -> bool:
        return is_dark_theme(self)

    def _open_project_object(self, object_type: str, object_id: str) -> None:
        if object_type == "pattern":
            self.tree.set_checked_pattern_ids([object_id])
            return
        if object_type == "phase":
            self.tree.set_checked_phase_ids([object_id])

    @traced_operation("project.reorder")
    def _move_current_tree_object(self, direction: int) -> None:
        current = self.tree.current_object()
        if current is None:
            return
        object_type, object_id = current
        if object_type == "series":
            objects = self.project.series
            visible_indices = list(range(len(objects)))
        elif object_type == "pattern":
            tree_changed, display_changed = self._move_pattern_order(object_id, direction)
            if not tree_changed and not display_changed:
                return
            if tree_changed:
                self._rebuild_tree_after_reorder(object_type, object_id)
            self.project_changed.emit()
            if display_changed:
                self._refresh_plot_after_tree_reorder(object_type)
            return
        elif object_type == "phase":
            objects = self.project.phases
            visible_indices = self._active_tree_object_indices(object_type, objects)
        else:
            return
        index = next((i for i, project_object in enumerate(objects) if project_object.id == object_id), -1)
        try:
            visible_index = visible_indices.index(index)
        except ValueError:
            return
        new_visible_index = visible_index + direction
        if new_visible_index < 0 or new_visible_index >= len(visible_indices):
            return
        new_index = visible_indices[new_visible_index]
        objects[index], objects[new_index] = objects[new_index], objects[index]
        if object_type == "phase":
            self._sync_structures_to_phase_order()
        # Rebuilding the tree normally emits pattern/phase selection signals
        # and changing its current item emits another selection signal.  A
        # reorder does not change the actual selection, so those signals used
        # to run the complete scientific refresh several times and discard the
        # Gain caches.  Keep the rebuild silent and refresh the plot once only
        # when its visible stacking/order is affected.
        self._rebuild_tree_after_reorder(object_type, object_id)
        self.project_changed.emit()
        self._refresh_plot_after_tree_reorder(object_type)

    def _move_pattern_order(self, pattern_id: str, direction: int) -> tuple[bool, bool]:
        """Move inside a series first; at its edge move only the multi-XRD queue."""
        series = self.project.series_for_object("pattern", pattern_id)
        if series is not None:
            group_ids = series.pattern_ids
        else:
            assigned_ids = {
                item_id
                for project_series in self.project.series
                for item_id in project_series.pattern_ids
            }
            group_ids = [
                pattern.id for pattern in self.project.patterns
                if pattern.id not in assigned_ids
            ]
        try:
            group_index = group_ids.index(pattern_id)
        except ValueError:
            return False, False
        target_group_index = group_index + direction
        if 0 <= target_group_index < len(group_ids):
            target_id = group_ids[target_group_index]
            if series is not None:
                series.pattern_ids[group_index], series.pattern_ids[target_group_index] = (
                    series.pattern_ids[target_group_index],
                    series.pattern_ids[group_index],
                )
            else:
                self._swap_project_objects_by_id(self.project.patterns, pattern_id, target_id)
            display_changed = self._swap_pattern_display_ids(pattern_id, target_id)
            return True, display_changed
        if not bool(getattr(self, "show_all_selected_patterns", False)):
            return False, False
        return False, self._move_pattern_in_active_queue(pattern_id, direction)

    def _move_pattern_in_active_queue(self, pattern_id: str, direction: int) -> bool:
        checked = set(self.tree.checked_pattern_ids())
        if pattern_id not in checked:
            return False
        order = self._normalized_pattern_display_order()
        active_order = [item_id for item_id in order if item_id in checked]
        try:
            active_index = active_order.index(pattern_id)
        except ValueError:
            return False
        target_index = active_index + direction
        if target_index < 0 or target_index >= len(active_order):
            return False
        return self._swap_pattern_display_ids(pattern_id, active_order[target_index])

    def _swap_pattern_display_ids(self, first_id: str, second_id: str) -> bool:
        order = self._normalized_pattern_display_order()
        try:
            first_index = order.index(first_id)
            second_index = order.index(second_id)
        except ValueError:
            return False
        order[first_index], order[second_index] = order[second_index], order[first_index]
        return True

    def _normalized_pattern_display_order(self) -> list[str]:
        available = [pattern.id for pattern in self.project.patterns]
        available_set = set(available)
        stored = list(getattr(self, "pattern_display_order_ids", []) or [])
        order = [item_id for item_id in stored if item_id in available_set]
        order.extend(item_id for item_id in available if item_id not in set(order))
        self.pattern_display_order_ids = order
        return order

    @staticmethod
    def _swap_project_objects_by_id(objects: list, first_id: str, second_id: str) -> None:
        first_index = next(index for index, item in enumerate(objects) if item.id == first_id)
        second_index = next(index for index, item in enumerate(objects) if item.id == second_id)
        objects[first_index], objects[second_index] = objects[second_index], objects[first_index]

    def _rebuild_tree_after_reorder(self, object_type: str, object_id: str) -> None:
        signals_were_blocked = self.tree.blockSignals(True)
        try:
            self.tree.set_project(self.project)
            self.tree.select_object(object_type, object_id)
        finally:
            self.tree.blockSignals(signals_were_blocked)

    def _active_tree_object_indices(self, object_type: str, objects: list) -> list[int]:
        """Return global-list indices of checked objects in their display order."""
        active_ids = set(
            self.tree.checked_pattern_ids()
            if object_type == "pattern"
            else self.tree.checked_phase_ids()
        )
        return [index for index, item in enumerate(objects) if item.id in active_ids]

    def _refresh_plot_after_tree_reorder(self, object_type: str) -> None:
        if not hasattr(self, "match_plot"):
            return
        needs_plot_refresh = object_type == "phase" or (
            object_type == "pattern" and bool(getattr(self, "show_all_selected_patterns", False))
        )
        if not needs_plot_refresh:
            if hasattr(self, "_update_profile_view_context"):
                self._update_profile_view_context()
            return
        view_range = self._plot_view_range()
        try:
            self._refresh_observed_pattern_plot()
            displayed_patterns = (
                self._patterns_to_display()
                if self.show_all_selected_patterns
                else [self._active_pattern()]
            )
            has_profile_candidates = any(
                self._profile_candidates_for_pattern(pattern)
                for pattern in displayed_patterns
                if pattern is not None
            )
            if has_profile_candidates:
                self._recalculate_match_profile(auto_zoom=False, active_only=False)
        finally:
            self._restore_plot_view_range(view_range)
            if hasattr(self, "_update_profile_view_context"):
                self._update_profile_view_context()

    def _sync_structures_to_phase_order(self) -> None:
        phase_rank = {phase.id: index for index, phase in enumerate(self.project.phases)}
        self.project.structures.sort(
            key=lambda structure: (
                phase_rank.get(structure.phase_id or "", len(phase_rank)),
                structure.name,
            )
        )

    def _new_project(self) -> None:
        if not self._confirm_project_replacement():
            return
        self.project = Project(name="XRD Phase Finder Project")
        self._project_read_only_example = False
        self.setWindowTitle(f"{self._base_title} - {self.project.name}")
        self.tree.set_project(self.project)
        self._after_new_project()
        self.project_changed.emit()
        self._remember_saved_project_state()

    def _load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load XRD project",
            self._last_directory(),
            "XRD Phase Finder File (*.xpff)",
        )
        if not path:
            return
        self._open_project_path(path)

    def _open_project_path(self, path: str | Path) -> bool:
        if not self._confirm_project_replacement():
            return False
        try:
            project = load_project_manifest(path)
        except Exception as exc:
            QMessageBox.warning(self, "Load project failed", str(exc))
            return False
        self._remember_directory(str(path))
        self.project = project
        self._project_read_only_example = False
        self.setWindowTitle(f"{self._base_title} - {project.name}")
        self.tree.set_project(project)
        self._after_project_loaded()
        self.project_changed.emit()
        return True

    def _show_project_load_warnings(self, warnings: list[str]) -> None:
        details = "\n".join(f"• {warning}" for warning in warnings)
        QMessageBox.warning(self, "Project loaded with warnings", details)

    def _project_has_save_path(self) -> bool:
        return bool(
            self.project.root_path
            and Path(self.project.root_path).suffix.lower() == PORTABLE_PROJECT_SUFFIX
            and not self._project_read_only_example
            and not self._is_bundled_example_path(self.project.root_path)
        )

    def _update_project_save_actions(self) -> None:
        enabled = self._project_has_save_path()
        action = getattr(self, "save_project_action", None)
        if action is not None:
            action.setEnabled(enabled)
        toolbar = getattr(self, "finder_top_toolbar", None)
        if toolbar is not None:
            toolbar.save_button.setEnabled(enabled)

    def _project_save_snapshot(self) -> str:
        self._sync_finder_state_to_project()
        state = asdict(self.project)
        for key in ("root_path", "updated_at", "analysis_summary"):
            state.pop(key, None)
        # Browsing a saved project is not an edit, even though its view is portable.
        for key in (
            "current_object_type", "current_object_id", "tree_expansion_state",
            "right_tab", "candidate_current_row", "match_current_row", "plot_view_range",
        ):
            state["finder_state"].pop(key, None)
        return json.dumps(state, sort_keys=True)

    def _remember_saved_project_state(self) -> None:
        try:
            self._saved_project_snapshot = self._project_save_snapshot()
        except (OSError, ValueError, TypeError):
            self._saved_project_snapshot = None
        self._update_project_save_actions()

    def _has_unsaved_changes(self) -> bool:
        if self._project_read_only_example:
            return False
        if not self._project_has_save_path() and (
            self.project.patterns or self.project.phases or self.project.structures
            or self.project.series or self.project.analyses or self.project.refinements
            or self.project.notes
        ):
            return True
        try:
            return self._project_save_snapshot() != self._saved_project_snapshot
        except (OSError, ValueError, TypeError):
            # An unreadable asset must never make unsaved work look unchanged.
            return True

    def _confirm_project_replacement(self) -> bool:
        if not self._has_unsaved_changes():
            return True
        response = QMessageBox.question(
            self,
            "Unsaved project changes",
            "Save changes to the current project before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if response == QMessageBox.StandardButton.Discard:
            return True
        if response == QMessageBox.StandardButton.Save:
            return self._save_project() if self._project_has_save_path() else self._save_project_as()
        return False

    def _is_bundled_example_path(self, path: str | Path) -> bool:
        example = Path(__file__).resolve().parents[1] / "examples" / "XRD_Phase_Finder_example.xpff"
        return Path(path).resolve() == example

    def _save_project(self) -> bool:
        if not self._project_has_save_path():
            return False
        return self._write_project(self.project.root_path)

    def _save_project_as(self) -> bool:
        current_path = Path(self.project.root_path) if self.project.root_path else None
        if self._project_read_only_example:
            default_path = str(Path.home() / "Documents" / f"{self.project.name}_copy{PORTABLE_PROJECT_SUFFIX}")
        elif current_path is not None and current_path.suffix.lower() == PORTABLE_PROJECT_SUFFIX:
            default_path = str(current_path)
        else:
            default_path = str(Path(self._last_directory()) / f"{self.project.name}{PORTABLE_PROJECT_SUFFIX}")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save XRD Phase Finder File",
            default_path,
            "XRD Phase Finder File (*.xpff)",
        )
        if not path:
            return False
        selected = Path(path)
        if selected.suffix.lower() != PORTABLE_PROJECT_SUFFIX:
            path = str(selected.with_name(selected.name + PORTABLE_PROJECT_SUFFIX))
            if Path(path).exists() and QMessageBox.question(
                self,
                "Replace existing project",
                f"The file already exists:\n{path}\n\nReplace it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return False
        return self._write_project(path)

    @traced_operation("project.save")
    def _write_project(self, path: str | Path) -> bool:
        path = str(path)
        if self._is_bundled_example_path(path):
            self._show_example_read_only_message()
            return False
        try:
            self._sync_finder_state_to_project()
            self.project.touch()
            save_project_manifest(self.project, path)
            self.project.root_path = path
        except Exception as exc:
            QMessageBox.warning(self, "Save project failed", str(exc))
            return False
        self._project_read_only_example = False
        self.setWindowTitle(f"{self._base_title} - {self.project.name}")
        self._remember_saved_project_state()
        self.background_status_changed.emit(f"Project saved: {path}")
        self._remember_directory(path)
        return True

    def _after_new_project(self) -> None:
        self._on_project_tree_selection_changed()

    def _after_project_loaded(self) -> None:
        self._after_new_project()

    def _import_scientific_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import XRD data or CIF structure",
            self._last_directory(),
            "XRD and structure files (*.xy *.txt *.dat *.csv *.xye *.cif);;XRD patterns (*.xy *.txt *.dat *.csv *.xye);;CIF structures (*.cif);;All files (*.*)",
        )
        if not paths:
            return
        self._import_scientific_paths([Path(path) for path in paths])

    @traced_operation("import.scientific")
    def _import_scientific_paths(
        self,
        paths: list[Path],
        *,
        target_series_id: str | None = None,
        use_current_series: bool = True,
        refresh: bool = True,
        show_errors: bool = True,
        remember_directory: bool = True,
    ) -> tuple[bool, list[str]]:
        paths = [path for path in paths if path.is_file()]
        if not paths:
            return False, []
        if remember_directory:
            self._remember_directory(paths[0])
        imported = False
        if use_current_series:
            target_series_id = self._series_id_for_new_project_object()
        errors: list[str] = []
        for path in paths:
            suffix = path.suffix.lower()
            if suffix not in self.IMPORT_SUFFIXES:
                errors.append(f"{path.name}: unsupported file type")
                continue
            try:
                if suffix == ".cif":
                    phase, structure = create_phase_from_cif(path)
                    self._after_cif_import(path, phase, structure)
                    self.project.phases.append(phase)
                    self.project.structures.append(structure)
                    if target_series_id:
                        self.project.assign_object_to_series("phase", phase.id, target_series_id)
                else:
                    data = load_xy(path)
                    pattern = Pattern.create(name=path.stem, source_path=str(path))
                    self.project.patterns.append(pattern)
                    from xrd_finder.ui.xrd_range_warning import warn_outside_xrd_range
                    warn_outside_xrd_range(self, pattern, data[:, 0])
                    if target_series_id:
                        self.project.assign_object_to_series("pattern", pattern.id, target_series_id)
                imported = True
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")

        if imported and refresh:
            self._finalize_scientific_import()
        if errors and show_errors:
            QMessageBox.warning(self, "Import", "\n".join(errors[:5]))
        return imported, errors

    def _finalize_scientific_import(self) -> None:
        self.tree.set_project(self.project)
        self._on_project_tree_selection_changed()
        if hasattr(self, "_refresh_project_phase_candidates"):
            self._refresh_project_phase_candidates()
        self.project_changed.emit()

    def _import_scientific_drop_paths(self, paths: list[Path]) -> None:
        files = [path for path in paths if path.is_file()]
        directories = [path for path in paths if path.is_dir()]
        if not files and not directories:
            return
        self._remember_directory(paths[0])
        imported_any = False
        errors: list[str] = []
        if files:
            imported, file_errors = self._import_scientific_paths(
                files,
                refresh=False,
                show_errors=False,
                remember_directory=False,
            )
            imported_any = imported_any or imported
            errors.extend(file_errors)

        existing_names = [series.name for series in self.project.series]
        for directory in directories:
            groups = collect_scientific_folder_groups(directory, self.IMPORT_SUFFIXES)
            if not groups:
                errors.append(f"{directory.name}: no supported XRD/CIF files")
                continue
            for group in groups:
                series_name = unique_series_name(group.name, existing_names)
                series = SeriesAnalysis.create(name=series_name, kind="collection")
                self.project.series.append(series)
                imported, group_errors = self._import_scientific_paths(
                    list(group.paths),
                    target_series_id=series.id,
                    use_current_series=False,
                    refresh=False,
                    show_errors=False,
                    remember_directory=False,
                )
                errors.extend(f"{group.name}/{error}" for error in group_errors)
                if imported:
                    imported_any = True
                    existing_names.append(series_name)
                else:
                    self.project.series = [item for item in self.project.series if item.id != series.id]

        if imported_any:
            self._finalize_scientific_import()
        if errors:
            QMessageBox.warning(self, "Import", "\n".join(errors[:5]))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._drop_file_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._drop_file_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._drop_file_paths(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._import_scientific_drop_paths(paths)

    def _drop_file_paths(self, event) -> list[Path]:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_dir() or (path.is_file() and path.suffix.lower() in self.IMPORT_SUFFIXES):
                paths.append(path)
        return paths

    def _register_drop_target(self, widget: QWidget) -> None:
        widget.setAcceptDrops(True)
        widget.installEventFilter(self)
        self._drop_targets.append(widget)

    def eventFilter(self, watched, event) -> bool:
        if watched in self._drop_targets:
            if event.type() in {QEvent.Type.DragEnter, QEvent.Type.DragMove}:
                paths = self._drop_file_paths(event)
                if paths:
                    event.acceptProposedAction()
                    return True
            if event.type() == QEvent.Type.Drop:
                paths = self._drop_file_paths(event)
                if paths:
                    event.acceptProposedAction()
                    self._import_scientific_drop_paths(paths)
                    return True
        return super().eventFilter(watched, event)

    def _last_directory(self) -> str:
        settings = app_settings()
        path = str(settings.value("files/last_directory", "", type=str) or "")
        return path if path and Path(path).exists() else str(Path.home())

    def _remember_directory(self, path: str | Path) -> None:
        source = Path(path)
        directory = source if source.is_dir() else source.parent
        if directory.exists():
            app_settings().setValue("files/last_directory", str(directory))

    def _after_cif_import(self, _path: Path, _phase, _structure) -> None:
        """Hook for subclasses that need to cache or index imported CIF files."""
        # Intentionally empty in the base standalone window.

    def _on_project_tree_selection_changed(self) -> None:
        """Hook for subclasses that react to tree selection/check-state changes."""
        # Intentionally empty in the base standalone window.

    def _active_pattern(self):
        current_pattern_id = self.tree.current_pattern_id()
        if current_pattern_id:
            for pattern in self.project.patterns:
                if pattern.id == current_pattern_id:
                    return pattern
        checked = self.tree.checked_pattern_ids()
        if checked:
            for pattern in self.project.patterns:
                if pattern.id == checked[0]:
                    return pattern
        return self.project.patterns[0] if self.project.patterns else None

    def _active_wavelength(self) -> float:
        pattern = self._active_pattern()
        return float(getattr(pattern, "wavelength", None) or CU_KA1_WAVELENGTH)

    def _plot_widget(self, title: str = "", xrd_navigation: bool = False) -> pg.PlotWidget:
        plot = create_xrd_plot_widget()
        if title:
            plot.setTitle(title, color="#111111", size="13pt")
        return plot

    def _table(self, headers: list[str], rows: list[list[str]]) -> QTableWidget:
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row[: len(headers)]):
                table.setItem(row_index, col_index, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        return table


class PhaseFinderWindow(
    ManualCalibrationActionsMixin,
    ManualPeakActionsMixin,
    FindPeaksActionsMixin,
    PeakInformationActionsMixin,
    PhaseFinderMenuActionsMixin,
    InterfaceScalingMixin,
    PhaseFinderPeakSelectionActionsMixin,
    GainLineMixin,
    GainCalculationMixin,
    PhaseFinderInstrumentProfileActionsMixin,
    PhaseFinderProjectStateActionsMixin,
    PhaseFinderProjectTreeActionsMixin,
    PhaseFinderSelectedPhasesActionsMixin,
    PhaseFinderCandidateInfoActionsMixin,
    PhaseFinderCandidateStructureActionsMixin,
    PhaseFinderPreprocessingActionsMixin,
    PhaseFinderObservedPatternActionsMixin,
    PhaseFinderPlotViewActionsMixin,
    PhaseFinderPlotActionsMixin,
    PhaseFinderCandidateSearchActionsMixin,
    PhaseFinderDatabaseActionsMixin,
    AnalysisWindow,
):
    def __init__(self, project: Project, *, defer_initial_plot: bool = False) -> None:
        self._defer_initial_plot = bool(defer_initial_plot)
        super().__init__(project, "Phase Finder")
        self.menu_bar = build_phase_finder_menu_bar(self)
        self.layout().setMenuBar(self.menu_bar)
        self.resize(1500, 850)
        self.right_tabs.setMinimumWidth(360)
        self._init_filter_state()
        self._init_services()
        self._init_runtime_state()
        self._init_instrument_profile_state()
        self._create_cursor_readout_panel()
        self._create_action_bar()
        self._create_top_toolbar()
        self._create_match_plot(project)
        self._create_candidate_tables()
        self._initialize_candidate_batch_updates()
        self._create_center_splitter()
        self.visible_profile_calculation_queue = VisibleProfileCalculationQueue(
            self._calculate_visible_profile,
            self,
        )
        self._create_right_tabs()
        self._init_interface_scaling()
        if project.root_path:
            # Saved Finder state is restored by _after_project_loaded().
            self._update_project_save_actions()
        else:
            self._remember_saved_project_state()
        self.post_match_pipeline = PostMatchPipeline(
            refresh_selected_profile=self._recalculate_match_profile,
            refine_indexed_cells=self._fit_active_sample_indexed_cells,
            refresh_gain=self._schedule_candidate_gain_ranking,
            should_autozoom=self._should_autozoom_match_profile,
        )
        self.gain_job_controller = GainJobController(self)
        self.gain_job_controller.drained.connect(self._finish_gain_close)
        available=self.screen().availableGeometry()
        self.resize(min(self.width(),available.width()-24),min(self.height(),available.height()-48))
        self._plot_initial_settings_timer.start(0)

    def _init_filter_state(self) -> None:
        self._search_mode = "search"
        self._manual_search_peaks: dict[str, list[float]] = {}
        self.element_table: PeriodicTableWidget | None = None
        self.element_states: dict[str, str] = {}
        self.selected_elements: set[str] = set()
        self.selected_element_order: list[str] = []
        self.exclude_all_other_elements = False
        self._last_formula_text = ""

    def _init_services(self) -> None:
        self.settings = app_settings()
        self.cod_online = CodOnlineService(
            status_callback=self.background_status_changed.emit,
            alert_callback=self.cod_server_alert.emit,
        )
        self.ccdc = CcdcService()
        self.local_phase_cache = LocalPhaseCache()
        self.candidate_line_provider = CandidateLineProvider(self.local_phase_cache)
        self.rruff = RruffService(self.local_phase_cache.root / "rruff")
        self.match_pdf2 = MatchPdf2Service(str(self.settings.value("match_pdf2/root", "", type=str) or "") or None)
        self.materials_project = MaterialsProjectService(
            str(self.settings.value("materials_project/api_key", "", type=str) or "")
        )
        self.aflow = AflowService()
        self.oqmd = OqmdService()
        self.calculated_pattern_service = CalculatedPatternService()
        self.finder_service = FinderService(self.calculated_pattern_service)
        self.refinement_service = RefinementService(self.calculated_pattern_service)
        self.indexed_cell_matching_service = IndexedCellMatchingService(self.refinement_service)
        self.candidate_search_service = CandidateSearchService(
            self.local_phase_cache,
            self.cod_online,
            self.ccdc,
            self.rruff,
            self.match_pdf2,
            self.materials_project,
            self.aflow,
            self.oqmd,
            status_callback=self.background_status_changed.emit,
            prepared_callback=self.candidate_prepared.emit,
            preparation_progress_callback=self.candidate_preparation_progress.emit,
        )
        self._background_tasks: set[BackgroundTaskHandle] = set()
        self._background_task_threads: set[BackgroundTaskHandle] = set()
        self._start_match_pdf2_preload()

    def _init_runtime_state(self) -> None:
        self.finder_action_bar: FinderActionBar | None = None
        self.pattern_display_order_ids = [pattern.id for pattern in self.project.patterns]
        self.search_input: QLineEdit | None = None
        self.name_input: QLineEdit | None = None
        self.elem_count_input: QLineEdit | None = None
        self.formula_sum_input: QLineEdit | None = None
        self.ccdc_doi_input: QLineEdit | None = None
        self.database_panel: DatabasePanelWidget | None = None
        self.compound_card: CompoundCardWidget | None = None
        self._init_plot_view_state()
        self.inorganics_checkbox: QCheckBox | None = None
        self.organics_checkbox: QCheckBox | None = None
        self.structural_data_checkbox: QCheckBox | None = None
        self.reference_patterns_checkbox: QCheckBox | None = None
        self.rank_by_probability_checkbox: QCheckBox | None = None
        self.plot_layers: dict[str, list] = {
            "observed": [],
            "pattern_legends": [],
            "phase_legend": [],
            "calculated_profile": [],
            "total_profile": [],
            "phase_profiles": [],
            "background": [],
            "amorphous": [],
            "difference": [],
            "peak_positions": [],
            "phase_ticks": [],
            "phase_peak_sticks": [],
            "peak_links": [],
            "coverage_markers": [],
            "peak_labels": [],
            "unknown_peaks": [],
            "hkl": [],
            "candidate_markers": [],
            "preview_profile": [],
            "preview_peak_positions": [],
            "preview_peak_links": [],
            "preview_hkl": [],
            "legend_info": [],
        }
        self.grid_visible = True
        self.show_hkl_labels = False
        self.cursor_position_enabled = True
        self.cursor_vertical_line_enabled = False
        self.cursor_position_line = None
        self.cursor_position_proxy = None
        self.cursor_position_status_label: QLabel | None = None
        self.scoring_status_label: QLabel | None = None
        self._scoring_source = "Auto"
        self._auto_scoring_cache: dict[tuple[object, ...], object] = {}
        self.legend_item = None
        self.active_overlay_entry_id: str | None = None
        self.match_candidates: list[dict[str, str]] = []
        self.match_structures: dict[str, object] = {}
        self.match_scales: dict[str, float] = {}
        self.match_quantities: dict[str, float] = {}
        self.match_iic: dict[str, float] = {}
        self._corundum_peak_cache: dict[tuple[float, float, float], list] = {}
        self.match_zero_shifts: dict[str, float] = {}
        self.match_cell_scales: dict[str, float] = {}
        self.match_alignment_scores: dict[str, str] = {}
        self._last_match_profile_fwhm: float | None = None
        self._last_match_profile_eta: float | None = None
        self._observed_probability_cache: tuple[tuple[object, ...], np.ndarray, np.ndarray, list[tuple[float, float]]] | None = None
        self._candidate_peak_cache: dict[tuple[object, ...], list] = {}
        self._candidate_json_peak_cache: dict[tuple[object, ...], list[HKLPeak]] = {}
        self._candidate_probability_cache: dict[tuple[object, ...], float] = {}
        self._candidate_gain_profile_cache: dict[tuple[object, ...], np.ndarray] = {}
        self._candidate_gain_indexed_evidence: dict[str, GainIndexedEvidence] = {}
        self._active_gain_stage = ""
        self._gain_overlap_locked = False
        self._candidate_preview_token = 0
        self.show_all_selected_patterns = False
        self.pattern_stack_offset_percent = 10
        self.normalize_observed_patterns = False
        self.observed_pattern_plot_context: dict[str, dict[str, object]] = {}
        self.observed_pattern_colors: dict[str, str] = {}
        # Phase colors are project-wide, so the same phase keeps the same color
        # when several observed patterns are shown or activated in turn.
        self.phase_colors: dict[str, str] = {}
        self.active_profile_pattern_id: str | None = None
        self.profile_states: dict[str, dict[str, object]] = {}
        self.analysis_preview_paths: dict[str, str] = {}
        self.match_profile_result_cache: dict[tuple[object, ...], object] = {}
        self._profile_state_loading = False
        self.match_plot_view_initialized = False
        self._pending_candidate_row = -1
        self._candidate_activation_timer = QTimer(self)
        self._candidate_activation_timer.setSingleShot(True)
        self._candidate_activation_timer.setInterval(120)
        self._candidate_activation_timer.timeout.connect(self._activate_pending_candidate_row)
        self._candidate_rank_token = 0
        self._candidate_rank_rows: list[list[str]] = []
        self._candidate_rank_scores: dict[int, float] = {}
        self._candidate_rank_index = 0
        self._candidate_hidden_match_by_key: dict[str, str] = {}
        self._candidate_gain_ranking_pending = False
        self._candidate_gain_ranking_running = False
        self._candidate_gain_refresh_requested = False
        self._candidate_gain_refresh_after_preparation = False
        self._candidate_gain_idle_check_pending = False

    def _candidate_copy_list(self, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        copies = [dict(candidate) for candidate in candidates]
        entries = self.local_phase_cache.iic_entries(
            (self._candidate_source(candidate), candidate.get("Entry", ""))
            for candidate in copies
            if candidate.get("_IicProvenance") != "reference"
        )
        for candidate in copies:
            key = (self._candidate_source(candidate), candidate.get("Entry", ""))
            self._apply_cached_iic(candidate, entries.get(key), lookup_cache=False)
        return copies

    def _current_profile_pattern_id(self) -> str | None:
        pattern = self._active_pattern()
        return pattern.id if pattern is not None else None

    def _save_active_profile_state(self) -> None:
        if getattr(self, "_profile_state_loading", False):
            return
        pattern_id = self.active_profile_pattern_id or self._current_profile_pattern_id()
        if not pattern_id:
            return
        state = self.profile_states.setdefault(pattern_id, {})
        state["candidates"] = self._candidate_copy_list(self.match_candidates)
        state["gain_overlap_locked"] = bool(self._gain_overlap_locked)

    def _load_profile_state(self, pattern_id: str | None) -> None:
        self._profile_state_loading = True
        try:
            state = self.profile_states.get(pattern_id or "", {})
            candidates = state.get("candidates", [])
            self.match_candidates = self._candidate_copy_list(candidates) if isinstance(candidates, list) else []
            self._gain_overlap_locked = bool(state.get("gain_overlap_locked", False))
            self._active_gain_stage = ""
            self.match_structures.clear()
            self.match_scales.clear()
            self.match_quantities.clear()
            self.match_iic.clear()
            self.match_zero_shifts.clear()
            self.match_cell_scales.clear()
            self.match_alignment_scores.clear()
            if hasattr(self, "_update_match_table"):
                self._update_match_table()
        finally:
            self._profile_state_loading = False
        self._sync_zero_shift_controls()

    def _activate_profile_state_for_pattern(self, pattern_id: str | None) -> None:
        if not pattern_id:
            return
        previous_id = self.active_profile_pattern_id
        if previous_id == pattern_id:
            return
        if previous_id and self._search_mode in {"auto", "peaks"}:
            self._cancel_candidate_search_jobs()
        if previous_id:
            self._save_active_profile_state()
        elif self.match_candidates and pattern_id not in self.profile_states:
            self.active_profile_pattern_id = pattern_id
            self._save_active_profile_state()
        self.active_profile_pattern_id = pattern_id
        self._load_profile_state(pattern_id)
        self._redraw_selected_search_peaks()

    def _activate_current_profile_state(self) -> None:
        self._activate_profile_state_for_pattern(self._current_profile_pattern_id())

    def _profile_candidates_for_pattern(self, pattern) -> list[dict[str, str]]:
        if pattern is None:
            return []
        if pattern.id == self.active_profile_pattern_id:
            return self._candidate_copy_list(self.match_candidates)
        state = self.profile_states.get(pattern.id, {})
        candidates = state.get("candidates", [])
        return self._candidate_copy_list(candidates) if isinstance(candidates, list) else []

    def _invalidate_match_profile_cache(self, pattern_id: str | None = None) -> None:
        queue = getattr(self, '_accepted_profile_queue', None)
        if queue is not None:
            queue.invalidate()
        if pattern_id is None:
            try:
                self.finder_service.clear_observed_cache()
            except Exception:
                pass
            self.match_profile_result_cache.clear()
            selected = getattr(self, '_peak_info_selected', None)
            if selected is not None:
                self._refresh_peak_information_assignments(selected['pattern_id'])
            return
        self.match_profile_result_cache = {
            key: value
            for key, value in self.match_profile_result_cache.items()
            if not key or key[0] != pattern_id
        }
        self._refresh_peak_information_assignments(pattern_id)

    def _finder_cache_key(
        self,
        pattern,
        candidates: list[dict[str, str]],
        *,
        snap_peak_positions: bool = True,
    ) -> tuple[object, ...]:
        processed_observed = self._pattern_finder_observed_data(pattern)
        background_data = self._pattern_finder_background_data(pattern)
        background_signature = self._finder_background_signature(background_data)
        structure_overrides = self._finder_candidate_structure_overrides(pattern, candidates)
        if processed_observed is None or len(processed_observed) == 0:
            observed_signature = None
        else:
            x_values = processed_observed[:, 0]
            y_values = processed_observed[:, 1]
            observed_signature = (
                array_fingerprint(x_values),
                array_fingerprint(y_values),
                bool(self._pattern_finder_background_removed(pattern)),
                bool(self.normalize_observed_patterns),
                getattr(self, "_scoring_source", "Auto"),
            )
        candidate_signature = []
        for candidate in candidates:
            resolution = self.candidate_line_provider.resolve(candidate)
            line_fingerprint = (
                None
                if resolution.line_set is None
                else resolution.line_set.fingerprint
            )
            cif_path = ""
            local_path = None
            try:
                local_path = self._candidate_local_cif_path(candidate)
                if line_fingerprint is None:
                    cif_path = "" if local_path is None else str(local_path)
            except Exception:
                pass
            candidate_signature.append((
                self._candidate_source(candidate),
                candidate.get("Entry", ""),
                candidate.get("Formula", ""),
                candidate.get("Phase", "") or candidate.get("Name", ""),
                line_fingerprint,
                cif_path,
                self._structure_cell_signature(structure_overrides.get(self._candidate_key(candidate))),
                None if (initial_cell := resolve_candidate_initial_cell(
                    candidate, structure_overrides.get(self._candidate_key(candidate)))) is None else tuple(
                    round(float(getattr(initial_cell, name)), 8)
                    for name in ("a", "b", "c", "alpha", "beta", "gamma")
                ),
                quantification_source_signature(
                    local_path, structure_overrides.get(self._candidate_key(candidate))
                ),
            ))
        instrument_profile = self._instrument_profile_for_pattern(pattern)
        wavelength, include_kalpha2 = self._legacy_radiation_for_pattern(pattern)
        return (
            pattern.id,
            str(getattr(pattern, "source_path", "")),
            float(wavelength),
            bool(include_kalpha2),
            instrument_profile.calculation_key(),
            observed_signature,
            background_signature,
            bool(snap_peak_positions),
            tuple(candidate_signature),
        )

    def _finder_result_for_pattern(
        self,
        pattern,
        candidates: list[dict[str, str]],
        *,
        snap_peak_positions: bool = True,
        cache_only: bool = False,
        background: bool = False,
    ):
        if getattr(pattern, 'input_kind', '') == 'peak_list':
            return None, {}
        instrument = self._instrument_profile_for_pattern(pattern)
        candidate_build = build_finder_candidate_inputs(
            candidates,
            self._candidate_cif_path,
            self._candidate_key,
            self._candidate_phase_name,
            self._candidate_source,
            line_resolver=lambda candidate: self.candidate_line_provider.resolve(candidate,
                wavelength=float(instrument.radiation.components[0].wavelength_angstrom)),
            cell_resolver=lambda candidate: resolve_candidate_initial_cell(
                candidate, self.match_structures.get(self._candidate_key(candidate))),
            quantification_cif_path=self._candidate_local_cif_path,
        )
        finder_candidates = candidate_build.ready
        candidate_by_key = candidate_build.candidate_by_key
        self._finder_candidates_needing_index = list(candidate_build.needs_index)
        if not finder_candidates:
            return None, candidate_by_key
        cache_key = self._finder_cache_key(pattern, candidates, snap_peak_positions=snap_peak_positions)
        result = self.match_profile_result_cache.get(cache_key)
        if result is not None:
            self._record_pattern_zero_shift(pattern, result)
            return result, candidate_by_key
        if cache_only:
            return None, candidate_by_key
        processed_observed = self._pattern_finder_observed_data(pattern)
        background_data = self._pattern_finder_background_data(pattern)
        structure_overrides = self._finder_candidate_structure_overrides(pattern, candidates)
        for finder_candidate in finder_candidates:
            if finder_candidate.cif_path:
                continue
            structure = candidate_structure_override(finder_candidate, structure_overrides)
            if structure is not None:
                finder_candidate.structure = structure
        wavelength, include_kalpha2 = self._legacy_radiation_for_pattern(pattern)
        inputs = FinderInput(
                pattern_path=pattern.source_path,
                candidates=finder_candidates,
                quantification_complete=len(finder_candidates) == len(candidates),
                refine_sample_broadening=True,
                wavelength=wavelength,
                include_kalpha2=include_kalpha2,
                instrument_profile=self._instrument_profile_for_pattern(pattern),
                fwhm=self._legacy_fwhm_for_pattern(pattern),
                observed_x=processed_observed[:, 0].tolist() if processed_observed is not None else None,
                observed_y=processed_observed[:, 1].tolist() if processed_observed is not None else None,
                background_x=background_data[:, 0].tolist() if background_data is not None else None,
                background_y=background_data[:, 1].tolist() if background_data is not None else None,
                subtract_background=(
                    background_data is not None
                    or not bool(self._pattern_finder_background_removed(pattern))
                ),
                snap_peak_positions=bool(snap_peak_positions),
            )
        if background:
            from xrd_finder.ui.accepted_profile_job import AcceptedProfileQueue
            queue = getattr(self, '_accepted_profile_queue', None)
            if queue is None:
                queue = self._accepted_profile_queue = AcceptedProfileQueue(self)
            queue.request(pattern, cache_key, inputs)
            return None, candidate_by_key
        result = self.finder_service.run(inputs)
        self.match_profile_result_cache[cache_key] = result
        self._record_pattern_zero_shift(pattern, result)
        self._trim_match_profile_result_cache()
        return result, candidate_by_key

    def _finder_candidate_structure_overrides(self, pattern, candidates: list[dict[str, str]]) -> dict[str, object]:
        if pattern is None:
            return {}
        linked_phase_ids = set(getattr(pattern, "linked_phase_ids", []) or [])
        if not linked_phase_ids:
            return {}
        phase_by_id = {phase.id: phase for phase in self.project.phases if phase.id in linked_phase_ids}
        structure_by_id = {structure.id: structure for structure in self.project.structures}
        phase_by_source_path = {
            self._compound_card_path_key(getattr(phase, "source_path", "")): phase
            for phase in phase_by_id.values()
            if self._compound_card_path_key(getattr(phase, "source_path", ""))
        }
        phase_by_name_formula = {
            (str(phase.name or "").casefold(), str(phase.formula or "").casefold()): phase
            for phase in phase_by_id.values()
        }
        overrides: dict[str, object] = {}
        for candidate in candidates:
            phase = None
            if self._candidate_source(candidate) == "USER" and candidate.get("Entry") in phase_by_id:
                phase = phase_by_id.get(candidate.get("Entry", ""))
            if phase is None:
                try:
                    phase = phase_by_source_path.get(
                        self._compound_card_path_key(str(self._candidate_cif_path(candidate)))
                    )
                except Exception:
                    phase = None
            if phase is None:
                phase = phase_by_name_formula.get(
                    (
                        self._candidate_phase_name(candidate).casefold(),
                        str(candidate.get("Formula", "") or "").casefold(),
                    )
                )
            if phase is None:
                continue
            structure = structure_by_id.get(phase.structure_id or "") or next(
                (item for item in self.project.structures if item.phase_id == phase.id),
                None,
            )
            if structure is not None:
                overrides[self._candidate_key(candidate)] = structure
        return overrides


    def _pattern_finder_background_data(self, pattern) -> np.ndarray | None:
        if pattern is None:
            return None
        if self._pattern_finder_background_removed(pattern):
            return _processed_amorphous_background_data(pattern)
        points = getattr(pattern, "estimated_background_with_halo_points", None)
        if not points:
            points = getattr(pattern, "estimated_background_points", None)
        if not points:
            return None
        try:
            values = np.asarray(points, dtype=float)
        except Exception:
            return None
        if values.ndim != 2 or values.shape[1] < 2 or len(values) < 2:
            return None
        values = values[:, :2]
        mask = np.isfinite(values[:, 0]) & np.isfinite(values[:, 1])
        if np.count_nonzero(mask) < 2:
            return None
        return values[mask]

    def _finder_background_signature(self, background_data: np.ndarray | None) -> tuple[object, ...] | None:
        if background_data is None or len(background_data) == 0:
            return None
        x_values = np.asarray(background_data[:, 0], dtype=float)
        y_values = np.asarray(background_data[:, 1], dtype=float)
        return (array_fingerprint(x_values), array_fingerprint(y_values))

    def _create_cursor_readout_panel(self) -> None:
        self.finder_plot_control_bar = FinderPlotControlBar()
        self.cursor_status_panel = self.finder_plot_control_bar
        self.cursor_position_status_label = self.finder_plot_control_bar.cursor_position_status_label
        self.scoring_status_label = None
        self.finder_plot_control_bar.patternDisplayModeChanged.connect(self._set_pattern_display_mode)
        self.finder_plot_control_bar.plotAspectModeChanged.connect(self._set_plot_aspect_mode)
        self.finder_plot_control_bar.patternOffsetPercentChanged.connect(self._set_pattern_stack_offset)
        self.finder_plot_control_bar.normalizePatternsChanged.connect(self._set_pattern_normalization)
        self.finder_plot_control_bar.zeroCorrectionChanged.connect(self._set_zero_correction_visible)

    def _scoring_source_status_text(self) -> str:
        return f"Score: {getattr(self, '_scoring_source', 'Auto')}"

    def _set_scoring_source_status(self, source: str) -> None:
        self._scoring_source = source
        if getattr(self, "scoring_status_label", None) is not None:
            self.scoring_status_label.setText(self._scoring_source_status_text())

    def _create_action_bar(self) -> None:
        self.finder_action_bar = FinderActionBar()
        self.finder_action_bar.smoothRequested.connect(self._smooth_active_pattern_plot)
        self.finder_action_bar.cropRequested.connect(self._crop_xrd_patterns_plot)
        self.finder_action_bar.subtractBackgroundRequested.connect(self._subtract_active_background_plot)
        self.finder_action_bar.searchRequested.connect(self._search_pdf2_text)
        self.finder_action_bar.instrumentProfileSelected.connect(self._select_instrument_profile)
        self.finder_action_bar.instrumentProfileEditRequested.connect(self._open_instrument_profile_editor)
        self.finder_action_bar.manualZeroShiftChanged.connect(self._set_manual_zero_shift)
        self.search_input = self.finder_action_bar.search_input
        self._refresh_instrument_profile_selector()
        self._sync_zero_shift_controls()

    def _set_auto_search_busy(self, busy: bool) -> None:
        self._auto_search_in_progress = bool(busy)
        toolbar = getattr(self, "finder_top_toolbar", None)
        if toolbar is not None:
            toolbar.set_auto_search_busy(busy)
        controller = getattr(self, "_candidate_batch_updates", None)
        self._set_candidate_batch_state("busy" if busy else controller.activity_state if controller is not None else "idle")
        if hasattr(self, '_refresh_candidate_score_labels'):
            self._refresh_candidate_score_labels()

    def _refresh_candidate_score_labels(self) -> None:
        table = getattr(self, 'candidate_table', None)
        if table is None or not hasattr(table, 'set_score_context'):
            return
        rank = getattr(self, 'rank_by_probability_checkbox', None)
        gain = getattr(self, 'gain_job_controller', None)
        match = getattr(self, '_loaded_match_queue', None)
        pattern = self._active_pattern()
        table.set_score_context(
            has_pattern=pattern is not None,
            match_enabled=getattr(self, '_search_mode', 'search') == 'peaks' or (rank is not None and rank.isChecked()),
            gain_enabled=bool(getattr(self, '_candidate_gain_auto_enabled', False)),
            match_busy=bool(getattr(self, '_auto_search_in_progress', False) or getattr(match, 'running', False)),
            gain_busy=bool(getattr(gain, 'running', False)),
            identity=(getattr(pattern, 'id', None), getattr(self, '_candidate_rank_token', 0)))

    def _create_top_toolbar(self) -> None:
        self.finder_top_toolbar = FinderTopToolBar()
        self.finder_top_toolbar.newProjectRequested.connect(self._new_project)
        self.finder_top_toolbar.openProjectRequested.connect(self._load_project)
        self.finder_top_toolbar.saveProjectRequested.connect(self._save_project)
        self.finder_top_toolbar.importRequested.connect(self._import_scientific_files)
        self.finder_top_toolbar.autoSearchRequested.connect(self._auto_search_candidates)
        self.finder_top_toolbar.peakSearchRequested.connect(self._toggle_peak_search)
        self.finder_top_toolbar.resetDataRequested.connect(self._reset_observed_preprocessing)
        self.finder_top_toolbar.resetViewRequested.connect(self._reset_match_plot_view)
        self.finder_top_toolbar.databaseSettingsRequested.connect(self._show_database_settings_window)
        self.finder_top_toolbar.plotAppearanceRequested.connect(self._show_plot_view_settings_window)
        self.finder_top_toolbar.instrumentSettingsRequested.connect(self._open_instrument_profile_editor)
        self.layout().insertWidget(0, self.finder_top_toolbar)

    def _create_match_plot(self, project: Project) -> None:
        self.match_plot = self._plot_widget("Phase Finder: pattern and candidate phase markers", xrd_navigation=True)
        self.match_plot.getViewBox().full_range_callback = self._reset_match_plot_view
        self.match_plot.setTitle("Phase Finder: pattern and candidate phase markers", color="#111111", size="13pt")
        self.match_plot.setLabel("bottom", "2theta", color="#111111", **{"font-size": "12pt"})
        self.match_plot.setLabel("left", "I rel.", color="#111111", **{"font-size": "12pt"})
        self.legend_item = ensure_right_legend(self.match_plot, clear=True)
        self.match_plot.getViewBox().sigRangeChanged.connect(self._schedule_multi_pattern_legend_layout)
        self.match_plot.getViewBox().sigResized.connect(self._schedule_multi_pattern_legend_layout)
        self.match_plot.getViewBox().sigRangeChangedManually.connect(self._remember_common_legend_manual_range)
        self.match_plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.match_plot.customContextMenuRequested.connect(self._show_plot_context_menu)
        self.match_plot.scene().sigMouseClicked.connect(self._on_search_peak_click)
        self._ensure_cursor_position_items()
        self._apply_saved_plot_view_settings()
        if project.patterns and not self._defer_initial_plot:
            try:
                self._refresh_observed_pattern_plot()
            except Exception:
                pass

    def _apply_saved_plot_view_settings(self) -> None:
        if hasattr(self, "match_plot") and hasattr(self, "plot_view_settings"):
            self._apply_plot_view_settings(self.plot_view_settings, force=True)

    def _create_candidate_tables(self) -> None:
        candidate_rows = self._project_phase_candidate_rows()

        self.candidate_table = CandidateTableWidget(candidate_rows)
        self.candidate_table.rowActivated.connect(self._queue_candidate_row_activation)
        self.candidate_table.addRequested.connect(self._add_selected_candidate_to_match_list)
        self.candidate_table.contextRequested.connect(self._show_candidate_context_menu)
        self.match_table = SelectedCandidatesTableWidget()
        self.match_table.rowClicked.connect(self._on_match_row_clicked)
        self.match_table.contextRequested.connect(self._show_match_context_menu)
        self.match_table.phaseNameEdited.connect(self._rename_selected_match_phase)
        self.candidate_panel = QWidget()
        candidate_layout = QVBoxLayout(self.candidate_panel)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.setSpacing(4)
        self.candidate_list_label = QLabel("Candidate list")
        self.candidate_list_label.setProperty('uiRole', 'sectionTitle')
        self.candidate_search_detail_label = QLabel("")
        self.candidate_search_detail_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.candidate_search_detail_label.setMinimumHeight(28)
        self.candidate_search_detail_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.candidate_status_bar = QWidget()
        self.candidate_status_bar.setObjectName("candidateSearchStatus")
        candidate_header_layout = QHBoxLayout(self.candidate_status_bar)
        candidate_header_layout.setContentsMargins(8, 0, 8, 0)
        candidate_header_layout.setSpacing(8)
        candidate_header_layout.addWidget(self.candidate_list_label)
        candidate_header_layout.addWidget(self.candidate_search_detail_label, 1)
        self._set_candidate_status_state("idle")
        candidate_layout.addWidget(self.candidate_status_bar)
        candidate_layout.addWidget(self.candidate_table, 1)

    def _create_center_splitter(self) -> None:
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        self._layout_state.register("center_splitter", self.center_splitter)
        self.plot_canvas = QWidget()
        self.plot_canvas.setObjectName("plotCanvas")
        self.plot_canvas.installEventFilter(self)
        self.plot_canvas.setStyleSheet('QWidget#plotCanvas { background: #ffffff; border: 1px solid #dce3eb; border-radius: 9px; }')
        self.plot_canvas_layout = QGridLayout(self.plot_canvas)
        self.plot_canvas_layout.setContentsMargins(12, 10, 12, 12)
        self.plot_canvas_layout.setSpacing(0)
        self.plot_canvas_layout.addWidget(self.match_plot, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        self.plot_area = QWidget()
        plot_area_layout = QVBoxLayout(self.plot_area)
        plot_area_layout.setContentsMargins(0, 0, 0, 0)
        plot_area_layout.setSpacing(6)
        self.center_splitter.setHandleWidth(8)
        plot_area_layout.addWidget(self.plot_canvas, 1)
        plot_area_layout.addWidget(self.cursor_status_panel)
        self.center_splitter.addWidget(self.plot_area)
        self.center_splitter.addWidget(self.candidate_panel)
        self.center_splitter.setStretchFactor(0, 3)
        self.center_splitter.setStretchFactor(1, 2)
        self.center_splitter.setSizes([520, 260])
        self.center_layout.addWidget(self.center_splitter, 1)

    def _create_right_tabs(self) -> None:
        self.right_tabs.addTab(self._composition_tab(), "Elements")
        self.right_tabs.addTab(self.finder_action_bar, "Processing")
        self.compound_card = CompoundCardWidget()
        self.compound_card.cellFitRequested.connect(self._fit_active_sample_indexed_cells)
        if hasattr(self, "_update_compound_card_sample"):
            self._update_compound_card_sample()
        self.right_tabs.addTab(self.compound_card, "Phase details")
        self.right_tabs.tabBar().setTabData(self.right_tabs.count()-1,"Card")
        self._layout_state.register_table('candidates', self.candidate_table)
        self._layout_state.register_table('accepted', self.match_table)
        self._layout_state.add_pin_corner(self.right_tabs, self._show_quick_help)
        self._layout_state.restore()
        self._layout_state.apply_lock()
        saved_geometry = self.settings.value("layout/window_geometry", None)
        if saved_geometry is not None:
            self.restoreGeometry(saved_geometry)
        self._apply_default_phase_filter()

    def _after_new_project(self) -> None:
        self.project.finder_state = FinderProjectState()
        self._reset_phase_finder_state(
            candidate_rows=[["", "", "", "No phases yet", "", ""]],
            reset_plot_range=True,
        )

    def _after_project_loaded(self) -> None:
        self._reset_phase_finder_state(
            candidate_rows=self._project_phase_candidate_rows(),
            refresh_observed=False,
        )
        if getattr(self.project, "finder_state", None) is None:
            self._refresh_observed_pattern_plot()
        else:
            self._restore_finder_state_from_project()
        self._remember_saved_project_state()

    def _reset_phase_finder_state(
        self,
        candidate_rows: list[list[str]],
        *,
        reset_plot_range: bool = False,
        refresh_observed: bool = False,
    ) -> None:
        self._close_manual_calibration()
        if getattr(self, '_manual_peak_input_armed', False):
            self._close_manual_peak_editor()
        warning = getattr(self, '_xrd_range_warning_dialog', None)
        if warning is not None: warning.close()
        self._xrd_range_warnings = {}
        self._cancel_peak_information(close_card=True)
        preparation = getattr(self, '_observed_search_controller', None)
        if preparation is not None:
            preparation.invalidate()
            self._set_auto_search_busy(False)
        preview = getattr(self, 'preview_observation_controller', None)
        if preview is not None:
            preview.invalidate()
        self._candidate_preview_token = int(getattr(self, '_candidate_preview_token', 0)) + 1
        self._cancel_candidate_search_jobs()
        self._manual_search_peaks.clear()
        self._set_search_mode("search")
        queue = getattr(self, "visible_profile_calculation_queue", None)
        if queue is not None:
            queue.clear()
        self.pattern_display_order_ids = [pattern.id for pattern in self.project.patterns]
        self._clear_probability_caches()
        self.match_candidates.clear()
        self.match_structures.clear()
        self.match_scales.clear()
        self.match_quantities.clear()
        self.match_iic.clear()
        self.match_zero_shifts.clear()
        self.match_cell_scales.clear()
        self.match_alignment_scores.clear()
        self._active_gain_stage = ""
        self._gain_overlap_locked = False
        self.profile_states.clear()
        self.analysis_preview_paths.clear()
        self.phase_colors.clear()
        self.observed_pattern_colors.clear()
        self.match_profile_result_cache.clear()
        self.active_profile_pattern_id = None
        self.active_overlay_entry_id = None
        self.observed_pattern_plot_context.clear()
        self.match_plot_view_initialized = False
        for layer, items in list(self.plot_layers.items()):
            for item in items:
                try:
                    self.match_plot.removeItem(item)
                except Exception:
                    pass
            self.plot_layers[layer] = []
        self.legend_item = ensure_right_legend(self.match_plot, clear=True)
        self.legend_item.setVisible(bool(self.plot_view_settings.legend_visible))
        if reset_plot_range:
            self._apply_plot_view_settings(self.plot_view_settings)
            self.match_plot.setXRange(0, 1, padding=0.0)
            self.match_plot.setYRange(0, 1, padding=0.0)
        self._reset_selected_elements()
        self._set_candidate_rows(candidate_rows)
        self._update_match_table()
        if self.compound_card is not None:
            if hasattr(self, "_update_compound_card_sample"):
                self._update_compound_card_sample()
            self.compound_card.set_candidate(None)
        if refresh_observed:
            self._refresh_observed_pattern_plot()

    def _project_phase_candidate_rows(self) -> list[list[str]]:
        rows = [
            ["USER", phase.id, phase.formula, phase.name, "", "project structure"]
            for phase in self.project.phases
        ]
        return rows if rows else [["", "", "", "No phases yet", "", ""]]

    def reject(self) -> None:
        # QDialog maps Escape to reject(); route it through the same guarded
        # close path instead of silently discarding the current analysis.
        self.close()

    def closeEvent(self, event) -> None:
        if not getattr(self, '_preparation_close_confirmed', False):
            if not self._confirm_project_replacement():
                event.ignore()
                return
        self._preparation_close_confirmed = True
        self._close_manual_calibration()
        if getattr(self, '_manual_peak_input_armed', False):
            self._close_manual_peak_editor()
        activation_timer = getattr(self, '_candidate_activation_timer', None)
        if activation_timer is not None:
            activation_timer.stop()
        self._gain_close_confirmed = True
        self._cancel_candidate_search_jobs()
        preparations = (getattr(self, '_observed_search_controller', None),
                        getattr(self, 'preview_observation_controller', None),
                        getattr(self, 'gain_job_controller', None))
        drained = [controller.request_close() for controller in preparations if controller is not None]
        if not all(drained):
            self.setEnabled(False)
            event.ignore()
            return
        if self._background_task_threads:
            # SQL retrieval/ranking and reference preparation also own QThreads.
            # Keep the window alive until their stopped signals have arrived.
            self.setEnabled(False)
            event.ignore()
            return
        self._stop_candidate_batch_updates()
        queue = getattr(self, "visible_profile_calculation_queue", None)
        if queue is not None:
            queue.clear()
        self._save_workspace_preferences()
        self._layout_state.save()
        self.settings.setValue("layout/window_geometry", self.saveGeometry())
        self.settings.sync()
        self.candidate_search_service.shutdown_background_downloads()
        event.accept()

    def _finish_gain_close(self):
        if getattr(self, "_gain_close_confirmed", False):
            self.close()

    def _run_background_task(
        self,
        title: str,
        label: str,
        task,
        on_success,
        on_error=None,
        with_progress: bool = False,
        operation_name: str = "background.task",
        on_partial=None,
        show_progress_dialog: bool = False,
    ) -> None:
        self._set_background_status(label)

        progress_dialog = None
        if show_progress_dialog:
            progress_dialog = QProgressDialog(label, "", 0, 0, self)
            progress_dialog.setWindowTitle(title)
            progress_dialog.setCancelButton(None)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setAutoClose(False)
            progress_dialog.setAutoReset(False)
            progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            progress_dialog.setMinimumWidth(440)
            progress_dialog.show()
            progress_bar = progress_dialog.findChild(QProgressBar)
            if progress_bar is not None:
                progress_bar.hide()
            QApplication.processEvents()

        handle = BackgroundTaskHandle(
            task,
            self,
            accepts_progress=with_progress,
            accepts_partial=on_partial is not None,
            operation_name=operation_name,
        )
        self._background_tasks.add(handle)
        self._background_task_threads.add(handle)

        def cleanup() -> None:
            if progress_dialog is not None:
                progress_dialog.close()
            self._background_tasks.discard(handle)
            if not self._background_tasks and not getattr(self, '_preparation_close_confirmed', False):
                self._set_background_status('Ready')

        def stopped() -> None:
            self._background_task_threads.discard(handle)
            if getattr(self, '_preparation_close_confirmed', False):
                self._finish_preparation_close()

        def finish(result) -> None:
            cleanup()
            if not getattr(self, '_preparation_close_confirmed', False):
                on_success(result)

        def fail(message: str, details: str) -> None:
            cleanup()
            if getattr(self, '_preparation_close_confirmed', False):
                return
            self._set_background_status(f"{title}: failed — {message or 'no response'}")
            if on_error is not None:
                on_error(message, details)
            else:
                QMessageBox.warning(self, title, message or details)

        def progress(message: str, value: int, maximum: int) -> None:
            if getattr(self, '_preparation_close_confirmed', False):
                return
            if message:
                suffix = ""
                maximum = int(maximum)
                if maximum > 0:
                    value = max(0, min(int(value), maximum))
                    suffix = f" ({value}/{maximum})"
                self._set_background_status(f"{message}{suffix}")
                if progress_dialog is not None:
                    progress_dialog.setLabelText(message)
                    progress_bar = progress_dialog.findChild(QProgressBar)
                    if progress_bar is not None:
                        progress_bar.hide()
                    if maximum > 0:
                        progress_dialog.setRange(0, maximum)
                        progress_dialog.setValue(value)
                    else:
                        progress_dialog.setRange(0, 0)

        def show_waiting_status() -> None:
            if handle in self._background_tasks and not getattr(self, '_preparation_close_confirmed', False):
                self._set_background_status(f"{title}: waiting for response...")

        handle.progress.connect(progress)
        if on_partial is not None:
            handle.partial.connect(lambda result: on_partial(result)
                                   if not getattr(self, '_preparation_close_confirmed', False) else None)
        handle.finished.connect(finish)
        handle.failed.connect(fail)
        handle.stopped.connect(stopped)
        handle.start()
        QTimer.singleShot(8000, show_waiting_status)

    def _composition_tab(self) -> QWidget:
        panel = CompositionPanel(self.match_table, self._layout_state)
        panel.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        self.composition_panel = panel
        panel.requiredElementToggled.connect(self._toggle_required_element)
        panel.excludedElementToggled.connect(self._toggle_excluded_element)
        panel.elementsPainted.connect(self._paint_elements)
        panel.exclusionModeToggleRequested.connect(self._toggle_excluded_mode)
        panel.searchRequested.connect(self._search_candidates_in_current_mode)
        panel.resetRequested.connect(self._reset_candidate_search_table)

        self.composition_splitter = panel.splitter
        self.element_table = panel.element_table
        self.name_input = panel.name_input
        self.elem_count_input = panel.elem_count_input
        self.formula_sum_input = panel.formula_sum_input
        self.element_gate_label = panel.element_gate_label
        self.ccdc_doi_input = panel.ccdc_doi_input
        self.inorganics_checkbox = panel.inorganics_checkbox
        self.organics_checkbox = panel.organics_checkbox
        self.structural_data_checkbox = panel.structural_data_checkbox
        self.reference_patterns_checkbox = panel.reference_patterns_checkbox
        self.rank_by_probability_checkbox = panel.rank_by_probability_checkbox
        self.rank_by_probability_checkbox.toggled.connect(lambda _checked: self._refresh_candidate_score_labels())
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _show_quick_help(self) -> None:
        QMessageBox.information(self, PHASE_FINDER_HELP_TITLE, PHASE_FINDER_HELP_TEXT)

    def _refresh_network_mode_action(self) -> None:
        action = getattr(self, "network_mode_action", None)
        if action is None:
            return
        enabled = offline_mode_enabled()
        action.blockSignals(True)
        action.setChecked(enabled)
        action.setText(
            "Network mode: Offline / secure" if enabled else "Network mode: Online"
        )
        if env_offline_mode_enabled():
            action.setToolTip("Offline / secure mode is forced by XRD_FINDER_OFFLINE.")
        else:
            action.setToolTip(
                "Disable online database requests and use local caches only."
                if not enabled
                else "Online database requests are disabled; local caches remain available."
            )
        action.blockSignals(False)

    def _toggle_network_mode(self) -> None:
        if env_offline_mode_enabled():
            QMessageBox.information(
                self,
                "Network mode",
                "Offline / secure mode is forced by XRD_FINDER_OFFLINE.\n\n"
                "Unset that environment variable before switching back to online mode.",
            )
            self._refresh_network_mode_action()
            return
        enabled = not offline_mode_enabled()
        path = set_saved_offline_mode_enabled(enabled)
        self._refresh_network_mode_action()
        QMessageBox.information(
            self,
            "Network mode",
            (
                "Offline / secure mode is now enabled.\n\n"
                "Online database requests are disabled. Local projects, user CIF libraries, "
                "local SQL indexes and cached phase libraries remain available.\n\n"
                f"Saved to:\n{path}"
                if enabled
                else
                "Online mode is now enabled.\n\n"
                "Online sources can be used when they are enabled in Database settings and "
                "the network is available."
            ),
        )

    def _create_secure_macos_installer(self) -> None:
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose secure installer output folder",
            str(Path.cwd() / "dist"),
        )
        if not output_dir:
            return

        progress_dialog = QProgressDialog(
            "Preparing secure macOS installer...",
            "",
            0,
            0,
            self,
        )
        progress_dialog.setWindowTitle("Secure macOS installer")
        progress_dialog.setCancelButton(None)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.show()

        def task(progress_emit):
            return build_secure_macos_pkg(
                output_dir=output_dir,
                progress=lambda message: progress_emit(message, 0, 0),
            )

        handle = BackgroundTaskHandle(
            task,
            parent=self,
            accepts_progress=True,
            operation_name="secure_installer.build_macos_pkg",
        )
        self._secure_installer_task = handle

        def on_progress(message: str, _value: int, _maximum: int) -> None:
            progress_dialog.setLabelText(message)

        def on_finished(result: object) -> None:
            progress_dialog.close()
            self._secure_installer_task = None
            QMessageBox.information(
                self,
                "Secure macOS installer",
                "Secure/offline installer was created:\n\n"
                f"{result}\n\n"
                "It installs the application, the current Sci runtime, local Finder data, "
                "cached databases and secure/offline mode settings.",
            )

        def on_failed(message: str, details: str) -> None:
            progress_dialog.close()
            self._secure_installer_task = None
            box = QMessageBox(QMessageBox.Critical, "Secure macOS installer", message, parent=self)
            box.setInformativeText(
                "The secure installer was not created. Check that Xcode Command Line Tools "
                "are installed and that the Sci runtime is already prepared on this Mac."
            )
            box.setDetailedText(details)
            box.exec()

        handle.progress.connect(on_progress)
        handle.finished.connect(on_finished)
        handle.failed.connect(on_failed)
        handle.start()

    def _create_secure_windows_installer(self) -> None:
        output_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose secure installer output folder",
            str(Path.cwd() / "dist" / "secure"),
        )
        if not output_dir:
            return

        progress_dialog = QProgressDialog(
            "Preparing secure Windows installer...",
            "",
            0,
            0,
            self,
        )
        progress_dialog.setWindowTitle("Secure Windows installer")
        progress_dialog.setCancelButton(None)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.show()

        def task(progress_emit):
            return build_secure_windows_installer(
                output_dir=output_dir,
                progress=lambda message: progress_emit(message, 0, 0),
            )

        handle = BackgroundTaskHandle(
            task,
            parent=self,
            accepts_progress=True,
            operation_name="secure_installer.build_windows_installer",
        )
        self._secure_windows_installer_task = handle

        def on_progress(message: str, _value: int, _maximum: int) -> None:
            progress_dialog.setLabelText(message)

        def on_finished(result: object) -> None:
            progress_dialog.close()
            self._secure_windows_installer_task = None
            QMessageBox.information(
                self,
                "Secure Windows installer",
                "Secure/offline Windows installer was created:\n\n"
                f"{result}\n\n"
                "It installs the application, the prepared Sci runtime, local Finder data, "
                "cached databases and secure/offline mode settings. Keep this local package "
                "out of public GitHub releases because it contains local data.",
            )

        def on_failed(message: str, details: str) -> None:
            progress_dialog.close()
            self._secure_windows_installer_task = None
            box = QMessageBox(QMessageBox.Critical, "Secure Windows installer", message, parent=self)
            box.setInformativeText(
                "The secure installer was not created. Check that Inno Setup is installed "
                "and that the Sci runtime is already prepared on this Windows computer."
            )
            box.setDetailedText(details)
            box.exec()

        handle.progress.connect(on_progress)
        handle.finished.connect(on_finished)
        handle.failed.connect(on_failed)
        handle.start()

    def _show_security_info_dialog(self) -> None:
        mode = "Offline / secure" if offline_mode_enabled() else "Online"
        settings_path = security_settings_path()
        QMessageBox.information(
            self,
            "Security and offline use",
            (
                f"Current network mode: {mode}\n\n"
                "XRD Phase Finder has no telemetry. Online access is used only for visible "
                "operations such as update checks, online database searches and requested "
                "downloads from COD, Materials Project, AFLOW, OQMD, RRUFF or CCDC.\n\n"
                "Offline / secure mode disables online database requests. Local projects, "
                "user CIF libraries, local SQL indexes and cached phase libraries remain available.\n\n"
                "Runtime diagnostics are local-only, capped and path-redacted. Start with "
                "XRD_FINDER_DIAGNOSTICS=0 to disable them on locked-down workstations.\n\n"
                f"Saved security mode file:\n{settings_path}"
            ),
        )

    def _show_example_read_only_message(self) -> None:
        QMessageBox.information(
            self,
            "Example project",
            "The bundled example cannot be overwritten. Use Save project as... to create an editable copy.",
        )

    def _open_example_project(self) -> None:
        example_path = Path(__file__).resolve().parents[1] / "examples" / "XRD_Phase_Finder_example.xpff"
        if not example_path.is_file():
            QMessageBox.warning(
                self,
                "Example project",
                f"Example project is missing:\n{example_path}",
            )
            return
        if self._open_project_path(example_path):
            self.project.root_path = ""
            self._project_read_only_example = True
            self._update_project_save_actions()
            self.setWindowTitle(f"{self._base_title} - {self.project.name} (example)")
            QMessageBox.information(
                self,
                "Example project",
                "The bundled example is protected. Use Save project as... to create your own editable copy.",
            )

    def _show_about_dialog(self) -> None:
        QMessageBox.about(
            self,
            "About XRD Phase Finder",
            (
                f"<b>XRD Phase Finder {__version__}</b><br><br>"
                "Open-source desktop application for powder X-ray diffraction phase identification.<br><br>"
                "It helps load experimental XRD patterns, search local and online phase sources, "
                "compare calculated and reference peaks with the experiment, and save the full "
                "interpretation state in portable .xpff project files.<br><br>"
                "<b>Security / offline use</b><br>"
                "No telemetry. Offline / secure mode disables online database requests and "
                "keeps local caches available. Runtime diagnostics are local-only and can be "
                "disabled with <code>XRD_FINDER_DIAGNOSTICS=0</code>.<br><br>"
                'Project: <a href="https://github.com/ABKuznetsov/XRD_Analysis_Toolkit">'
                "github.com/ABKuznetsov/XRD_Analysis_Toolkit</a><br>"
                "License: MIT"
            ),
        )

    def _export_user_settings(self) -> None:
        default_path = Path.home() / "Desktop" / "xrd_phase_finder_settings.json"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export XRD Phase Finder settings",
            str(default_path),
            "XRD Phase Finder settings (*.json);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            export_user_settings_bundle(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "Export settings failed", str(exc))
            return
        message = f"Settings were exported to:\n{path}"
        api_key = str(
            self.settings.value("materials_project/api_key", "", type=str) or ""
        ).strip()
        if api_key:
            QMessageBox.warning(
                self,
                "Export settings",
                message
                + "\n\nThis file contains the saved Materials Project API key in readable form. "
                "Keep it private and do not publish it.",
            )
        else:
            QMessageBox.information(self, "Export settings", message)

    def _import_user_settings(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import XRD Phase Finder settings",
            str(Path.home()),
            "XRD Phase Finder settings (*.json);;JSON files (*.json);;All files (*)",
        )
        if not path:
            return
        try:
            import_user_settings_bundle(Path(path))
            self._reload_imported_user_settings()
        except Exception as exc:
            QMessageBox.warning(self, "Import settings failed", str(exc))
            return
        QMessageBox.information(
            self,
            "Import settings",
            "Settings were imported. Plot appearance and instrument profiles were refreshed. Window layout is fully applied on the next launch.",
        )

    def _reload_imported_user_settings(self) -> None:
        self.settings = app_settings()
        imported_plot_settings = PlotViewSettingsWidget.load_saved_default_settings() or PlotViewSettings()
        self.plot_view_settings = imported_plot_settings
        if getattr(self, "plot_settings_panel", None) is not None:
            self.plot_settings_panel.set_settings(imported_plot_settings, emit=False)
        if hasattr(self, "match_plot"):
            self._apply_plot_view_settings(imported_plot_settings, force=True)
        if hasattr(self, "instrument_profile_library"):
            self.instrument_profile_library = InstrumentProfileLibrary()
            preferred_id = str(
                self.settings.value("instrument/active_profile_id", BUILTIN_PROFILE_ID, type=str)
                or BUILTIN_PROFILE_ID
            )
            if self.instrument_profile_library.get(preferred_id) is None:
                preferred_id = BUILTIN_PROFILE_ID
            self._selected_instrument_profile_id = preferred_id
            self._refresh_instrument_profile_selector()
        self.match_pdf2 = MatchPdf2Service(str(self.settings.value("match_pdf2/root", "", type=str) or "") or None)
        self.materials_project = MaterialsProjectService(
            str(self.settings.value("materials_project/api_key", "", type=str) or "")
        )
        self.candidate_search_service.match_pdf2 = self.match_pdf2
        self.candidate_search_service.materials_project = self.materials_project
        if getattr(self, "database_panel", None) is not None:
            for setting_key, checked in source_states(self.settings, self.match_pdf2).items():
                self.database_panel.set_source_checked(setting_key, checked)
            self.database_panel.set_materials_project_checked(
                bool(self.settings.value("materials_project/enabled", False, type=bool))
            )
            if self.database_panel.materials_project_api_key_input is not None:
                self.database_panel.materials_project_api_key_input.setText(self.materials_project.api_key)
            self.database_panel.set_materials_project_status(self._materials_project_status_text())
            self._refresh_database_rows()

    def _fit_active_sample_indexed_cells(
        self,
        *,
        show_messages: bool = True,
        recalculate: bool = True,
        latest_only: bool = False,
    ) -> bool:
        pattern = self._active_pattern()
        if pattern is None:
            if show_messages:
                QMessageBox.information(self, "Cell fit", "Select an XRD sample first.")
            return False
        linked_phase_ids = list(getattr(pattern, "linked_phase_ids", []) or [])
        if not linked_phase_ids:
            if show_messages:
                QMessageBox.information(self, "Cell fit", "Add candidate phases to this sample first.")
            return False
        if latest_only:
            linked_phase_ids = linked_phase_ids[-1:]
        observed = self._pattern_scoring_observed_data(pattern)
        if observed is None or len(observed) < 5:
            if show_messages:
                QMessageBox.information(self, "Cell fit", "No observed profile is available for this sample.")
            return False
        phase_by_id = {phase.id: phase for phase in self.project.phases}
        structure_by_id = {structure.id: structure for structure in self.project.structures}
        phase_structures = []
        for phase_id in linked_phase_ids:
            phase = phase_by_id.get(phase_id)
            if phase is None:
                continue
            structure = structure_by_id.get(phase.structure_id or "")
            if structure is None:
                structure = next((item for item in self.project.structures if item.phase_id == phase.id), None)
            if structure is None:
                continue
            phase_structures.append((phase.id, phase.name, structure))
        if not phase_structures:
            if show_messages:
                QMessageBox.information(self, "Cell fit", "Linked phases do not have CIF structures.")
            return False
        wavelength = self._active_wavelength()
        indexed_peak_matches = self._active_indexed_peak_matches(
            pattern,
            phase_structures,
            wavelength=wavelength,
        )
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            results = self.refinement_service.fit_indexed_cells(
                phase_structures,
                wavelength=wavelength,
                indexed_peak_matches=indexed_peak_matches,
            )
        except Exception as exc:
            if show_messages:
                QMessageBox.warning(self, "Cell fit", str(exc))
            return False
        finally:
            self.unsetCursor()
        structure_by_phase_id = {
            phase_id: structure
            for phase_id, _phase_name, structure in phase_structures
        }
        summary = []
        for result in results:
            if not result.success:
                summary.append(f"{result.phase_name}: skipped ({result.message or 'not enough matched peaks'})")
                continue
            structure = structure_by_phase_id.get(result.phase_id)
            if structure is None:
                continue
            structure.cell = result.refined_cell
            source_path_key = self._compound_card_path_key(getattr(structure, "source_path", ""))
            for match_structure in self.match_structures.values():
                match_source_key = self._compound_card_path_key(
                    getattr(match_structure, "source_path", "")
                )
                if source_path_key and match_source_key == source_path_key:
                    match_structure.cell = deepcopy(result.refined_cell)
            summary.append(
                f"{result.phase_name}: {result.matched_peaks} peaks, RMS {result.rms_delta_two_theta:.4g} deg\n"
                f"{self._cell_change_text(result.initial_cell, result.refined_cell)}"
            )
            self.project.refinements.append(
                {
                    "method": "indexed_cell",
                    "pattern_id": pattern.id,
                    "phase_id": result.phase_id,
                    "phase_name": result.phase_name,
                    "matched_peaks": result.matched_peaks,
                    "rms_delta_two_theta": result.rms_delta_two_theta,
                    "max_delta_two_theta": result.max_delta_two_theta,
                    "cell": {
                        "a": result.refined_cell.a,
                        "b": result.refined_cell.b,
                        "c": result.refined_cell.c,
                        "alpha": result.refined_cell.alpha,
                        "beta": result.refined_cell.beta,
                        "gamma": result.refined_cell.gamma,
                        "volume": result.refined_cell.volume,
                    },
                }
            )
        self.project.touch()
        self.project_changed.emit()
        if hasattr(self, "_invalidate_match_profile_cache"):
            self._invalidate_match_profile_cache(pattern.id)
        if hasattr(self, "_update_compound_card_sample"):
            self._update_compound_card_sample()
        if recalculate:
            self._recalculate_match_profile(auto_zoom=False, active_only=True)
        if show_messages and summary:
            QMessageBox.information(self, "Cell fit", "\n".join(summary[:8]))
        return any(result.success for result in results)

    def _cell_change_text(self, initial_cell: CellParameters, refined_cell: CellParameters) -> str:
        parts = []
        for name in ("a", "b", "c", "alpha", "beta", "gamma"):
            before = getattr(initial_cell, name, None)
            after = getattr(refined_cell, name, None)
            if before is None or after is None:
                continue
            parts.append(f"{name} {float(before):.5g}->{float(after):.5g}")
        return "; ".join(parts)

    def _active_indexed_peak_matches(
        self,
        pattern,
        phase_structures,
        *,
        wavelength: float,
    ) -> dict[str, list[tuple[int, int, int, float, float]]]:
        candidates = self._profile_candidates_for_pattern(pattern)
        if not candidates:
            return {}
        try:
            result, _candidate_by_key = self._finder_result_for_pattern(pattern, candidates, snap_peak_positions=False)
        except Exception:
            return {}
        if result is None:
            return {}
        global_zero_shift = float(getattr(result, "global_zero_shift", 0.0) or 0.0)
        phase_ids = {phase_id for phase_id, _phase_name, _structure in phase_structures}
        phase_by_source_path = {
            self._compound_card_path_key(phase.source_path): phase.id
            for phase in self.project.phases
            if phase.id in phase_ids and self._compound_card_path_key(getattr(phase, "source_path", ""))
        }
        phase_by_name_formula = {
            (str(phase.name or "").casefold(), str(phase.formula or "").casefold()): phase.id
            for phase in self.project.phases
            if phase.id in phase_ids
        }
        phase_id_by_candidate_key: dict[str, str] = {}
        for candidate in candidates:
            phase_id = ""
            if self._candidate_source(candidate) == "USER" and candidate.get("Entry") in phase_ids:
                phase_id = candidate.get("Entry", "")
            if not phase_id:
                key = self._candidate_key(candidate)
                structure = self.match_structures.get(key)
                source_path = str(getattr(structure, "source_path", "") or "")
                if source_path:
                    phase_id = phase_by_source_path.get(self._compound_card_path_key(source_path), "")
            if not phase_id:
                try:
                    phase_id = phase_by_source_path.get(self._compound_card_path_key(str(self._candidate_cif_path(candidate))), "")
                except Exception:
                    phase_id = ""
            if not phase_id:
                phase_id = phase_by_name_formula.get(
                    (
                        self._candidate_phase_name(candidate).casefold(),
                        str(candidate.get("Formula", "") or "").casefold(),
                    ),
                    "",
                )
            if phase_id:
                phase_id_by_candidate_key[self._candidate_key(candidate)] = phase_id
        matches: dict[str, list[tuple[int, int, int, float, float]]] = {}
        structure_by_phase_id = {
            phase_id: structure
            for phase_id, _phase_name, structure in phase_structures
        }
        phase_name_by_id = {
            phase_id: phase_name
            for phase_id, phase_name, _structure in phase_structures
        }
        observed_peaks = [
            (
                float(peak.two_theta),
                float(peak.intensity),
                float(getattr(peak, "fwhm", 0.0) or 0.0),
            )
            for peak in getattr(result, "observed_peaks", []) or []
        ]
        phase_order = {
            phase_id: index
            for index, (phase_id, _phase_name, _structure) in enumerate(phase_structures)
        }
        linked_results = []
        for candidate_result in getattr(result, "candidates", []) or []:
            # FinderInput.entry_id preserves the UI candidate key. The service-level
            # candidate_key may prefix the source once more (for example
            # "COD:COD:9008195"), so use entry_id first when linking back to a phase.
            phase_id = phase_id_by_candidate_key.get(getattr(candidate_result, "entry_id", ""))
            if not phase_id:
                phase_id = phase_id_by_candidate_key.get(getattr(candidate_result, "candidate_key", ""))
            if not phase_id:
                continue
            linked_results.append((phase_order.get(phase_id, len(phase_order)), phase_id, candidate_result))

        claimed_observed_peaks: list[tuple[float, float]] = []
        for _phase_index, phase_id, candidate_result in sorted(linked_results, key=lambda item: item[0]):
            gain_evidence = None
            if len(self.match_candidates) > 1:
                gain_evidence = self._candidate_gain_indexed_evidence.get(
                    getattr(candidate_result, "entry_id", "")
                )
                if gain_evidence is None:
                    gain_evidence = self._candidate_gain_indexed_evidence.get(
                        getattr(candidate_result, "candidate_key", "")
                    )
            available_observed_peaks = self.refinement_service.unclaimed_observed_peaks(
                observed_peaks,
                claimed_observed_peaks,
            )
            references = list(getattr(candidate_result, "matched_reference_two_theta", []) or [])
            observed = list(getattr(candidate_result, "matched_observed_two_theta", []) or [])
            peak_positions = list(getattr(candidate_result, "peak_reference_two_theta", []) or [])
            if not peak_positions:
                peak_positions = list(getattr(candidate_result, "peak_two_theta", []) or [])
            h_values = list(getattr(candidate_result, "peak_h", []) or [])
            k_values = list(getattr(candidate_result, "peak_k", []) or [])
            l_values = list(getattr(candidate_result, "peak_l", []) or [])
            intensities = list(getattr(candidate_result, "peak_intensity", []) or [])
            if not peak_positions or not h_values or not k_values or not l_values:
                continue
            direct_matches = []
            overlapping_matches = []
            for reference_two_theta, observed_two_theta in zip(references, observed):
                try:
                    reference_value = float(reference_two_theta)
                    observed_value = float(observed_two_theta)
                except Exception:
                    continue
                nearest_index = min(
                    range(len(peak_positions)),
                    key=lambda index: abs(float(peak_positions[index]) - reference_value),
                )
                if abs(float(peak_positions[nearest_index]) - reference_value) > 0.25:
                    continue
                try:
                    h = int(round(float(h_values[nearest_index])))
                    k = int(round(float(k_values[nearest_index])))
                    l = int(round(float(l_values[nearest_index])))
                    intensity = float(intensities[nearest_index]) if nearest_index < len(intensities) else 1.0
                except Exception:
                    continue
                if (h, k, l) == (0, 0, 0):
                    continue
                corrected_observed = observed_value - global_zero_shift
                indexed_match = (
                    h,
                    k,
                    l,
                    corrected_observed,
                    max(intensity, 1.0),
                )
                nearest_observed = (
                    min(
                        observed_peaks,
                        key=lambda peak: abs(float(peak[0]) - observed_value),
                    )
                    if observed_peaks
                    else None
                )
                if nearest_observed in available_observed_peaks:
                    direct_matches.append(indexed_match)
                else:
                    overlapping_matches.append(indexed_match)
            reference_peaks = []
            for index, reference_two_theta in enumerate(peak_positions):
                if index >= len(h_values) or index >= len(k_values) or index >= len(l_values):
                    continue
                try:
                    reference_peaks.append(
                        (
                            int(round(float(h_values[index]))),
                            int(round(float(k_values[index]))),
                            int(round(float(l_values[index]))),
                            float(reference_two_theta),
                            float(intensities[index]) if index < len(intensities) else 1.0,
                        )
                    )
                except Exception:
                    continue
            structure = structure_by_phase_id.get(phase_id)
            if structure is not None:
                if gain_evidence is not None:
                    gain_matches = [
                        (h, k, l, float(observed_two_theta) - global_zero_shift, weight)
                        for h, k, l, observed_two_theta, weight in gain_evidence.indexed_matches
                    ]
                    if gain_evidence.stage == GainStage.OVERLAP:
                        direct_matches = []
                        overlapping_matches = gain_matches
                    else:
                        direct_matches = gain_matches
                        overlapping_matches = []
                else:
                    direct_matches = self.refinement_service.complete_direct_indexed_matches(
                        structure=structure,
                        indexed_matches=direct_matches,
                        reference_peaks=reference_peaks,
                        observed_peaks=available_observed_peaks,
                        global_zero_shift=global_zero_shift,
                    )
                prepared_matches = self.indexed_cell_matching_service.prepare_phase_matches(
                    phase_id=phase_id,
                    phase_name=phase_name_by_id.get(phase_id, ""),
                    structure=structure,
                    wavelength=wavelength,
                    direct_matches=direct_matches,
                    overlapping_matches=overlapping_matches,
                    observed_peaks=observed_peaks,
                    available_observed_peaks=available_observed_peaks,
                )
                matches[phase_id] = prepared_matches.matches
                for _h, _k, _l, corrected_two_theta, _weight in prepared_matches.direct_matches_to_claim:
                    raw_two_theta = float(corrected_two_theta) + global_zero_shift
                    if not observed_peaks:
                        continue
                    nearest_peak = min(
                        observed_peaks,
                        key=lambda peak: abs(float(peak[0]) - raw_two_theta),
                    )
                    claimed_observed_peaks.append(
                        (float(nearest_peak[0]), max(float(nearest_peak[2]), 0.05))
                    )
                continue

        return {phase_id: phase_matches for phase_id, phase_matches in matches.items() if phase_matches}

    @traced_operation("match.profile")
    def _recalculate_match_profile(
        self,
        auto_zoom: bool = False,
        active_only: bool = False,
        *,
        refresh_pattern_id: str | None = None,
    ) -> None:
        self._close_manual_calibration()
        self._activate_current_profile_state()
        self._save_active_profile_state()
        active_pattern = self._active_pattern()
        refresh_pattern = active_pattern
        if refresh_pattern_id is not None and self.show_all_selected_patterns:
            refresh_pattern = next((pattern for pattern in self._patterns_to_display()
                                    if pattern.id == refresh_pattern_id), None)
            if refresh_pattern is None:
                return
        incremental = bool(
            (active_only or refresh_pattern_id is not None)
            and self.show_all_selected_patterns
            and refresh_pattern is not None
        )
        clear_pattern_id = refresh_pattern.id if incremental else None
        patterns = (
            [refresh_pattern]
            if incremental
            else self._patterns_to_display()
            if self.show_all_selected_patterns
            else [active_pattern]
        )
        patterns = [pattern for pattern in patterns if pattern is not None]
        if not patterns:
            self._clear_calculated_overlay()
            self._update_match_table()
            return

        active_pattern_id = active_pattern.id if active_pattern is not None else ""
        has_candidates = any(self._profile_candidates_for_pattern(pattern) for pattern in patterns)
        if not has_candidates:
            self._clear_calculated_overlay(clear_pattern_id)
            if hasattr(self, "_refresh_multi_pattern_legends"):
                self._refresh_multi_pattern_legends()
            self._update_match_table()
            return

        self._clear_calculated_overlay(clear_pattern_id)
        if hasattr(self, "_redraw_estimated_background_components_for_current_view"):
            self._redraw_estimated_background_components_for_current_view(
                clear_pattern_id
            )
        deferred_pattern_ids: list[str] = []
        try:
            preview_required_pattern_id: str | None = None
            for pattern in patterns:
                candidates = self._profile_candidates_for_pattern(pattern)
                if not candidates:
                    continue
                is_active = pattern.id == active_pattern_id
                # In multi-pattern mode only the active sample may trigger a
                # scientific recalculation. Other samples are drawn from their
                # already verified cache and will be calculated when activated.
                result, candidate_by_key = self._finder_result_for_pattern(
                    pattern,
                    candidates,
                    cache_only=bool(self.show_all_selected_patterns and not is_active),
                    background=True,
                )
                if result is None:
                    if self.show_all_selected_patterns and not is_active:
                        deferred_pattern_ids.append(pattern.id)
                    continue
                for candidate in candidate_by_key.values():
                    if not isinstance(candidate, dict) or candidate.get("_CifPath"):
                        continue
                    try:
                        candidate["_CifPath"] = str(self._candidate_cif_path(candidate))
                    except Exception:
                        pass
                if is_active:
                    self._last_match_profile_fwhm = float(getattr(result, "fwhm", 0.0) or 0.0)
                    reported_eta = getattr(result, 'profile_eta', None)
                    self._last_match_profile_eta = None if reported_eta is None else float(reported_eta)
                metrics = (
                    self.match_scales,
                    self.match_quantities,
                    self.match_iic,
                    self.match_zero_shifts,
                    self.match_cell_scales,
                    self.match_alignment_scores,
                ) if is_active else ({}, {}, {}, {}, {}, {})
                layer_state = {}
                if self.show_all_selected_patterns:
                    profile_state = self.profile_states.get(pattern.id, {})
                    state_value = profile_state.get("layer_visibility", {}) if isinstance(profile_state, dict) else {}
                    layer_state = state_value if isinstance(state_value, dict) else {}
                show_hkl_labels = bool(
                    layer_state.get(
                        "hkl_labels_visible",
                        self._field_setting_value("hkl_labels_visible", False) if hasattr(self, "_field_setting_value") else self.show_hkl_labels,
                    )
                ) if self.show_all_selected_patterns else (
                    self._active_hkl_labels_requested() if hasattr(self, "_active_hkl_labels_requested") else self.show_hkl_labels
                )
                show_peak_labels = bool(
                    layer_state.get(
                        "layer_peak_labels_visible",
                        self._field_setting_value("layer_peak_labels_visible", False) if hasattr(self, "_field_setting_value") else False,
                    )
                ) if self.show_all_selected_patterns else (
                    self._active_peak_labels_requested() if hasattr(self, "_active_peak_labels_requested") else False
                )
                summary_snapshot = draw_match_profile_result(
                    result=result,
                    candidate_by_key=candidate_by_key,
                    match_plot=self.match_plot,
                    plot_layers=self.plot_layers,
                    show_all_selected_patterns=self.show_all_selected_patterns,
                    active_plot_context=self.observed_pattern_plot_context.get(
                        pattern.id,
                        {"offset": 0.0, "raw_min": 0.0, "raw_max": 1.0, "plot_min": 0.0, "plot_max": 1.0, "height": 1.0},
                    ),
                    pattern_id=pattern.id,
                    phase_color=self._phase_color,
                    phase_legend_label=self._phase_legend_label,
                    candidate_key=self._candidate_key,
                    estimate_candidate_iic=self._estimate_candidate_corundum_iic,
                    profile_fit_quality=self._profile_fit_quality,
                    add_peak_coverage_markers=self._add_peak_coverage_markers,
                    match_scales=metrics[0],
                    match_quantities=metrics[1],
                    match_iic=metrics[2],
                    match_zero_shifts=metrics[3],
                    match_cell_scales=metrics[4],
                    match_alignment_scores=metrics[5],
                    style=self.plot_style,
                    show_hkl_labels=show_hkl_labels,
                    show_peak_labels=show_peak_labels,
                    show_background_line=not self._pattern_has_saved_background_components(pattern),
                )
                context = self.observed_pattern_plot_context.get(pattern.id)
                if context is not None:
                    context['accepted_profile_result_key'] = next(
                        (key for key, value in self.match_profile_result_cache.items() if value is result), None)
                self._refresh_peak_information_assignments(pattern.id)
                profile_state = self.profile_states.setdefault(pattern.id, {})
                working_candidates = self.match_candidates if is_active else candidates
                store_accepted_cell_results(result, working_candidates, self._candidate_key)
                if isinstance(profile_state, dict):
                    profile_state["candidates"] = self._candidate_copy_list(working_candidates)
                    previous_snapshot = profile_state.get("result_snapshot")
                    previous_scientific = (
                        {key: value for key, value in previous_snapshot.items() if key != "preview_path"}
                        if isinstance(previous_snapshot, dict)
                        else None
                    )
                    current_scientific = {
                        key: value for key, value in summary_snapshot.items() if key != "preview_path"
                    }
                    scientific_changed = previous_scientific != current_scientific
                    if is_active and scientific_changed and self.show_all_selected_patterns:
                        self.analysis_preview_paths.pop(pattern.id, None)
                    if (
                        is_active
                        and not self.show_all_selected_patterns
                        and (scientific_changed or pattern.id not in self.analysis_preview_paths)
                    ):
                        preview_required_pattern_id = pattern.id
                    profile_state["result_snapshot"] = summary_snapshot
            if hasattr(self, "_refresh_multi_pattern_legends"):
                self._refresh_multi_pattern_legends()
        except Exception as exc:
            QMessageBox.warning(self, "Finder calculation failed", str(exc))
            self._update_match_table()
            return

        if incremental:
            restore_profile_layer_stacking(self.match_plot,
                (pattern.id for pattern in self._patterns_to_display()))
        self._update_match_table()
        if hasattr(self, "_apply_plot_layer_visibility_settings"):
            self._apply_plot_layer_visibility_settings(self.plot_view_settings)
        if auto_zoom:
            self._reset_match_plot_view()
        if active_pattern is not None and preview_required_pattern_id == active_pattern.id:
            try:
                preview_path = capture_analysis_preview(
                    self._publication_plot_image(),
                    project_id=self.project.id,
                    pattern_id=active_pattern.id,
                )
                if preview_path:
                    self.analysis_preview_paths[active_pattern.id] = preview_path
                    self.profile_states[active_pattern.id]["result_snapshot"]["preview_path"] = preview_path
            except Exception:
                # A preview is supplementary; it must never interrupt analysis.
                pass
        queue = getattr(self, "visible_profile_calculation_queue", None)
        if queue is not None and deferred_pattern_ids:
            queue.schedule(deferred_pattern_ids)

    def _calculate_visible_profile(self, pattern_id: str) -> None:
        if not self.show_all_selected_patterns:
            return
        visible_by_id = {
            pattern.id: pattern
            for pattern in self._patterns_to_display()
            if pattern is not None
        }
        pattern = visible_by_id.get(pattern_id)
        if pattern is None:
            return
        candidates = self._profile_candidates_for_pattern(pattern)
        if not candidates:
            return
        previous_network_suppression = bool(getattr(self, "_suppress_candidate_network", False))
        self._suppress_candidate_network = True
        try:
            result, _candidate_by_key = self._finder_result_for_pattern(
                pattern,
                candidates,
                cache_only=False,
                background=True,
            )
        except Exception as exc:
            self._set_background_status(f"Profile {pattern.name}: {exc}")
            return
        finally:
            self._suppress_candidate_network = previous_network_suppression
        if result is not None:
            self._recalculate_match_profile(auto_zoom=False, refresh_pattern_id=pattern_id)

    def _pattern_has_saved_background_components(self, pattern) -> bool:
        if pattern is None:
            return False
        if getattr(pattern, "processed_background_removed", False):
            return _processed_amorphous_background_data(pattern) is not None
        return bool(
            getattr(pattern, "estimated_background_points", None)
            or getattr(pattern, "estimated_background_with_halo_points", None)
        )

    def _should_autozoom_match_profile(self) -> bool:
        return not self.show_all_selected_patterns and len(self._patterns_to_display()) == 1



    def _observed_peak_positions(self, x, corrected_y) -> np.ndarray:
        return observed_peak_positions(x, corrected_y)


    def _profile_fit_quality(self, observed_y: np.ndarray, background: np.ndarray, calculated_total: np.ndarray) -> float:
        observed_corrected = np.clip(np.asarray(observed_y, dtype=float) - np.asarray(background, dtype=float), 0.0, None)
        calculated_corrected = np.clip(np.asarray(calculated_total, dtype=float) - np.asarray(background, dtype=float), 0.0, None)
        return self._corrected_profile_fit_quality(observed_corrected, calculated_corrected)


    def _add_peak_coverage_markers(
        self,
        x: np.ndarray,
        observed_y: np.ndarray,
        corrected_y: np.ndarray,
        phase_peak_sets: list[tuple[str, str, np.ndarray]],
        observed_peak_assignments=None,
        phase_assignment_styles: dict[str, tuple[str, str]] | None = None,
        show_peak_labels: bool | None = None,
    ) -> tuple[int, int]:
        return add_peak_coverage_markers(
            plot=self.match_plot,
            plot_layers=self.plot_layers,
            observed_peak_positions=self._observed_peak_positions,
            x=x,
            observed_y=observed_y,
            corrected_y=corrected_y,
            phase_peak_sets=phase_peak_sets,
            observed_peak_assignments=observed_peak_assignments,
            phase_assignment_styles=phase_assignment_styles,
            show_peak_labels=(
                bool(show_peak_labels)
                if show_peak_labels is not None
                else self._active_peak_labels_requested() if hasattr(self, "_active_peak_labels_requested") else False
            ),
            style=self.plot_style,
        )

    def _add_peak_residual_links(
        self,
        peaks,
        observed_x: np.ndarray,
        observed_y: np.ndarray,
        observed_positions: np.ndarray,
        max_delta: float = 0.45,
        min_delta: float = 0.08,
        limit: int = 36,
        layer: str = "peak_links",
    ) -> None:
        if len(observed_positions) == 0:
            return
        strong_peaks = [
            peak for peak in peaks
            if getattr(peak, "intensity", 0.0) >= 4.0
        ]
        strong_peaks = sorted(strong_peaks, key=lambda peak: peak.intensity, reverse=True)[:limit]
        for peak in strong_peaks:
            calc_x = float(peak.two_theta)
            nearest_index = nearest_peak_index(observed_positions, calc_x)
            obs_x = float(observed_positions[nearest_index])
            delta = obs_x - calc_x
            if abs(delta) > max_delta or abs(delta) < min_delta:
                continue
            y_index = int(np.argmin(np.abs(observed_x - obs_x)))
            link_y = float(observed_y[y_index])
            cap = max(float(np.nanpercentile(observed_y, 98)) * 0.015, 10.0)
            y0 = link_y - cap
            y1 = link_y + cap
            pen = pg.mkPen("#ff2b16", width=3.0)
            line_item = self.match_plot.plot(
                [calc_x, calc_x, obs_x, obs_x],
                [y0, link_y, link_y, y1],
                pen=pen,
            )
            self.plot_layers[layer].append(line_item)

    def _estimate_phase_alignment(self, peaks, observed_positions: np.ndarray, structure) -> PhaseAlignmentEstimate:
        alignment = estimate_phase_alignment(peaks, observed_positions, structure)
        if self.match_zero_shifts:
            alignment.zero_shift = common_zero_shift(self.match_zero_shifts.values())
        elif alignment.status == "weak":
            observed = self._active_scoring_observed_data()
            if observed is not None and len(observed):
                records = [
                    ObservedPeak(float(position), float(np.interp(position, observed[:, 0], observed[:, 1])), 0.)
                    for position in observed_positions
                ]
                alignment.zero_shift = self.finder_service.estimate_zero_shift(
                    peaks, records, wavelength=self._active_wavelength(),
                )
        return alignment

    def _peak_presence_probability(self, peaks, observed_x: np.ndarray, corrected_y: np.ndarray, structure) -> float:
        return peak_presence_probability(peaks, observed_x, corrected_y, structure)

    def _clear_probability_caches(self) -> None:
        self._observed_probability_cache = None
        self._candidate_probability_cache.clear()
        self._candidate_gain_profile_cache.clear()
        self._candidate_hidden_match_by_key.clear()


    def _trim_candidate_probability_cache(self, limit: int = 5000) -> None:
        while len(self._candidate_probability_cache) > limit:
            self._candidate_probability_cache.pop(next(iter(self._candidate_probability_cache)), None)


    def _trim_match_profile_result_cache(self, limit: int = 128) -> None:
        while len(self.match_profile_result_cache) > limit:
            self.match_profile_result_cache.pop(next(iter(self.match_profile_result_cache)), None)


    def _active_probability_context_key(self) -> tuple[object, ...]:
        pattern = self._active_pattern()
        pattern_id = getattr(pattern, "id", "") if pattern is not None else ""
        source_path = getattr(pattern, "source_path", "") if pattern is not None else ""
        wavelength, include_kalpha2 = self._legacy_radiation_for_pattern(pattern)
        processed = self._active_scoring_observed_data()
        data_len = int(len(processed)) if processed is not None else -1
        data_signature = self._processed_probability_signature(processed)
        background_signature = self._finder_background_signature(self._pattern_finder_background_data(pattern))
        instrument = self._instrument_profile_for_pattern(pattern)
        instrument_key = instrument.calculation_key() if instrument is not None else None
        return (
            pattern_id,
            source_path,
            round(float(wavelength), 6),
            bool(include_kalpha2),
            getattr(self, "_scoring_source", "Auto"),
            self._active_background_removed(),
            data_len,
            data_signature,
            background_signature,
            instrument_key,
            round(common_zero_shift(getattr(self, 'match_zero_shifts', {}).values()), 8),
        )

    def _gain_instrument_profile(self):
        return self._instrument_profile_for_pattern(self._active_pattern())

    def _gain_structure_override(self, candidate):
        pattern = self._active_pattern()
        if pattern is None:
            return None
        return self._finder_candidate_structure_overrides(pattern, [candidate]).get(self._candidate_key(candidate))

    def _gain_line_locations(self):
        return (getattr(self.project.finder_state, "candidate_cif_paths", {}) or {}, self.project.phases)

    def _gain_radiation(self):
        return self._legacy_radiation_for_pattern(self._active_pattern())

    def _gain_context_key(self):
        return self._active_probability_context_key()

    def _gain_accepted_profile_snapshot(self):
        snapshot = accepted_profile_snapshot(self, self._active_pattern())
        if not snapshot:
            return None
        return snapshot['accepted_fit_x'], snapshot['accepted_fit_target'], snapshot['accepted_fit_profiles']

    def _gain_mass_profile_snapshot(self):
        return accepted_profile_snapshot(self, self._active_pattern()).get('accepted_fit_mass_profiles')

    def _gain_accepted_peak_positions(self):
        return accepted_profile_snapshot(self, self._active_pattern()).get('accepted_fit_peak_positions')

    def _gain_observation(self):
        pattern = self._active_pattern()
        background = self._pattern_finder_background_data(pattern)
        return (
            self._active_scoring_observed_data(), background,
            self._pattern_finder_observed_data(pattern) if background is not None else None,
            self._pattern_scoring_background_removed(pattern),
        )

    def _gain_search_options(self):
        return self._candidate_search_options()

    def _gain_process_events(self):
        QApplication.processEvents()

    def _gain_set_status(self, text):
        if getattr(self, "scoring_status_label", None) is not None:
            self.scoring_status_label.setText(text)
        if getattr(self, "candidate_search_detail_label", None) is not None:
            self.candidate_search_detail_label.setText(text)
            self.candidate_search_detail_label.setToolTip(text)

    def _processed_probability_signature(self, processed) -> tuple[object, ...] | None:
        if processed is None or not len(processed):
            return None
        return (
            array_fingerprint(processed[:, 0]),
            array_fingerprint(processed[:, 1]),
        )

    def _probability_observed_data(self) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]] | None:
        observed = self._active_scoring_observed_data()
        if observed is None or not len(observed):
            return None
        key = self._active_probability_context_key()
        if self._observed_probability_cache is not None and self._observed_probability_cache[0] == key:
            return self._observed_probability_cache[1], self._observed_probability_cache[2], self._observed_probability_cache[3]
        try:
            if getattr(self, "_scoring_source", "Auto") == "Auto" or self._pattern_scoring_background_removed(self._active_pattern()):
                corrected = np.asarray(observed[:, 1], dtype=float)
            else:
                background = self._estimate_background(observed[:, 0], observed[:, 1])
                corrected = np.asarray(observed[:, 1], dtype=float) - np.asarray(background, dtype=float)
            records = self._observed_peak_records(observed[:, 0], corrected, limit=80)
        except Exception:
            return None
        self._observed_probability_cache = (key, np.asarray(observed[:, 0], dtype=float), corrected, records)
        return self._observed_probability_cache[1], self._observed_probability_cache[2], self._observed_probability_cache[3]








    def _capture_candidate_gain_indexed_evidence(self, candidate: dict[str, str]) -> None:
        if not self.match_candidates:
            return
        prepared = self.gain_job_controller.cached_indexed_evidence(candidate)
        if prepared is not None:
            if prepared.indexed_matches:
                self._candidate_gain_indexed_evidence[self._candidate_key(candidate)] = prepared
            return
        context = self._candidate_gain_context()
        if context is None:
            return
        candidate_key = self._candidate_key(candidate)
        stage = context.get("_gain_dominant_evidence_by_key", {}).get(candidate_key)
        if stage is None:
            stage = GainStage(self._gain_stage_for_context(context))
        else:
            stage = GainStage(stage)
        context["gain_stage"] = str(stage)
        records = self._gain_stage_records(context, str(stage), limit=90)
        peaks = self._candidate_aligned_gain_peaks_cached(candidate, context)
        peaks, _profile, _gain, _snr = self._candidate_profile_with_cell_refinement(candidate, peaks, context)
        evidence = build_gain_indexed_evidence(
            peaks=peaks,
            records=records,
            stage=stage,
            base_fwhm=float(context.get("fwhm", 0.18) or 0.18),
        )
        if evidence.indexed_matches:
            self._candidate_gain_indexed_evidence[candidate_key] = evidence














    def _candidate_gain_line_support(self, peaks: list[HKLPeak], context) -> float:
        x = np.asarray(context.get("x", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        residual = np.asarray(context.get("residual_target", []), dtype=float)
        if len(x) < 5 or len(target) != len(x) or len(residual) != len(x):
            return 0.0
        observed_records = self._observed_peak_records(x, target, limit=160)
        residual_records = self._gain_context_observed_peak_records(context, "residual_target", limit=120)
        if not observed_records:
            return 0.0

        x_min = float(np.nanmin(x))
        x_max = float(np.nanmax(x))
        in_range = [
            peak
            for peak in peaks
            if x_min <= float(getattr(peak, "two_theta", 0.0) or 0.0) <= x_max
            and float(getattr(peak, "intensity", 0.0) or 0.0) >= 2.0
        ]
        in_range.sort(key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0), reverse=True)
        strong = in_range[:40]
        if len(strong) < 2:
            return 0.0

        weights = np.asarray(
            [
                math.sqrt(max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0))
                / math.sqrt(index + 1.0)
                for index, peak in enumerate(strong)
            ],
            dtype=float,
        )
        total_weight = max(float(np.sum(weights)), 1.0e-12)
        base_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)

        def matched_weight(records) -> tuple[float, int, list[tuple[HKLPeak, object]]]:
            available = set(range(len(records)))
            covered_weight = 0.0
            covered_count = 0
            pairs = []
            for peak, weight in zip(strong, weights, strict=False):
                position = float(getattr(peak, "two_theta", 0.0) or 0.0)
                best_index = -1
                best_delta = float("inf")
                for record_index in available:
                    record = records[record_index]
                    delta = abs(self._record_position_value(record) - position)
                    local_fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), base_fwhm)
                    tolerance = max(0.14, min(0.58, 0.10 + 0.85 * local_fwhm))
                    if delta <= tolerance and delta < best_delta:
                        best_index = record_index
                        best_delta = delta
                if best_index >= 0:
                    available.remove(best_index)
                    covered_weight += float(weight)
                    covered_count += 1
                    pairs.append((peak, records[best_index]))
            return covered_weight, covered_count, pairs

        observed_weight, observed_count, observed_pairs = matched_weight(observed_records)
        residual_weight, residual_count, _residual_pairs = matched_weight(residual_records)
        extra_weight = max(0.0, total_weight - observed_weight)

        # Extra calculated lines are stronger evidence against a phase than peaks
        # left in the experimental residual, while overlap remains possible.
        observed_factor = observed_weight / max(observed_weight + 2.5 * extra_weight, 1.0e-12)
        intensity_factor = self._candidate_gain_intensity_factor(observed_pairs)
        residual_coverage = residual_weight / total_weight
        residual_factor = 0.25 + 0.75 * min(1.0, residual_coverage / 0.35)
        count_factor = min(1.0, 0.25 + 0.25 * residual_count)
        if residual_count == 0:
            count_factor = 0.20 if observed_count >= 4 else 0.08

        density_penalty = 1.0
        if len(in_range) > 55:
            density_penalty = math.sqrt(55.0 / float(len(in_range)))
        support = observed_factor * intensity_factor * residual_factor * count_factor * density_penalty
        return float(np.clip(support, 0.0, 1.0))









    def _candidate_gain_novelty_factor(self, row: list[str], context) -> float:
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        peaks = self._candidate_peaks_for_gain(candidate)
        if not peaks:
            return 0.0
        selected_positions = np.asarray(context.get("selected_peak_positions", []), dtype=float)
        selected_positions = selected_positions[np.isfinite(selected_positions)]
        if len(selected_positions) == 0:
            return 1.0
        selected_positions.sort()
        strong = [
            peak
            for peak in peaks
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
            and 5.0 <= float(getattr(peak, "two_theta", 0.0) or 0.0) <= 120.0
        ]
        strong = sorted(strong, key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0), reverse=True)[:32]
        if len(strong) < 3:
            return 0.0
        base_tolerance = max(0.26, min(0.75, float(context.get("fwhm", 0.18) or 0.18) * 2.2))
        total_weight = 0.0
        novel_weight = 0.0
        novel_strong = 0
        top_covered = 0
        for index, peak in enumerate(strong):
            position = float(getattr(peak, "two_theta", 0.0) or 0.0)
            intensity = max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0)
            weight = max(intensity / 100.0, 0.03) ** 0.55
            total_weight += weight
            nearest = self._nearest_selected_line_delta(selected_positions, position)
            covered = nearest <= base_tolerance
            if covered and index < 8:
                top_covered += 1
            if not covered:
                novel_weight += weight
                if index < 12:
                    novel_strong += 1
        if total_weight <= 0.0:
            return 0.0
        novelty = novel_weight / total_weight
        if novel_strong < 2 or novelty < 0.12:
            return 0.0
        if top_covered >= 6:
            novelty *= 0.35
        return float(np.clip((novelty / 0.55) ** 1.35, 0.0, 1.0))

    def _candidate_gain_line_gate(self, peaks: list[HKLPeak], gain_records: list[tuple[float, float]], context) -> float:
        if not peaks or not gain_records:
            return 0.0
        gain_positions = self._record_positions(gain_records[:32])
        if len(gain_positions) == 0:
            return 0.0
        strong = [
            peak
            for peak in sorted(peaks, key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0), reverse=True)[:28]
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
        ]
        if len(strong) < 3:
            return 0.0
        tolerance = max(0.28, min(0.75, float(context.get("fwhm", 0.18) or 0.18) * 2.4))
        total_weight = 0.0
        matched_weight = 0.0
        matched_top = 0
        candidate_positions = []
        for index, peak in enumerate(strong):
            position = float(getattr(peak, "two_theta", 0.0) or 0.0)
            if not 5.0 <= position <= 120.0:
                continue
            candidate_positions.append(position)
            intensity = max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0)
            weight = max(intensity / 100.0, 0.02) ** 0.55 / math.sqrt(index + 1.0)
            total_weight += weight
            if self._nearest_selected_line_delta(gain_positions, position) <= tolerance:
                matched_weight += weight
                if index < 10:
                    matched_top += 1
        coverage = matched_weight / max(total_weight, 1.0e-12)
        if not candidate_positions:
            return 0.0
        candidate_positions_array = np.asarray(candidate_positions, dtype=float)
        candidate_positions_array.sort()
        residual_top = list(gain_records[: min(14, len(gain_records))])
        residual_top_matched = 0
        residual_top_area = 0.0
        residual_matched_area = 0.0
        for record in residual_top:
            area = max(float(getattr(record, "area", 0.0) or 0.0), 0.0)
            residual_top_area += area
            position = self._record_position_value(record)
            if self._nearest_selected_line_delta(candidate_positions_array, position) <= tolerance:
                residual_top_matched += 1
                residual_matched_area += area
        residual_fraction = residual_matched_area / max(residual_top_area, 1.0e-12)
        if total_weight <= 0.0 or matched_top < 2 or coverage < 0.24:
            return 0.0
        if residual_top_matched < 2 or residual_fraction < 0.16:
            return 0.0
        return float(np.clip(0.45 * coverage + 0.55 * residual_fraction, 0.0, 1.0))














    def _candidate_row_peak_probability_from_records(
        self,
        row: list[str],
        observed_records: list[tuple[float, float]],
        *,
        allow_cif_fallback: bool = True,
        use_cache: bool = True,
    ) -> float:
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        source = self._candidate_source(candidate)
        if source not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD", "PDF2"}:
            return 0.0
        if source == "PDF2":
            peaks = self._pdf2_peaks_for_candidate(candidate)
        else:
            peaks = self._candidate_indexed_peaks(candidate)
            if not peaks and allow_cif_fallback:
                peaks = self._candidate_cached_json_peaks(candidate)
        cif_path = None
        if not peaks and allow_cif_fallback:
            cif_path = self._candidate_local_cif_path(candidate)
        if not peaks and cif_path is None:
            return 0.0
        probability_key = self._candidate_probability_key(candidate, cif_path)
        cached_probability = self._candidate_probability_cache.get(probability_key) if use_cache else None
        if use_cache and cached_probability is not None:
            return cached_probability
        try:
            structure = None
            if peaks:
                structure = self._candidate_lightweight_structure(candidate)
            elif allow_cif_fallback:
                _phase, structure = create_phase_from_cif(cif_path)
                if candidate.get("Phase"):
                    structure.name = candidate["Phase"]
                structure.wavelength = self._active_wavelength()
                peaks = self._candidate_cached_peaks(cif_path, structure)
            else:
                return 0.0
            probability_data = self._probability_observed_data()
            if probability_data is not None:
                scan_x = np.asarray(probability_data[0], dtype=float)
                finite_x = scan_x[np.isfinite(scan_x)]
                if finite_x.size:
                    low, high = float(finite_x.min()), float(finite_x.max())
                    peaks = [peak for peak in peaks if low <= float(peak.two_theta) <= high]
            probability = fingerprint_match_score(
                peaks,
                observed_records,
                wavelength=float(self._active_wavelength()),
            ).score
            if use_cache:
                self._candidate_probability_cache[probability_key] = probability
                self._trim_candidate_probability_cache()
            return probability
        except Exception:
            return 0.0

    def _candidate_row_peak_probability(self, row: list[str], observed_x: np.ndarray, corrected_y: np.ndarray) -> float:
        records = self._observed_peak_records(observed_x, corrected_y, limit=80)
        return self._candidate_row_peak_probability_from_records(row, records)


    def _candidate_lightweight_structure(self, candidate: dict[str, str]):
        class _CandidateStructure:
            pass

        structure = _CandidateStructure()
        structure.name = candidate.get("Phase", "") or candidate.get("Entry", "")
        structure.formula = candidate.get("Formula", "")
        structure.wavelength = self._active_wavelength()
        return structure

    def _candidate_probability_key(self, candidate: dict[str, str], cif_path: Path | None) -> tuple[object, ...]:
        if cif_path is None:
            source = self._candidate_source(candidate)
            entry_id = candidate.get("Entry", "")
            provider = getattr(self, "candidate_line_provider", None)
            resolution = provider.resolve(candidate) if provider is not None else None
            line_set = getattr(resolution, "line_set", None)
            if line_set is not None:
                file_key = ("indexed-lines", line_set.fingerprint)
            else:
                entry = self.local_phase_cache.get(source, entry_id) if source and entry_id else None
                peaks_json = getattr(entry, "peaks_json", "") if entry is not None else ""
                file_key = (
                    "cached-peaks",
                    int(getattr(entry, "derived_version", 0) or 0) if entry is not None else 0,
                    hashlib.sha256(peaks_json.encode('utf-8')).digest(),
                )
        else:
            try:
                file_key = candidate_cif_fingerprint(cif_path)
            except OSError:
                file_key = (str(cif_path), None)
        return (
            self._active_probability_context_key(),
            self._candidate_source(candidate),
            candidate.get("Entry", ""),
            file_key,
        )


    def _rank_by_peak_probability_enabled(self) -> bool:
        return self.rank_by_probability_checkbox is not None and self.rank_by_probability_checkbox.isChecked()

    def _structure_peak_probability(self, structure) -> float:
        probability_data = self._probability_observed_data()
        if probability_data is None:
            return 0.0
        observed_x, corrected, observed_records = probability_data
        if not observed_records:
            return 0.0
        try:
            structure.wavelength = self._active_wavelength()
            peaks = self.calculated_pattern_service.calculate_sticks(
                structure,
                wavelength=self._active_wavelength(),
                two_theta_min=5.0,
                two_theta_max=120.0,
                intensity_min=0.5,
            )
            return self._peak_presence_probability(peaks, observed_x, corrected, structure)
        except Exception:
            return 0.0


    def _estimate_candidate_corundum_iic(self, candidate: dict[str, str]) -> float:
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            if not getattr(structure, "formula", "") and candidate.get("Formula"):
                structure.formula = candidate["Formula"]
            return self._estimate_structure_corundum_iic(structure)
        except Exception:
            return 0.0

    def _estimate_structure_corundum_iic(self, structure) -> float:
        wavelength = float(getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH)
        # Keep I/Ic stable: it is a reference-pattern property, not a current zoom/window property.
        two_theta_min = 5.0
        two_theta_max = 120.0
        try:
            sample_peaks = self.calculated_pattern_service.calculate_sticks(
                structure,
                two_theta_min=two_theta_min,
                two_theta_max=two_theta_max,
                wavelength=wavelength,
                use_lp=True,
            )
            corundum_peaks = self._corundum_peaks(wavelength, two_theta_min, two_theta_max)
        except Exception:
            return 0.0
        sample_total = self._diffraction_power_reference_intensity(sample_peaks, structure, wavelength)
        corundum_total = self._diffraction_power_reference_intensity(
            corundum_peaks,
            self._corundum_structure(),
            wavelength,
        )
        if sample_total <= 0 or corundum_total <= 0:
            return 0.0
        value = sample_total / corundum_total
        return float(np.clip(value, 0.0, 99.9))

    def _corundum_peaks(self, wavelength: float, two_theta_min: float, two_theta_max: float):
        key = (round(float(wavelength), 6), round(float(two_theta_min), 3), round(float(two_theta_max), 3))
        if key not in self._corundum_peak_cache:
            self._corundum_peak_cache[key] = self.calculated_pattern_service.calculate_sticks(
                self._corundum_structure(),
                two_theta_min=two_theta_min,
                two_theta_max=two_theta_max,
                wavelength=wavelength,
                use_lp=True,
            )
        return self._corundum_peak_cache[key]

    def _corundum_structure(self) -> Structure:
        return create_corundum_reference_structure()

    def _diffraction_power_reference_intensity(self, peaks, structure, wavelength: float) -> float:
        values = [
            max(float(getattr(peak, "raw_intensity", 0.0) or getattr(peak, "intensity", 0.0)), 0.0)
            for peak in peaks
        ]
        strongest = float(max(values, default=0.0))
        volume = float(getattr(getattr(structure, "cell", None), "volume", 0.0) or 0.0)
        if strongest <= 0.0 or volume <= 0.0:
            return 0.0
        return strongest * (float(wavelength) / volume) ** 2

    def _calculate_candidate_overlay(self, candidate: dict[str, str], show_errors: bool, preview_token: int | None = None) -> None:
        if preview_token is None:
            self._candidate_preview_token = int(getattr(self, '_candidate_preview_token', 0)) + 1
            preview_token = self._candidate_preview_token
        if preview_token is not None and preview_token != getattr(self, "_candidate_preview_token", None):
            return
        entry_id = candidate.get("Entry", "")
        try:
            observed = self._active_observed_data()
            cache = getattr(self, '_preview_observation_cache', None)
            if cache is None:
                cache = OverlayObservationCache()
                self._preview_observation_cache = cache
            if observed is not None:
                key = overlay_observation_key(observed, self._estimate_background,
                                              self._observed_peak_positions, self._estimate_profile_fwhm)
                if cache._key != key or cache._data is None:
                    controller = getattr(self, 'preview_observation_controller', None)
                    if controller is None:
                        controller = PreviewObservationController(self)
                        self.preview_observation_controller = controller
                        controller.drained.connect(self._finish_preparation_close)
                    captured_candidate = candidate.copy()
                    def failed(message):
                        if show_errors and preview_token == getattr(self, '_candidate_preview_token', None):
                            QMessageBox.warning(self, 'Calculate pattern failed', message)
                    controller.request(
                        observed, cache,
                        lambda: self._calculate_candidate_overlay(captured_candidate, show_errors, preview_token),
                        failed,
                    )
                    return
            view_range = self._plot_view_range()
            if preview_token is not None and preview_token != getattr(self, "_candidate_preview_token", None):
                return
            active_pattern = self._active_pattern()
            wavelength, include_kalpha2 = self._legacy_radiation_for_pattern(active_pattern)
            indexed_peaks = self._candidate_indexed_peaks(candidate)
            if indexed_peaks:
                structure = self._candidate_lightweight_structure(candidate)
            else:
                cif_path = self._candidate_cif_path(candidate)
                _phase, structure = create_phase_from_cif(cif_path)
            self._clear_transient_candidate_preview()
            before_counts = self._transient_candidate_preview_counts()
            overlay = prepare_structure_overlay(
                structure=structure,
                observed=observed,
                calculated_pattern_service=self.calculated_pattern_service,
                estimate_background=self._estimate_background,
                observed_peak_positions=self._observed_peak_positions,
                estimate_profile_fwhm=self._estimate_profile_fwhm,
                estimate_phase_alignment=self._estimate_phase_alignment,
                wavelength=wavelength,
                include_kalpha2=include_kalpha2,
                profile_fwhm_override=self._legacy_fwhm_for_pattern(active_pattern),
                peaks_override=indexed_peaks or None,
                include_profile=False,
                observation_cache=cache,
            )
            draw_structure_overlay(
                overlay=overlay,
                structure=structure,
                preview=True,
                match_plot=self.match_plot,
                plot_layers=self.plot_layers,
                active_plot_context=self._active_pattern_plot_context(),
                show_all_selected_patterns=self.show_all_selected_patterns,
                show_hkl_labels=self.show_hkl_labels,
                add_peak_residual_links=self._add_peak_residual_links,
                observed=observed,
                style=self.plot_style,
                pattern_id=getattr(self._active_pattern(), "id", None),
                candidate_id=self._candidate_key(candidate),
            )
            self._tag_transient_candidate_preview_items(before_counts)
            if observed is None:
                self._reset_match_plot_view()
            else:
                self._restore_plot_view_range(view_range)
            if hasattr(self, "_apply_plot_layer_visibility_settings"):
                self._apply_plot_layer_visibility_settings(self.plot_view_settings)
            self.active_overlay_entry_id = entry_id or None
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Calculate pattern failed", str(exc))

    def _preview_rruff_reference(self, candidate: dict[str, str], show_errors: bool, preview_token: int | None = None) -> None:
        if preview_token is not None and preview_token != getattr(self, "_candidate_preview_token", None):
            return
        entry_id = candidate.get("Entry", "")
        if not entry_id:
            return
        try:
            pattern_path = self.rruff.pattern_path(entry_id)
            if pattern_path is None:
                raise ValueError("RRUFF reference pattern is not indexed or the XY file is missing.")
            data = load_xy(pattern_path)
            observed = self._active_observed_data()
            transient_preview = bool(getattr(self, "match_candidates", None))
            if transient_preview:
                self._clear_transient_candidate_preview()
                before_counts = self._transient_candidate_preview_counts()
            else:
                self._clear_calculated_overlay()
                before_counts = {}
            label = self._phase_legend_label(candidate)
            draw_rruff_reference(
                plot=self.match_plot,
                plot_layers=self.plot_layers,
                data=np.asarray(data, dtype=float),
                observed=observed,
                label=label,
                style=self.plot_style,
                pattern_id=getattr(self._active_pattern(), "id", None),
                candidate_id=self._candidate_key(candidate),
            )
            if transient_preview:
                self._tag_transient_candidate_preview_items(before_counts)
            if observed is None:
                self._reset_match_plot_view()
            if hasattr(self, "_apply_plot_layer_visibility_settings"):
                self._apply_plot_layer_visibility_settings(self.plot_view_settings)
            self.active_overlay_entry_id = entry_id
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "RRUFF preview failed", str(exc))

    def _preview_pdf2_reference(self, candidate: dict[str, str], show_errors: bool, preview_token: int | None = None) -> None:
        if preview_token is not None and preview_token != getattr(self, "_candidate_preview_token", None):
            return
        entry_id = candidate.get("Entry", "")
        if not entry_id:
            return
        view_range = self._plot_view_range()
        try:
            peaks = self._pdf2_peaks_for_candidate(candidate)
            if not peaks:
                raise ValueError("PDF-2 diffraction lines were not found for this card.")
            observed = self._active_observed_data()
            transient_preview = bool(getattr(self, "match_candidates", None))
            if transient_preview:
                self._clear_transient_candidate_preview()
                before_counts = self._transient_candidate_preview_counts()
            else:
                self._clear_preview_overlay()
                before_counts = {}
            label = self._phase_legend_label(candidate)
            draw_pdf2_reference(
                plot=self.match_plot,
                plot_layers=self.plot_layers,
                peaks=peaks,
                observed=observed,
                active_plot_context=self._active_pattern_plot_context(),
                label=label,
                show_hkl_labels=self.show_hkl_labels,
                style=self.plot_style,
                pattern_id=getattr(self._active_pattern(), "id", None),
                candidate_id=self._candidate_key(candidate),
            )
            if transient_preview:
                self._tag_transient_candidate_preview_items(before_counts)
            if observed is None:
                self._reset_match_plot_view()
            else:
                self._restore_plot_view_range(view_range)
            if hasattr(self, "_apply_plot_layer_visibility_settings"):
                self._apply_plot_layer_visibility_settings(self.plot_view_settings)
            self.active_overlay_entry_id = entry_id
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "PDF-2 preview failed", str(exc))

    def _calculate_structure_overlay(self, structure, preview: bool = False) -> None:
        if preview:
            self._clear_preview_overlay()
        else:
            self._clear_calculated_overlay()
        observed = self._active_observed_data()
        active_pattern = self._active_pattern()
        wavelength, include_kalpha2 = self._legacy_radiation_for_pattern(active_pattern)
        overlay = prepare_structure_overlay(
            structure=structure,
            observed=observed,
            calculated_pattern_service=self.calculated_pattern_service,
            estimate_background=self._estimate_background,
            observed_peak_positions=self._observed_peak_positions,
            estimate_profile_fwhm=self._estimate_profile_fwhm,
            estimate_phase_alignment=self._estimate_phase_alignment,
            wavelength=wavelength,
            include_kalpha2=include_kalpha2,
            profile_fwhm_override=self._legacy_fwhm_for_pattern(active_pattern),
        )
        draw_structure_overlay(
            overlay=overlay,
            structure=structure,
            preview=preview,
            match_plot=self.match_plot,
            plot_layers=self.plot_layers,
            active_plot_context=self._active_pattern_plot_context(),
            show_all_selected_patterns=self.show_all_selected_patterns,
            show_hkl_labels=self.show_hkl_labels,
            add_peak_residual_links=self._add_peak_residual_links,
            observed=observed,
            style=self.plot_style,
            pattern_id=getattr(self._active_pattern(), "id", None),
            candidate_id=(
                str(getattr(structure, "id", "") or getattr(structure, "name", ""))
                or None
            ),
        )
        if hasattr(self, "_apply_plot_layer_visibility_settings"):
            self._apply_plot_layer_visibility_settings(self.plot_view_settings)

    def _apply_default_phase_filter(self) -> None:
        self.exclude_all_other_elements = False
        self.element_states.clear()
        self.selected_element_order.clear()
        for element in self._element_symbols():
            self._set_element_state(element, "neutral")
        if self.inorganics_checkbox is not None:
            self.inorganics_checkbox.setChecked(True)
        if self.organics_checkbox is not None:
            self.organics_checkbox.setChecked(False)
        if self.structural_data_checkbox is not None:
            self.structural_data_checkbox.setChecked(True)
        if self.reference_patterns_checkbox is not None:
            self.reference_patterns_checkbox.setChecked(False)
        self._update_element_fields()

    def _toggle_required_element(self, element: str) -> None:
        current = self.element_states.get(element, "neutral")
        self._set_element_state(element, "neutral" if current == "required" else "required")
        self._update_element_fields()

    def _toggle_excluded_element(self, element: str) -> None:
        current = self.element_states.get(element, "neutral")
        self._set_element_state(element, "neutral" if current == "excluded" else "excluded")
        self._update_element_fields()

    def _clear_excluded_elements(self) -> None:
        for element in self._element_symbols():
            if self.element_states.get(element) == "excluded":
                self._set_element_state(element, "neutral")
        self.exclude_all_other_elements = False
        self._update_element_fields()

    def _restore_excluded_elements(self) -> None:
        for element in self._element_symbols():
            if self.element_states.get(element, "neutral") == "neutral":
                self._set_element_state(element, "excluded")
        self.exclude_all_other_elements = True
        self._update_element_fields()

    def _toggle_excluded_mode(self) -> None:
        if self.exclude_all_other_elements:
            self._clear_excluded_elements()
        else:
            self._restore_excluded_elements()

    def _paint_elements(self, elements: list[str], state: str) -> None:
        if state not in {"required", "excluded", "neutral"}:
            return
        for element in dict.fromkeys(elements):
            self._set_element_state(element, state)
        self._update_element_fields()

    def _reset_selected_elements(self) -> None:
        self.element_states.clear()
        self.selected_element_order.clear()
        self.exclude_all_other_elements = False
        for element in self._element_symbols():
            self._set_element_state(element, "neutral")
        if self.ccdc_doi_input is not None:
            self.ccdc_doi_input.clear()
        self._update_element_fields()

    def _reset_candidate_search_table(self) -> None:
        preparation = getattr(self, '_observed_search_controller', None)
        if preparation is not None:
            preparation.invalidate()
            self._set_auto_search_busy(False)
        preview = getattr(self, 'preview_observation_controller', None)
        if preview is not None:
            preview.invalidate()
        self._candidate_preview_token = int(getattr(self, '_candidate_preview_token', 0)) + 1
        keep_peak_mode = self._search_mode == "peaks"
        self._cancel_candidate_search_jobs()
        if not keep_peak_mode:
            self._set_search_mode("search")
        self._reset_selected_elements()
        if self.search_input is not None:
            self.search_input.clear()
        if hasattr(self, "_clear_transient_candidate_preview"):
            self._clear_transient_candidate_preview()
        if hasattr(self, "_clear_probability_caches"):
            self._clear_probability_caches()
        detail_label = getattr(self, "candidate_search_detail_label", None)
        if detail_label is not None:
            detail_label.setText("Found 0 | Loading 0 | Ready 0")
        self._set_candidate_rows([["", "", "", "Candidate list cleared", "", ""]])

    def _cancel_candidate_search_jobs(self) -> None:
        cancel_find = getattr(self, '_cancel_find_peaks', None)
        if callable(cancel_find):
            cancel_find()
        loaded_queue = getattr(self, '_loaded_match_queue', None)
        if loaded_queue is not None:
            loaded_queue.invalidate()
        search_cancel = getattr(self, '_candidate_search_cancel', None)
        if search_cancel is not None:
            search_cancel.set()
        selected_peak_cancel = getattr(self, "_selected_peak_search_cancel", None)
        if selected_peak_cancel is not None:
            selected_peak_cancel.set()
        self._candidate_gain_auto_enabled = False
        self._candidate_gain_refresh_after_preparation = False
        self._candidate_gain_refresh_requested = False
        self._auto_search_token = int(getattr(self, "_auto_search_token", 0)) + 1
        self._candidate_search_request_token = int(
            getattr(self, "_candidate_search_request_token", 0)
        ) + 1
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is not None:
            controller.stop()
        gain_controller = getattr(self, "gain_job_controller", None)
        if gain_controller is not None:
            gain_controller.invalidate()
        self._set_auto_search_busy(False)
        queue = getattr(self, "visible_profile_calculation_queue", None)
        if queue is not None:
            queue.clear()
        if hasattr(self, "candidate_search_service"):
            self.candidate_search_service.cancel_background_downloads()

    def _update_element_fields(self) -> None:
        if self.element_table is not None and hasattr(self.element_table, "set_excluded_mode"):
            self.element_table.set_excluded_mode(self.exclude_all_other_elements)
        self.selected_elements = {
            element for element, state in self.element_states.items() if state == "required"
        }
        self.selected_element_order = [
            element for element in self.selected_element_order if element in self.selected_elements
        ]
        for element in sorted(self.selected_elements, key=element_sort_key):
            if element not in self.selected_element_order:
                self.selected_element_order.append(element)
        formula = " ".join(self.selected_element_order)
        if self.elem_count_input is not None:
            self.elem_count_input.setText(str(len(self.selected_elements)))
        if self.formula_sum_input is not None:
            self.formula_sum_input.setText(formula)
        if hasattr(self, "element_gate_label") and self.element_gate_label is not None:
            excluded_labels=[element for element,state in self.element_states.items() if state=='excluded']
            parts=[formula] if formula else []
            if excluded_labels:parts.append(f'{len(excluded_labels)} excluded')
            self.element_gate_label.setText('Chemical filter: '+('; '.join(parts) if parts else 'none'))
            self.element_gate_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
            from textwrap import fill
            self.element_gate_label.setToolTip(fill('Required: '+(formula or 'none'),width=60)+'\n'+fill('Excluded: '+(' '.join(sorted(excluded_labels,key=element_sort_key)) or 'none'),width=60))
        if self.name_input is not None:
            excluded = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: element_sort_key(item[0]))
                if state == "excluded"
            ]
            any_elements = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: element_sort_key(item[0]))
                if state == "any"
            ]
            summary = []
            if self.exclude_all_other_elements:
                summary.append("not: all other elements")
            elif excluded:
                summary.append("not " + " ".join(excluded))
            if any_elements:
                summary.append("any " + " ".join(any_elements))
            self.name_input.setText("; ".join(summary))
        if self.search_input is not None and (
            not self.search_input.text().strip() or self.search_input.text().strip() == self._last_formula_text
        ):
            self.search_input.setText(formula)
        self._last_formula_text = formula
        self._apply_candidate_element_filter()

    def _apply_candidate_element_filter(self) -> None:
        table = getattr(self, "candidate_table", None)
        if table is None:
            return
        required = set(self.selected_elements)
        optional: set[str] = set()
        excluded = {
            element for element, state in self.element_states.items() if state == "excluded"
        }
        strict = getattr(self, "exclude_all_other_elements", True)
        if getattr(self, "_auto_search_ranked_rows", None) is not None:
            self._rerank_auto_search_element_subset(required, optional)
        first_visible = -1
        for row in range(table.rowCount()):
            values = table.row_values(row)
            formula = values.get("Formula", "")
            source = values.get("Source", "")
            visible = PhaseFinderWindow._candidate_formula_matches_gate(
                formula, source, required, optional, excluded=excluded, strict=strict
            )
            table.setRowHidden(row, not visible)
            if visible and first_visible < 0:
                first_visible = row
        if table.currentRow() >= 0 and table.isRowHidden(table.currentRow()):
            table.clearSelection()
            if first_visible >= 0:
                table.setCurrentCell(first_visible, 0)
                table.selectRow(first_visible)
            else:
                table.setCurrentCell(-1, -1)
                if getattr(self, "compound_card", None) is not None:
                    self.compound_card.set_candidate(None)

    @staticmethod
    def _candidate_formula_matches_gate(
        formula: str, source: str, required: set[str], optional: set[str],
        *, excluded: set[str] | None = None, strict: bool = True,
    ) -> bool:
        excluded = excluded or set()
        if not source or not (required or excluded):
            return True
        elements = formula_elements(formula) if formula else set()
        return (
            bool(elements)
            and required.issubset(elements)
            and not elements.intersection(excluded)
        )

    def _rerank_auto_search_element_subset(
        self, required: set[str], optional: set[str]
    ) -> None:
        base_rows = self._auto_search_ranked_rows
        if not (required or optional):
            ordered_rows = base_rows
        else:
            excluded = {
                element for element, state in getattr(self, "element_states", {}).items()
                if state == "excluded"
            }
            strict = getattr(self, "exclude_all_other_elements", True)
            matching = [
                (index, row)
                for index, row in enumerate(base_rows)
                if self._candidate_formula_matches_gate(
                    row[2], row[0], required, optional, excluded=excluded, strict=strict
                )
                and row[0] and row[1]
            ]
            scored_keys = self._auto_search_scored_keys
            unscored = [
                row for _index, row in matching
                if (str(row[0]).upper(), str(row[1])) not in scored_keys
            ]
            if unscored:
                from xrd_finder.ui.candidate_match_job import CandidateMatchQueue
                queue = getattr(self, '_loaded_match_queue', None)
                if queue is None:
                    queue = self._loaded_match_queue = CandidateMatchQueue(self)
                queue.request(base_rows)
            matching.sort(key=lambda item: (-self._percent_text_value(item[1][5]), item[0]))
            matched_indices = {index for index, _row in matching}
            ordered_rows = [row for _index, row in matching] + [
                row for index, row in enumerate(base_rows) if index not in matched_indices
            ]
        current_keys = [
            (values.get("Source", ""), values.get("Entry", ""))
            for values in self.candidate_table.all_row_values()
        ]
        new_keys = [(row[0], row[1]) for row in ordered_rows]
        if current_keys != new_keys or any(
            self.candidate_table.row_values(index).get("Match (%)", "") != row[5]
            for index, row in enumerate(ordered_rows)
        ):
            self.candidate_table.set_rows(ordered_rows, lambda row: row)

    def _set_element_state(self, element: str, state: str) -> None:
        if self.element_table is None:
            return
        if state == "optional":
            state = "neutral"
        if state == "neutral":
            self.element_states.pop(element, None)
            if element in self.selected_element_order:
                self.selected_element_order.remove(element)
        else:
            self.element_states[element] = state
            if state == "required" and element not in self.selected_element_order:
                self.selected_element_order.append(element)
            elif state != "required" and element in self.selected_element_order:
                self.selected_element_order.remove(element)
        self.element_table.set_element_state(element, state)

    def _excluded_elements(self) -> list[str]:
        return [element for element, state in self.element_states.items() if state == "excluded"]

    def _optional_elements(self) -> list[str]:
        return []

    def _element_symbols(self) -> list[str]:
        return self.element_table.element_symbols if self.element_table is not None else []

    def _search_pdf2_candidates(self) -> None:
        if self.selected_elements:
            self._search_from_controls()
        else:
            self._search_pdf2_text()


    def _set_candidate_rows(
        self,
        rows: list[list[str]],
        force_rank: bool = False,
        rank_progress=None,
        gain_context=None,
        skip_rank: bool = False,
    ) -> None:
        self._auto_search_ranked_rows = None
        self._auto_search_scored_keys = set()
        self._candidate_rank_token += 1
        rows = [normalize_candidate_row(row) for row in rows]
        if not getattr(self, "_candidate_gain_auto_enabled", False):
            for row in rows:
                row[6] = ""
        search_token = getattr(self, "_candidate_search_request_token", 0)
        rank_requested = (not skip_rank and (force_rank or self._rank_by_peak_probability_enabled())
                          and any(row[0] and row[1] for row in rows))
        if rank_requested and not self.match_candidates:
            from xrd_finder.ui.candidate_match_job import CandidateMatchQueue
            queue = getattr(self, '_loaded_match_queue', None)
            if queue is None:
                queue = self._loaded_match_queue = CandidateMatchQueue(self)
            queue.request(rows)
        if search_token != getattr(self, "_candidate_search_request_token", 0):
            return
        self.candidate_table.set_rows(rows, lambda row: row)
        if hasattr(self, '_refresh_candidate_score_labels'):
            self._refresh_candidate_score_labels()
        self._apply_candidate_element_filter()
        if rank_requested and self.match_candidates:
            self._schedule_candidate_gain_ranking()
        if hasattr(self, "_update_profile_view_context"):
            self._update_profile_view_context()
        active_row = self.candidate_table.currentRow()
        if active_row < 0 or self.candidate_table.isRowHidden(active_row):
            active_row = next(
                (row for row in range(self.candidate_table.rowCount())
                 if not self.candidate_table.isRowHidden(row)),
                -1,
            )
        if active_row >= 0:
            candidate = self._candidate_row_values(active_row)
            if candidate.get("Source", "").strip():
                self._update_compound_card(candidate)

    def _finish_preparation_close(self) -> None:
        if getattr(self, '_preparation_close_confirmed', False):
            self.close()
