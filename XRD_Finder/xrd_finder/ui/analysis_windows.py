from __future__ import annotations

from copy import deepcopy
import json
import math

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal
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
    QProgressDialog,
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

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.series import SeriesAnalysis
from xrd_finder.core.structure import AtomSite, CellParameters, Structure
from xrd_finder.finder import FinderInput, FinderService
from xrd_finder.finder.models import candidate_structure_override
from xrd_finder.finder.fingerprint_matching import fingerprint_match_score
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
from xrd_finder.services.cod_online_service import CodOnlineService
from xrd_finder.services.computational_database_service import AflowService, OqmdService
from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.services.match_pdf2_service import MatchPdf2Service
from xrd_finder.services.materials_project_service import MaterialsProjectService
from xrd_finder.services.preprocessing_service import estimate_background
from xrd_finder.services.refinement_service import RefinementService
from xrd_finder.services.runtime_diagnostics import traced_operation
from xrd_finder.services.indexed_cell_matching import IndexedCellMatchingService
from xrd_finder.services.rruff_service import RruffService
from xrd_finder.ui.pattern_plot_helpers import (
    ensure_right_legend,
    estimate_profile_fwhm,
)
from xrd_finder.ui.phase_finder_menu import build_phase_finder_menu_bar
from xrd_finder.ui.background_task import BackgroundTaskHandle
from xrd_finder.ui.candidate_info_actions import PhaseFinderCandidateInfoActionsMixin
from xrd_finder.ui.candidate_search_actions import PhaseFinderCandidateSearchActionsMixin
from xrd_finder.ui.candidate_structure_actions import PhaseFinderCandidateStructureActionsMixin
from xrd_finder.ui.candidate_tables import CandidateTableWidget, SelectedCandidatesTableWidget
from xrd_finder.ui.compound_card import CompoundCardWidget
from xrd_finder.ui.composition_panel import CompositionPanel
from xrd_finder.ui.database_actions import PhaseFinderDatabaseActionsMixin
from xrd_finder.ui.database_panel import DatabasePanelWidget
from xrd_finder.ui.element_filter import PeriodicTableWidget, element_sort_key
from xrd_finder.ui.finder_action_bar import FinderActionBar
from xrd_finder.ui.gain_scoring import (
    DEFAULT_GAIN_POLICY,
    GainIndexedEvidence,
    GainStage,
    build_gain_indexed_evidence,
    profile_residual_gain,
)
from xrd_finder.ui.help_text import PHASE_FINDER_HELP_TEXT, PHASE_FINDER_HELP_TITLE
from xrd_finder.ui.layout_state import SplitterLayoutState
from xrd_finder.ui.match_profile_renderer import build_finder_candidate_inputs, draw_match_profile_result
from xrd_finder.ui.observed_pattern_actions import PhaseFinderObservedPatternActionsMixin
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
)
from xrd_finder.ui.plot_actions import PhaseFinderPlotActionsMixin
from xrd_finder.ui.plot_view_actions import PhaseFinderPlotViewActionsMixin
from xrd_finder.ui.post_match_pipeline import PostMatchPipeline
from xrd_finder.ui.preprocessing_actions import PhaseFinderPreprocessingActionsMixin
from xrd_finder.ui.project_state_actions import PhaseFinderProjectStateActionsMixin
from xrd_finder.ui.project_tree_actions import PhaseFinderProjectTreeActionsMixin
from xrd_finder.ui.project_controls import ProjectControlsWidget
from xrd_finder.ui.project_tree import ProjectTree
from xrd_finder.ui.reference_preview_renderer import draw_pdf2_reference, draw_rruff_reference
from xrd_finder.ui.selected_phases_actions import PhaseFinderSelectedPhasesActionsMixin
from xrd_finder.ui.structure_overlay import draw_structure_overlay, prepare_structure_overlay
from xrd_finder.ui.toolkit_catalog_actions import PhaseFinderToolkitCatalogActionsMixin
from xrd_finder.ui.theme import is_dark_theme, window_style
from xrd_finder.ui.xrd_plot import create_xrd_plot_widget
from xrd_finder.ui.analysis_preview import capture_analysis_preview


