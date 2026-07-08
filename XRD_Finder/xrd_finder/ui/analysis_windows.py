from __future__ import annotations

import re
from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenuBar,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QDialog,
)
import numpy as np
import pyqtgraph as pg
from scipy.signal import find_peaks
from pathlib import Path

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.structure import AtomSite, CellParameters, Structure
from xrd_finder.finder import FinderInput, FinderService
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.xy_loader import load_xy
from xrd_finder.io.project_io import load_project_manifest, save_project_manifest
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    CalculatedPatternService,
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
from xrd_finder.services.rruff_service import RruffService
from xrd_finder.ui.pattern_plot_helpers import (
    ensure_right_legend,
    estimate_profile_fwhm,
)
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
from xrd_finder.ui.help_text import PHASE_FINDER_HELP_TEXT, PHASE_FINDER_HELP_TITLE
from xrd_finder.ui.layout_state import SplitterLayoutState
from xrd_finder.ui.match_profile_renderer import build_finder_candidate_inputs, draw_match_profile_result
from xrd_finder.ui.observed_pattern_actions import PhaseFinderObservedPatternActionsMixin
from xrd_finder.ui.peak_marker_renderer import (
    add_peak_coverage_markers,
    assignment_marker_label,
    primary_assignment,
)
from xrd_finder.ui.peak_matching import (
    PhaseAlignmentEstimate,
    estimate_phase_alignment,
    nearest_index as nearest_peak_index,
    observed_peak_positions,
    observed_peak_records,
    peak_presence_probability,
    peak_probability_from_alignment,
)
from xrd_finder.ui.phase_finder_menu import build_phase_finder_menu_bar
from xrd_finder.ui.plot_actions import PhaseFinderPlotActionsMixin
from xrd_finder.ui.preprocessing_actions import PhaseFinderPreprocessingActionsMixin
from xrd_finder.ui.project_state_actions import PhaseFinderProjectStateActionsMixin
from xrd_finder.ui.project_tree_actions import PhaseFinderProjectTreeActionsMixin
from xrd_finder.ui.project_controls import ProjectControlsWidget
from xrd_finder.ui.project_tree import ProjectTree
from xrd_finder.ui.reference_preview_renderer import draw_pdf2_reference, draw_rruff_reference
from xrd_finder.ui.selected_phases_actions import PhaseFinderSelectedPhasesActionsMixin
from xrd_finder.ui.structure_overlay import draw_structure_overlay, prepare_structure_overlay, shifted_peaks as shift_overlay_peaks
from xrd_finder.ui.theme import is_dark_theme, window_style
from xrd_finder.ui.xrd_plot import create_xrd_plot_widget


ATOMIC_WEIGHTS = {
    "H": 1.008, "D": 2.014, "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06,
    "Cl": 35.45, "K": 39.098, "Ca": 40.078, "Ti": 47.867, "V": 50.942, "Cr": 51.996,
    "Mn": 54.938, "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
    "Ga": 69.723, "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904, "Sr": 87.62,
    "Y": 88.906, "Zr": 91.224, "Nb": 92.906, "Mo": 95.95, "Ag": 107.868, "Cd": 112.414,
    "In": 114.818, "Sn": 118.710, "Sb": 121.760, "Te": 127.60, "I": 126.904, "Ba": 137.327,
    "La": 138.905, "Ce": 140.116, "Pr": 140.908, "Nd": 144.242, "W": 183.84, "Pb": 207.2,
    "Bi": 208.980,
}

ATOMIC_NUMBERS = {
    "H": 1, "D": 1, "C": 6, "N": 7, "O": 8, "F": 9, "Na": 11, "Mg": 12, "Al": 13,
    "Si": 14, "P": 15, "S": 16, "Cl": 17, "K": 19, "Ca": 20, "Ti": 22, "V": 23,
    "Cr": 24, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28, "Cu": 29, "Zn": 30, "Ga": 31,
    "Ge": 32, "As": 33, "Se": 34, "Br": 35, "Sr": 38, "Y": 39, "Zr": 40, "Nb": 41,
    "Mo": 42, "Ag": 47, "Cd": 48, "In": 49, "Sn": 50, "Sb": 51, "Te": 52, "I": 53,
    "Ba": 56, "La": 57, "Ce": 58, "Pr": 59, "Nd": 60, "W": 74, "Pb": 82, "Bi": 83,
}