class AnalysisWindow(QDialog):
    project_changed = Signal()
    background_status_changed = Signal(str)
    IMPORT_SUFFIXES = {".xy", ".txt", ".dat", ".csv", ".xye", ".cif"}

    def __init__(self, project: Project, title: str) -> None:
        super().__init__()
        self.project = project
        self._base_title = title
        self.setWindowTitle(f"{title} - {project.name}")
        self._layout_state = SplitterLayoutState(QSettings("Xrdfinder", "Standalone"))
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
        self.tree.itemSelectionChanged.connect(self._on_project_tree_selection_changed)
        self.tree.pattern_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())
        self.tree.phase_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())

        self.sidebar = QWidget()
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
        self.center_layout.setContentsMargins(6, 6, 6, 6)

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
        self.main_splitter.setSizes([190, 980, 330])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.addWidget(self.main_splitter)
        self.background_status_label = QLabel("Ready")
        self.background_status_label.setFixedHeight(20)
        self.background_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.background_status_label.setStyleSheet(
            "background: #20262d; border-top: 1px solid #3b4652; "
            "color: #b8c5d6; padding: 1px 7px;"
        )
        layout.addWidget(self.background_status_label)
        self.background_status_changed.connect(self._set_background_status)

    def _set_background_status(self, message: str) -> None:
        text = str(message or "Ready")
        self.background_status_label.setText(text)
        self.background_status_label.setToolTip(text)

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
        if self.project.patterns or self.project.phases or self.project.structures:
            response = QMessageBox.warning(
                self,
                "New project",
                "Clear all imported XRD patterns, CIF structures, candidates, and calculated overlays?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if response != QMessageBox.StandardButton.Yes:
                return
        self.project.patterns.clear()
        self.project.phases.clear()
        self.project.structures.clear()
        self.project.refinements.clear()
        self.project.analyses.clear()
        self.project.series.clear()
        self.project.root_path = ""
        self.project.touch()
        self.tree.set_project(self.project)
        self._after_new_project()
        self.project_changed.emit()

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
        try:
            project = load_project_manifest(path)
        except Exception as exc:
            QMessageBox.warning(self, "Load project failed", str(exc))
            return False
        self._remember_directory(str(path))
        self.project = project
        self.setWindowTitle(f"{self._base_title} - {project.name}")
        self.tree.set_project(project)
        self._after_project_loaded()
        self.project_changed.emit()
        return True

    def _show_project_load_warnings(self, warnings: list[str]) -> None:
        details = "\n".join(f"• {warning}" for warning in warnings)
        QMessageBox.warning(self, "Project loaded with warnings", details)

    def _save_project(self) -> bool:
        if not self.project.root_path or Path(self.project.root_path).suffix.lower() != PORTABLE_PROJECT_SUFFIX:
            return self._save_project_as()
        return self._write_project(self.project.root_path)

    def _save_project_as(self) -> bool:
        current_path = Path(self.project.root_path) if self.project.root_path else None
        if current_path is not None and current_path.suffix.lower() == PORTABLE_PROJECT_SUFFIX:
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
        if selected.suffix == "":
            path = str(selected.with_suffix(PORTABLE_PROJECT_SUFFIX))
        return self._write_project(path)

    @traced_operation("project.save")
    def _write_project(self, path: str | Path) -> bool:
        path = str(path)
        try:
            self._sync_finder_state_to_project()
            self.project.touch()
            save_project_manifest(self.project, path)
            self.project.root_path = path
        except Exception as exc:
            QMessageBox.warning(self, "Save project failed", str(exc))
            return False
        QMessageBox.information(self, "Project saved", f"Project saved to:\n{path}")
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
                    load_xy(path)
                    pattern = Pattern.create(name=path.stem, source_path=str(path))
                    self.project.patterns.append(pattern)
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
        settings = QSettings("Xrdfinder", "Standalone")
        path = str(settings.value("files/last_directory", "", type=str) or "")
        return path if path and Path(path).exists() else str(Path.home())

    def _remember_directory(self, path: str | Path) -> None:
        source = Path(path)
        directory = source if source.is_dir() else source.parent
        if directory.exists():
            QSettings("Xrdfinder", "Standalone").setValue("files/last_directory", str(directory))

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
    PhaseFinderToolkitCatalogActionsMixin,
    AnalysisWindow,
):
    def __init__(self, project: Project, *, defer_initial_plot: bool = False) -> None:
        self._defer_initial_plot = bool(defer_initial_plot)
        super().__init__(project, "Phase Finder")
        self.layout().setMenuBar(build_phase_finder_menu_bar(self))
        self.resize(1500, 850)
        self.right_tabs.setMinimumWidth(360)
        self._init_filter_state()
        self._init_services()
        self._init_runtime_state()
        self._create_cursor_readout_panel()
        self._create_action_bar()
        self._create_match_plot(project)
        self._create_candidate_tables()
        self._create_center_splitter()
        self._create_right_tabs()
        self.post_match_pipeline = PostMatchPipeline(
            refresh_selected_profile=self._recalculate_match_profile,
            refine_indexed_cells=self._fit_active_sample_indexed_cells,
            refresh_gain=self._schedule_candidate_gain_ranking,
            should_autozoom=self._should_autozoom_match_profile,
        )
        self._schedule_toolkit_announcement()

    def _init_filter_state(self) -> None:
        self.element_table: PeriodicTableWidget | None = None
        self.element_states: dict[str, str] = {}
        self.selected_elements: set[str] = set()
        self.selected_element_order: list[str] = []
        self.exclude_all_other_elements = False
        self._last_formula_text = ""

    def _init_services(self) -> None:
        self.settings = QSettings("Xrdfinder", "Standalone")
        self.cod_online = CodOnlineService()
        self.ccdc = CcdcService()
        self.local_phase_cache = LocalPhaseCache()
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
        )
        self._background_tasks: set[BackgroundTaskHandle] = set()
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
            "calculated_profile": [],
            "total_profile": [],
            "phase_profiles": [],
            "background": [],
            "difference": [],
            "peak_positions": [],
            "phase_ticks": [],
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
        self._candidate_peak_cache: dict[tuple[str, float, float, float], list] = {}
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

    def _candidate_copy_list(self, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        return [dict(candidate) for candidate in candidates]

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

    def _activate_profile_state_for_pattern(self, pattern_id: str | None) -> None:
        if not pattern_id:
            return
        previous_id = self.active_profile_pattern_id
        if previous_id == pattern_id:
            return
        if previous_id:
            self._save_active_profile_state()
        elif self.match_candidates and pattern_id not in self.profile_states:
            self.active_profile_pattern_id = pattern_id
            self._save_active_profile_state()
        self.active_profile_pattern_id = pattern_id
        self._load_profile_state(pattern_id)

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
        if pattern_id is None:
            try:
                self.finder_service.clear_observed_cache()
            except Exception:
                pass
            self.match_profile_result_cache.clear()
            return
        self.match_profile_result_cache = {
            key: value
            for key, value in self.match_profile_result_cache.items()
            if not key or key[0] != pattern_id
        }

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
                int(len(processed_observed)),
                float(x_values[0]),
                float(x_values[-1]),
                float(np.nanmin(y_values)),
                float(np.nanmax(y_values)),
                bool(self._pattern_finder_background_removed(pattern)),
                bool(self.normalize_observed_patterns),
                getattr(self, "_scoring_source", "Auto"),
            )
        candidate_signature = []
        for candidate in candidates:
            try:
                cif_path = str(self._candidate_cif_path(candidate))
            except Exception:
                cif_path = ""
            candidate_signature.append((
                self._candidate_source(candidate),
                candidate.get("Entry", ""),
                candidate.get("Formula", ""),
                candidate.get("Phase", "") or candidate.get("Name", ""),
                cif_path,
                self._structure_cell_signature(structure_overrides.get(self._candidate_key(candidate))),
            ))
        return (
            pattern.id,
            str(getattr(pattern, "source_path", "")),
            float(getattr(pattern, "wavelength", None) or CU_KA1_WAVELENGTH),
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
    ):
        finder_candidates, candidate_by_key = build_finder_candidate_inputs(
            candidates,
            self._candidate_cif_path,
            self._candidate_key,
            self._candidate_phase_name,
            self._candidate_source,
        )
        if not finder_candidates:
            return None, candidate_by_key
        cache_key = self._finder_cache_key(pattern, candidates, snap_peak_positions=snap_peak_positions)
        result = self.match_profile_result_cache.get(cache_key)
        if result is not None:
            return result, candidate_by_key
        if cache_only:
            return None, candidate_by_key
        processed_observed = self._pattern_finder_observed_data(pattern)
        background_data = self._pattern_finder_background_data(pattern)
        structure_overrides = self._finder_candidate_structure_overrides(pattern, candidates)
        for finder_candidate in finder_candidates:
            structure = candidate_structure_override(finder_candidate, structure_overrides)
            if structure is not None:
                finder_candidate.structure = structure
        result = self.finder_service.run(
            FinderInput(
                pattern_path=pattern.source_path,
                candidates=finder_candidates,
                wavelength=pattern.wavelength,
                observed_x=processed_observed[:, 0].tolist() if processed_observed is not None else None,
                observed_y=processed_observed[:, 1].tolist() if processed_observed is not None else None,
                background_x=background_data[:, 0].tolist() if background_data is not None else None,
                background_y=background_data[:, 1].tolist() if background_data is not None else None,
                subtract_background=not bool(self._pattern_finder_background_removed(pattern)),
                snap_peak_positions=bool(snap_peak_positions),
            )
        )
        self.match_profile_result_cache[cache_key] = result
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

    def _structure_cell_signature(self, structure) -> tuple[object, ...] | None:
        if structure is None:
            return None
        cell = getattr(structure, "cell", None)
        if cell is None:
            return None
        return tuple(
            None if getattr(cell, name, None) is None else round(float(getattr(cell, name)), 8)
            for name in ("a", "b", "c", "alpha", "beta", "gamma", "volume")
        )

    def _pattern_finder_background_data(self, pattern) -> np.ndarray | None:
        if pattern is None or self._pattern_finder_background_removed(pattern):
            return None
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
        return (
            int(len(background_data)),
            round(float(x_values[0]), 6),
            round(float(x_values[-1]), 6),
            round(float(np.nanmin(y_values)), 6),
            round(float(np.nanmax(y_values)), 6),
            round(float(np.nanmean(y_values)), 6),
        )

    def _create_cursor_readout_panel(self) -> None:
        status_panel = QWidget()
        status_layout = QVBoxLayout(status_panel)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(2)
        self.cursor_position_status_label = QLabel("2theta: -    I: -")
        self.cursor_position_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.cursor_position_status_label.setStyleSheet(
            "background: #20262d; border: 1px solid #3b4652; border-radius: 3px; "
            "color: #d7e3f4; font-weight: 700; padding: 6px 8px;"
        )
        self.cursor_position_status_label.setMinimumHeight(24)
        self.scoring_status_label = QLabel(self._scoring_source_status_text())
        self.scoring_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.scoring_status_label.setStyleSheet(
            "background: #1b3030; border: 1px solid #3f6a6a; border-radius: 3px; "
            "color: #d7fff4; font-weight: 700; padding: 6px 8px;"
        )
        self.scoring_status_label.setMinimumHeight(24)
        self.scoring_status_label.setToolTip("Profile used for match/gain scoring.")
        status_layout.addWidget(self.cursor_position_status_label)
        status_layout.addWidget(self.scoring_status_label)
        sidebar_layout = self.sidebar.layout()
        if sidebar_layout is not None:
            sidebar_layout.addWidget(status_panel)

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
        self.finder_action_bar.resetDataRequested.connect(self._reset_observed_preprocessing)
        self.finder_action_bar.searchRequested.connect(self._search_pdf2_text)
        self.finder_action_bar.autoSearchRequested.connect(self._auto_search_candidates)
        self.finder_action_bar.patternDisplayModeChanged.connect(self._set_pattern_display_mode)
        self.finder_action_bar.patternOffsetPercentChanged.connect(self._set_pattern_stack_offset)
        self.finder_action_bar.normalizePatternsChanged.connect(self._set_pattern_normalization)
        self.finder_action_bar.resetViewRequested.connect(self._reset_match_plot_view)
        self.search_input = self.finder_action_bar.search_input
        self.center_layout.addWidget(self.finder_action_bar)

    def _create_match_plot(self, project: Project) -> None:
        self.match_plot = self._plot_widget("Phase Finder: pattern and candidate phase markers", xrd_navigation=True)
        self.match_plot.setTitle("Phase Finder: pattern and candidate phase markers", color="#111111", size="13pt")
        self.match_plot.setLabel("bottom", "2theta", color="#111111", **{"font-size": "12pt"})
        self.match_plot.setLabel("left", "I rel.", color="#111111", **{"font-size": "12pt"})
        self.legend_item = ensure_right_legend(self.match_plot, clear=True)
        self.match_plot.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.match_plot.customContextMenuRequested.connect(self._show_plot_context_menu)
        self._ensure_cursor_position_items()
        if project.patterns and not self._defer_initial_plot:
            try:
                self._refresh_observed_pattern_plot()
            except Exception:
                pass

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
        candidate_layout.addWidget(QLabel("Candidate list"))
        candidate_layout.addWidget(self.candidate_table, 1)

    def _create_center_splitter(self) -> None:
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        self._layout_state.register("center_splitter", self.center_splitter)
        self.plot_canvas = QWidget()
        self.plot_canvas.setObjectName("plotCanvas")
        self.plot_canvas.setStyleSheet("QWidget#plotCanvas { background: #d7dadd; border: 1px solid #56616c; }")
        self.plot_canvas_layout = QGridLayout(self.plot_canvas)
        self.plot_canvas_layout.setContentsMargins(10, 10, 10, 10)
        self.plot_canvas_layout.setSpacing(0)
        self.plot_canvas_layout.addWidget(self.match_plot, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        self.center_splitter.addWidget(self.plot_canvas)
        self.center_splitter.addWidget(self.candidate_panel)
        self.center_splitter.setStretchFactor(0, 3)
        self.center_splitter.setStretchFactor(1, 2)
        self.center_splitter.setSizes([520, 260])
        self.center_layout.addWidget(self.center_splitter, 1)

    def _create_right_tabs(self) -> None:
        self.right_tabs.addTab(self._composition_tab(), "Elements")
        self.compound_card = CompoundCardWidget()
        self.compound_card.cellFitRequested.connect(self._fit_active_sample_indexed_cells)
        if hasattr(self, "_update_compound_card_sample"):
            self._update_compound_card_sample()
        self.right_tabs.addTab(self.compound_card, "Card")
        self.right_tabs.addTab(self._database_tab(), "Databases")
        self.right_tabs.addTab(self._plot_view_tab(), "View")
        self._layout_state.add_pin_corner(self.right_tabs, self._show_quick_help)
        self._layout_state.restore()
        self._layout_state.apply_lock()
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

    def _reset_phase_finder_state(
        self,
        candidate_rows: list[list[str]],
        *,
        reset_plot_range: bool = False,
        refresh_observed: bool = False,
    ) -> None:
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
        has_data = bool(self.project.patterns or self.project.phases or self.project.structures)
        if has_data:
            response = QMessageBox.question(
                self,
                "Close XRD Phase Finder",
                "Save the current project before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if response == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if response == QMessageBox.StandardButton.Save and not self._save_project():
                event.ignore()
                return
        self.candidate_search_service.shutdown_background_downloads()
        event.accept()

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
            QApplication.processEvents()

        handle = BackgroundTaskHandle(
            task,
            self,
            accepts_progress=with_progress,
            accepts_partial=on_partial is not None,
            operation_name=operation_name,
        )
        self._background_tasks.add(handle)

        def cleanup() -> None:
            if progress_dialog is not None:
                progress_dialog.close()
            self._background_tasks.discard(handle)
            if not self._background_tasks:
                self._set_background_status("Ready")

        def finish(result) -> None:
            cleanup()
            on_success(result)

        def fail(message: str, details: str) -> None:
            if progress_dialog is not None:
                progress_dialog.close()
            self._background_tasks.discard(handle)
            self._set_background_status(f"{title}: failed — {message or 'no response'}")
            if on_error is not None:
                on_error(message, details)
            else:
                QMessageBox.warning(self, title, message or details)

        def progress(message: str, value: int, maximum: int) -> None:
            if message:
                suffix = ""
                maximum = int(maximum)
                if maximum > 0:
                    value = max(0, min(int(value), maximum))
                    suffix = f" ({value}/{maximum})"
                self._set_background_status(f"{message}{suffix}")
                if progress_dialog is not None:
                    progress_dialog.setLabelText(message)
                    if maximum > 0:
                        progress_dialog.setRange(0, maximum)
                        progress_dialog.setValue(value)
                    else:
                        progress_dialog.setRange(0, 0)

        def show_waiting_status() -> None:
            if handle in self._background_tasks:
                self._set_background_status(f"{title}: waiting for response...")

        handle.progress.connect(progress)
        if on_partial is not None:
            handle.partial.connect(on_partial)
        handle.finished.connect(finish)
        handle.failed.connect(fail)
        handle.start()
        QTimer.singleShot(8000, show_waiting_status)

    def _composition_tab(self) -> QWidget:
        panel = CompositionPanel(self.match_table, self._layout_state)
        panel.requiredElementToggled.connect(self._toggle_required_element)
        panel.optionalElementToggled.connect(self._toggle_optional_element)
        panel.searchRequested.connect(self._search_from_controls)
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
        return panel

    def _show_quick_help(self) -> None:
        QMessageBox.information(self, PHASE_FINDER_HELP_TITLE, PHASE_FINDER_HELP_TEXT)

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
    ) -> None:
        self._activate_current_profile_state()
        self._save_active_profile_state()
        active_pattern = self._active_pattern()
        incremental = bool(
            active_only
            and self.show_all_selected_patterns
            and active_pattern is not None
        )
        patterns = (
            [active_pattern]
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
            self._clear_calculated_overlay(active_pattern_id if incremental else None)
            if hasattr(self, "_refresh_multi_pattern_legends"):
                self._refresh_multi_pattern_legends()
            self._update_match_table()
            return

        self._clear_calculated_overlay(active_pattern_id if incremental else None)
        if hasattr(self, "_redraw_estimated_background_components_for_current_view"):
            self._redraw_estimated_background_components_for_current_view(
                active_pattern_id if incremental else None
            )
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
                )
                if result is None:
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
                    self._last_match_profile_eta = float(getattr(result, "profile_eta", 0.0) or 0.0)
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
                profile_state = self.profile_states.setdefault(pattern.id, {})
                if isinstance(profile_state, dict):
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

    def _pattern_has_saved_background_components(self, pattern) -> bool:
        if pattern is None:
            return False
        if getattr(pattern, "processed_background_removed", False):
            return False
        return bool(
            getattr(pattern, "estimated_background_points", None)
            or getattr(pattern, "estimated_background_with_halo_points", None)
        )

    def _should_autozoom_match_profile(self) -> bool:
        return not self.show_all_selected_patterns and len(self._patterns_to_display()) == 1

    def _estimate_profile_fwhm(self, x, corrected_y) -> float:
        return estimate_profile_fwhm(x, corrected_y)

    def _fit_weights(self, corrected_y: np.ndarray) -> np.ndarray:
        y = np.asarray(corrected_y, dtype=float)
        if len(y) == 0:
            return np.ones_like(y)
        scale = max(float(np.nanpercentile(y, 98)), 1.0)
        weights = 0.15 + np.clip(y / scale, 0.0, 1.0) ** 0.7
        peak_indices, _properties = find_peaks(
            y,
            prominence=max(scale * 0.015, float(np.nanstd(y)) * 2.0, 1.0),
            distance=max(3, len(y) // 1000),
        )
        half_width = max(2, len(y) // 900)
        for index in peak_indices:
            left = max(0, index - half_width)
            right = min(len(y), index + half_width + 1)
            weights[left:right] *= 3.0
        return weights

    def _observed_peak_positions(self, x, corrected_y) -> np.ndarray:
        return observed_peak_positions(x, corrected_y)

    def _observed_peak_records(self, x, corrected_y, limit: int = 24) -> list[ObservedLineRecord]:
        return observed_peak_records(x, corrected_y, limit=limit)

    def _profile_fit_quality(self, observed_y: np.ndarray, background: np.ndarray, calculated_total: np.ndarray) -> float:
        observed_corrected = np.clip(np.asarray(observed_y, dtype=float) - np.asarray(background, dtype=float), 0.0, None)
        calculated_corrected = np.clip(np.asarray(calculated_total, dtype=float) - np.asarray(background, dtype=float), 0.0, None)
        return self._corrected_profile_fit_quality(observed_corrected, calculated_corrected)

    def _corrected_profile_fit_quality(self, observed_corrected: np.ndarray, calculated_corrected: np.ndarray) -> float:
        observed_corrected = np.clip(np.asarray(observed_corrected, dtype=float), 0.0, None)
        calculated_corrected = np.clip(np.asarray(calculated_corrected, dtype=float), 0.0, None)
        if len(observed_corrected) == 0 or float(np.nanmax(observed_corrected)) <= 0:
            return 0.0
        if len(calculated_corrected) != len(observed_corrected):
            return 0.0
        weights = self._fit_weights(observed_corrected)
        residual = observed_corrected - calculated_corrected
        numerator = float(np.nansum(weights * residual * residual))
        denominator = float(np.nansum(weights * observed_corrected * observed_corrected))
        if denominator <= 0:
            return 0.0
        return float(np.clip(100.0 * (1.0 - numerator / denominator), 0.0, 100.0))

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
        return estimate_phase_alignment(peaks, observed_positions, structure)

    def _peak_presence_probability(self, peaks, observed_x: np.ndarray, corrected_y: np.ndarray, structure) -> float:
        return peak_presence_probability(peaks, observed_x, corrected_y, structure)

    def _clear_probability_caches(self) -> None:
        self._observed_probability_cache = None
        self._candidate_probability_cache.clear()
        self._candidate_gain_profile_cache.clear()
        self._candidate_hidden_match_by_key.clear()

    def _trim_candidate_json_peak_cache(self, limit: int = 5000) -> None:
        while len(self._candidate_json_peak_cache) > limit:
            self._candidate_json_peak_cache.pop(next(iter(self._candidate_json_peak_cache)), None)

    def _trim_candidate_probability_cache(self, limit: int = 5000) -> None:
        while len(self._candidate_probability_cache) > limit:
            self._candidate_probability_cache.pop(next(iter(self._candidate_probability_cache)), None)

    def _trim_candidate_gain_profile_cache(self, limit: int = 512) -> None:
        while len(self._candidate_gain_profile_cache) > limit:
            self._candidate_gain_profile_cache.pop(next(iter(self._candidate_gain_profile_cache)), None)

    def _trim_match_profile_result_cache(self, limit: int = 128) -> None:
        while len(self.match_profile_result_cache) > limit:
            self.match_profile_result_cache.pop(next(iter(self.match_profile_result_cache)), None)

    def _trim_candidate_peak_cache(self, limit: int = 2048) -> None:
        while len(self._candidate_peak_cache) > limit:
            self._candidate_peak_cache.pop(next(iter(self._candidate_peak_cache)), None)

    def _active_probability_context_key(self) -> tuple[object, ...]:
        pattern = self._active_pattern()
        pattern_id = getattr(pattern, "id", "") if pattern is not None else ""
        source_path = getattr(pattern, "source_path", "") if pattern is not None else ""
        wavelength = round(float(getattr(pattern, "wavelength", None) or CU_KA1_WAVELENGTH), 6)
        processed = self._active_scoring_observed_data()
        data_len = int(len(processed)) if processed is not None else -1
        data_signature = self._processed_probability_signature(processed)
        background_signature = self._finder_background_signature(self._pattern_finder_background_data(pattern))
        return (
            pattern_id,
            source_path,
            wavelength,
            getattr(self, "_scoring_source", "Auto"),
            self._active_background_removed(),
            data_len,
            data_signature,
            background_signature,
        )

    def _processed_probability_signature(self, processed) -> tuple[float, float, float]:
        if processed is None or not len(processed):
            return (0.0, 0.0, 0.0)
        try:
            y_values = np.asarray(processed[:, 1], dtype=float)
            y_values = y_values[np.isfinite(y_values)]
            if not len(y_values):
                return (0.0, 0.0, 0.0)
            return (
                round(float(np.nanpercentile(y_values, 10)), 3),
                round(float(np.nanpercentile(y_values, 50)), 3),
                round(float(np.nanpercentile(y_values, 99)), 3),
            )
        except Exception:
            return (0.0, 0.0, 0.0)

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

    @traced_operation("gain.rank")
    def _rank_candidate_rows_by_peak_probability(
        self,
        rows: list[list[str]],
        force: bool = False,
        progress=None,
        gain_context=None,
    ) -> list[list[str]]:
        if not force and not self._rank_by_peak_probability_enabled():
            return rows
        probability_data = self._probability_observed_data()
        if probability_data is None:
            return rows
        _observed_x, _corrected, observed_records = probability_data
        if not observed_records:
            return rows
        gain_records = observed_records
        if gain_context is None and self.match_candidates:
            gain_context = self._candidate_gain_context()
        if gain_context is not None:
            residual_share = float(gain_context.get("residual_share", 0.0) or 0.0)
            before_fit = float(gain_context.get("before_fit", 0.0) or 0.0)
            remaining_fit = max(0.0, 100.0 - before_fit)
            if DEFAULT_GAIN_POLICY.residual_is_exhausted(
                selected_phase_count=len(self.match_candidates),
                before_fit=before_fit,
                residual_share=residual_share,
            ):
                self._last_gain_debug = (
                    f"Gain: fit {before_fit:.1f}%, remaining {remaining_fit:.1f}%; "
                    "adding more phases is likely overfitting"
                )
                gain_records = []
            else:
                try:
                    gain_records = self._gain_observed_records(gain_context, limit=80)
                except Exception:
                    gain_records = []
        if gain_context is not None and gain_records:
            if len(self.match_candidates) >= 5:
                low_angle_gain_count = 0
                for record in gain_records:
                    position = self._record_position_value(record)
                    if 5.0 <= position <= 60.0:
                        low_angle_gain_count += 1
                    if low_angle_gain_count >= 3:
                        break
                if low_angle_gain_count < 3:
                    self._last_gain_debug = (
                        f"Gain: residual exhausted ({low_angle_gain_count} uncovered peaks below 60 deg); "
                        "adding more phases is likely overfitting"
                    )
                    gain_records = []

        if force and not self.match_candidates:
            rank_limit = min(len(rows), 1000)
        elif force:
            # Gain rows already passed the indexed peak preselection. Do not
            # discard a valid residual phase merely because it was appended
            # below an arbitrary ranking cutoff.
            rank_limit = len(rows)
        else:
            rank_limit = 120
        rows_to_rank = rows[:rank_limit]
        tail_rows = rows[rank_limit:]
        scored_rows = []
        selected_keys = {self._candidate_key(candidate) for candidate in (self.match_candidates or [])}
        has_selected_phases = bool(self.match_candidates)
        precomputed_gains: dict[int, float] = {}
        active_gain_stage = ""
        if has_selected_phases and gain_context is not None:
            active_gain_stage = self._gain_stage_for_context(gain_context)
            gain_context["gain_stage"] = active_gain_stage
            for row_index, row in enumerate(rows_to_rank):
                if progress is not None and row_index % 25 == 0:
                    try:
                        progress(row_index, len(rows_to_rank))
                    except Exception:
                        pass
                candidate = {
                    "Source": row[0] if len(row) > 0 else "",
                    "Entry": row[1] if len(row) > 1 else "",
                    "Formula": row[2] if len(row) > 2 else "",
                    "Phase": row[3] if len(row) > 3 else "",
                }
                if self._candidate_key(candidate) in selected_keys:
                    continue
                precomputed_gains[row_index] = self._candidate_row_integral_gain(row, gain_context)
            if (
                active_gain_stage == str(GainStage.DIRECT)
                and not any(gain > 0.0 for gain in precomputed_gains.values())
                and len(self._gain_stage_records(gain_context, GainStage.OVERLAP, limit=24))
                >= DEFAULT_GAIN_POLICY.minimum_stage_records
            ):
                active_gain_stage = str(GainStage.OVERLAP)
                self._gain_overlap_locked = True
                gain_context["gain_stage"] = active_gain_stage
                for row_index, row in enumerate(rows_to_rank):
                    candidate = {
                        "Source": row[0] if len(row) > 0 else "",
                        "Entry": row[1] if len(row) > 1 else "",
                        "Formula": row[2] if len(row) > 2 else "",
                        "Phase": row[3] if len(row) > 3 else "",
                    }
                    if self._candidate_key(candidate) in selected_keys:
                        continue
                    precomputed_gains[row_index] = self._candidate_row_integral_gain(row, gain_context)
            self._active_gain_stage = active_gain_stage
        for index, row in enumerate(rows_to_rank):
            if progress is not None and not precomputed_gains and (index == 0 or index % 25 == 0):
                try:
                    progress(index, len(rows_to_rank))
                except Exception:
                    pass
            elif progress is None and index > 0 and index % 50 == 0:
                QApplication.processEvents()
            scored_row = list(row)
            row_candidate = {
                "Source": scored_row[0] if len(scored_row) > 0 else "",
                "Entry": scored_row[1] if len(scored_row) > 1 else "",
                "Formula": scored_row[2] if len(scored_row) > 2 else "",
                "Phase": scored_row[3] if len(scored_row) > 3 else "",
            }
            row_key = self._candidate_key(row_candidate)
            existing_match_text = scored_row[5] if len(scored_row) > 5 else ""
            hidden_matches = getattr(self, "_candidate_hidden_match_by_key", None)
            if hidden_matches is None:
                hidden_matches = {}
                self._candidate_hidden_match_by_key = hidden_matches
            if existing_match_text:
                hidden_matches[row_key] = existing_match_text
            elif has_selected_phases:
                existing_match_text = hidden_matches.get(row_key, "")
            scored_row[5] = ""
            scored_row[6] = ""
            if has_selected_phases:
                probability = self._percent_text_value(existing_match_text)
            else:
                probability = self._candidate_row_peak_probability_from_records(
                    scored_row,
                    observed_records,
                    allow_cif_fallback=False,
                )
            if probability > 0 and not has_selected_phases:
                scored_row[5] = f"{probability:.0f}%"
            gain = 0.0
            if has_selected_phases:
                gain = precomputed_gains.get(index, 0.0)
            if gain > 0:
                scored_row[6] = f"{gain:.1f}%" if gain < 10.0 else f"{gain:.0f}%"
            scored_rows.append([gain, probability, index, scored_row])
        if progress is not None:
            try:
                progress(len(rows_to_rank), len(rows_to_rank))
            except Exception:
                pass

        if getattr(self, "scoring_status_label", None) is not None:
            match_nonzero = sum(1 for _gain, probability, _index, _row in scored_rows if probability > 0.0)
            gain_nonzero = sum(1 for gain, _probability, _index, _row in scored_rows if gain > 0.0)
            gain_text = ""
            if self.match_candidates:
                residual_share = float(gain_context.get("residual_share", 0.0) or 0.0) if gain_context is not None else 0.0
                before_fit = float(gain_context.get("before_fit", 0.0) or 0.0) if gain_context is not None else 0.0
                remaining_fit = max(0.0, 100.0 - before_fit)
                if gain_context is not None:
                    stage_label = {
                        "direct": "Direct",
                        "overlap": "Overlap",
                        "hidden": "Hidden",
                    }.get(active_gain_stage, "")
                    if (before_fit >= 98.0 or residual_share < 0.025 or remaining_fit < 1.5) and gain_nonzero == 0:
                        gain_text = f"Gain: fit {before_fit:.1f}%, remaining {remaining_fit:.1f}%"
                    else:
                        gain_text = (
                            f"Gain {stage_label}: fit {before_fit:.1f}%, "
                            f"remaining {remaining_fit:.1f}%, candidates {gain_nonzero}/{len(scored_rows)}"
                        )
                if not gain_text and gain_nonzero == 0:
                    gain_text = getattr(self, "_last_gain_debug", "") or "Gain: no new phase signal"
            suffix = gain_text or f"FP: match {match_nonzero}/{len(scored_rows)}, gain {gain_nonzero}/{len(scored_rows)}"
            self.scoring_status_label.setText(f"{self._scoring_source_status_text()} | {suffix}")
        if not any(gain > 0 or probability > 0 for gain, probability, _index, _row in scored_rows):
            return [row for _gain, _probability, _index, row in scored_rows] + tail_rows
        scored_rows.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [row for _gain, _probability, _index, row in scored_rows] + tail_rows

    def _percent_text_value(self, text: object) -> float:
        try:
            value = str(text).strip().replace("%", "").replace(",", ".")
            return float(value) if value else 0.0
        except Exception:
            return 0.0

    def _gain_observed_records(self, context, limit: int = 80) -> list[ObservedLineRecord]:
        x = np.asarray(context["x"], dtype=float)
        residual_target = np.asarray(context["residual_target"], dtype=float)
        residual_records = self._observed_peak_records(x, residual_target, limit=limit * 2)
        selected_total = np.asarray(context.get("selected_total", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        records = list(residual_records)
        if not records:
            return []
        if len(selected_total) != len(x) or len(target) != len(x):
            return records[:limit]
        selected_peak_positions = np.asarray(context.get("selected_peak_positions", []), dtype=float)
        selected_peak_positions = selected_peak_positions[np.isfinite(selected_peak_positions)]
        selected_peak_positions.sort()
        stick_tolerance = max(0.32, min(0.72, float(context.get("fwhm", 0.18) or 0.18) * 3.0))
        explained_peak_indices, _properties = find_peaks(
            np.clip(selected_total, 0.0, None),
            prominence=max(float(np.nanpercentile(np.clip(selected_total, 0.0, None), 98)) * 0.015, 1.0),
            distance=max(3, len(selected_total) // 1600),
        )
        if len(explained_peak_indices) == 0 and not len(selected_peak_positions):
            return records[:limit]
        explained_positions = x[explained_peak_indices]
        explained_strength = selected_total[explained_peak_indices]
        strength_floor = max(float(np.nanpercentile(explained_strength, 55)), 1.0) if len(explained_strength) else 1.0
        keep_records: list[tuple[float, float]] = []
        seen_positions: set[int] = set()
        tolerance = max(0.34, min(0.85, float(context.get("fwhm", 0.18) or 0.18) * 2.7))
        residual_positive = residual_target[np.isfinite(residual_target) & (residual_target > 0.0)]
        residual_height_floor = (
            max(
                float(np.nanpercentile(residual_positive, 72)) * 0.28,
                float(np.nanpercentile(residual_positive, 93)) * 0.045,
                1.0,
            )
            if len(residual_positive)
            else 1.0
        )
        for record in records:
            position = self._record_position_value(record)
            line_fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), float(context.get("fwhm", 0.18) or 0.18))
            line_stick_tolerance = max(0.24, min(0.95, line_fwhm * 1.45))
            line_profile_tolerance = max(0.28, min(1.05, line_fwhm * 1.70))
            if len(selected_peak_positions):
                stick_index = int(np.searchsorted(selected_peak_positions, float(position)))
                stick_deltas = []
                if stick_index < len(selected_peak_positions):
                    stick_deltas.append(abs(float(selected_peak_positions[stick_index]) - float(position)))
                if stick_index > 0:
                    stick_deltas.append(abs(float(selected_peak_positions[stick_index - 1]) - float(position)))
                if stick_deltas and min(stick_deltas) <= max(stick_tolerance, line_stick_tolerance):
                    continue
            covered_by_profile = False
            if len(explained_positions):
                index = int(np.argmin(np.abs(explained_positions - float(position))))
                delta = abs(float(explained_positions[index]) - float(position))
                covered_by_profile = delta <= max(tolerance, line_profile_tolerance) and float(explained_strength[index]) >= strength_floor
            if covered_by_profile:
                target_index = int(np.argmin(np.abs(x - float(position))))
                target_height = max(float(target[target_index]), 1.0)
                residual_height = max(float(residual_target[target_index]), 0.0)
                if residual_height <= max(target_height * 0.45, residual_height_floor):
                    continue
            else:
                target_index = int(np.argmin(np.abs(x - float(position))))
                residual_height = max(float(residual_target[target_index]), 0.0)
                if residual_height <= residual_height_floor:
                    continue
            position_key = int(round(float(position) * 1000.0))
            if position_key in seen_positions:
                continue
            seen_positions.add(position_key)
            keep_records.append(record)
            if len(keep_records) >= limit:
                break
        return keep_records

    def _gain_stage_records(self, context, stage: str, limit: int = 80) -> list[ObservedLineRecord]:
        cache = context.setdefault("_gain_stage_records_cache", {})
        cache_key = (str(stage), int(limit))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        records = self._compute_gain_stage_records(context, stage, limit=limit)
        cache[cache_key] = records
        return records

    def _compute_gain_stage_records(self, context, stage: str, limit: int = 80) -> list[ObservedLineRecord]:
        if stage == "direct":
            return self._gain_observed_records(context, limit=limit)

        x = np.asarray(context.get("x", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        residual_target = np.asarray(context.get("residual_target", []), dtype=float)
        if len(x) == 0 or len(target) != len(x) or len(residual_target) != len(x):
            return []
        if stage == "hidden":
            return self._observed_peak_records(x, target, limit=limit)

        selected_positions = np.asarray(context.get("selected_peak_positions", []), dtype=float)
        selected_positions = selected_positions[np.isfinite(selected_positions)]
        selected_positions.sort()
        if not len(selected_positions):
            return []
        records = self._observed_peak_records(x, target, limit=limit * 3)
        overlap_records: list[ObservedLineRecord] = []
        base_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        selected_total = np.asarray(context.get("selected_total", []), dtype=float)
        if len(selected_total) != len(x):
            return []
        target_positive = target[np.isfinite(target) & (target > 0.0)]
        residual_positive = residual_target[np.isfinite(residual_target) & (residual_target > 0.0)]
        if not len(target_positive) or not len(residual_positive):
            return []
        deficit_floor = max(
            float(np.nanpercentile(residual_positive, 65)) * 0.20,
            float(np.nanpercentile(target_positive, 80)) * 0.025,
            1.0,
        )
        for record in records:
            position = self._record_position_value(record)
            index = int(np.searchsorted(selected_positions, position))
            neighbours = []
            if index < len(selected_positions):
                neighbours.append(abs(float(selected_positions[index]) - position))
            if index > 0:
                neighbours.append(abs(float(selected_positions[index - 1]) - position))
            local_tolerance = max(
                0.28,
                min(
                    0.85,
                    max(float(getattr(record, "fwhm", 0.0) or 0.0), base_fwhm) * 1.7,
                ),
            )
            if not neighbours or min(neighbours) > local_tolerance:
                continue
            half_width = max(local_tolerance, float(getattr(record, "fwhm", 0.0) or 0.0) * 1.25)
            left = int(np.searchsorted(x, position - half_width, side="left"))
            right = int(np.searchsorted(x, position + half_width, side="right"))
            if right <= left:
                continue
            observed_height = float(np.nanmax(target[left:right]))
            calculated_height = float(np.nanmax(selected_total[left:right]))
            residual_height = float(np.nanmax(residual_target[left:right]))
            deficit_height = max(observed_height - calculated_height, residual_height, 0.0)
            deficit_fraction = deficit_height / max(observed_height, 1.0e-12)
            if deficit_height < deficit_floor or deficit_fraction < 0.12:
                continue
            overlap_records.append(
                ObservedLineRecord(
                    two_theta=float(position),
                    area=max(float(getattr(record, "area", 0.0) or 0.0) * deficit_fraction, deficit_height),
                    fwhm=float(getattr(record, "fwhm", base_fwhm) or base_fwhm),
                    height=deficit_height,
                )
            )
            if len(overlap_records) >= limit:
                break
        overlap_records.sort(key=lambda item: float(item.area), reverse=True)
        return overlap_records

    def _gain_stage_for_context(self, context) -> str:
        if self._gain_overlap_locked:
            overlap_count = len(self._gain_stage_records(context, GainStage.OVERLAP, limit=24))
            if overlap_count >= DEFAULT_GAIN_POLICY.minimum_stage_records:
                return str(GainStage.OVERLAP)
            return str(GainStage.HIDDEN)
        return str(
            DEFAULT_GAIN_POLICY.select_stage(
                direct_count=len(self._gain_stage_records(context, GainStage.DIRECT, limit=24)),
                overlap_count=len(self._gain_stage_records(context, GainStage.OVERLAP, limit=24)),
            )
        )

    def _capture_candidate_gain_indexed_evidence(self, candidate: dict[str, str]) -> None:
        if not self.match_candidates:
            return
        context = self._candidate_gain_context()
        if context is None:
            return
        stage = GainStage(
            getattr(self, "_active_gain_stage", "") or self._gain_stage_for_context(context)
        )
        context["gain_stage"] = str(stage)
        records = self._gain_stage_records(context, str(stage), limit=90)
        peaks = self._candidate_peaks_for_gain(candidate)
        peaks = self._aligned_candidate_gain_peaks(candidate, peaks, context)
        evidence = build_gain_indexed_evidence(
            peaks=peaks,
            records=records,
            stage=stage,
            base_fwhm=float(context.get("fwhm", 0.18) or 0.18),
        )
        if evidence.indexed_matches:
            self._candidate_gain_indexed_evidence[self._candidate_key(candidate)] = evidence

    def _gain_sql_candidate_rows(self, *, stage: str = "direct", context=None) -> list[list[str]]:
        if context is None:
            context = self._candidate_gain_context()
        if context is None:
            return []
        context["gain_stage"] = stage
        before_fit = float(context.get("before_fit", 0.0) or 0.0)
        remaining_fit = max(0.0, 100.0 - before_fit)
        residual_share = float(context.get("residual_share", 0.0) or 0.0)
        if DEFAULT_GAIN_POLICY.residual_is_exhausted(
            selected_phase_count=len(self.match_candidates),
            before_fit=before_fit,
            residual_share=residual_share,
        ):
            self._last_gain_debug = (
                f"Gain: fit {before_fit:.1f}%, remaining {remaining_fit:.1f}%; "
                "adding more phases is likely overfitting"
            )
            return []
        stage_records = self._gain_stage_records(context, stage, limit=80)
        positions = []
        for record in sorted(
            stage_records,
            key=lambda item: max(float(getattr(item, "area", 0.0) or 0.0), 0.0),
            reverse=True,
        ):
            position = self._record_position_value(record)
            if 5.0 <= position <= 60.0:
                positions.append(position)
            if len(positions) >= (10 if stage == "hidden" else 12):
                break
        if len(positions) < 2:
            return []
        options = self._candidate_search_options() if hasattr(self, "_candidate_search_options") else None
        sources = options.local_sources if options is not None else self._local_cache_sources()
        excluded = options.excluded_elements if options is not None else self._excluded_elements()
        try:
            entries = self.local_phase_cache.search_by_peaks(
                positions,
                excluded_elements=excluded,
                sources=sources,
                tolerance_two_theta=max(
                    0.30,
                    min(0.70, float(context.get("fwhm", 0.18) or 0.18) * 2.4),
                ),
                limit=700,
            )
        except Exception:
            return []
        rows = self.candidate_search_service.dedupe_candidate_rows(
            self.candidate_search_service.cache_rows(entries)
        )
        if options is not None:
            rows = self.candidate_search_service.filter_candidate_rows_by_excluded_elements(rows, options)
        return rows

    def _candidate_gain_context(self):
        selected_candidates = list(self.match_candidates or [])
        pattern = self._active_pattern()
        observed = self._active_scoring_observed_data()
        if observed is None or not len(observed):
            self._last_gain_debug = "Gain: no observed data"
            return None
        try:
            finder_background = self._pattern_finder_background_data(pattern)
            finder_observed = self._pattern_finder_observed_data(pattern) if finder_background is not None else None
            if finder_background is not None and finder_observed is not None and len(finder_observed):
                x = np.asarray(finder_observed[:, 0], dtype=float)
                y = np.asarray(finder_observed[:, 1], dtype=float)
                background_x = np.asarray(finder_background[:, 0], dtype=float)
                background_y = np.asarray(finder_background[:, 1], dtype=float)
                background = np.interp(x, background_x, background_y, left=float(background_y[0]), right=float(background_y[-1]))
                corrected = np.clip(y - background, 0.0, None)
            else:
                x = np.asarray(observed[:, 0], dtype=float)
                y = np.asarray(observed[:, 1], dtype=float)
            if finder_background is None and (
                getattr(self, "_scoring_source", "Auto") == "Auto"
                or self._pattern_scoring_background_removed(pattern)
            ):
                corrected = np.clip(y, 0.0, None)
            elif finder_background is None:
                background = self._estimate_background(x, y)
                corrected = np.clip(y - background, 0.0, None)
            if len(corrected) == 0 or float(np.nanmax(corrected)) <= 0:
                self._last_gain_debug = "Gain: corrected profile is empty"
                return None
            noise_floor = self._gain_noise_floor(corrected)
            target = np.clip(corrected - noise_floor, 0.0, None)
            if float(np.nanmax(target)) <= 0:
                self._last_gain_debug = f"Gain: target empty, noise floor {noise_floor:.4g}"
                return None
            fwhm = float(getattr(self, "_last_match_profile_fwhm", 0.0) or self._estimate_profile_fwhm(x, corrected))
            eta = float(getattr(self, "_last_match_profile_eta", 0.0) or 0.0)
            weights = self._fit_weights(target)
            selected_profiles = []
            selected_peak_positions = []
            for candidate in selected_candidates:
                peaks = self._candidate_peaks_for_gain(candidate)
                peaks = self._adjusted_gain_peaks(candidate, peaks)
                profile = self._profile_from_gain_peaks(peaks, x, fwhm, eta) if peaks else None
                if profile is not None:
                    selected_profiles.append(profile)
                    selected_peak_positions.extend(
                        float(getattr(peak, "two_theta", 0.0))
                        for peak in peaks
                        if float(getattr(peak, "intensity", 0.0) or 0.0) >= 1.0
                    )
            if selected_candidates and not selected_profiles:
                self._last_gain_debug = "Gain: no selected phase profiles"
                return None
            selected_scales = self._fit_nonnegative_scales(target, selected_profiles, weights)
            selected_total = self._scaled_profile_sum(selected_profiles, selected_scales, target)
            difference_curve = target - selected_total
            residual_target = self._gain_residual_target(difference_curve, x, fwhm)
            residual_weights = self._fit_weights(residual_target) if float(np.nanmax(residual_target)) > 0 else weights
            before_error = self._weighted_gain_error(residual_target, np.zeros_like(residual_target), residual_weights)
            residual_area = self._weighted_integral_area(residual_target, residual_weights)
            target_area = self._weighted_integral_area(target, weights)
            residual_share = residual_area / max(target_area, 1.0e-12)
            before_fit = self._corrected_profile_fit_quality(target, selected_total)
            residual_signal = self._gain_residual_signal_factor(target, residual_target, x)
            if residual_signal <= 0.0:
                residual_max = float(np.nanmax(residual_target)) if len(residual_target) else 0.0
                self._last_gain_debug = f"Gain: residual below background, max {residual_max:.4g}"
                return None
            if residual_area <= 0:
                residual_max = float(np.nanmax(residual_target)) if len(residual_target) else 0.0
                self._last_gain_debug = f"Gain: residual empty, max {residual_max:.4g}"
                return None
            return {
                "key": self._active_probability_context_key(),
                "x": x,
                "target": target,
                "weights": residual_weights,
                "target_weights": weights,
                "fwhm": fwhm,
                "eta": eta,
                "selected_profiles": selected_profiles,
                "selected_total": selected_total,
                "selected_peak_positions": np.asarray(selected_peak_positions, dtype=float),
                "difference_curve": difference_curve,
                "residual_target": residual_target,
                "before_error": before_error,
                "before_fit": before_fit,
                "residual_area": residual_area,
                "target_area": target_area,
                "residual_share": residual_share,
                "residual_signal": residual_signal,
            }
        except Exception:
            import traceback
            self._last_gain_debug = "Gain: context exception"
            print("Gain context exception:", traceback.format_exc(), flush=True)
            return None

    def _candidate_row_integral_gain(self, row: list[str], context) -> float:
        if context is None:
            return 0.0
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        peaks = self._candidate_cached_json_peaks(candidate)
        if not peaks:
            peaks = self._candidate_cif_peaks_for_gain(candidate)
        if not peaks:
            return 0.0
        peaks = self._aligned_candidate_gain_peaks(candidate, peaks, context)
        stage = str(context.get("gain_stage", "direct") or "direct")
        if stage in {"direct", "overlap"}:
            line_gain = self._candidate_residual_line_gain(peaks, context)
            if line_gain <= 0.0:
                return 0.0
            candidate_profile = self._candidate_gain_profile(candidate, peaks, context)
            if candidate_profile is None:
                return line_gain
            # Residual sticks are the primary Gain evidence. The full profile
            # only moderates that score: profile fitting may be underdetermined
            # for strongly overlapping phases and must not erase valid direct
            # matches altogether.
            profile_gain = self._candidate_gain_value_for_profile(candidate_profile, context)
            return DEFAULT_GAIN_POLICY.combine_line_and_profile(
                line_gain=line_gain,
                profile_gain=profile_gain,
            )

        observed_records = self._gain_stage_records(context, "hidden", limit=120)
        presence = self._candidate_gain_presence_factor(
            row,
            observed_records,
            observed_records,
        )
        if presence <= 0.0:
            return 0.0
        return DEFAULT_GAIN_POLICY.hidden_gain(
            before_fit=float(context.get("before_fit", 0.0) or 0.0),
            presence=presence,
        )

    def _candidate_cif_peaks_for_gain(self, candidate: dict[str, str]) -> list[HKLPeak]:
        structure = None
        pattern = self._active_pattern()
        if pattern is not None:
            structure = self._finder_candidate_structure_overrides(pattern, [candidate]).get(
                self._candidate_key(candidate)
            )
        cif_path = self._candidate_local_cif_path(candidate)
        try:
            if structure is None:
                if cif_path is None:
                    return []
                _phase, structure = create_phase_from_cif(cif_path)
            if candidate.get("Phase"):
                structure.name = candidate["Phase"]
            structure.wavelength = self._active_wavelength()
            if cif_path is not None:
                return self._candidate_cached_peaks(cif_path, structure)
            return self.calculated_pattern_service.calculate_sticks(
                structure,
                wavelength=self._active_wavelength(),
                two_theta_min=5.0,
                two_theta_max=120.0,
                intensity_min=0.5,
            )
        except Exception:
            return []

    def _candidate_gain_value_for_profile(self, candidate_profile: np.ndarray, context) -> float:
        residual_target = np.asarray(context["residual_target"], dtype=float)
        target = np.asarray(context["target"], dtype=float)
        selected_total = np.asarray(context["selected_total"], dtype=float)
        weights = np.asarray(context.get("target_weights", context["weights"]), dtype=float)
        candidate_scale = self._fit_residual_candidate_scale(
            target,
            selected_total,
            candidate_profile,
            weights,
        )
        if candidate_scale <= 1.0e-8:
            return 0.0
        calculated = candidate_profile * candidate_scale
        return profile_residual_gain(
            residual_target=residual_target,
            calculated=calculated,
            weights=weights,
            residual_area=float(context["residual_area"]),
            before_fit=float(context.get("before_fit", 0.0) or 0.0),
        )

    def _aligned_candidate_gain_peaks(
        self,
        candidate: dict[str, str],
        peaks: list[HKLPeak],
        context,
    ) -> list[HKLPeak]:
        key = self._candidate_key(candidate)
        if key in self.match_zero_shifts or key in self.match_cell_scales:
            return self._adjusted_gain_peaks(candidate, peaks)
        x = np.asarray(context.get("x", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        if len(x) < 5 or len(target) != len(x):
            return peaks
        records = self._gain_context_observed_peak_records(context, "target", limit=140)
        positions = self._record_positions(records)
        if len(positions) < 3:
            return peaks
        alignment = self._estimate_phase_alignment(peaks, positions, None)
        if alignment.matched_peaks < 3 or alignment.status == "weak":
            return peaks
        zero_shift = float(alignment.zero_shift)
        if abs(zero_shift) < 1.0e-8:
            return peaks
        return [
            HKLPeak(
                h=int(getattr(peak, "h", 0) or 0),
                k=int(getattr(peak, "k", 0) or 0),
                l=int(getattr(peak, "l", 0) or 0),
                d=float(getattr(peak, "d", 0.0) or 0.0),
                two_theta=float(getattr(peak, "two_theta", 0.0) or 0.0) + zero_shift,
                intensity=float(getattr(peak, "intensity", 0.0) or 0.0),
                multiplicity=int(getattr(peak, "multiplicity", 1) or 1),
                f2=float(getattr(peak, "f2", 0.0) or 0.0),
                lp=float(getattr(peak, "lp", 1.0) or 1.0),
                raw_intensity=float(getattr(peak, "raw_intensity", 0.0) or 0.0),
            )
            for peak in peaks
        ]

    def _candidate_gain_line_support(self, peaks: list[HKLPeak], context) -> float:
        x = np.asarray(context.get("x", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        residual = np.asarray(context.get("residual_target", []), dtype=float)
        if len(x) < 5 or len(target) != len(x) or len(residual) != len(x):
            return 0.0
        observed_records = self._observed_peak_records(x, target, limit=160)
        residual_records = self._observed_peak_records(x, residual, limit=120)
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

    def _candidate_gain_intensity_factor(self, pairs: list[tuple[HKLPeak, object]]) -> float:
        if len(pairs) < 3:
            return 0.0
        ratios = []
        weights = []
        for peak, record in pairs:
            theoretical = max(float(getattr(peak, "intensity", 0.0) or 0.0), 1.0e-6)
            experimental = getattr(record, "area", None)
            if experimental is None:
                try:
                    experimental = record[1]
                except Exception:
                    continue
            experimental = max(float(experimental or 0.0), 1.0e-6)
            ratios.append(math.log(experimental / theoretical))
            weights.append(math.sqrt(theoretical))
        if len(ratios) < 3:
            return 0.0
        values = np.asarray(ratios, dtype=float)
        line_weights = np.asarray(weights, dtype=float)
        center = float(np.median(values))
        deviations = np.abs(values - center)
        order = np.argsort(deviations)
        # One or two systematic texture-enhanced directions should not reject
        # an otherwise coherent phase.
        keep_count = max(3, len(order) - min(2, max(0, len(order) // 5)))
        keep = order[:keep_count]
        mean_deviation = float(np.average(deviations[keep], weights=line_weights[keep]))
        coherent_fraction = keep_count / max(len(values), 1)
        return float(np.clip(math.exp(-mean_deviation / 0.95) * coherent_fraction, 0.05, 1.0))

    def _candidate_residual_line_gain(self, peaks: list[HKLPeak], context) -> float:
        if not peaks or context is None:
            return 0.0
        x = np.asarray(context.get("x", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        residual_target = np.asarray(context.get("residual_target", []), dtype=float)
        if len(x) == 0 or len(target) != len(x) or len(residual_target) != len(x):
            return 0.0
        stage = str(context.get("gain_stage", "direct") or "direct")
        residual_records = self._gain_stage_records(context, stage, limit=90)
        target_records = self._gain_context_observed_peak_records(context, "target", limit=140)
        if not residual_records or not target_records:
            return 0.0
        residual_records = sorted(
            residual_records,
            key=lambda record: max(float(getattr(record, "area", 0.0) or 0.0), 0.0),
            reverse=True,
        )
        strong = [
            peak
            for peak in sorted(peaks, key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0), reverse=True)
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
            and 5.0 <= float(getattr(peak, "two_theta", 0.0) or 0.0) <= 120.0
        ][:42]
        if len(strong) < 3:
            return 0.0

        base_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        tolerance = max(0.26, min(0.72, base_fwhm * 2.4))
        candidate_positions = np.asarray([float(getattr(peak, "two_theta", 0.0) or 0.0) for peak in strong], dtype=float)
        candidate_weights = np.asarray(
            [
                max(float(getattr(peak, "intensity", 0.0) or 0.0) / 100.0, 0.025) ** 0.55 / math.sqrt(index + 1.0)
                for index, peak in enumerate(strong)
            ],
            dtype=float,
        )
        candidate_ranks = np.arange(len(strong), dtype=int)
        order = np.argsort(candidate_positions)
        candidate_positions = candidate_positions[order]
        candidate_weights = candidate_weights[order]
        candidate_ranks = candidate_ranks[order]

        useful_area = 0.0
        matched_residual_count = 0
        matched_major_residual_count = 0
        matched_candidate_indices: set[int] = set()
        matched_residual_pairs: list[tuple[HKLPeak, ObservedLineRecord]] = []
        matched_top_count = 0
        residual_area = sum(max(float(getattr(record, "area", 0.0) or 0.0), 0.0) for record in residual_records)
        major_residual_limit = min(14, len(residual_records))
        for residual_index, record in enumerate(residual_records):
            position = self._record_position_value(record)
            area = max(float(getattr(record, "area", 0.0) or 0.0), 0.0)
            if area <= 0.0:
                continue
            best_delta = 999.0
            best_index = -1
            for candidate_index, candidate_position in enumerate(candidate_positions):
                if candidate_index in matched_candidate_indices:
                    continue
                delta = abs(float(candidate_position) - float(position))
                if delta < best_delta:
                    best_delta = delta
                    best_index = candidate_index
            line_fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), base_fwhm)
            local_tolerance = max(tolerance, min(0.95, line_fwhm * 1.7))
            if best_index < 0 or best_delta > local_tolerance:
                continue
            position_quality = max(0.0, 1.0 - best_delta / max(local_tolerance, 1.0e-6))
            useful_area += area * (0.35 + 0.65 * position_quality)
            matched_residual_count += 1
            if residual_index < major_residual_limit:
                matched_major_residual_count += 1
            if int(candidate_ranks[best_index]) < 12:
                matched_top_count += 1
            matched_candidate_indices.add(best_index)
            matched_residual_pairs.append((strong[int(candidate_ranks[best_index])], record))

        if useful_area <= 0.0 or matched_residual_count < 2:
            return 0.0
        major_fraction = matched_major_residual_count / max(major_residual_limit, 1)
        residual_coverage = useful_area / max(residual_area, 1.0e-12)

        target_positions = self._record_positions(target_records)
        selected_total = np.asarray(context.get("selected_total", []), dtype=float)
        selected_positions = np.asarray(context.get("selected_peak_positions", []), dtype=float)
        selected_positions = selected_positions[np.isfinite(selected_positions)]
        selected_positions.sort()
        target_positive = target[np.isfinite(target) & (target > 0.0)]
        residual_positive = residual_target[np.isfinite(residual_target) & (residual_target > 0.0)]
        if not len(target_positive) or not len(residual_positive):
            return 0.0
        target_floor = max(
            float(np.nanpercentile(target_positive, 70)) * 0.22,
            float(np.nanpercentile(target_positive, 92)) * 0.035,
            1.0,
        )
        residual_floor = max(
            float(np.nanpercentile(residual_positive, 70)) * 0.30,
            float(np.nanpercentile(residual_positive, 92)) * 0.045,
            1.0,
        )

        def local_max(values: np.ndarray, center: float, half_width: float) -> float:
            if len(values) != len(x):
                return 0.0
            left = int(np.searchsorted(x, center - half_width, side="left"))
            right = int(np.searchsorted(x, center + half_width, side="right"))
            if right <= left:
                return 0.0
            return float(np.nanmax(values[left:right]))

        absent_weight = 0.0
        repeated_weight = 0.0
        matched_weight = 0.0
        observed_only_weight = 0.0
        anchor_weight = 0.0
        matched_anchor_weight = 0.0
        absent_top_count = 0
        checked_top_count = 0
        local_signal_width = max(0.20, min(0.80, tolerance * 1.25))
        for index, (position, weight) in enumerate(zip(candidate_positions, candidate_weights, strict=False)):
            rank = int(candidate_ranks[index])
            if rank < 12:
                checked_top_count += 1
                anchor_weight += float(weight)
            if index in matched_candidate_indices:
                matched_weight += float(weight)
                if rank < 12:
                    matched_anchor_weight += float(weight)
                continue
            target_peak = local_max(target, float(position), local_signal_width)
            residual_peak = local_max(residual_target, float(position), local_signal_width)
            selected_peak = local_max(selected_total, float(position), local_signal_width) if len(selected_total) == len(x) else 0.0
            has_observed_signal = target_peak >= target_floor or residual_peak >= residual_floor
            if len(selected_positions) and self._nearest_selected_line_delta(selected_positions, float(position)) <= tolerance:
                if stage == "overlap":
                    observed_only_weight += float(weight) * 0.15
                else:
                    repeated_weight += float(weight) * 0.80
            elif selected_peak >= max(target_floor, target_peak * 0.35):
                if stage == "overlap":
                    observed_only_weight += float(weight) * 0.15
                else:
                    repeated_weight += float(weight) * 0.65
            elif has_observed_signal or self._nearest_selected_line_delta(target_positions, float(position)) <= tolerance:
                observed_only_weight += float(weight) * 0.50
            else:
                penalty = 3.25 if rank < 10 else 1.35
                absent_weight += float(weight) * penalty
                if rank < 12:
                    absent_top_count += 1

        support = matched_weight / max(matched_weight + 3.4 * absent_weight + 1.6 * repeated_weight + observed_only_weight, 1.0e-12)
        anchor_support = matched_anchor_weight / max(anchor_weight, 1.0e-12)
        intensity_factor = self._candidate_gain_intensity_factor(matched_residual_pairs)
        if matched_top_count < 2 and anchor_support < 0.20:
            return 0.0
        if checked_top_count and absent_top_count >= max(3, int(math.ceil(checked_top_count * 0.34))):
            if absent_weight > matched_weight * 1.15:
                return 0.0
        if (
            major_fraction < 0.18
            or residual_coverage < 0.035
            or support < 0.22
            or anchor_support < 0.16
            or intensity_factor < 0.10
        ):
            return 0.0
        before_fit = float(context.get("before_fit", 0.0) or 0.0)
        remaining_fit = max(0.0, 100.0 - before_fit)
        line_gain = (
            remaining_fit
            * min(1.0, residual_coverage)
            * min(1.0, major_fraction / 0.38)
            * min(1.0, support / 0.48)
            * min(1.0, anchor_support / 0.42)
            * (0.45 + 0.55 * intensity_factor)
        )
        return float(np.clip(line_gain, 0.0, remaining_fit))

    def _gain_residual_target(self, difference_curve: np.ndarray, x: np.ndarray, fwhm: float) -> np.ndarray:
        values = np.asarray(difference_curve, dtype=float)
        if len(values) == 0:
            return values
        raw_positive = np.clip(values, 0.0, None)
        step = float(np.nanmedian(np.diff(np.asarray(x, dtype=float)))) if len(x) > 1 else 0.03
        sigma = max(1.0, min(14.0, float(fwhm) / max(abs(step), 1.0e-6) / 4.0))
        smooth = gaussian_filter1d(values, sigma=sigma, mode="nearest")
        positive = np.clip(smooth, 0.0, None)
        if float(np.nanmax(positive)) <= 0:
            return raw_positive
        floor = max(float(np.nanpercentile(positive, 35)) * 0.25, self._gain_noise_floor(positive) * 0.05)
        residual = np.clip(positive - floor, 0.0, None)
        if float(np.nanmax(residual)) <= 0 or self._weighted_integral_area(residual, np.ones_like(residual)) <= 0:
            return positive
        return residual

    def _fit_residual_candidate_scale(
        self,
        target: np.ndarray,
        selected_total: np.ndarray,
        profile: np.ndarray,
        weights: np.ndarray,
    ) -> float:
        target = np.asarray(target, dtype=float)
        current = np.asarray(selected_total, dtype=float)
        candidate = np.asarray(profile, dtype=float)
        fit_weights = np.clip(np.asarray(weights, dtype=float), 0.0, None)
        usable = (
            np.isfinite(target)
            & np.isfinite(current)
            & np.isfinite(candidate)
            & np.isfinite(fit_weights)
            & (fit_weights > 0.0)
        )
        if not np.any(usable) or float(np.nanmax(candidate[usable])) <= 0.0:
            return 0.0
        residual = np.clip(target - current, 0.0, None)
        weighted_profile = candidate * fit_weights
        denominator = float(np.dot(weighted_profile[usable], candidate[usable]))
        if denominator <= 1.0e-12:
            return 0.0
        initial = max(
            0.0,
            float(np.dot(weighted_profile[usable], residual[usable])) / denominator,
        )
        if initial <= 1.0e-12:
            return 0.0
        before_error = self._weighted_gain_error(
            target,
            current,
            fit_weights,
            excess_penalty=5.0,
        )
        best_scale = 0.0
        best_error = before_error
        for factor in np.linspace(0.05, 1.35, 27):
            scale = initial * float(factor)
            error = self._weighted_gain_error(
                target,
                current + candidate * scale,
                fit_weights,
                excess_penalty=5.0,
            )
            if error < best_error:
                best_error = error
                best_scale = scale
        return float(best_scale)

    def _adjusted_gain_peaks(self, candidate: dict[str, str], peaks: list[HKLPeak]) -> list[HKLPeak]:
        if not peaks:
            return []
        key = self._candidate_key(candidate)
        zero_shift = float(self.match_zero_shifts.get(key, 0.0) or 0.0)
        cell_scale = float(self.match_cell_scales.get(key, 1.0) or 1.0)
        if abs(zero_shift) < 1.0e-8 and abs(cell_scale - 1.0) < 1.0e-8:
            return peaks
        wavelength = float(self._active_wavelength())
        adjusted: list[HKLPeak] = []
        for peak in peaks:
            try:
                d_value = float(getattr(peak, "d", 0.0) or 0.0)
                if d_value > 0.0 and abs(cell_scale - 1.0) >= 1.0e-8:
                    two_theta = self._two_theta_from_d_spacing(d_value * cell_scale, wavelength)
                    if two_theta is None:
                        continue
                else:
                    two_theta = float(getattr(peak, "two_theta", 0.0) or 0.0)
                adjusted.append(
                    HKLPeak(
                        h=int(getattr(peak, "h", 0) or 0),
                        k=int(getattr(peak, "k", 0) or 0),
                        l=int(getattr(peak, "l", 0) or 0),
                        d=d_value * cell_scale if d_value > 0.0 else d_value,
                        two_theta=float(two_theta) + zero_shift,
                        intensity=float(getattr(peak, "intensity", 0.0) or 0.0),
                        multiplicity=int(getattr(peak, "multiplicity", 1) or 1),
                        f2=float(getattr(peak, "f2", 0.0) or 0.0),
                        lp=float(getattr(peak, "lp", 1.0) or 1.0),
                        raw_intensity=float(getattr(peak, "raw_intensity", 0.0) or 0.0),
                    )
                )
            except Exception:
                continue
        return adjusted

    def _two_theta_from_d_spacing(self, d_spacing: float, wavelength: float) -> float | None:
        d_spacing = float(d_spacing)
        if d_spacing <= 0.0:
            return None
        argument = float(wavelength) / (2.0 * d_spacing)
        if not 0.0 < argument < 1.0:
            return None
        return float(np.rad2deg(2.0 * np.arcsin(argument)))

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

    def _candidate_gain_presence_factor(
        self,
        row: list[str],
        observed_records: list[tuple[float, float]],
        gain_records: list[tuple[float, float]],
    ) -> float:
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        peaks = self._candidate_peaks_for_gain(candidate)
        if not peaks or not observed_records or not gain_records:
            return 0.0
        strong = [
            peak
            for peak in sorted(peaks, key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0), reverse=True)[:36]
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
        ]
        if len(strong) < 3:
            return 0.0
        observed_positions = self._record_positions(observed_records)
        gain_positions = self._record_positions(gain_records)
        full_coverage, full_count = self._weighted_candidate_line_coverage(strong, observed_positions, tolerance=0.42)
        gain_coverage, gain_count = self._weighted_candidate_line_coverage(strong[:24], gain_positions, tolerance=0.48)
        required_count = 5 if len(strong) >= 12 else 4 if len(strong) >= 8 else 3
        if full_count < required_count or gain_count < required_count:
            return 0.0
        if full_coverage < 0.18 or gain_coverage < 0.22:
            return 0.0
        return float(np.clip((0.25 + 0.75 * full_coverage) * (gain_coverage / 0.48) ** 1.15, 0.0, 1.0))

    def _record_position_value(self, record) -> float:
        value = getattr(record, "two_theta", None)
        if value is not None:
            return float(value)
        return float(record[0])

    def _record_positions(self, records: list[ObservedLineRecord]) -> np.ndarray:
        positions = np.asarray([self._record_position_value(record) for record in records], dtype=float)
        positions = positions[np.isfinite(positions)]
        positions.sort()
        return positions

    def _weighted_candidate_line_coverage(
        self,
        peaks: list[HKLPeak],
        positions: np.ndarray,
        *,
        tolerance: float,
    ) -> tuple[float, int]:
        if len(positions) == 0 or not peaks:
            return 0.0, 0
        total_weight = 0.0
        covered_weight = 0.0
        covered_count = 0
        for index, peak in enumerate(peaks):
            position = float(getattr(peak, "two_theta", 0.0) or 0.0)
            intensity = max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0)
            weight = math.sqrt(intensity) / math.sqrt(index + 1.0)
            total_weight += weight
            if self._nearest_selected_line_delta(positions, position) <= float(tolerance):
                covered_weight += weight
                covered_count += 1
        return covered_weight / max(total_weight, 1.0e-12), covered_count

    def _nearest_selected_line_delta(self, selected_positions: np.ndarray, position: float) -> float:
        if len(selected_positions) == 0:
            return 999.0
        index = int(np.searchsorted(selected_positions, float(position)))
        deltas = []
        if index < len(selected_positions):
            deltas.append(abs(float(selected_positions[index]) - float(position)))
        if index > 0:
            deltas.append(abs(float(selected_positions[index - 1]) - float(position)))
        return min(deltas) if deltas else 999.0

    def _candidate_gain_profile(self, candidate: dict[str, str], peaks: list[HKLPeak], context) -> np.ndarray | None:
        peak_signature = (
            len(peaks),
            round(float(peaks[0].two_theta), 5) if peaks else 0.0,
            round(float(peaks[-1].two_theta), 5) if peaks else 0.0,
        )
        key = (
            context.get("key"),
            self._candidate_source(candidate),
            candidate.get("Entry", ""),
            peak_signature,
            round(float(context.get("fwhm", 0.0)), 5),
            round(float(context.get("eta", 0.0)), 4),
            len(context.get("x", [])),
        )
        cached = self._candidate_gain_profile_cache.get(key)
        if cached is not None:
            return cached
        profile = self._profile_from_gain_peaks(peaks, context["x"], context["fwhm"], context.get("eta", 0.0))
        if profile is not None:
            self._candidate_gain_profile_cache[key] = profile
            self._trim_candidate_gain_profile_cache()
        return profile

    def _profile_from_gain_peaks(self, peaks: list[HKLPeak], x: np.ndarray, fwhm: float, eta: float = 0.0) -> np.ndarray | None:
        try:
            _grid, profile = calculated_profile_from_peaks(
                peaks,
                x,
                fwhm=fwhm,
                eta=eta,
                wavelength=self._active_wavelength(),
                include_kalpha2=True,
            )
        except Exception:
            return None
        profile = np.asarray(profile, dtype=float)
        if len(profile) != len(x) or float(np.nanmax(profile)) <= 0:
            return None
        return profile

    def _gain_noise_floor(self, corrected: np.ndarray) -> float:
        y = np.asarray(corrected, dtype=float)
        finite = y[np.isfinite(y)]
        if not len(finite):
            return 0.0
        median = float(np.nanmedian(finite))
        mad = float(np.nanmedian(np.abs(finite - median)))
        robust_sigma = 1.4826 * mad
        return max(median + 2.7 * robust_sigma, float(np.nanpercentile(finite, 20)))

    def _gain_residual_signal_factor(self, target: np.ndarray, residual_target: np.ndarray, x: np.ndarray) -> float:
        target_records = self._observed_peak_records(x, target, limit=80)
        residual_records = self._observed_peak_records(x, residual_target, limit=80)
        if not target_records or not residual_records:
            return 0.0
        target_area = sum(max(float(record.area), 0.0) for record in target_records)
        residual_area = sum(max(float(record.area), 0.0) for record in residual_records)
        if target_area <= 0.0:
            return 0.0
        strongest_residual = max(max(float(record.area), 0.0) for record in residual_records)
        strongest_fraction = strongest_residual / target_area
        residual_fraction = residual_area / target_area
        if strongest_fraction < 0.025 and residual_fraction < 0.10:
            return 0.0
        signal = max(strongest_fraction / 0.08, residual_fraction / 0.30)
        return float(np.clip(signal ** 0.85, 0.0, 1.0))

    def _fit_nonnegative_scales(self, target: np.ndarray, profiles: list[np.ndarray], weights: np.ndarray) -> list[float]:
        target_values = np.clip(np.asarray(target, dtype=float), 0.0, None)
        result = [0.0] * len(profiles)
        usable: list[np.ndarray] = []
        usable_indices: list[int] = []
        for index, profile in enumerate(profiles):
            values = np.asarray(profile, dtype=float)
            if len(values) != len(target_values) or not np.any(np.isfinite(values)):
                continue
            values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
            if float(np.max(values)) <= 0.0:
                continue
            usable.append(values)
            usable_indices.append(index)
        if not usable:
            return result
        fit_weights = np.clip(np.asarray(weights, dtype=float), 0.0, None)
        sqrt_weights = np.sqrt(fit_weights)
        design = np.column_stack(usable)
        try:
            scales, _residual = nnls(
                design * sqrt_weights[:, None],
                target_values * sqrt_weights,
            )
        except Exception:
            scales = np.clip(
                np.linalg.lstsq(
                    design * sqrt_weights[:, None],
                    target_values * sqrt_weights,
                    rcond=None,
                )[0],
                0.0,
                None,
            )
        for index, scale in zip(usable_indices, scales, strict=False):
            result[index] = max(0.0, float(scale))
        return result

    def _weighted_gain_error(
        self,
        target: np.ndarray,
        calculated: np.ndarray,
        weights: np.ndarray,
        excess_penalty: float = 3.0,
    ) -> float:
        residual = np.asarray(calculated, dtype=float) - np.asarray(target, dtype=float)
        asymmetric = np.where(residual > 0.0, residual * float(excess_penalty), -residual)
        weighted = asymmetric * np.clip(np.asarray(weights, dtype=float), 0.0, None)
        return float(np.trapezoid(weighted, dx=1.0))

    def _scaled_profile_sum(self, profiles: list[np.ndarray], scales: list[float], target: np.ndarray) -> np.ndarray:
        if not profiles or not scales:
            return np.zeros_like(target, dtype=float)
        total = np.zeros_like(target, dtype=float)
        for profile, scale in zip(profiles, scales, strict=False):
            total += np.asarray(profile, dtype=float) * float(scale)
        return total

    def _weighted_integral_area(self, target: np.ndarray, weights: np.ndarray) -> float:
        weighted = np.asarray(target, dtype=float) * np.clip(np.asarray(weights, dtype=float), 0.0, None)
        return float(np.trapezoid(weighted, dx=1.0))

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
        peaks = self._pdf2_peaks_for_candidate(candidate) if source == "PDF2" else self._candidate_cached_json_peaks(candidate)
        cif_path = None if peaks else self._candidate_local_cif_path(candidate)
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

    def _candidate_cached_json_peaks(self, candidate: dict[str, str]) -> list[HKLPeak]:
        if self._candidate_embedded_cif_path(candidate) is not None:
            return []
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if source not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"} or not entry_id:
            return []
        entry = self.local_phase_cache.get(source, entry_id)
        if entry is None or not entry.peaks_json:
            return []
        cache_key = (
            source,
            entry_id,
            int(getattr(entry, "derived_version", 0) or 0),
            len(entry.peaks_json),
            entry.peaks_json[:32],
        )
        cached = self._candidate_json_peak_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            rows = json.loads(entry.peaks_json)
        except Exception:
            return []
        peaks = []
        for item in rows:
            try:
                peaks.append(
                    HKLPeak(
                        h=int(item.get("h", 0)),
                        k=int(item.get("k", 0)),
                        l=int(item.get("l", 0)),
                        d=float(item.get("d", 0.0)),
                        two_theta=float(item.get("two_theta", 0.0)),
                        intensity=float(item.get("intensity", 0.0)),
                        multiplicity=int(item.get("multiplicity", 1) or 1),
                        raw_intensity=float(item.get("raw_intensity", 0.0) or 0.0),
                    )
                )
            except Exception:
                continue
        self._candidate_json_peak_cache[cache_key] = peaks
        self._trim_candidate_json_peak_cache()
        return peaks

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
            entry = self.local_phase_cache.get(source, entry_id) if source and entry_id else None
            peaks_json = getattr(entry, "peaks_json", "") if entry is not None else ""
            file_key = (
                "cached-peaks",
                int(getattr(entry, "derived_version", 0) or 0) if entry is not None else 0,
                len(peaks_json),
                peaks_json[:32],
            )
        else:
            try:
                stat = cif_path.stat()
                file_key = (str(cif_path), int(stat.st_mtime), int(stat.st_size))
            except Exception:
                file_key = (str(cif_path), 0, 0)
        return (
            self._active_probability_context_key(),
            self._candidate_source(candidate),
            candidate.get("Entry", ""),
            file_key,
        )

    def _candidate_cached_peaks(self, cif_path: Path, structure) -> list:
        try:
            stat = cif_path.stat()
            file_key = (str(cif_path), int(stat.st_mtime), int(stat.st_size))
        except Exception:
            file_key = (str(cif_path), 0, 0)
        wavelength = round(float(self._active_wavelength()), 6)
        cache_key = (
            file_key[0],
            wavelength,
            float(file_key[1]),
            float(file_key[2]),
            self._structure_cell_signature(structure),
        )
        cached = self._candidate_peak_cache.get(cache_key)
        if cached is not None:
            return cached
        peaks = self.calculated_pattern_service.calculate_sticks(
            structure,
            wavelength=self._active_wavelength(),
            two_theta_min=5.0,
            two_theta_max=120.0,
            intensity_min=0.5,
        )
        self._candidate_peak_cache[cache_key] = peaks
        self._trim_candidate_peak_cache()
        return peaks

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

    def _estimate_background(self, x, y, degree: int = 10, method: str = "auto") -> np.ndarray:
        return estimate_background(x, y, degree=degree, method=method)

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
        reference_cif = Path(__file__).resolve().parents[2] / "Entry_96-100-0018.cif"
        if reference_cif.exists():
            try:
                _phase, structure = create_phase_from_cif(reference_cif)
                if not structure.formula:
                    structure.formula = "Al2O3"
                return structure
            except Exception:
                pass
        structure = Structure.create("Corundum")
        structure.formula = "Al2O3"
        structure.space_group = "R -3 c"
        structure.space_group_number = "167"
        structure.cell = CellParameters(a=4.76060, b=4.76060, c=12.99400, alpha=90.0, beta=90.0, gamma=120.0)
        structure.symops = [
            "x,y,z",
            "-y,x-y,z",
            "-x+y,-x,z",
            "y,x,-z+1/2",
            "x-y,-y,-z+1/2",
            "-x,-x+y,-z+1/2",
            "x+2/3,y+1/3,z+1/3",
            "-y+2/3,x-y+1/3,z+1/3",
            "-x+y+2/3,-x+1/3,z+1/3",
            "y+2/3,x+1/3,-z+5/6",
            "x-y+2/3,-y+1/3,-z+5/6",
            "-x+2/3,-x+y+1/3,-z+5/6",
            "x+1/3,y+2/3,z+2/3",
            "-y+1/3,x-y+2/3,z+2/3",
            "-x+y+1/3,-x+2/3,z+2/3",
            "y+1/3,x+2/3,-z+7/6",
            "x-y+1/3,-y+2/3,-z+7/6",
            "-x+1/3,-x+y+2/3,-z+7/6",
        ]
        structure.atoms = [
            AtomSite(label="Al", element="Al", x=0.0, y=0.0, z=0.3522, occupancy=1.0),
            AtomSite(label="O", element="O", x=0.694, y=0.0, z=0.25, occupancy=1.0),
        ]
        return structure

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
        if preview_token is not None and preview_token != getattr(self, "_candidate_preview_token", None):
            return
        entry_id = candidate.get("Entry", "")
        view_range = self._plot_view_range()
        try:
            if preview_token is not None and preview_token != getattr(self, "_candidate_preview_token", None):
                return
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            observed = self._active_observed_data()
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
        overlay = prepare_structure_overlay(
            structure=structure,
            observed=observed,
            calculated_pattern_service=self.calculated_pattern_service,
            estimate_background=self._estimate_background,
            observed_peak_positions=self._observed_peak_positions,
            estimate_profile_fwhm=self._estimate_profile_fwhm,
            estimate_phase_alignment=self._estimate_phase_alignment,
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
        self.exclude_all_other_elements = True
        self.element_states.clear()
        self.selected_element_order.clear()
        for element in self._element_symbols():
            self._set_element_state(element, "excluded")
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
        self.exclude_all_other_elements = True
        current = self.element_states.get(element, "excluded")
        self._set_element_state(element, "excluded" if current == "required" else "required")
        if not any(state == "required" for state in self.element_states.values()):
            for symbol in self._element_symbols():
                if self.element_states.get(symbol) != "optional":
                    self._set_element_state(symbol, "excluded")
        self._update_element_fields()

    def _toggle_optional_element(self, element: str) -> None:
        self.exclude_all_other_elements = True
        current = self.element_states.get(element, "excluded")
        self._set_element_state(element, "excluded" if current == "optional" else "optional")
        if not any(state == "required" for state in self.element_states.values()):
            for symbol in self._element_symbols():
                if symbol != element and self.element_states.get(symbol) != "optional":
                    self._set_element_state(symbol, "excluded")
        self._update_element_fields()

    def _reset_selected_elements(self) -> None:
        for element in list(self.element_states):
            self._set_element_state(element, "excluded")
        self.element_states.clear()
        self.selected_element_order.clear()
        self.exclude_all_other_elements = True
        for element in self._element_symbols():
            self._set_element_state(element, "excluded")
        if self.ccdc_doi_input is not None:
            self.ccdc_doi_input.clear()
        self._update_element_fields()

    def _reset_candidate_search_table(self) -> None:
        self._auto_search_token = int(getattr(self, "_auto_search_token", 0)) + 1
        if self.finder_action_bar is not None:
            self.finder_action_bar.set_auto_search_busy(False)
        self._reset_selected_elements()
        if self.search_input is not None:
            self.search_input.clear()
        if hasattr(self, "_clear_transient_candidate_preview"):
            self._clear_transient_candidate_preview()
        if hasattr(self, "_clear_probability_caches"):
            self._clear_probability_caches()
        if hasattr(self, "candidate_search_service"):
            self.candidate_search_service.cancel_background_downloads()
        self._set_candidate_rows([["", "", "", "Candidate list cleared", "", ""]])

    def _update_element_fields(self) -> None:
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
            optional = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: element_sort_key(item[0]))
                if state == "optional"
            ]
            optional_text = f"; optional: {' '.join(optional)}" if optional else ""
            self.element_gate_label.setText(f"Gate: {formula or 'none'}{optional_text}")
        if self.name_input is not None:
            excluded = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: element_sort_key(item[0]))
                if state == "excluded"
            ]
            optional = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: element_sort_key(item[0]))
                if state == "optional"
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
            if optional:
                summary.append("optional " + " ".join(optional))
            if any_elements:
                summary.append("any " + " ".join(any_elements))
            self.name_input.setText("; ".join(summary))
        if self.search_input is not None and (
            not self.search_input.text().strip() or self.search_input.text().strip() == self._last_formula_text
        ):
            self.search_input.setText(formula)
        self._last_formula_text = formula

    def _set_element_state(self, element: str, state: str) -> None:
        if self.element_table is None:
            return
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
        if not self.selected_elements:
            return []
        if self.exclude_all_other_elements:
            return [
                element
                for element in self._element_symbols()
                if element not in self.selected_elements
                and self.element_states.get(element, "neutral") not in {"optional", "any"}
            ]
        return [element for element, state in self.element_states.items() if state == "excluded"]

    def _element_symbols(self) -> list[str]:
        return self.element_table.element_symbols if self.element_table is not None else []

    def _search_pdf2_candidates(self) -> None:
        if self.selected_elements:
            self._search_from_controls()
        else:
            self._search_pdf2_text()

    def _gain_context_observed_peak_records(
        self,
        context,
        signal: str,
        *,
        limit: int,
    ) -> list[ObservedLineRecord]:
        cache = context.setdefault("_gain_observed_peak_records_cache", {})
        cache_key = (str(signal), int(limit))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        x = np.asarray(context.get("x", []), dtype=float)
        y = np.asarray(context.get(signal, []), dtype=float)
        if len(x) == 0 or len(y) != len(x):
            records: list[ObservedLineRecord] = []
        else:
            records = self._observed_peak_records(x, y, limit=limit)
        cache[cache_key] = records
        return records

    def _set_candidate_rows(
        self,
        rows: list[list[str]],
        force_rank: bool = False,
        rank_progress=None,
        gain_context=None,
        skip_rank: bool = False,
    ) -> None:
        self._candidate_rank_token += 1
        rows = [normalize_candidate_row(row) for row in rows]
        if not skip_rank and (force_rank or self._rank_by_peak_probability_enabled()) and rows:
            rows = self._rank_candidate_rows_by_peak_probability(
                rows,
                force=force_rank,
                progress=rank_progress,
                gain_context=gain_context,
            )
        self.candidate_table.set_rows(rows, lambda row: row)
        if hasattr(self, "_update_profile_view_context"):
            self._update_profile_view_context()
        if rows and normalize_candidate_row(rows[0])[0]:
            self._update_compound_card(self._candidate_row_values(0))