class AnalysisWindow(QDialog):
    project_changed = Signal()
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

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._layout_state.register("main_splitter", self.main_splitter)
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.addWidget(self.center)
        self.main_splitter.addWidget(self.right_tabs)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([190, 980, 330])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.main_splitter)

    def _is_dark_theme(self) -> bool:
        return is_dark_theme(self)

    def _open_project_object(self, object_type: str, object_id: str) -> None:
        if object_type == "pattern":
            self.tree.set_checked_pattern_ids([object_id])
            return
        if object_type == "phase":
            self.tree.set_checked_phase_ids([object_id])

    def _move_current_tree_object(self, direction: int) -> None:
        current = self.tree.current_object()
        if current is None:
            return
        object_type, object_id = current
        objects = self.project.patterns if object_type == "pattern" else self.project.phases
        index = next((i for i, project_object in enumerate(objects) if project_object.id == object_id), -1)
        new_index = index + direction
        if index < 0 or new_index < 0 or new_index >= len(objects):
            return
        objects[index], objects[new_index] = objects[new_index], objects[index]
        if object_type == "phase":
            self._sync_structures_to_phase_order()
        self.tree.set_project(self.project)
        self.tree.select_object(object_type, object_id)
        self.project_changed.emit()
        self._on_project_tree_selection_changed()

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
        self.project.touch()
        self.tree.set_project(self.project)
        self._after_new_project()
        self.project_changed.emit()

    def _load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load XRD project",
            self._last_directory(),
            "XRD project (*.xrd-project.json *.json);;JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            project = load_project_manifest(path)
        except Exception as exc:
            QMessageBox.warning(self, "Load project failed", str(exc))
            return
        self._remember_directory(path)
        self.project = project
        self.setWindowTitle(f"{self._base_title} - {project.name}")
        self.tree.set_project(project)
        self._after_project_loaded()
        self.project_changed.emit()

    def _save_project(self) -> None:
        default_path = self.project.root_path or str(Path(self._last_directory()) / f"{self.project.name}.xrd-project.json")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save XRD project",
            default_path,
            "XRD project (*.xrd-project.json *.json);;JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        try:
            self.project.root_path = path
            self._sync_finder_state_to_project()
            self.project.touch()
            save_project_manifest(self.project, path)
        except Exception as exc:
            QMessageBox.warning(self, "Save project failed", str(exc))
            return
        QMessageBox.information(self, "Project saved", f"Project saved to:\n{path}")

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

    def _import_scientific_paths(self, paths: list[Path]) -> None:
        paths = [path for path in paths if path.is_file()]
        if not paths:
            return
        self._remember_directory(paths[0])
        imported = False
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
                else:
                    load_xy(path)
                    self.project.patterns.append(Pattern.create(name=path.stem, source_path=str(path)))
                imported = True
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")

        if imported:
            self.tree.set_project(self.project)
            self._on_project_tree_selection_changed()
            if hasattr(self, "_refresh_project_phase_candidates"):
                self._refresh_project_phase_candidates()
            self.project_changed.emit()
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
        self._import_scientific_paths(paths)

    def _drop_file_paths(self, event) -> list[Path]:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.lower() in self.IMPORT_SUFFIXES:
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
                    self._import_scientific_paths(paths)
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
    PhaseFinderPlotActionsMixin,
    PhaseFinderCandidateSearchActionsMixin,
    PhaseFinderDatabaseActionsMixin,
    AnalysisWindow,
):
    def __init__(self, project: Project) -> None:
        super().__init__(project, "Phase Finder")
        self.resize(1500, 850)
        self.right_tabs.setMinimumWidth(360)
        self._init_filter_state()
        self._init_services()
        self._init_runtime_state()
        self._create_action_bar()
        self._create_match_plot(project)
        self._create_candidate_tables()
        self._create_center_splitter()
        self._create_right_tabs()

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
        self.candidate_search_service = CandidateSearchService(
            self.local_phase_cache,
            self.cod_online,
            self.ccdc,
            self.rruff,
            self.match_pdf2,
            self.materials_project,
            self.aflow,
            self.oqmd,
        )
        self._background_tasks: set[BackgroundTaskHandle] = set()
        self._start_match_pdf2_preload()

    def _init_runtime_state(self) -> None:
        self.finder_action_bar: FinderActionBar | None = None
        self.search_input: QLineEdit | None = None
        self.name_input: QLineEdit | None = None
        self.elem_count_input: QLineEdit | None = None
        self.formula_sum_input: QLineEdit | None = None
        self.ccdc_doi_input: QLineEdit | None = None
        self.database_panel: DatabasePanelWidget | None = None
        self.compound_card: CompoundCardWidget | None = None
        self.inorganics_checkbox: QCheckBox | None = None
        self.organics_checkbox: QCheckBox | None = None
        self.structural_data_checkbox: QCheckBox | None = None
        self.reference_patterns_checkbox: QCheckBox | None = None
        self.rank_by_probability_checkbox: QCheckBox | None = None
        self.plot_layers: dict[str, list] = {
            "observed": [],
            "calculated_profile": [],
            "total_profile": [],
            "phase_profiles": [],
            "background": [],
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
        self.cursor_position_enabled = False
        self.cursor_position_line = None
        self.cursor_position_label = None
        self.cursor_position_proxy = None
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
        self._observed_probability_cache: tuple[tuple[object, ...], np.ndarray, np.ndarray, list[tuple[float, float]]] | None = None
        self._candidate_peak_cache: dict[tuple[str, float, float, float], list] = {}
        self._candidate_probability_cache: dict[tuple[object, ...], float] = {}
        self.show_all_selected_patterns = False
        self.pattern_stack_offset_percent = 10
        self.observed_pattern_plot_context: dict[str, dict[str, float]] = {}
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

    def _create_action_bar(self) -> None:
        self.finder_action_bar = FinderActionBar()
        self.finder_action_bar.smoothRequested.connect(self._smooth_active_pattern_plot)
        self.finder_action_bar.subtractBackgroundRequested.connect(self._subtract_active_background_plot)
        self.finder_action_bar.resetDataRequested.connect(self._reset_observed_preprocessing)
        self.finder_action_bar.searchRequested.connect(self._search_pdf2_text)
        self.finder_action_bar.patternDisplayModeChanged.connect(self._set_pattern_display_mode)
        self.finder_action_bar.patternOffsetPercentChanged.connect(self._set_pattern_stack_offset)
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
        if project.patterns:
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
        self.candidate_panel = QWidget()
        candidate_layout = QVBoxLayout(self.candidate_panel)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.setSpacing(4)
        candidate_layout.addWidget(QLabel("Candidate list"))
        candidate_layout.addWidget(self.candidate_table, 1)

    def _create_center_splitter(self) -> None:
        self.center_splitter = QSplitter(Qt.Orientation.Vertical)
        self._layout_state.register("center_splitter", self.center_splitter)
        self.center_splitter.addWidget(self.match_plot)
        self.center_splitter.addWidget(self.candidate_panel)
        self.center_splitter.setStretchFactor(0, 3)
        self.center_splitter.setStretchFactor(1, 2)
        self.center_splitter.setSizes([520, 260])
        self.center_layout.addWidget(self.center_splitter, 1)

    def _create_right_tabs(self) -> None:
        self.right_tabs.addTab(self._composition_tab(), "Elements")
        self.compound_card = CompoundCardWidget()
        self.right_tabs.addTab(self.compound_card, "Card")
        self.right_tabs.addTab(self._database_tab(), "Databases")
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
            refresh_observed=True,
        )
        self._restore_finder_state_from_project()

    def _reset_phase_finder_state(
        self,
        candidate_rows: list[list[str]],
        *,
        reset_plot_range: bool = False,
        refresh_observed: bool = False,
    ) -> None:
        self._clear_probability_caches()
        self.match_candidates.clear()
        self.match_structures.clear()
        self.match_scales.clear()
        self.match_quantities.clear()
        self.match_iic.clear()
        self.match_zero_shifts.clear()
        self.match_cell_scales.clear()
        self.match_alignment_scores.clear()
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
        if self.legend_item is not None:
            self.legend_item = ensure_right_legend(self.match_plot, clear=True)
        if reset_plot_range:
            self.match_plot.setTitle("Phase Finder: pattern and candidate phase markers", color="#111111", size="13pt")
            self.match_plot.setXRange(0, 1, padding=0.02)
            self.match_plot.setYRange(0, 1, padding=0.02)
        self._reset_selected_elements()
        self._set_candidate_rows(candidate_rows)
        self._update_match_table()
        if self.compound_card is not None:
            self.compound_card.set_candidate(None)
        if refresh_observed:
            self._refresh_observed_pattern_plot()

    def _project_phase_candidate_rows(self) -> list[list[str]]:
        rows = [
            ["USER", phase.id, phase.formula, phase.name, "", "project structure"]
            for phase in self.project.phases
        ]
        return rows if rows else [["", "", "", "No phases yet", "", ""]]

    def closeEvent(self, event) -> None:
        self.candidate_search_service.shutdown_background_downloads()
        super().closeEvent(event)

    def _run_background_task(self, title: str, label: str, task, on_success, on_error=None) -> None:
        dialog = QProgressDialog(label, "", 0, 0, self)
        dialog.setWindowTitle(title)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()

        handle = BackgroundTaskHandle(task, self)
        self._background_tasks.add(handle)

        def cleanup() -> None:
            dialog.close()
            self._background_tasks.discard(handle)

        def finish(result) -> None:
            cleanup()
            on_success(result)

        def fail(message: str, details: str) -> None:
            cleanup()
            if on_error is not None:
                on_error(message, details)
            else:
                QMessageBox.warning(self, title, message or details)

        handle.finished.connect(finish)
        handle.failed.connect(fail)
        handle.start()

    def _match_menu_bar(self) -> QMenuBar:
        return build_phase_finder_menu_bar(self)

    def _match_tool_bar(self) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        buttons = [
            "Open",
            "Save",
            "Overlay",
            "FP",
            "Peaks",
            "BG",
            "Search",
            "Add",
            "Undo",
            "Redo",
            "DB",
            "Color",
            "Export",
            "Zoom",
        ]
        for label in buttons:
            button = QToolButton()
            button.setText(label)
            button.setAutoRaise(True)
            if label == "Search":
                button.clicked.connect(self._search_pdf2_candidates)
            if label == "Add":
                button.clicked.connect(self._add_selected_candidate_to_match_list)
            layout.addWidget(button)

        search = QLineEdit()
        search.setPlaceholderText("Formula, phase name, entry id, or DOI")
        search.returnPressed.connect(self._search_pdf2_text)
        self.search_input = search
        layout.addWidget(search, 1)
        return wrapper

    def _composition_tab(self) -> QWidget:
        panel = CompositionPanel(self.match_table, self._layout_state)
        panel.requiredElementToggled.connect(self._toggle_required_element)
        panel.optionalElementToggled.connect(self._toggle_optional_element)
        panel.searchRequested.connect(self._search_from_controls)
        panel.resetRequested.connect(self._reset_selected_elements)

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

    def _recalculate_match_profile(self, auto_zoom: bool = False) -> None:
        if not self.match_candidates:
            self._clear_calculated_overlay()
            self._update_match_table()
            return

        self._clear_calculated_overlay()
        pattern = self._active_pattern()
        if pattern is None:
            self._update_match_table()
            return
        finder_candidates, candidate_by_key = build_finder_candidate_inputs(
            self.match_candidates,
            self._candidate_cif_path,
            self._candidate_key,
            self._candidate_phase_name,
            self._candidate_source,
        )
        if not finder_candidates:
            self._update_match_table()
            return

        processed_observed = self._active_processed_observed_data()
        try:
            result = self.finder_service.run(
                FinderInput(
                    pattern_path=pattern.source_path,
                    candidates=finder_candidates,
                    wavelength=pattern.wavelength,
                    observed_x=processed_observed[:, 0].tolist() if processed_observed is not None else None,
                    observed_y=processed_observed[:, 1].tolist() if processed_observed is not None else None,
                    subtract_background=not self._active_background_removed(),
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Finder calculation failed", str(exc))
            self._update_match_table()
            return

        draw_match_profile_result(
            result=result,
            candidate_by_key=candidate_by_key,
            match_plot=self.match_plot,
            plot_layers=self.plot_layers,
            show_all_selected_patterns=self.show_all_selected_patterns,
            active_plot_context=self._active_pattern_plot_context(),
            phase_color=self._phase_color,
            phase_legend_label=self._phase_legend_label,
            candidate_key=self._candidate_key,
            estimate_candidate_iic=self._estimate_candidate_corundum_iic,
            profile_fit_quality=self._profile_fit_quality,
            add_peak_coverage_markers=self._add_peak_coverage_markers,
            match_scales=self.match_scales,
            match_quantities=self.match_quantities,
            match_iic=self.match_iic,
            match_zero_shifts=self.match_zero_shifts,
            match_cell_scales=self.match_cell_scales,
            match_alignment_scores=self.match_alignment_scores,
        )
        self._update_match_table()
        if auto_zoom:
            self._reset_match_plot_view()

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

    def _observed_peak_records(self, x, corrected_y, limit: int = 24) -> list[tuple[float, float]]:
        return observed_peak_records(x, corrected_y, limit=limit)

    def _profile_fit_quality(self, observed_y: np.ndarray, background: np.ndarray, calculated_total: np.ndarray) -> float:
        observed_corrected = np.clip(np.asarray(observed_y, dtype=float) - np.asarray(background, dtype=float), 0.0, None)
        calculated_corrected = np.clip(np.asarray(calculated_total, dtype=float) - np.asarray(background, dtype=float), 0.0, None)
        if len(observed_corrected) == 0 or float(np.nanmax(observed_corrected)) <= 0:
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
            show_hkl_labels=self.show_hkl_labels,
        )

    def _add_assignment_markers(
        self,
        x: np.ndarray,
        observed_y: np.ndarray,
        observed_peaks,
        phase_assignment_styles: dict[str, tuple[str, str]],
    ) -> tuple[int, int]:
        return add_peak_coverage_markers(
            plot=self.match_plot,
            plot_layers=self.plot_layers,
            observed_peak_positions=self._observed_peak_positions,
            x=x,
            observed_y=observed_y,
            corrected_y=np.zeros_like(observed_y),
            phase_peak_sets=[],
            observed_peak_assignments=observed_peaks,
            phase_assignment_styles=phase_assignment_styles,
            show_hkl_labels=self.show_hkl_labels,
        )

    def _primary_assignment(self, assignments):
        return primary_assignment(assignments)

    def _assignment_marker_label(self, assignments) -> str:
        return assignment_marker_label(assignments)

    def _phase_label_prefix(self, phase_name: str) -> str:
        words = [word for word in re.split(r"[^A-Za-z0-9]+", phase_name) if word]
        if not words:
            return "P"
        if len(words) == 1:
            return words[0][:1].upper()
        return "".join(word[:1].upper() for word in words[:2])

    def _phase_lane_label(self, candidate: dict[str, str]) -> str:
        phase = self._candidate_phase_name(candidate) or "phase"
        entry = candidate.get("Entry", "")
        source = self._candidate_source(candidate)
        code = f"{source}#{entry}" if source and entry else entry
        return f"{phase}\n{code}" if code else phase

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

    def _peak_probability_from_alignment(self, alignment: PhaseAlignmentEstimate) -> float:
        return peak_probability_from_alignment(alignment)

    def _peak_presence_probability(self, peaks, observed_x: np.ndarray, corrected_y: np.ndarray, structure) -> float:
        return peak_presence_probability(peaks, observed_x, corrected_y, structure)

    def _clear_probability_caches(self) -> None:
        self._observed_probability_cache = None
        self._candidate_probability_cache.clear()

    def _active_probability_context_key(self) -> tuple[object, ...]:
        pattern = self._active_pattern()
        pattern_id = getattr(pattern, "id", "") if pattern is not None else ""
        source_path = getattr(pattern, "source_path", "") if pattern is not None else ""
        wavelength = round(float(getattr(pattern, "wavelength", None) or CU_KA1_WAVELENGTH), 6)
        processed = self._active_processed_observed_data()
        data_len = int(len(processed)) if processed is not None else -1
        return (pattern_id, source_path, wavelength, self._active_background_removed(), data_len)

    def _probability_observed_data(self) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]]] | None:
        observed = self._active_observed_data()
        if observed is None or not len(observed):
            return None
        key = self._active_probability_context_key()
        if self._observed_probability_cache is not None and self._observed_probability_cache[0] == key:
            return self._observed_probability_cache[1], self._observed_probability_cache[2], self._observed_probability_cache[3]
        try:
            background = self._estimate_background(observed[:, 0], observed[:, 1])
            corrected = np.clip(observed[:, 1] - background, 0.0, None)
            records = self._observed_peak_records(observed[:, 0], corrected, limit=24)
        except Exception:
            return None
        self._observed_probability_cache = (key, np.asarray(observed[:, 0], dtype=float), corrected, records)
        return self._observed_probability_cache[1], self._observed_probability_cache[2], self._observed_probability_cache[3]

    def _rank_candidate_rows_by_peak_probability(self, rows: list[list[str]]) -> list[list[str]]:
        if not self._rank_by_peak_probability_enabled():
            return rows
        probability_data = self._probability_observed_data()
        if probability_data is None:
            return rows
        observed_x, corrected, observed_records = probability_data
        if not observed_records:
            return rows

        scored_rows = []
        max_ranked_rows = 35
        for index, row in enumerate(rows[:max_ranked_rows]):
            scored_row = list(row)
            probability = self._candidate_row_peak_probability(scored_row, observed_x, corrected)
            if probability > 0:
                scored_row[5] = f"{probability:.0f}%"
            scored_rows.append((probability, index, scored_row))
        for index, row in enumerate(rows[max_ranked_rows:], start=max_ranked_rows):
            scored_rows.append((0.0, index, row))
        if not any(score > 0 for score, _index, _row in scored_rows):
            return [row for _score, _index, row in scored_rows]
        scored_rows.sort(key=lambda item: (-item[0], item[1]))
        return [row for _score, _index, row in scored_rows]

    def _candidate_row_peak_probability(self, row: list[str], observed_x: np.ndarray, corrected_y: np.ndarray) -> float:
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"}:
            return 0.0
        cif_path = self._candidate_local_cif_path(candidate)
        if cif_path is None:
            return 0.0
        probability_key = self._candidate_probability_key(candidate, cif_path)
        cached_probability = self._candidate_probability_cache.get(probability_key)
        if cached_probability is not None:
            return cached_probability
        try:
            _phase, structure = create_phase_from_cif(cif_path)
            if candidate.get("Phase"):
                structure.name = candidate["Phase"]
            structure.wavelength = self._active_wavelength()
            peaks = self._candidate_cached_peaks(cif_path, structure)
            probability = self._peak_presence_probability(peaks, observed_x, corrected_y, structure)
            self._candidate_probability_cache[probability_key] = probability
            return probability
        except Exception:
            return 0.0

    def _candidate_probability_key(self, candidate: dict[str, str], cif_path: Path) -> tuple[object, ...]:
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
        cache_key = (file_key[0], wavelength, float(file_key[1]), float(file_key[2]))
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
        if len(self._candidate_peak_cache) > 256:
            self._candidate_peak_cache.clear()
        self._candidate_peak_cache[cache_key] = peaks
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

    def _shift_overlay_peaks(self, peaks, zero_shift: float):
        return shift_overlay_peaks(peaks, zero_shift)

    def _estimate_background(self, x, y, degree: int = 10, method: str = "auto") -> np.ndarray:
        return estimate_background(x, y, degree=degree, method=method)

    def _estimate_theoretical_iic(self, profile: np.ndarray) -> float:
        profile = np.asarray(profile, dtype=float)
        if len(profile) == 0:
            return 0.0
        peak = float(np.nanmax(profile))
        positive = np.clip(profile, 0.0, None)
        integrator = getattr(np, "trapezoid", None) or getattr(np, "trapz", None)
        area = float(integrator(positive)) if integrator is not None else float(np.sum(positive))
        if peak <= 0 or area <= 0:
            return 0.0
        return area / peak

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

    def _corundum_absorption_correction(self, formula: str) -> float:
        sample_proxy = self._formula_absorption_proxy(formula)
        corundum_proxy = self._formula_absorption_proxy("Al2O3")
        if sample_proxy <= 0 or corundum_proxy <= 0:
            return 1.0
        return float(np.clip(corundum_proxy / sample_proxy, 0.02, 8.0))

    def _formula_absorption_proxy(self, formula: str) -> float:
        counts = self._formula_counts(formula)
        if not counts:
            return 0.0
        mass = sum(ATOMIC_WEIGHTS.get(element, 0.0) * count for element, count in counts.items())
        if mass <= 0:
            return 0.0
        weighted_z = sum((ATOMIC_NUMBERS.get(element, 0) ** 3.0) * count for element, count in counts.items())
        return float(weighted_z / mass)

    def _formula_counts(self, formula: str) -> dict[str, float]:
        counts: dict[str, float] = {}
        if not formula:
            return counts
        for element, amount in re.findall(r"([A-Z][a-z]?|D)([0-9]*\.?[0-9]*)", formula):
            if element not in ATOMIC_NUMBERS:
                continue
            counts[element] = counts.get(element, 0.0) + (float(amount) if amount else 1.0)
        return counts

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

    def _calculate_candidate_overlay(self, candidate: dict[str, str], show_errors: bool) -> None:
        entry_id = candidate.get("Entry", "")
        view_range = self._plot_view_range()
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            observed = self._active_observed_data()
            self._calculate_structure_overlay(structure, preview=True)
            if observed is None:
                self.match_plot.autoRange(padding=0.02)
                self.match_plot_view_initialized = True
            else:
                self._restore_plot_view_range(view_range)
            self.active_overlay_entry_id = entry_id or None
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Calculate pattern failed", str(exc))

    def _preview_rruff_reference(self, candidate: dict[str, str], show_errors: bool) -> None:
        entry_id = candidate.get("Entry", "")
        if not entry_id:
            return
        try:
            pattern_path = self.rruff.pattern_path(entry_id)
            if pattern_path is None:
                raise ValueError("RRUFF reference pattern is not indexed or the XY file is missing.")
            data = load_xy(pattern_path)
            observed = self._active_observed_data()
            self._clear_calculated_overlay()
            label = self._phase_legend_label(candidate)
            draw_rruff_reference(
                plot=self.match_plot,
                plot_layers=self.plot_layers,
                data=np.asarray(data, dtype=float),
                observed=observed,
                label=label,
            )
            if observed is None:
                self.match_plot.autoRange(padding=0.02)
                self.match_plot_view_initialized = True
            self.active_overlay_entry_id = entry_id
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "RRUFF preview failed", str(exc))

    def _preview_pdf2_reference(self, candidate: dict[str, str], show_errors: bool) -> None:
        entry_id = candidate.get("Entry", "")
        if not entry_id:
            return
        view_range = self._plot_view_range()
        try:
            peaks = self._pdf2_peaks_for_candidate(candidate)
            if not peaks:
                raise ValueError("PDF-2 diffraction lines were not found for this card.")
            observed = self._active_observed_data()
            self._clear_preview_overlay()
            label = self._phase_legend_label(candidate)
            draw_pdf2_reference(
                plot=self.match_plot,
                plot_layers=self.plot_layers,
                peaks=peaks,
                observed=observed,
                active_plot_context=self._active_pattern_plot_context(),
                label=label,
                show_hkl_labels=self.show_hkl_labels,
            )
            if observed is None:
                self.match_plot.autoRange(padding=0.02)
                self.match_plot_view_initialized = True
            else:
                self._restore_plot_view_range(view_range)
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
        )

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
            self.reference_patterns_checkbox.setChecked(True)
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

    def _format_entry_first_peak(self, entry) -> str:
        return ""

    def _search_pdf2_candidates(self) -> None:
        if self.selected_elements:
            self._search_from_controls()
        else:
            self._search_pdf2_text()

    def _set_candidate_rows(self, rows: list[list[str]]) -> None:
        self._candidate_rank_token += 1
        rows = [normalize_candidate_row(row) for row in rows]
        self.candidate_table.set_rows(rows, normalize_candidate_row)
        if rows:
            self._update_compound_card(self._candidate_row_values(0))
        if self._rank_by_peak_probability_enabled() and rows:
            self._start_candidate_probability_ranking(rows)

    def _start_candidate_probability_ranking(self, rows: list[list[str]]) -> None:
        probability_data = self._probability_observed_data()
        if probability_data is None:
            return
        _observed_x, _corrected, observed_records = probability_data
        if not observed_records:
            return
        self._candidate_rank_token += 1
        token = self._candidate_rank_token
        self._candidate_rank_rows = [list(row) for row in rows]
        self._candidate_rank_scores = {}
        self._candidate_rank_index = 0
        QTimer.singleShot(60, lambda token=token: self._rank_candidate_rows_step(token))

    def _rank_candidate_rows_step(self, token: int) -> None:
        if token != self._candidate_rank_token or not self._candidate_rank_rows:
            return
        probability_data = self._probability_observed_data()
        if probability_data is None:
            return
        observed_x, corrected, _observed_records = probability_data
        max_ranked_rows = min(35, len(self._candidate_rank_rows))
        batch_size = 3
        stop = min(self._candidate_rank_index + batch_size, max_ranked_rows)
        for row_index in range(self._candidate_rank_index, stop):
            row = self._candidate_rank_rows[row_index]
            probability = self._candidate_row_peak_probability(row, observed_x, corrected)
            self._candidate_rank_scores[row_index] = probability
            if probability > 0:
                row[5] = f"{probability:.0f}%"
                self.candidate_table.set_probability(row_index, row[5])
        self._candidate_rank_index = stop
        if self._candidate_rank_index < max_ranked_rows:
            QTimer.singleShot(20, lambda token=token: self._rank_candidate_rows_step(token))
            return
        if not any(score > 0 for score in self._candidate_rank_scores.values()):
            return
        indexed_rows = []
        for index, row in enumerate(self._candidate_rank_rows):
            indexed_rows.append((self._candidate_rank_scores.get(index, 0.0), index, row))
        indexed_rows.sort(key=lambda item: (-item[0], item[1]))
        current = self.candidate_table.selected_row_values() or {}
        current_key = (current.get("Source", ""), current.get("Entry", ""), current.get("Phase", ""))
        sorted_rows = [row for _score, _index, row in indexed_rows]
        self.candidate_table.set_rows(sorted_rows, normalize_candidate_row)
        for row_index in range(self.candidate_table.rowCount()):
            values = self._candidate_row_values(row_index)
            if (values.get("Source", ""), values.get("Entry", ""), values.get("Phase", "")) == current_key:
                self.candidate_table.selectRow(row_index)
                break

    def _format_first_peak_two_theta(self, candidate) -> str:
        return ""

    def _draw_candidate_markers(self, candidates) -> None:
        for item in self.plot_layers.get("candidate_markers", []):
            self.match_plot.removeItem(item)
        self.plot_layers["candidate_markers"] = []

    def _simple_tab(self, labels: list[str]) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for label in labels:
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            layout.addWidget(checkbox)
        layout.addStretch(1)
        return widget
