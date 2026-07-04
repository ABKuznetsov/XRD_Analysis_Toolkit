from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
import shutil
import threading
from urllib.request import urlopen
from zipfile import ZipFile
from types import SimpleNamespace
from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDragMoveEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QSplitter,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
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
from xrd_finder.core.structure import AtomSite, CellParameters, Structure
from xrd_finder.finder import FinderCandidateInput, FinderInput, FinderService
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.xy_loader import load_xy
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    CalculatedPatternService,
    calculated_profile_from_peaks,
    radiation_lines_from_wavelength,
)
from xrd_finder.services.candidate_search_service import (
    CandidateSearchOptions,
    CandidateSearchService,
    normalize_candidate_row,
)
from xrd_finder.services.ccdc_service import CcdcService
from xrd_finder.services.cod_online_service import CodOnlineService, formula_elements
from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.services.match_pdf2_service import MatchPdf2Service
from xrd_finder.services.materials_project_service import MaterialsProjectService
from xrd_finder.services.rruff_service import RRUFF_POWDER_XY_PROCESSED_URL, RruffService
from xrd_finder.ui.pattern_plot_helpers import (
    add_hkl_labels,
    calculate_profile_for_structure,
    ensure_right_legend,
    estimate_background,
    estimate_profile_fwhm,
    plot_hkl_sticks,
    plot_hkl_ticks,
    plot_peak_intensity_sticks,
    plot_phase_marker_lane,
    plot_profile,
    scale_profile_to_reference,
)
from xrd_finder.ui.candidate_tables import CandidateTableWidget, SelectedCandidatesTableWidget
from xrd_finder.ui.compound_card import CompoundCardWidget
from xrd_finder.ui.database_panel import DatabasePanelWidget
from xrd_finder.ui.element_filter import PeriodicTableWidget, element_sort_key
from xrd_finder.ui.finder_action_bar import FinderActionBar
from xrd_finder.ui.project_tree import ProjectTree
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


@dataclass(slots=True)
class PhaseAlignmentEstimate:
    zero_shift: float = 0.0
    matched_peaks: int = 0
    total_peaks: int = 0
    score: float = float("inf")
    status: str = "unmatched"


def _command_button_style(background: str, border: str, color: str = "#ffffff") -> str:
    return (
        "QPushButton {"
        f"background: {background}; border: 1px solid {border}; color: {color};"
        "border-radius: 5px; padding: 7px 14px; font-weight: 700;"
        "}"
        "QPushButton:pressed { padding-top: 8px; padding-bottom: 6px; }"
    )

class AnalysisWindow(QDialog):
    project_changed = Signal()
    IMPORT_SUFFIXES = {".xy", ".txt", ".dat", ".csv", ".xye", ".cif"}

    def __init__(self, project: Project, title: str) -> None:
        super().__init__()
        self.project = project
        self.setWindowTitle(f"{title} - {project.name}")
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
        self.tree.itemSelectionChanged.connect(self._on_project_tree_selection_changed)
        self.tree.pattern_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())
        self.tree.phase_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())

        self.sidebar = QWidget()
        self._register_drop_target(self.sidebar)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)
        import_button = QPushButton("Import XRD / CIF")
        import_button.setMinimumHeight(34)
        import_button.setToolTip("Import XRD patterns and CIF structures. You can also drag files into the window.")
        import_button.setStyleSheet(_command_button_style("#e9328f", "#ff65b3"))
        import_button.clicked.connect(self._import_scientific_files)
        order_row = QHBoxLayout()
        order_row.setContentsMargins(0, 0, 0, 0)
        order_row.setSpacing(4)
        order_row.addWidget(QLabel("Order"))
        move_up_button = QToolButton()
        move_up_button.setText("↑")
        move_up_button.setToolTip("Move selected XRD or CIF up")
        move_up_button.clicked.connect(lambda: self._move_current_tree_object(-1))
        move_down_button = QToolButton()
        move_down_button.setText("↓")
        move_down_button.setToolTip("Move selected XRD or CIF down")
        move_down_button.clicked.connect(lambda: self._move_current_tree_object(1))
        order_row.addWidget(move_up_button)
        order_row.addWidget(move_down_button)
        order_row.addStretch(1)
        sidebar_layout.addWidget(import_button)
        sidebar_layout.addLayout(order_row)
        sidebar_layout.addWidget(self.tree, 1)

        self.center = QWidget()
        self._register_drop_target(self.center)
        self.center_layout = QVBoxLayout(self.center)
        self.center_layout.setContentsMargins(6, 6, 6, 6)

        self.right_tabs = QTabWidget()
        self._register_drop_target(self.right_tabs)
        self.right_tabs.setMinimumWidth(280)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.center)
        splitter.addWidget(self.right_tabs)
        splitter.setSizes([260, 820, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(splitter)

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

    def _on_project_tree_selection_changed(self) -> None:
        pass

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


class PhaseFinderWindow(AnalysisWindow):
    def __init__(self, project: Project) -> None:
        super().__init__(project, "Phase Finder")
        self.resize(1500, 850)
        self.right_tabs.setMinimumWidth(520)
        self.element_table: PeriodicTableWidget | None = None
        self.element_states: dict[str, str] = {}
        self.selected_elements: set[str] = set()
        self.selected_element_order: list[str] = []
        self.exclude_all_other_elements = False
        self._last_formula_text = ""
        self.settings = QSettings("Xrdfinder", "Standalone")
        self.cod_online = CodOnlineService()
        self.ccdc = CcdcService()
        self.local_phase_cache = LocalPhaseCache()
        self.rruff = RruffService(self.local_phase_cache.root / "rruff")
        self.match_pdf2 = MatchPdf2Service(str(self.settings.value("match_pdf2/root", "", type=str) or "") or None)
        self.materials_project = MaterialsProjectService(
            str(self.settings.value("materials_project/api_key", "", type=str) or "")
        )
        self.calculated_pattern_service = CalculatedPatternService()
        self.finder_service = FinderService(self.calculated_pattern_service)
        self.candidate_search_service = CandidateSearchService(
            self.local_phase_cache,
            self.cod_online,
            self.ccdc,
            self.rruff,
            self.match_pdf2,
            self.materials_project,
        )
        self._start_match_pdf2_preload()
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
        self.preprocessed_observed_data: np.ndarray | None = None
        self.preprocessing_background_removed = False
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

        candidate_rows = [
            ["USER", phase.id, phase.formula, phase.name, "", "project structure"]
            for phase in project.phases
        ]
        if not candidate_rows:
            candidate_rows = [["", "", "", "No phases yet", "", ""]]

        self.center_layout.addWidget(self.match_plot, 4)
        self.candidate_table = CandidateTableWidget(candidate_rows)
        self.candidate_table.rowActivated.connect(self._queue_candidate_row_activation)
        self.candidate_table.addRequested.connect(self._add_selected_candidate_to_match_list)
        self.candidate_table.contextRequested.connect(self._show_candidate_context_menu)
        self.match_table = SelectedCandidatesTableWidget()
        self.match_table.rowClicked.connect(self._on_match_row_clicked)
        self.match_table.contextRequested.connect(self._show_match_context_menu)
        candidate_panel = QWidget()
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.setSpacing(4)
        candidate_layout.addWidget(QLabel("Candidate list"))
        candidate_layout.addWidget(self.candidate_table, 1)
        self.center_layout.addWidget(candidate_panel, 1)

        self.right_tabs.addTab(self._composition_tab(), "Elements")
        self.compound_card = CompoundCardWidget()
        self.right_tabs.addTab(self.compound_card, "Card")
        self.right_tabs.addTab(self._database_tab(), "Databases")
        help_button = QToolButton()
        help_button.setText("?")
        help_button.setToolTip("Open quick help")
        help_button.clicked.connect(self._show_quick_help)
        self.right_tabs.setCornerWidget(help_button, Qt.Corner.TopRightCorner)
        self._apply_default_phase_filter()

    def closeEvent(self, event) -> None:
        self.candidate_search_service.shutdown_background_downloads()
        super().closeEvent(event)

    def _smooth_active_pattern_plot(self) -> None:
        data = self._active_observed_data()
        if data is None:
            return
        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)
        window = max(5, min(31, len(y) // 80 * 2 + 1))
        smooth_y = self.finder_service._smooth_y(y, window)
        self._set_preprocessed_observed_curve(x, smooth_y, "Observed smoothed", self.preprocessing_background_removed)

    def _subtract_active_background_plot(self) -> None:
        data = self._active_observed_data()
        if data is None:
            return
        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)
        background = self._estimate_background(x, y)
        corrected = np.clip(y - background, 0.0, None)
        self._set_preprocessed_observed_curve(x, corrected, "Observed - background", True)

    def _reset_observed_preprocessing(self) -> None:
        self.preprocessed_observed_data = None
        self.preprocessing_background_removed = False
        self._clear_probability_caches()
        self._refresh_observed_pattern_plot()
        self._rerun_active_calculation()

    def _set_preprocessed_observed_curve(
        self,
        x: np.ndarray,
        y: np.ndarray,
        name: str,
        background_removed: bool,
    ) -> None:
        self.preprocessed_observed_data = np.column_stack([x, y])
        self.preprocessing_background_removed = background_removed
        self._clear_probability_caches()
        self._replace_observed_curve(x, y, name)
        self._rerun_active_calculation()

    def _rerun_active_calculation(self) -> None:
        if self.match_candidates:
            self._recalculate_match_profile()
        elif self.active_overlay_entry_id:
            candidate = self._selected_candidate_row()
            if candidate is not None:
                self.active_overlay_entry_id = None
                self._calculate_candidate_overlay(candidate, show_errors=False)

    def _replace_observed_curve(self, x: np.ndarray, y: np.ndarray, name: str) -> None:
        pattern = self._active_pattern()
        self._draw_observed_patterns(
            active_override=(pattern.id if pattern is not None else "", np.column_stack([x, y]), name)
        )

    def _refresh_project_phase_candidates(self) -> None:
        if not hasattr(self, "candidate_table"):
            return
        rows = [
            ["USER", phase.id, phase.formula, phase.name, "", "loaded structure"]
            for phase in self.project.phases
        ]
        if not rows:
            rows = [["", "", "", "No phases yet", "", ""]]
        self._set_candidate_rows(rows)

    def _on_project_tree_selection_changed(self) -> None:
        if not hasattr(self, "match_plot"):
            return
        self._clear_probability_caches()
        view_range = self._plot_view_range() if self.show_all_selected_patterns else None
        try:
            self._refresh_observed_pattern_plot()
            if self.match_candidates:
                self._recalculate_match_profile()
            elif self.active_overlay_entry_id:
                candidate = self._selected_candidate_row()
                if candidate is not None:
                    self.active_overlay_entry_id = None
                    self._calculate_candidate_overlay(candidate, show_errors=False)
        finally:
            self._restore_plot_view_range(view_range)

    def _set_pattern_display_mode(self, mode: str) -> None:
        self.show_all_selected_patterns = mode == "All selected"
        self._refresh_observed_pattern_plot()
        self._rerun_active_calculation()

    def _set_pattern_stack_offset(self, percent: int) -> None:
        self.pattern_stack_offset_percent = max(0, int(percent))
        if self.show_all_selected_patterns:
            self._refresh_observed_pattern_plot()
            self._rerun_active_calculation()

    def _active_observed_data(self):
        if self.preprocessed_observed_data is not None:
            return self.preprocessed_observed_data
        pattern = self._active_pattern()
        if pattern is None:
            return None
        try:
            return load_xy(pattern.source_path)
        except Exception:
            return None

    def _refresh_observed_pattern_plot(self) -> None:
        self.preprocessed_observed_data = None
        self.preprocessing_background_removed = False
        self._draw_observed_patterns()

    def _patterns_to_display(self):
        if self.show_all_selected_patterns:
            checked = set(self.tree.checked_pattern_ids())
            patterns = [pattern for pattern in self.project.patterns if pattern.id in checked]
            if patterns:
                return patterns
        pattern = self._active_pattern()
        return [pattern] if pattern is not None else []

    def _draw_observed_patterns(self, active_override=None) -> None:
        for item in self.plot_layers.get("observed", []):
            self.match_plot.removeItem(item)
        self.plot_layers["observed"] = []
        self.legend_item = ensure_right_legend(self.match_plot, clear=True)
        self.observed_pattern_plot_context = {}

        patterns = self._patterns_to_display()
        active_pattern = self._active_pattern()
        active_id = active_pattern.id if active_pattern is not None else ""
        colors = ["#202124", "#d93025", "#1a73e8", "#188038", "#f9ab00", "#8e24aa", "#00acc1", "#c5221f"]
        x_values = []
        y_values = []
        color_index = 0
        loaded_patterns = []

        for pattern in patterns:
            try:
                if active_override is not None and pattern.id == active_override[0]:
                    data = np.asarray(active_override[1], dtype=float)
                    name = active_override[2]
                else:
                    data = load_xy(pattern.source_path)
                    name = f"Observed: {pattern.name}"
            except Exception:
                continue
            if data is None or len(data) == 0:
                continue
            x = np.asarray(data[:, 0], dtype=float)
            y = np.asarray(data[:, 1], dtype=float)
            finite_y = y[np.isfinite(y)]
            pattern_height = float(np.nanmax(finite_y) - np.nanmin(finite_y)) if finite_y.size else 0.0
            loaded_patterns.append((pattern, name, x, y, pattern_height))

        offsets: dict[str, float] = {}
        if self.show_all_selected_patterns:
            y_offset = 0.0
            previous_height = 0.0
            for pattern, _name, _x, _y, pattern_height in reversed(loaded_patterns):
                if offsets:
                    y_offset += previous_height * (self.pattern_stack_offset_percent / 100.0)
                offsets[pattern.id] = y_offset
                previous_height = pattern_height

        for pattern, name, x, raw_y, pattern_height in loaded_patterns:
            y_offset = offsets.get(pattern.id, 0.0)
            y = raw_y + y_offset
            if pattern.id == active_id:
                color = "#202124"
            else:
                color_index += 1
                color = colors[color_index % len(colors)]
            width = 1.35 if pattern.id == active_id else 1.15
            alpha_color = color
            curve_item = self.match_plot.plot(x, y, pen=pg.mkPen(alpha_color, width=width))
            legend_proxy = self.match_plot.plot(
                [],
                [],
                pen=pg.mkPen(alpha_color, width=width),
                symbol="o" if pattern.id == active_id else None,
                symbolSize=7,
                symbolBrush=pg.mkBrush("#e11d21") if pattern.id == active_id else None,
                symbolPen=pg.mkPen("#e11d21", width=1.0) if pattern.id == active_id else None,
                name=name,
            )
            self.plot_layers["observed"].extend([curve_item, legend_proxy])
            finite_raw_y = raw_y[np.isfinite(raw_y)]
            raw_min = float(np.nanmin(finite_raw_y)) if finite_raw_y.size else 0.0
            raw_max = float(np.nanmax(finite_raw_y)) if finite_raw_y.size else 1.0
            self.observed_pattern_plot_context[pattern.id] = {
                "offset": float(y_offset),
                "raw_min": raw_min,
                "raw_max": raw_max,
                "plot_min": raw_min + float(y_offset),
                "plot_max": raw_max + float(y_offset),
                "height": float(pattern_height),
            }
            x_values.append(x)
            y_values.append(y)

        if x_values and y_values and not self.match_plot_view_initialized:
            self._reset_match_plot_view()

    def _plot_view_range(self) -> tuple[tuple[float, float], tuple[float, float]]:
        view_range = self.match_plot.plotItem.vb.viewRange()
        return (tuple(view_range[0]), tuple(view_range[1]))

    def _restore_plot_view_range(self, view_range: tuple[tuple[float, float], tuple[float, float]] | None) -> None:
        if view_range is None:
            return
        (xmin, xmax), (ymin, ymax) = view_range
        self.match_plot.setXRange(float(xmin), float(xmax), padding=0.0)
        self.match_plot.setYRange(float(ymin), float(ymax), padding=0.0)

    def _active_pattern_plot_context(self) -> dict[str, float]:
        pattern = self._active_pattern()
        if pattern is None:
            return {"offset": 0.0, "raw_min": 0.0, "raw_max": 1.0, "plot_min": 0.0, "plot_max": 1.0, "height": 1.0}
        return self.observed_pattern_plot_context.get(
            pattern.id,
            {"offset": 0.0, "raw_min": 0.0, "raw_max": 1.0, "plot_min": 0.0, "plot_max": 1.0, "height": 1.0},
        )

    def _reset_match_plot_view(self) -> None:
        self.match_plot.autoRange()
        self.match_plot_view_initialized = True

    def _match_menu_bar(self) -> QMenuBar:
        menu_bar = QMenuBar()

        file_menu = menu_bar.addMenu("File")
        file_menu.addAction("Insert/overlay...")
        file_menu.addAction("Restore original pattern")

        edit_menu = menu_bar.addMenu("Edit")
        edit_menu.addAction("Sample ID...")
        edit_menu.addAction("Sample date/time...")

        view_menu = menu_bar.addMenu("View")
        view_menu.addAction("Show grid")
        view_menu.addAction("Autoscale")
        view_menu.addAction("Reset zoom")

        pattern_menu = menu_bar.addMenu("Pattern")
        pattern_menu.addAction("Insert/overlay...")

        automatic_menu = pattern_menu.addMenu("Automatic")
        automatic_menu.addAction("Increase resolution...")
        automatic_menu.addAction("Strip K-Alpha2")
        automatic_menu.addAction("Edit background")
        automatic_menu.addAction("Recalculate background")
        automatic_menu.addAction("Subtract background")
        automatic_menu.addAction("Smooth raw data")
        automatic_menu.addSeparator()
        automatic_menu.addAction("Correct zero-point error")
        automatic_menu.addAction("Correct specimen-displacement")

        peak_search_menu = pattern_menu.addMenu("Peak searching")
        peak_search_menu.addAction("Find peaks")
        peak_search_menu.addAction("Mark selected peaks")
        peak_search_menu.addAction("Clear peak list")

        profile_menu = pattern_menu.addMenu("Profile fitting")
        profile_menu.addAction("Fit selected peaks")
        profile_menu.addAction("Calculate profile integrals...")

        pattern_menu.addSeparator()
        pattern_menu.addAction("Resolution...")
        pattern_menu.addAction("Wavelength...")

        peaks_menu = menu_bar.addMenu("Peaks")
        peaks_menu.addAction("Add peak")
        peaks_menu.addAction("Delete peak")
        peaks_menu.addAction("Peak list")

        search_menu = menu_bar.addMenu("Search")
        search_menu.addAction("Search by name/formula", self._search_pdf2_text)
        search_menu.addAction("Search by peaks", self._search_pdf2_candidates)
        search_menu.addAction("Search by formula")
        search_menu.addAction("Search by elements")

        entries_menu = menu_bar.addMenu("Entries")
        entries_menu.addAction("Add selected to working set", self._add_selected_candidate_to_match_list)
        entries_menu.addAction("Add selected CIF to project", self._add_selected_cif_to_project)
        entries_menu.addAction("Open entry card")
        entries_menu.addAction("Candidate list")

        database_menu = menu_bar.addMenu("Database")
        database_menu.addAction("Project phases")
        database_menu.addAction("Materials Project")
        database_menu.addAction("User phase library")
        database_menu.addAction("Database settings", self._show_database_settings_tab)

        tools_menu = menu_bar.addMenu("Tools")
        tools_menu.addAction("Calibrate pattern")
        tools_menu.addAction("Export candidate list")

        help_menu = menu_bar.addMenu("Help")
        help_menu.addAction("Phase Finder help")

        return menu_bar

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
        widget = QWidget()
        outer_layout = QVBoxLayout(widget)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Element filters"))
        top_row.addStretch(1)
        top_row.addWidget(QLabel("Scale"))
        scale = QComboBox()
        scale.addItems(["90%", "100%", "110%", "120%"])
        scale.setCurrentText("100%")
        top_row.addWidget(scale)
        outer_layout.addLayout(top_row)

        self.element_table = PeriodicTableWidget()
        self.element_table.leftClicked.connect(self._toggle_required_element)
        self.element_table.rightClicked.connect(self._toggle_optional_element)
        scale.currentTextChanged.connect(self.element_table.set_scale)
        outer_layout.addWidget(self.element_table)

        self.name_input = QLineEdit()
        self.name_input.hide()
        self.elem_count_input = QLineEdit()
        self.elem_count_input.hide()
        self.formula_sum_input = QLineEdit()
        self.formula_sum_input.hide()
        self.element_gate_label = QLabel("Gate: none")
        outer_layout.addWidget(self.element_gate_label)
        self.ccdc_doi_input = QLineEdit()
        self.ccdc_doi_input.setPlaceholderText("CCDC DOI / CSD refcode")
        self.ccdc_doi_input.returnPressed.connect(self._search_from_controls)
        outer_layout.addWidget(self.ccdc_doi_input)
        material_row = QHBoxLayout()
        self.inorganics_checkbox = QCheckBox("Inorganic")
        self.inorganics_checkbox.setChecked(True)
        self.inorganics_checkbox.toggled.connect(lambda _checked: self._search_from_controls())
        self.organics_checkbox = QCheckBox("Organic")
        self.organics_checkbox.setChecked(False)
        self.organics_checkbox.toggled.connect(lambda _checked: self._search_from_controls())
        material_row.addWidget(self.inorganics_checkbox)
        material_row.addWidget(self.organics_checkbox)
        material_row.addStretch(1)
        outer_layout.addLayout(material_row)
        data_mode_row = QHBoxLayout()
        self.structural_data_checkbox = QCheckBox("Structural data")
        self.structural_data_checkbox.setChecked(True)
        self.structural_data_checkbox.setToolTip("Include sources with CIF or atomic coordinates that can be calculated.")
        self.structural_data_checkbox.toggled.connect(lambda _checked: self._search_from_controls())
        self.reference_patterns_checkbox = QCheckBox("Experimental/reference patterns")
        self.reference_patterns_checkbox.setChecked(True)
        self.reference_patterns_checkbox.setToolTip("Include RRUFF and PDF-2 diffraction-line cards as reference overlays.")
        self.reference_patterns_checkbox.toggled.connect(lambda _checked: self._search_from_controls())
        self.rank_by_probability_checkbox = QCheckBox("Rank by peak match")
        self.rank_by_probability_checkbox.setChecked(True)
        self.rank_by_probability_checkbox.setToolTip("Estimate whether locally available structural candidates have peaks present in the active XRD pattern.")
        self.rank_by_probability_checkbox.toggled.connect(lambda _checked: self._search_from_controls())
        data_mode_row.addWidget(self.structural_data_checkbox)
        data_mode_row.addWidget(self.reference_patterns_checkbox)
        data_mode_row.addWidget(self.rank_by_probability_checkbox)
        data_mode_row.addStretch(1)
        outer_layout.addLayout(data_mode_row)
        actions = QHBoxLayout()
        search_button = QPushButton("Find")
        search_button.setMinimumHeight(34)
        search_button.setToolTip("Search candidate phases using the selected required/optional elements and enabled databases.")
        search_button.setStyleSheet(_command_button_style("#0b8043", "#35a96c"))
        search_button.clicked.connect(self._search_from_controls)
        reset_button = QPushButton("Reset table")
        reset_button.setMinimumHeight(34)
        reset_button.setToolTip("Clear element filters and reset the candidate list.")
        reset_button.setStyleSheet(_command_button_style("#5f6368", "#8a8d91"))
        reset_button.clicked.connect(self._reset_selected_elements)
        actions.addWidget(search_button)
        actions.addWidget(reset_button)
        outer_layout.addLayout(actions)
        outer_layout.addWidget(QLabel("Selected candidates"))
        outer_layout.addWidget(self.match_table, 1)
        return widget

    def _show_quick_help(self) -> None:
        QMessageBox.information(
            self,
            "XRD Finder Help",
            (
                "Quick help\n\n"
                "Project tree\n"
                "- Select an XRD row to make it active for search, preview and calculation.\n"
                "- Checkboxes control which XRD patterns or CIF phases are visible.\n"
                "- Double click an XRD row to show only that pattern.\n"
                "- Use Order arrows to change plot and legend order.\n\n"
                "Element table\n"
                "- Left click: required element, shown in blue.\n"
                "- Right click: optional element, shown in green.\n"
                "- Click again to remove that element from the gate.\n\n"
                "Candidate list\n"
                "- Single click: preview candidate peaks and show the card.\n"
                "- Double click: add the candidate to Selected candidates.\n"
                "- Right click: add, calculate overlay, or export candidate CIF.\n\n"
                "Selected candidates\n"
                "- Single click: show that selected phase on the plot and card.\n"
                "- Right click: change color, export CIF, remove phase, or clear the list.\n\n"
                "Plot\n"
                "- Mouse wheel or drag: zoom/pan.\n"
                "- Reset view restores the full pattern.\n"
                "- Right click the plot to export an image or show the full pattern.\n\n"
                "Databases\n"
                "- Databases are enabled with checkboxes.\n"
                "- Large COD/RRUFF databases are downloaded and indexed only when you choose it."
            ),
        )

    def _queue_candidate_row_activation(self, row: int) -> None:
        self._pending_candidate_row = row
        self._candidate_activation_timer.start()

    def _activate_pending_candidate_row(self) -> None:
        row = self._pending_candidate_row
        self._pending_candidate_row = -1
        self._on_candidate_row_activated(row)

    def _on_candidate_row_activated(self, row: int) -> None:
        candidate = self._candidate_row_values(row)
        if not candidate:
            return
        self._enrich_candidate_with_structure_info(candidate)
        self._refresh_candidate_table_row(row, candidate)
        self.candidate_table.set_iic(row, candidate.get("I/Ic*", ""))
        self._update_compound_card(candidate)
        self._preview_candidate_row(row)

    def _update_compound_card(self, candidate: dict[str, str] | None) -> None:
        if self.compound_card is not None:
            self.compound_card.set_candidate(candidate)

    def _enrich_candidate_with_structure_info(self, candidate: dict[str, str]) -> None:
        if self._candidate_source(candidate) == "PDF2" and candidate.get("Entry"):
            self._enrich_candidate_with_pdf2_info(candidate)
            return
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC"} or not candidate.get("Entry"):
            return
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
        except Exception:
            return
        if structure.name:
            candidate["Phase"] = structure.name
        if structure.formula:
            candidate["Formula"] = self.candidate_search_service.display_formula(structure.formula)
        iic = self._estimate_structure_corundum_iic(structure)
        if iic > 0:
            candidate["I/Ic*"] = f"{iic:.3g}"
        probability = self._structure_peak_probability(structure)
        if probability > 0:
            candidate["Prob."] = f"{probability:.0f}%"
        candidate["Space group"] = structure.space_group or structure.space_group_number or ""
        cell = structure.cell
        if all(getattr(cell, name, None) is not None for name in ("a", "b", "c", "alpha", "beta", "gamma")):
            candidate["Cell"] = (
                f"a {cell.a:.4g}   b {cell.b:.4g}   c {cell.c:.4g}\n"
                f"alpha {cell.alpha:.4g}   beta {cell.beta:.4g}   gamma {cell.gamma:.4g}"
            )
            candidate["Crystal system"] = self._crystal_system_from_cell(cell)
        atoms = []
        atom_rows = []
        for atom in (structure.atoms or [])[:48]:
            coords = []
            for value in (atom.x, atom.y, atom.z):
                coords.append(f"{value:.4g}" if value is not None else "?")
            occ = f", occ={atom.occupancy:.3g}" if atom.occupancy is not None else ""
            atoms.append(f"{atom.label or atom.element} {atom.element} ({', '.join(coords)}{occ})")
            b_value = atom.biso if atom.biso is not None else atom.uiso
            atom_rows.append([
                atom.label or atom.element,
                atom.element,
                coords[0],
                coords[1],
                coords[2],
                f"{atom.occupancy:.3g}" if atom.occupancy is not None else "",
                f"{b_value:.3g}" if b_value is not None else "",
            ])
        if atoms:
            suffix = "" if len(structure.atoms) <= 48 else f"\n... +{len(structure.atoms) - 48} atoms"
            candidate["Atoms"] = "\n".join(atoms) + suffix
            candidate["_AtomRows"] = atom_rows
        diffraction_rows = self._diffraction_rows_for_structure(structure)
        if diffraction_rows:
            candidate["_DiffractionRows"] = diffraction_rows
        publication = str(structure.metadata.get("publication", "") or "")
        if publication:
            candidate["Notes"] = publication
        doi = str(structure.metadata.get("doi", "") or "")
        if doi:
            candidate["DOI"] = doi

    def _crystal_system_from_cell(self, cell: CellParameters) -> str:
        lengths = [cell.a, cell.b, cell.c]
        angles = [cell.alpha, cell.beta, cell.gamma]
        if any(value is None for value in lengths + angles):
            return ""
        a, b, c = (float(value) for value in lengths)
        alpha, beta, gamma = (float(value) for value in angles)

        def close(left: float, right: float, tolerance: float = 0.03) -> bool:
            return abs(left - right) <= tolerance

        def angle90(value: float) -> bool:
            return abs(value - 90.0) <= 0.2

        if all(angle90(value) for value in (alpha, beta, gamma)):
            if close(a, b) and close(b, c):
                return "cubic"
            if close(a, b):
                return "tetragonal"
            return "orthorhombic"
        if angle90(alpha) and angle90(beta) and abs(gamma - 120.0) <= 0.3 and close(a, b):
            return "hexagonal/trigonal"
        if sum(angle90(value) for value in (alpha, beta, gamma)) == 2:
            return "monoclinic"
        return "triclinic"

    def _enrich_candidate_with_pdf2_info(self, candidate: dict[str, str]) -> None:
        details = self.match_pdf2.card_details(candidate.get("Entry", ""))
        if details.get("space_group"):
            candidate["Space group"] = str(details.get("space_group", ""))
        if details.get("space_group_number"):
            candidate["Space group"] = " ".join(
                part for part in [candidate.get("Space group", ""), str(details.get("space_group_number", ""))] if part
            )
        cell_details = details.get("cell")
        if isinstance(cell_details, dict):
            cell = CellParameters(
                a=cell_details.get("a"),
                b=cell_details.get("b"),
                c=cell_details.get("c"),
                alpha=cell_details.get("alpha"),
                beta=cell_details.get("beta"),
                gamma=cell_details.get("gamma"),
                volume=cell_details.get("volume"),
            )
            if all(getattr(cell, name, None) is not None for name in ("a", "b", "c", "alpha", "beta", "gamma")):
                candidate["Cell"] = (
                    f"a {cell.a:.4g}   b {cell.b:.4g}   c {cell.c:.4g}\n"
                    f"alpha {cell.alpha:.4g}   beta {cell.beta:.4g}   gamma {cell.gamma:.4g}"
                )
                candidate["Crystal system"] = self._crystal_system_from_cell(cell)
        peaks = self._pdf2_peaks_for_candidate(candidate)
        if not peaks:
            return
        rows = []
        for peak in peaks[:80]:
            rows.append([
                f"{getattr(peak, 'd_spacing', 0.0):.5g}",
                f"{getattr(peak, 'two_theta', 0.0):.5g}",
                f"{getattr(peak, 'intensity', 0.0):.3g}",
                str(getattr(peak, "h", "") or ""),
                str(getattr(peak, "k", "") or ""),
                str(getattr(peak, "l", "") or ""),
                "",
            ])
        candidate["_DiffractionRows"] = rows

    def _pdf2_peaks_for_candidate(self, candidate: dict[str, str]):
        wavelength = self._active_wavelength()
        peaks = []
        for peak in self.match_pdf2.diffraction_peaks(candidate.get("Entry", "")):
            ratio = wavelength / (2.0 * peak.d_spacing)
            if ratio <= 0.0 or ratio > 1.0:
                continue
            two_theta = math.degrees(2.0 * math.asin(ratio))
            peaks.append(
                SimpleNamespace(
                    two_theta=two_theta,
                    reference_two_theta=two_theta,
                    d_spacing=peak.d_spacing,
                    intensity=peak.intensity,
                    h=peak.h,
                    k=peak.k,
                    l=peak.l,
                )
            )
        return peaks

    def _diffraction_rows_for_structure(self, structure) -> list[list[str]]:
        try:
            peaks = self.calculated_pattern_service.calculate_sticks(
                structure,
                wavelength=self._active_wavelength(),
                two_theta_min=5.0,
                two_theta_max=120.0,
                intensity_min=0.5,
            )
        except Exception:
            return []
        peaks = sorted(peaks, key=lambda peak: peak.two_theta)[:60]
        return [
            [
                f"{peak.d:.4f}",
                f"{peak.two_theta:.3f}",
                f"{peak.intensity:.1f}",
                str(peak.h),
                str(peak.k),
                str(peak.l),
                str(peak.multiplicity),
            ]
            for peak in peaks
        ]

    def _refresh_candidate_table_row(self, row: int, candidate: dict[str, str]) -> None:
        if row < 0 or row >= self.candidate_table.rowCount():
            return
        for header, value in {
            "Formula": candidate.get("Formula", ""),
            "Phase": candidate.get("Phase", ""),
            "Prob.": candidate.get("Prob.", ""),
            "I/Ic*": candidate.get("I/Ic*", ""),
        }.items():
            column = -1
            for index in range(self.candidate_table.columnCount()):
                header_item = self.candidate_table.horizontalHeaderItem(index)
                if header_item is not None and header_item.text() == header:
                    column = index
                    break
            if column >= 0 and value:
                self.candidate_table.setItem(row, column, QTableWidgetItem(value))

    def _on_match_row_clicked(self, row: int) -> None:
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates[row]
        self._enrich_candidate_with_structure_info(candidate)
        self._update_compound_card(candidate)
        self._recalculate_match_profile()

    def _show_candidate_context_menu(self, global_point) -> None:
        menu = QMenu(self)
        menu.addAction("Add to working set", self._add_selected_candidate_to_match_list)
        menu.addAction("Calculate pattern overlay", self._calculate_selected_cif_overlay)
        menu.addAction("Export candidate CIF...", self._export_candidate_table_cif)
        menu.exec(global_point)

    def _show_match_context_menu(self, global_point) -> None:
        menu = QMenu(self)
        menu.addAction("Recalculate selected profile", self._recalculate_match_profile)
        menu.addAction("Change color...", self._change_selected_match_color)
        menu.addAction("Export phase CIF...", self._export_match_table_cif)
        menu.addAction("Remove selected phase", self._remove_selected_match_candidate)
        menu.addAction("Clear working set", self._clear_match_list)
        menu.exec(global_point)

    def _show_plot_context_menu(self, point) -> None:
        menu = QMenu(self)
        menu.addAction("Export image...", self._export_plot_image)
        menu.addSeparator()
        menu.addAction("Show full pattern", self._full_pattern_range)
        grid_action = menu.addAction("Grid")
        grid_action.setCheckable(True)
        grid_action.setChecked(self.grid_visible)
        grid_action.toggled.connect(self._set_grid_visible)
        legend_action = menu.addAction("Legend")
        legend_action.setCheckable(True)
        legend_action.setChecked(self.legend_item is not None)
        legend_action.toggled.connect(self._set_legend_visible)
        hkl_action = menu.addAction("HKL labels")
        hkl_action.setCheckable(True)
        hkl_action.setChecked(self.show_hkl_labels)
        hkl_action.toggled.connect(self._set_hkl_labels_enabled)
        menu.addAction(self._layer_action("Experimental pattern", "observed"))
        menu.addAction(self._layer_action("Candidate preview", "preview_peak_positions"))
        menu.addAction(self._layer_action("Total calculated profile", "total_profile"))
        menu.addAction(self._layer_action("Individual phase profiles", "phase_profiles"))
        menu.addAction(self._layer_action("Background", "background"))
        menu.addAction(self._layer_action("Phase tick marks", "phase_ticks"))
        menu.addAction(self._layer_action("Assignment markers", "coverage_markers"))
        menu.addAction(self._layer_action("Peak labels (HKL)", "peak_labels"))
        menu.addAction(self._layer_action("Unknown peaks", "unknown_peaks"))
        menu.addSeparator()
        menu.addAction("Hide calculated overlay", lambda: self._set_calculated_visible(False))
        menu.addAction("Show calculated overlay", lambda: self._set_calculated_visible(True))
        menu.addAction("Clear calculated overlay", self._clear_calculated_overlay)
        menu.exec(self.match_plot.mapToGlobal(point))

    def _export_plot_image(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export image",
            str(Path(self._last_directory()) / "xrd_finder_plot.png"),
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg)",
        )
        if not path:
            return
        self._remember_directory(path)
        if not re.search(r"\.(png|jpe?g)$", path, flags=re.IGNORECASE):
            path += ".png"
        try:
            from pyqtgraph.exporters import ImageExporter

            exporter = ImageExporter(self.match_plot.plotItem)
            params = exporter.parameters()
            current_width = max(float(self.match_plot.width()), 1.0)
            target_width = max(3200.0, current_width * 2.0)
            params["width"] = target_width
            exporter.export(path)
        except Exception as exc:
            if not self.match_plot.grab().save(path):
                QMessageBox.warning(self, "Export image", f"Could not save current plot image:\n{exc}")

    def _export_candidate_table_cif(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Export CIF", "Select a candidate row first.")
            return
        self._export_candidate_cif(candidate)

    def _export_match_table_cif(self) -> None:
        row = self.match_table.currentRow()
        if row < 0 or row >= len(self.match_candidates):
            QMessageBox.information(self, "Export CIF", "Select a phase row first.")
            return
        self._export_candidate_cif(self.match_candidates[row])

    def _export_candidate_cif(self, candidate: dict[str, str]) -> None:
        try:
            source = self._candidate_cif_path(candidate)
        except Exception as exc:
            QMessageBox.warning(self, "Export CIF", str(exc))
            return
        default_name = f"{self._candidate_phase_name(candidate) or candidate.get('Entry') or 'phase'}.cif"
        default_name = re.sub(r"[^A-Za-z0-9._-]+", "_", default_name).strip("_") or "phase.cif"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export CIF",
            str(Path(self._last_directory()) / default_name),
            "CIF structure (*.cif)",
        )
        if not path:
            return
        self._remember_directory(path)
        if not path.lower().endswith(".cif"):
            path += ".cif"
        try:
            shutil.copy2(source, path)
        except Exception as exc:
            QMessageBox.warning(self, "Export CIF", str(exc))

    def _layer_action(self, label: str, layer: str, checked: bool | None = None, enabled: bool = True):
        action = self._make_action(label)
        action.setCheckable(True)
        has_items = bool(self.plot_layers.get(layer, []))
        action.setEnabled(enabled and has_items)
        action.setChecked(self._layer_visible(layer) if checked is None else checked)
        if enabled and has_items:
            action.toggled.connect(lambda visible, key=layer: self._set_layer_visible(key, visible))
        return action

    def _make_action(self, label: str):
        return QAction(label, self)

    def _layer_visible(self, layer: str) -> bool:
        items = self.plot_layers.get(layer, [])
        return bool(items) and all(item.isVisible() for item in items)

    def _set_layer_visible(self, layer: str, visible: bool) -> None:
        for item in self.plot_layers.get(layer, []):
            item.setVisible(visible)

    def _set_calculated_visible(self, visible: bool) -> None:
        self._set_layer_visible("calculated_profile", visible)
        self._set_layer_visible("total_profile", visible)
        self._set_layer_visible("phase_profiles", visible)
        self._set_layer_visible("background", visible)
        self._set_layer_visible("peak_positions", visible)
        self._set_layer_visible("phase_ticks", visible)
        self._set_layer_visible("peak_links", visible)
        self._set_layer_visible("coverage_markers", visible)
        self._set_layer_visible("peak_labels", visible)
        self._set_layer_visible("unknown_peaks", visible)
        self._set_layer_visible("hkl", visible)
        self._set_layer_visible("preview_profile", visible)
        self._set_layer_visible("preview_peak_positions", visible)
        self._set_layer_visible("preview_peak_links", visible)
        self._set_layer_visible("preview_hkl", visible)

    def _clear_calculated_overlay(self) -> None:
        for layer in [
            "calculated_profile",
            "total_profile",
            "phase_profiles",
            "background",
            "peak_positions",
            "phase_ticks",
            "peak_links",
            "coverage_markers",
            "peak_labels",
            "unknown_peaks",
            "hkl",
            "preview_profile",
            "preview_peak_positions",
            "preview_peak_links",
            "preview_hkl",
            "legend_info",
        ]:
            for item in self.plot_layers.get(layer, []):
                self.match_plot.removeItem(item)
            self.plot_layers[layer] = []
        self.active_overlay_entry_id = None

    def _clear_preview_overlay(self) -> None:
        for layer in ["preview_profile", "preview_peak_positions", "preview_peak_links", "preview_hkl"]:
            for item in self.plot_layers.get(layer, []):
                self.match_plot.removeItem(item)
            self.plot_layers[layer] = []

    def _set_hkl_labels_enabled(self, visible: bool) -> None:
        self.show_hkl_labels = visible
        if self.match_candidates:
            self._recalculate_match_profile()
            row = self.candidate_table.currentRow()
            if row >= 0:
                self._preview_candidate_row(row)
        elif self.active_overlay_entry_id:
            row = self.candidate_table.currentRow()
            if row >= 0:
                self.active_overlay_entry_id = None
                self._preview_candidate_row(row)

    def _set_grid_visible(self, visible: bool) -> None:
        self.grid_visible = visible
        alpha = 0.25 if visible else 0.0
        self.match_plot.showGrid(x=True, y=True, alpha=alpha)

    def _set_legend_visible(self, visible: bool) -> None:
        if visible and self.legend_item is None:
            self.legend_item = self.match_plot.addLegend()
        elif not visible and self.legend_item is not None:
            self.legend_item.scene().removeItem(self.legend_item)
            self.legend_item = None

    def _add_legend_info(self, text: str) -> None:
        item = self.match_plot.plot([], [], pen=pg.mkPen("#00000000", width=0.1), name=text)
        self.plot_layers["legend_info"].append(item)

    def _phase_legend_label(self, candidate: dict[str, str]) -> str:
        phase = self._candidate_phase_name(candidate) or candidate.get("Entry", "") or "phase"
        source = self._candidate_source(candidate)
        entry = candidate.get("Entry", "")
        if source and entry:
            return f"{phase} {source}#{entry}"
        if entry:
            return f"{phase} #{entry}"
        return phase

    def _full_pattern_range(self) -> None:
        self._reset_match_plot_view()

    def _selected_candidate_row(self) -> dict[str, str] | None:
        return self.candidate_table.selected_row_values()

    def _candidate_row_values(self, row: int) -> dict[str, str]:
        return self.candidate_table.row_values(row)

    def _candidate_rows(self) -> list[dict[str, str]]:
        rows = []
        for candidate in self.candidate_table.all_row_values():
            if candidate.get("Entry") and self._candidate_source(candidate) in {"COD", "USER", "MP", "CCDC"}:
                rows.append(candidate)
        return rows

    def _preview_candidate_row(self, row: int) -> None:
        candidate = self._candidate_row_values(row)
        if self._candidate_source(candidate) == "RRUFF" and candidate.get("Entry"):
            self._preview_rruff_reference(candidate, show_errors=False)
            return
        if self._candidate_source(candidate) == "PDF2" and candidate.get("Entry"):
            self._preview_pdf2_reference(candidate, show_errors=False)
            return
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC"} or not candidate.get("Entry"):
            return
        self._calculate_candidate_overlay(candidate, show_errors=False)

    def _candidate_source(self, candidate: dict[str, str]) -> str:
        return candidate.get("Source", "") or candidate.get("Qual.", "")

    def _candidate_phase_name(self, candidate: dict[str, str]) -> str:
        return candidate.get("Phase", "") or candidate.get("Candidate phase", "")

    def _candidate_cif_path(self, candidate: dict[str, str]) -> Path:
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if source in {"USER", "CCDC"} and entry_id:
            cached_path = self.local_phase_cache.cif_path(source, entry_id)
            if cached_path is not None:
                return cached_path
            raise ValueError("CIF is not in the user phase library. Save or import it first.")
        if source == "COD" and entry_id:
            cached_path = self.local_phase_cache.cif_path("COD", entry_id)
            if cached_path is not None:
                return cached_path
            entry = self._candidate_to_cod_entry(candidate)
            return self.local_phase_cache.download_cod_entry(entry, self.cod_online)
        if source == "MP" and entry_id:
            cached_path = self.local_phase_cache.cif_path("MP", entry_id)
            if cached_path is not None:
                return cached_path
            target_dir = self.local_phase_cache.root / "materials_project_cif"
            cif_path = self.materials_project.download_cif(entry_id, target_dir)
            self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=entry_id)
            return cif_path
        raise ValueError("Select a saved COD, CCDC, USER, or Materials Project row with an entry id.")

    def _candidate_local_cif_path(self, candidate: dict[str, str]) -> Path | None:
        source = self._candidate_source(candidate)
        entry_id = candidate.get("Entry", "")
        if not entry_id:
            return None
        if source == "USER":
            phase = next((item for item in self.project.phases if item.id == entry_id), None)
            if phase is not None and phase.source_path:
                path = Path(phase.source_path)
                if path.exists():
                    return path
            return self.local_phase_cache.cif_path("USER", entry_id)
        if source in {"COD", "CCDC", "MP"}:
            return self.local_phase_cache.cif_path(source, entry_id)
        return None

    def _add_selected_cif_to_project(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Add CIF", "Select a structure source row first.")
            return
        try:
            phase, structure = self._add_candidate_to_project(candidate)
            self.tree.set_project(self.project)
            self.project_changed.emit()
            if structure is not None:
                self._calculate_structure_overlay(structure)
            QMessageBox.information(self, "Add CIF", f"Added {phase.name} to project.")
        except Exception as exc:
            QMessageBox.warning(self, "Add CIF failed", str(exc))

    def _calculate_selected_cif_overlay(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Calculate pattern", "Select a structure source row first.")
            return
        if self._candidate_source(candidate) == "RRUFF":
            self._preview_rruff_reference(candidate, show_errors=True)
            return
        if self._candidate_source(candidate) == "PDF2":
            self._preview_pdf2_reference(candidate, show_errors=True)
            return
        self._calculate_candidate_overlay(candidate, show_errors=True)

    def _download_selected_candidate_to_cache(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Download CIF", "Select a COD or Materials Project row first.")
            return
        source = self._candidate_source(candidate)
        if source in {"USER", "CCDC"}:
            QMessageBox.information(self, "Download CIF", "This CIF is already in the user phase library.")
            return
        if source not in {"COD", "MP"} or not candidate.get("Entry"):
            QMessageBox.information(self, "Download CIF", "Only COD online or Materials Project rows can be saved to the user phase library.")
            return
        try:
            if source == "COD":
                saved_id = candidate.get("Entry", "")
                cached_path = self.local_phase_cache.cif_path("COD", saved_id)
                if cached_path is not None:
                    cif_path = cached_path
                else:
                    entry = self._candidate_to_cod_entry(candidate)
                    cif_path = self.local_phase_cache.download_cod_entry(entry, self.cod_online)
            else:
                saved_id = candidate.get("Entry", "")
                target_dir = self.local_phase_cache.root / "materials_project_cif"
                cif_path = self.materials_project.download_cif(saved_id, target_dir)
                self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=saved_id)
        except Exception as exc:
            QMessageBox.warning(self, "Download CIF failed", str(exc))
            return
        row = self.candidate_table.currentRow()
        if row >= 0:
            self.candidate_table.setItem(row, 0, QTableWidgetItem(source))
        QMessageBox.information(self, "Download CIF", f"Saved {saved_id}:\n{cif_path}")

    def _candidate_to_cod_entry(self, candidate: dict[str, str]) -> object:
        from xrd_finder.services.cod_online_service import CodEntry

        return CodEntry(
            cod_id=candidate.get("Entry", ""),
            formula=candidate.get("Formula", ""),
            name=self._candidate_phase_name(candidate),
            spacegroup="",
            source=candidate.get("Notes", ""),
        )

    def _candidate_key(self, candidate: dict[str, str]) -> str:
        return f"{self._candidate_source(candidate)}:{candidate.get('Entry', '')}"

    def _add_candidate_to_project(self, candidate: dict[str, str]):
        cif_path = self._candidate_cif_path(candidate)
        source_path = str(cif_path)
        for phase in self.project.phases:
            if phase.source_path == source_path:
                structure = next((item for item in self.project.structures if item.id == phase.structure_id), None)
                return phase, structure
        phase, structure = create_phase_from_cif(cif_path)
        phase_name = self._candidate_phase_name(candidate)
        if phase_name:
            phase.name = phase_name
            structure.name = phase_name
        if not phase.formula and candidate.get("Formula"):
            phase.formula = candidate["Formula"]
            structure.formula = candidate["Formula"]
        self.project.phases.append(phase)
        self.project.structures.append(structure)
        self.project.touch()
        return phase, structure

    def _add_selected_candidate_to_match_list(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Working set", "Select a structure source row first.")
            return
        if self._candidate_source(candidate) == "RRUFF":
            self._preview_rruff_reference(candidate, show_errors=True)
            QMessageBox.information(
                self,
                "RRUFF reference",
                "RRUFF entries are measured reference patterns. They can be previewed as overlays, but not used as calculated CIF phases.",
            )
            return
        if self._candidate_source(candidate) == "PDF2":
            self._preview_pdf2_reference(candidate, show_errors=True)
            QMessageBox.information(
                self,
                "PDF-2 reference",
                "PDF-2 entries are reference cards. They can be previewed as peak overlays, but not used as calculated CIF phases.",
            )
            return
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC"} or not candidate.get("Entry"):
            QMessageBox.information(self, "Working set", "Only saved COD, CCDC, user, or Materials Project structures can be calculated from CIF for now.")
            return
        self._add_candidate_to_match_list(candidate, show_errors=True, recalculate=True)

    def _add_candidate_to_match_list(
        self,
        candidate: dict[str, str],
        show_errors: bool,
        recalculate: bool = True,
    ) -> bool:
        key = self._candidate_key(candidate)
        if any(self._candidate_key(item) == key for item in self.match_candidates):
            if recalculate:
                self._recalculate_match_profile(auto_zoom=self._should_autozoom_match_profile())
            return True
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            phase_name = self._candidate_phase_name(candidate)
            if phase_name:
                structure.name = phase_name
            if not structure.formula and candidate.get("Formula"):
                structure.formula = candidate["Formula"]
            self.match_candidates.append(candidate.copy())
            self.match_structures[key] = structure
            if recalculate:
                self._recalculate_match_profile(auto_zoom=self._should_autozoom_match_profile())
            return True
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Working set failed", str(exc))
            return False

    def _sync_candidate_rows_to_match_list(self) -> None:
        candidates = self._candidate_rows()
        if not candidates:
            self._clear_match_list()
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        errors = []
        try:
            self.match_candidates.clear()
            self.match_structures.clear()
            for candidate in candidates:
                try:
                    self._add_candidate_to_match_list(candidate, show_errors=False, recalculate=False)
                except Exception as exc:
                    errors.append(str(exc))
            self._recalculate_match_profile(auto_zoom=self._should_autozoom_match_profile())
        finally:
            self.unsetCursor()
        if errors:
            QMessageBox.warning(self, "Selected phases", "; ".join(errors[:3]))

    def _add_selected_phases_to_xrd(self) -> None:
        if not self.match_candidates:
            QMessageBox.information(self, "Add phases", "Add candidates to selected phases first.")
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        errors = []
        try:
            for candidate in self.match_candidates:
                try:
                    self._add_candidate_to_project(candidate)
                except Exception as exc:
                    errors.append(str(exc))
            self.project.touch()
            self.tree.set_project(self.project)
            self.project_changed.emit()
        finally:
            self.unsetCursor()
        if errors:
            QMessageBox.warning(self, "Add phases", "; ".join(errors[:3]))

    def _remove_selected_match_candidate(self) -> None:
        row = self.match_table.currentRow()
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates.pop(row)
        key = self._candidate_key(candidate)
        self.match_structures.pop(key, None)
        self.match_scales.pop(key, None)
        self.match_quantities.pop(key, None)
        self.match_iic.pop(key, None)
        self.match_zero_shifts.pop(key, None)
        self.match_cell_scales.pop(key, None)
        self.match_alignment_scores.pop(key, None)
        self._recalculate_match_profile()

    def _change_selected_match_color(self) -> None:
        row = self.match_table.currentRow()
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates[row]
        current = QColor(self._phase_color(candidate, row))
        color = QColorDialog.getColor(current, self, "Select phase color")
        if not color.isValid():
            return
        candidate["_Color"] = color.name()
        self._recalculate_match_profile()

    def _clear_match_list(self) -> None:
        self.match_candidates.clear()
        self.match_structures.clear()
        self.match_scales.clear()
        self.match_quantities.clear()
        self.match_iic.clear()
        self.match_zero_shifts.clear()
        self.match_cell_scales.clear()
        self.match_alignment_scores.clear()
        self._clear_calculated_overlay()
        self._update_match_table()

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
        finder_candidates = []
        candidate_by_key = {}
        for candidate in self.match_candidates:
            try:
                cif_path = self._candidate_cif_path(candidate)
            except Exception:
                continue
            key = self._candidate_key(candidate)
            candidate_by_key[key] = candidate
            finder_candidates.append(
                FinderCandidateInput(
                    cif_path=str(cif_path),
                    entry_id=key,
                    name=self._candidate_phase_name(candidate) or candidate.get("Entry", ""),
                    formula=candidate.get("Formula", ""),
                    source=self._candidate_source(candidate),
                )
            )
        if not finder_candidates:
            self._update_match_table()
            return

        try:
            result = self.finder_service.run(
                FinderInput(
                    pattern_path=pattern.source_path,
                    candidates=finder_candidates,
                    wavelength=pattern.wavelength,
                    observed_x=self.preprocessed_observed_data[:, 0].tolist()
                    if self.preprocessed_observed_data is not None else None,
                    observed_y=self.preprocessed_observed_data[:, 1].tolist()
                    if self.preprocessed_observed_data is not None else None,
                    subtract_background=not self.preprocessing_background_removed,
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Finder calculation failed", str(exc))
            self._update_match_table()
            return

        x = np.asarray(result.pattern_x, dtype=float)
        background = np.asarray(result.background, dtype=float)
        calculated_total = np.asarray(result.calculated_total, dtype=float)
        observed_y = np.asarray(result.pattern_y, dtype=float)
        observed_ymax = float(np.nanmax(result.pattern_y)) if result.pattern_y else 100.0
        observed_ymin = float(np.nanmin(result.pattern_y)) if result.pattern_y else 0.0
        active_plot_context = self._active_pattern_plot_context()
        active_plot_offset = float(active_plot_context.get("offset", 0.0))
        observed_y_plot = observed_y + active_plot_offset
        observed_ymax_plot = observed_ymax + active_plot_offset
        observed_ymin_plot = observed_ymin + active_plot_offset
        background_plot = background + active_plot_offset
        calculated_total_plot = calculated_total + active_plot_offset
        phase_peak_sets: list[tuple[str, str, np.ndarray]] = []
        phase_assignment_styles: dict[str, tuple[str, str]] = {}
        self.match_scales.clear()
        self.match_quantities.clear()
        self.match_iic.clear()
        self.match_zero_shifts.clear()
        self.match_cell_scales.clear()
        self.match_alignment_scores.clear()

        for index, candidate_result in enumerate(result.candidates):
            candidate = candidate_by_key.get(candidate_result.entry_id)
            if candidate is None:
                continue
            key = self._candidate_key(candidate)
            color = self._phase_color(candidate, index)
            phase_label = self._phase_legend_label(candidate)
            phase_assignment_styles[str(candidate_result.candidate_key)] = (color, phase_label)
            profile = np.asarray(candidate_result.profile, dtype=float)
            self.match_scales[key] = float(candidate_result.scale)
            self.match_quantities[key] = float(candidate_result.quantity_percent)
            self.match_iic[key] = self._estimate_candidate_corundum_iic(candidate, x)
            self.match_zero_shifts[key] = float(result.global_zero_shift)
            self.match_cell_scales[key] = float(candidate_result.cell_scale)
            self.match_alignment_scores[key] = (
                f"{candidate_result.status} {candidate_result.matched_peaks}/{candidate_result.total_peaks}"
            )
            contribution_item = plot_profile(
                self.match_plot,
                x,
                background_plot + profile,
                color,
                f"phase {phase_label}",
                width=1.5,
            )
            self.plot_layers["phase_profiles"].append(contribution_item)
            phase_peak_sets.append(
                (
                    color,
                    phase_label,
                    np.asarray(candidate_result.peak_two_theta, dtype=float),
                )
            )
            tick_peaks = [
                SimpleNamespace(
                    two_theta=float(peak_two_theta),
                    reference_two_theta=float(reference_two_theta),
                    intensity=float(peak_intensity),
                )
                for peak_two_theta, reference_two_theta, peak_intensity in zip(
                    candidate_result.peak_two_theta,
                    candidate_result.peak_reference_two_theta
                    or candidate_result.peak_two_theta,
                    candidate_result.peak_intensity or [100.0] * len(candidate_result.peak_two_theta),
                )
            ]
            if not self.show_all_selected_patterns:
                y_span = max(observed_ymax - observed_ymin, observed_ymax, 1.0)
                lane_height = y_span * 0.038
                lane_gap = lane_height * 0.85
                lane_top = min(observed_ymin_plot, float(np.nanpercentile(background_plot, 5))) - y_span * 0.12
                lane_baseline = lane_top - index * (lane_height + lane_gap)
                lane_items = plot_phase_marker_lane(
                    self.match_plot,
                    tick_peaks,
                    color,
                    lane_baseline,
                    lane_height,
                    None,
                    float(np.nanmin(x) + (np.nanmax(x) - np.nanmin(x)) * 0.005),
                )
                self.plot_layers["phase_ticks"].extend(lane_items)

        background_item = plot_profile(
            self.match_plot,
            x,
            background_plot,
            "#9aa0a6",
            "background",
            width=1.2,
        )
        self.plot_layers["background"].append(background_item)
        fit_quality = self._profile_fit_quality(observed_y, background, calculated_total)
        explained, total_observed = self._add_peak_coverage_markers(
            x,
            observed_y_plot,
            np.clip(observed_y - background, 0.0, None),
            phase_peak_sets,
            getattr(result, "observed_peaks", []),
            phase_assignment_styles,
        )
        sum_item = plot_profile(
            self.match_plot,
            x,
            calculated_total_plot,
            "#0b8043",
            f"calculated total | fit {fit_quality:.0f}% | peaks {explained}/{total_observed}",
            width=1.9,
        )
        self.plot_layers["total_profile"].append(sum_item)
        self.match_plot.setTitle("")
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
        y = np.asarray(corrected_y, dtype=float)
        if len(y) < 5 or float(np.nanmax(y)) <= 0:
            return np.array([], dtype=float)
        prominence = max(float(np.nanmax(y)) * 0.04, float(np.nanstd(y)) * 3.5, 1.0)
        peak_indices, _properties = find_peaks(y, prominence=prominence, distance=max(5, len(y) // 700))
        if len(peak_indices) > 80:
            heights = y[peak_indices]
            keep = np.argsort(heights)[-80:]
            peak_indices = peak_indices[keep]
        return np.sort(np.asarray(x, dtype=float)[peak_indices])

    def _observed_peak_records(self, x, corrected_y, limit: int = 24) -> list[tuple[float, float]]:
        y = np.asarray(corrected_y, dtype=float)
        x_values = np.asarray(x, dtype=float)
        if len(y) < 5 or float(np.nanmax(y)) <= 0:
            return []
        prominence = max(float(np.nanmax(y)) * 0.025, float(np.nanstd(y)) * 2.5, 1.0)
        peak_indices, _properties = find_peaks(y, prominence=prominence, distance=max(5, len(y) // 800))
        if len(peak_indices) == 0:
            return []
        records = [
            (float(x_values[index]), max(float(y[index]), 0.0))
            for index in peak_indices
            if np.isfinite(x_values[index]) and np.isfinite(y[index]) and y[index] > 0
        ]
        records.sort(key=lambda item: item[1], reverse=True)
        return records[:limit]

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
        if observed_peak_assignments:
            return self._add_assignment_markers(x, observed_y, observed_peak_assignments, phase_assignment_styles or {})
        if not phase_peak_sets:
            return 0, 0
        peak_positions = self._observed_peak_positions(x, corrected_y)
        if len(peak_positions) == 0:
            return 0, 0
        y_span = max(float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)), float(np.nanmax(observed_y)), 1.0)
        marker_offset = y_span * 0.045
        marker_cutoff = float(np.nanpercentile(observed_y, 72))
        unknown_limit = 10
        unknown_count = 0
        explained = 0
        considered_positions = []
        for obs_x in peak_positions:
            y_index = int(np.argmin(np.abs(x - obs_x)))
            if float(observed_y[y_index]) >= float(np.nanpercentile(observed_y, 60)):
                considered_positions.append(float(obs_x))
        for obs_x in considered_positions:
            y_index = int(np.argmin(np.abs(x - obs_x)))
            marker_y = float(observed_y[y_index]) + marker_offset
            best_color = ""
            best_delta = 0.22
            for color, _label, phase_positions in phase_peak_sets:
                if len(phase_positions) == 0:
                    continue
                delta = float(np.min(np.abs(phase_positions - obs_x)))
                if delta <= best_delta:
                    best_delta = delta
                    best_color = color
            if best_color:
                item = pg.ScatterPlotItem(
                    [float(obs_x)],
                    [marker_y],
                    pen=pg.mkPen("#ffffff", width=0.8),
                    brush=pg.mkBrush(best_color),
                    size=8,
                    symbol="o",
                )
                self.match_plot.addItem(item)
                self.plot_layers["coverage_markers"].append(item)
                explained += 1
            else:
                if unknown_count >= unknown_limit or float(observed_y[y_index]) < marker_cutoff:
                    continue
                item = pg.ScatterPlotItem(
                    [float(obs_x)],
                    [marker_y],
                    pen=pg.mkPen("#6f6f6f", width=1.0),
                    brush=pg.mkBrush("#ffffff"),
                    size=8,
                    symbol="t",
                )
                self.match_plot.addItem(item)
                self.plot_layers["unknown_peaks"].append(item)
                unknown_count += 1
        return explained, int(len(considered_positions))

    def _add_assignment_markers(
        self,
        x: np.ndarray,
        observed_y: np.ndarray,
        observed_peaks,
        phase_assignment_styles: dict[str, tuple[str, str]],
    ) -> tuple[int, int]:
        y_span = max(float(np.nanmax(observed_y)) - float(np.nanmin(observed_y)), float(np.nanmax(observed_y)), 1.0)
        marker_offset = y_span * 0.05
        unknown_cutoff = float(np.nanpercentile(observed_y, 74))
        unknown_count = 0
        explained = 0
        legend_marker_names: set[str] = set()
        peak_records = []
        for observed_peak in observed_peaks:
            obs_x = float(observed_peak.two_theta)
            if not np.isfinite(obs_x):
                continue
            y_index = int(np.argmin(np.abs(x - obs_x)))
            peak_records.append((float(observed_y[y_index]), observed_peak, y_index))
        peak_records = sorted(peak_records, key=lambda item: item[0], reverse=True)[:80]
        peak_records = sorted(peak_records, key=lambda item: float(item[1].two_theta))
        for _peak_height, observed_peak, y_index in peak_records:
            obs_x = float(observed_peak.two_theta)
            marker_y = float(observed_y[y_index]) + marker_offset
            assignments = list(getattr(observed_peak, "assignments", []) or [])
            status = getattr(getattr(observed_peak, "status", ""), "value", getattr(observed_peak, "status", ""))
            if assignments:
                explained += 1
                primary_assignment = self._primary_assignment(assignments)
                color, _phase_label = phase_assignment_styles.get(
                    str(getattr(primary_assignment, "candidate_key", "")),
                    ("#d93025", ""),
                )
                item = pg.ScatterPlotItem(
                    [obs_x],
                    [marker_y],
                    pen=pg.mkPen("#ffffff", width=1.0),
                    brush=pg.mkBrush(color),
                    size=9,
                    symbol="d" if status == "overlapping" else "o",
                )
                self.match_plot.addItem(item)
                self.plot_layers["coverage_markers"].append(item)
                if self.show_hkl_labels:
                    label = self._assignment_marker_label(assignments)
                    if label:
                        text = pg.TextItem(label, color="#111111", anchor=(0.5, 1.05))
                        font = QFont()
                        font.setPointSize(8)
                        font.setWeight(QFont.Weight.DemiBold)
                        text.setFont(font)
                        text.setPos(obs_x, marker_y + marker_offset * 0.3)
                        self.match_plot.addItem(text)
                        self.plot_layers["peak_labels"].append(text)
            else:
                if unknown_count >= 10 or float(observed_y[y_index]) < unknown_cutoff:
                    continue
                item = pg.ScatterPlotItem(
                    [obs_x],
                    [marker_y],
                    pen=pg.mkPen("#6f6f6f", width=1.2),
                    brush=pg.mkBrush("#ffffff"),
                    size=9,
                    symbol="t",
                    name="unknown peak" if "unknown peak" not in legend_marker_names else None,
                )
                legend_marker_names.add("unknown peak")
                self.match_plot.addItem(item)
                self.plot_layers["unknown_peaks"].append(item)
                unknown_count += 1
        return explained, int(len(peak_records))

    def _primary_assignment(self, assignments):
        return max(
            assignments,
            key=lambda assignment: float(getattr(assignment, "intensity_ratio", 0.0)),
        )

    def _assignment_marker_label(self, assignments) -> str:
        labels = []
        for assignment in assignments[:2]:
            hkl = "-".join(str(value) for value in getattr(assignment, "hkl", ()) if value is not None)
            if hkl:
                labels.append(f"({hkl})")
        if len(assignments) > 2 and labels:
            labels[-1] = labels[-1] + "+"
        return " / ".join(labels)

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
            nearest_index = int(np.argmin(np.abs(observed_positions - calc_x)))
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
        if len(observed_positions) == 0 or not peaks:
            return PhaseAlignmentEstimate()
        strong_peaks = [
            peak for peak in peaks
            if getattr(peak, "intensity", 0.0) >= 5.0 and 5.0 <= getattr(peak, "two_theta", 0.0) <= 120.0
        ]
        strong_peaks = sorted(strong_peaks, key=lambda peak: peak.intensity, reverse=True)[:35]
        wavelength = radiation_lines_from_wavelength(
            getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH
        )[0][0]
        pairs = []
        for peak in strong_peaks:
            calc_tt = float(peak.two_theta)
            nearest_index = int(np.argmin(np.abs(observed_positions - calc_tt)))
            obs_tt = float(observed_positions[nearest_index])
            delta = obs_tt - calc_tt
            if abs(delta) > 0.45:
                continue
            pairs.append((peak, obs_tt))
        total_peaks = len(strong_peaks)
        if len(pairs) < 3:
            return PhaseAlignmentEstimate(matched_peaks=len(pairs), total_peaks=total_peaks, status="weak")
        residuals = []
        weights = []
        for peak, obs_tt in pairs:
            residuals.append(obs_tt - float(peak.two_theta))
            weights.append(max(float(getattr(peak, "intensity", 1.0)), 1.0))
        residuals = np.asarray(residuals, dtype=float)
        weights = np.asarray(weights, dtype=float)
        best_zero = float(np.average(residuals, weights=weights))
        centered = residuals - best_zero
        best_score = float(np.average(np.abs(centered), weights=weights))
        if not np.isfinite(best_score):
            return PhaseAlignmentEstimate(matched_peaks=len(pairs), total_peaks=total_peaks, status="weak")

        matched_fraction = len(pairs) / max(total_peaks, 1)
        if best_score > 0.18 or matched_fraction < 0.18:
            return PhaseAlignmentEstimate(
                matched_peaks=len(pairs),
                total_peaks=total_peaks,
                score=best_score,
                status="weak",
            )
        status = "good" if best_score <= 0.08 and matched_fraction >= 0.3 else "ok"
        return PhaseAlignmentEstimate(
            zero_shift=float(np.clip(best_zero, -0.5, 0.5)),
            matched_peaks=len(pairs),
            total_peaks=total_peaks,
            score=best_score,
            status=f"{status} shift-only",
        )

    def _peak_probability_from_alignment(self, alignment: PhaseAlignmentEstimate) -> float:
        if alignment.total_peaks <= 0:
            return 0.0
        matched_fraction = alignment.matched_peaks / max(alignment.total_peaks, 1)
        residual_penalty = 1.0
        if alignment.score > 0:
            residual_penalty = max(0.15, 1.0 - min(alignment.score / 0.45, 1.0))
        enough_peaks_factor = min(alignment.matched_peaks / 8.0, 1.0)
        return float(np.clip(100.0 * matched_fraction * residual_penalty * enough_peaks_factor, 0.0, 100.0))

    def _peak_presence_probability(self, peaks, observed_x: np.ndarray, corrected_y: np.ndarray, structure) -> float:
        observed_records = self._observed_peak_records(observed_x, corrected_y, limit=24)
        if not observed_records or not peaks:
            return 0.0
        observed_positions = np.asarray([position for position, _height in observed_records], dtype=float)
        strong_calc = [
            peak for peak in peaks
            if getattr(peak, "intensity", 0.0) >= 2.0 and 5.0 <= getattr(peak, "two_theta", 0.0) <= 120.0
        ]
        strong_calc = sorted(strong_calc, key=lambda peak: float(getattr(peak, "intensity", 0.0)), reverse=True)[:45]
        if not strong_calc:
            return 0.0
        alignment = self._estimate_phase_alignment(strong_calc, observed_positions, structure)
        zero_shift = alignment.zero_shift if alignment.matched_peaks >= 3 else 0.0
        calc_positions = np.asarray([float(peak.two_theta) + zero_shift for peak in strong_calc], dtype=float)
        calc_intensities = np.asarray([max(float(getattr(peak, "intensity", 0.0)), 1.0) for peak in strong_calc], dtype=float)

        tolerance = 0.42
        observed_weighted = 0.0
        observed_total = 0.0
        observed_matches = 0
        for obs_position, obs_height in observed_records[:18]:
            weight = max(obs_height, 1.0) ** 0.65
            observed_total += weight
            deltas = np.abs(calc_positions - obs_position)
            nearest = float(np.min(deltas)) if len(deltas) else 999.0
            if nearest <= tolerance:
                quality = max(0.0, 1.0 - nearest / tolerance)
                observed_weighted += weight * (0.45 + 0.55 * quality)
                observed_matches += 1
        observed_coverage = observed_weighted / observed_total if observed_total > 0 else 0.0

        top_count = min(18, len(calc_positions))
        calc_weighted = 0.0
        calc_total = 0.0
        for calc_position, calc_intensity in zip(calc_positions[:top_count], calc_intensities[:top_count]):
            weight = max(calc_intensity, 1.0) ** 0.55
            calc_total += weight
            deltas = np.abs(observed_positions - calc_position)
            nearest = float(np.min(deltas)) if len(deltas) else 999.0
            if nearest <= tolerance:
                quality = max(0.0, 1.0 - nearest / tolerance)
                calc_weighted += weight * (0.45 + 0.55 * quality)
        calc_coverage = calc_weighted / calc_total if calc_total > 0 else 0.0

        signature_bonus = min(calc_coverage / 0.45, 1.0) if calc_coverage > 0 else 0.0
        probability = 100.0 * (0.20 * observed_coverage + 0.68 * calc_coverage + 0.12 * signature_bonus)
        top_calc_matches = 0
        for calc_position in calc_positions[:min(8, len(calc_positions))]:
            deltas = np.abs(observed_positions - calc_position)
            if len(deltas) and float(np.min(deltas)) <= tolerance:
                top_calc_matches += 1
        if top_calc_matches < 1:
            probability = min(probability, 25.0)
        elif top_calc_matches < 2:
            probability = min(probability, 55.0)
        if alignment.score > 0.22:
            probability *= max(0.75, 1.0 - min((alignment.score - 0.22) / 0.5, 0.25))
        return float(np.clip(probability, 0.0, 100.0))

    def _clear_probability_caches(self) -> None:
        self._observed_probability_cache = None
        self._candidate_probability_cache.clear()

    def _active_probability_context_key(self) -> tuple[object, ...]:
        pattern = self._active_pattern()
        pattern_id = getattr(pattern, "id", "") if pattern is not None else ""
        source_path = getattr(pattern, "source_path", "") if pattern is not None else ""
        wavelength = round(float(getattr(pattern, "wavelength", None) or CU_KA1_WAVELENGTH), 6)
        data_len = int(len(self.preprocessed_observed_data)) if self.preprocessed_observed_data is not None else -1
        return (pattern_id, source_path, wavelength, self.preprocessing_background_removed, data_len)

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
                scored_row[4] = f"{probability:.0f}%"
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
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC"}:
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
        return [replace(peak, two_theta=float(peak.two_theta) + zero_shift) for peak in peaks]

    def _estimate_background(self, x, y) -> np.ndarray:
        return estimate_background(x, y)

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

    def _estimate_candidate_corundum_iic(self, candidate: dict[str, str], x_grid: np.ndarray | None = None) -> float:
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            return self._estimate_structure_corundum_iic(structure, x_grid=x_grid)
        except Exception:
            return 0.0

    def _estimate_structure_corundum_iic(self, structure, x_grid: np.ndarray | None = None) -> float:
        wavelength = float(getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH)
        if x_grid is not None and len(x_grid):
            two_theta_min = float(np.nanmin(x_grid))
            two_theta_max = float(np.nanmax(x_grid))
        else:
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
        sample_total = self._raw_peak_total(sample_peaks)
        corundum_total = self._raw_peak_total(corundum_peaks)
        if sample_total <= 0 or corundum_total <= 0:
            return 0.0
        correction = self._corundum_absorption_correction(getattr(structure, "formula", ""))
        value = (sample_total / corundum_total) * correction
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
        structure = Structure.create("Corundum")
        structure.formula = "Al2O3"
        structure.space_group = "R -3 c"
        structure.cell = CellParameters(a=4.759, b=4.759, c=12.991, alpha=90.0, beta=90.0, gamma=120.0)
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
            AtomSite(label="O", element="O", x=0.306, y=0.0, z=0.25, occupancy=1.0),
        ]
        return structure

    def _raw_peak_total(self, peaks) -> float:
        return float(
            sum(max(float(getattr(peak, "raw_intensity", 0.0) or getattr(peak, "intensity", 0.0)), 0.0) for peak in peaks)
        )

    def _update_match_table(self) -> None:
        rows = []
        for row, candidate in enumerate(self.match_candidates):
            key = self._candidate_key(candidate)
            rows.append([
                self._phase_color(candidate, row),
                self._phase_legend_label(candidate),
                self.match_alignment_scores.get(key, ""),
                f"{self.match_quantities.get(key, 0.0):.1f}",
                f"{self.match_iic.get(key, 0.0):.3g}",
            ])
        self.match_table.set_rows(rows)

    def _phase_color(self, candidate: dict[str, str], index: int) -> str:
        palette = ["#d93025", "#1a73e8", "#188038", "#f9ab00", "#8e24aa", "#7b1fa2"]
        color = candidate.get("_Color", "")
        if not QColor(color).isValid():
            color = palette[index % len(palette)]
            candidate["_Color"] = color
        return color

    def _calculate_candidate_overlay(self, candidate: dict[str, str], show_errors: bool) -> None:
        entry_id = candidate.get("Entry", "")
        view_range = self._plot_view_range()
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            self._calculate_structure_overlay(structure, preview=True)
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
            y = np.asarray(data[:, 1], dtype=float)
            if observed is not None and len(observed):
                observed_max = max(float(np.nanmax(observed[:, 1])), 1.0)
                y = scale_profile_to_reference(y, observed_max * 0.92)
            self._clear_calculated_overlay()
            label = self._phase_legend_label(candidate)
            item = plot_profile(
                self.match_plot,
                np.asarray(data[:, 0], dtype=float),
                y,
                "#1a73e8",
                f"RRUFF reference {label}",
                width=1.7,
            )
            self.plot_layers["calculated_profile"].append(item)
            self.match_plot.setTitle(f"RRUFF reference overlay: {label}", color="#111111", size="13pt")
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
            if observed is not None and len(observed):
                x_grid = np.asarray(observed[:, 0], dtype=float)
                active_plot_context = self._active_pattern_plot_context()
                active_plot_offset = float(active_plot_context.get("offset", 0.0))
                baseline_value = float(np.nanmin(observed[:, 1])) + active_plot_offset
                top_value = float(np.nanmax(observed[:, 1])) + active_plot_offset
                height = max(top_value - baseline_value, float(active_plot_context.get("height", 0.0)), 1.0)
            else:
                x_grid = np.linspace(5.0, 120.0, 5000)
                baseline_value = 0.0
                height = 100.0
            self._clear_preview_overlay()
            baseline = np.full_like(x_grid, baseline_value, dtype=float)
            label = self._phase_legend_label(candidate)
            stick_item = plot_peak_intensity_sticks(
                self.match_plot,
                peaks,
                "#1a73e8",
                x_grid,
                baseline,
                height,
                f"PDF-2 reference {label}",
                width=3.0,
            )
            self.plot_layers["preview_peak_positions"].append(stick_item)
            hkl_peaks = [peak for peak in peaks if getattr(peak, "h", "") or getattr(peak, "k", "") or getattr(peak, "l", "")]
            if self.show_hkl_labels and hkl_peaks:
                hkl_items = add_hkl_labels(
                    self.match_plot,
                    hkl_peaks,
                    "#1a73e8",
                    baseline_value,
                    height,
                    limit=18,
                    above_peaks=True,
                )
                self.plot_layers["preview_hkl"].extend(hkl_items)
            self.match_plot.setTitle(
                f"PDF-2 peak preview for {label} ({len(peaks)} lines)",
                color="#111111",
                size="13pt",
            )
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
        x_grid = None
        observed_ymax = None
        observed_ymin = None
        observed_peak_positions = np.array([], dtype=float)
        background = None
        profile_fwhm = 0.18
        observed = self._active_observed_data()
        if observed is not None:
            try:
                x_grid = observed[:, 0]
                observed_ymin = float(np.nanmin(observed[:, 1]))
                observed_ymax = float(np.nanmax(observed[:, 1]))
                background = self._estimate_background(observed[:, 0], observed[:, 1])
                corrected = np.clip(observed[:, 1] - background, 0.0, None)
                observed_peak_positions = self._observed_peak_positions(observed[:, 0], corrected)
                profile_fwhm = self._estimate_profile_fwhm(observed[:, 0], corrected)
            except Exception:
                x_grid = None
        if x_grid is None:
            x_grid = np.linspace(5.0, 120.0, 5000)
        if background is None:
            background = np.zeros_like(x_grid)
        x, y, peaks = calculate_profile_for_structure(
            self.calculated_pattern_service,
            structure,
            x_grid,
            fwhm=profile_fwhm,
        )
        alignment = self._estimate_phase_alignment(peaks, observed_peak_positions, structure)
        peaks = self._shift_overlay_peaks(peaks, alignment.zero_shift)
        wavelength = getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH
        x, y = calculated_profile_from_peaks(peaks, x_grid, fwhm=profile_fwhm, wavelength=wavelength)
        if observed_ymax is not None:
            baseline = float(np.nanpercentile(background, 50))
            y = scale_profile_to_reference(y, max(observed_ymax - baseline, 1.0))
            if not preview:
                active_plot_offset = float(self._active_pattern_plot_context().get("offset", 0.0))
                background_item = plot_profile(
                    self.match_plot,
                    x,
                    background + active_plot_offset,
                    "#9aa0a6",
                    "background",
                    width=0.8,
                )
                self.plot_layers["calculated_profile"].append(background_item)
        else:
            y = scale_profile_to_reference(y, 100.0)
        color = "#1a73e8" if preview else "#d93025"
        active_plot_context = self._active_pattern_plot_context()
        active_plot_offset = float(active_plot_context.get("offset", 0.0))
        marker_top = (
            observed_ymax + active_plot_offset
            if observed_ymax is not None else float(np.nanmax(y) if np.nanmax(y) > 0 else 100.0)
        )
        marker_bottom = (
            observed_ymin + active_plot_offset
            if observed_ymin is not None else float(np.nanmin(background) + active_plot_offset)
        )
        y_span = max(marker_top - marker_bottom, float(active_plot_context.get("height", 0.0)), 1.0)
        if preview:
            preview_baseline = np.full_like(x_grid, marker_bottom, dtype=float)
            preview_height = y_span
            stick_item = plot_peak_intensity_sticks(
                self.match_plot,
                peaks,
                color,
                x_grid,
                preview_baseline,
                preview_height,
                f"preview peaks {structure.name}",
                width=3.0,
            )
            self.plot_layers["preview_peak_positions"].append(stick_item)
            if self.show_hkl_labels:
                hkl_items = add_hkl_labels(
                    self.match_plot,
                    peaks,
                    color,
                    marker_bottom,
                    preview_height,
                    limit=18,
                    above_peaks=True,
                )
                self.plot_layers["preview_hkl"].extend(hkl_items)
            self.match_plot.setTitle(
                f"Phase Finder: peak preview for {structure.name} ({len(peaks)} peaks, {alignment.status} {alignment.matched_peaks}/{alignment.total_peaks})",
                color="#111111",
                size="13pt",
            )
            return
        if not preview:
            calc_item = plot_profile(
                self.match_plot,
                x,
                y + background + active_plot_offset,
                color,
                f"calculated total {structure.name}",
                width=1.8,
            )
            self.plot_layers["calculated_profile"].append(calc_item)
        lane_height = y_span * (0.045 if observed is not None else 0.032)
        lane_baseline = marker_bottom - y_span * (0.13 if observed is not None else 0.18)
        if not self.show_all_selected_patterns:
            lane_items = plot_phase_marker_lane(
                self.match_plot,
                peaks,
                color,
                lane_baseline,
                lane_height,
                None,
                float(np.nanmin(x) + (np.nanmax(x) - np.nanmin(x)) * 0.005),
            )
            self.plot_layers["preview_peak_positions" if preview else "peak_positions"].extend(lane_items)
        if not preview and observed is not None and len(observed_peak_positions):
            self._add_peak_residual_links(
                peaks,
                np.asarray(observed[:, 0], dtype=float),
                np.asarray(observed[:, 1], dtype=float),
                observed_peak_positions,
                max_delta=0.45,
                limit=36,
                layer="peak_links",
            )
        if self.show_hkl_labels and not self.show_all_selected_patterns:
            hkl_items = add_hkl_labels(
                self.match_plot,
                peaks,
                color,
                lane_baseline - lane_height * 0.2,
                lane_height,
                limit=18,
            )
            self.plot_layers["preview_hkl" if preview else "hkl"].extend(hkl_items)
        self.match_plot.setTitle(
            f"Phase Finder: calculated overlay for {structure.name} ({len(peaks)} peaks, FWHM {profile_fwhm:.3g}, {alignment.status} {alignment.matched_peaks}/{alignment.total_peaks})",
            color="#111111",
            size="13pt",
        )

    def _database_tab(self) -> QWidget:
        mp_status = self.materials_project.status()
        ccdc_status = self.ccdc.status()
        rruff_row = self.rruff.status_row()
        match_pdf2_row = self._match_pdf2_status_row()
        rows = [
            self._database_summary_row(self._user_phase_library_status_row()),
            [
                "COD online",
                "optional",
                "download CIF to user library",
                "crystallography.net/cod",
            ],
            [
                "COD local/bulk",
                "optional",
                "index downloaded COD CIF folder/archive",
                str(self.local_phase_cache.root),
            ],
            self._database_summary_row(rruff_row),
            match_pdf2_row,
            [
                "CCDC / CSD",
                "yes" if ccdc_status.configured else "not configured",
                ccdc_status.label,
                "CSD Python API / ccdc.cam.ac.uk",
            ],
        ]
        rows.append(
            [
                "Materials Project",
                "yes" if mp_status.configured else "not configured",
                mp_status.label,
                "user API key",
            ]
        )
        source_states = {
            "sources/user_library": bool(self.settings.value("sources/user_library", True, type=bool)),
            "sources/cod_local": bool(self.settings.value("sources/cod_local", True, type=bool)),
            "sources/cod_online": bool(self.settings.value("sources/cod_online", True, type=bool)),
            "sources/rruff": bool(self.settings.value("sources/rruff", False, type=bool)),
            "sources/match_pdf2": bool(
                self.settings.value("sources/match_pdf2", self.match_pdf2.is_configured(), type=bool)
            ),
        }
        self.database_panel = DatabasePanelWidget(
            rows,
            source_states,
            bool(self.settings.value("materials_project/enabled", False, type=bool)),
            self._materials_project_status_text(),
            self.materials_project.api_key,
        )
        self.database_panel.sourceToggled.connect(self._set_source_enabled)
        self.database_panel.materialsProjectToggled.connect(self._set_materials_project_enabled)
        self.database_panel.saveMaterialsProjectRequested.connect(self._save_materials_project_settings)
        self.database_panel.rebuildUserIndexRequested.connect(self._build_local_phase_cache_index)
        self.database_panel.clearUserLibraryRequested.connect(self._clear_user_phase_library)
        self.database_panel.indexCodFolderRequested.connect(self._index_cod_cif_folder)
        self.database_panel.indexCodZipRequested.connect(self._index_cod_zip_archive)
        self.database_panel.downloadCodArchiveRequested.connect(self._download_cod_archive_from_url)
        self.database_panel.clearCodRequested.connect(self._clear_cod_cache)
        self.database_panel.updateRruffRequested.connect(self._update_rruff_database)
        self.database_panel.clearRruffRequested.connect(self._clear_rruff_database)
        self.database_panel.chooseMatchPdf2FolderRequested.connect(self._choose_match_pdf2_folder)
        self.database_panel.refreshMatchPdf2Requested.connect(self._refresh_match_pdf2_database)
        self.database_panel.clearMatchPdf2Requested.connect(self._clear_match_pdf2_database)
        self.database_panel.clearMaterialsProjectRequested.connect(self._clear_materials_project_cache)
        return self.database_panel

    def _show_database_settings_tab(self) -> None:
        for index in range(self.right_tabs.count()):
            if self.right_tabs.tabText(index) == "Databases":
                self.right_tabs.setCurrentIndex(index)
                return

    def _materials_project_status_text(self) -> str:
        status = self.materials_project.status()
        enabled = self.settings.value("materials_project/enabled", False, type=bool)
        enabled_text = "enabled" if enabled else "disabled"
        return f"Materials Project: {status.label}; search {enabled_text}."

    def _start_match_pdf2_preload(self) -> None:
        if not self.match_pdf2.is_configured():
            return
        if not self._source_enabled("sources/match_pdf2", True):
            return

        def preload() -> None:
            try:
                self.match_pdf2.refresh()
            except Exception:
                pass

        threading.Thread(target=preload, name="xrd-match-pdf2-preload", daemon=True).start()

    def _set_source_enabled(self, setting_key: str, checked: bool) -> None:
        self.settings.setValue(setting_key, checked)
        if self.database_panel is not None:
            self.database_panel.set_source_checked(setting_key, checked)
        if setting_key == "sources/match_pdf2" and checked:
            self._start_match_pdf2_preload()

    def _set_materials_project_enabled(self, checked: bool) -> None:
        self.settings.setValue("materials_project/enabled", checked)
        if self.database_panel is not None:
            self.database_panel.set_materials_project_status(self._materials_project_status_text())

    def _save_materials_project_settings(self) -> None:
        api_key = self.database_panel.api_key() if self.database_panel is not None else ""
        enabled = self.database_panel.materials_project_enabled() if self.database_panel is not None else False
        self.settings.setValue("materials_project/api_key", api_key)
        self.settings.setValue("materials_project/enabled", enabled)
        self.materials_project = MaterialsProjectService(api_key)
        self.candidate_search_service.materials_project = self.materials_project
        if self.database_panel is not None:
            self.database_panel.set_materials_project_status(self._materials_project_status_text())
        self._refresh_materials_project_database_row()

    def _refresh_materials_project_database_row(self) -> None:
        if self.database_panel is None:
            return
        status = self.materials_project.status()
        self.database_panel.update_row(
            "Materials Project",
            [
                "Materials Project",
                "yes" if status.configured else "not configured",
                status.label,
                "user API key",
            ],
        )

    def _refresh_database_rows(self) -> None:
        if self.database_panel is None:
            return
        replacements = {
            "User phase library": self._database_summary_row(self._user_phase_library_status_row()),
            "RRUFF powder": self._database_summary_row(self.rruff.status_row()),
            "PDF-2": self._match_pdf2_status_row(),
        }
        for source_name, values in replacements.items():
            self.database_panel.update_row(source_name, values)
        self._refresh_materials_project_database_row()

    def _user_phase_library_status_row(self) -> list[str]:
        local_row = self.local_phase_cache.status_row()
        return [
            "User phase library",
            local_row[1],
            local_row[2],
            local_row[3],
            local_row[4],
            "sqlite+cif",
            local_row[6],
        ]

    def _database_summary_row(self, row: list[str]) -> list[str]:
        source = row[0] if len(row) > 0 else ""
        state = row[1] if len(row) > 1 else ""
        label = row[2] if len(row) > 2 else ""
        files = row[3] if len(row) > 3 else ""
        size = row[4] if len(row) > 4 else ""
        location = row[6] if len(row) > 6 else (row[3] if len(row) > 3 else "")
        details = label
        if files or size:
            suffix = ", ".join(part for part in [f"{files} files" if files else "", f"{size} MB" if size else ""] if part)
            details = f"{label} ({suffix})" if label else suffix
        return [source, state, details, location]

    def _match_pdf2_status_row(self) -> list[str]:
        status = self.match_pdf2.status()
        return [
            "PDF-2",
            "yes" if status.configured else "not configured",
            status.label,
            str(status.root),
        ]

    def _build_local_phase_cache_index(self) -> None:
        try:
            count = self.local_phase_cache.build_index()
        except Exception as exc:
            QMessageBox.warning(self, "Build local index failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Build local index", f"Indexed {count} saved CIF files.")

    def _confirm_clear_database(self, title: str, database_name: str) -> bool:
        response = QMessageBox.warning(
            self,
            title,
            f"This will permanently delete local data for {database_name}.\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return response == QMessageBox.StandardButton.Yes

    def _clear_user_phase_library(self) -> None:
        if not self._confirm_clear_database("Clear user phase library", "the user phase library"):
            return
        try:
            self.local_phase_cache.clear_user_library()
            self.settings.setValue("sources/user_library", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/user_library", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear user phase library failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear user phase library", "User phase library cache was cleared.")

    def _index_cod_cif_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select COD CIF folder", str(Path.home()))
        if not folder:
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self.local_phase_cache.index_cif_folder(folder, source="COD")
        except Exception as exc:
            QMessageBox.warning(self, "Index COD folder failed", str(exc))
            return
        finally:
            self.unsetCursor()
        self._refresh_database_rows()
        QMessageBox.information(self, "Index COD folder", f"Indexed {count} COD CIF files.")

    def _index_cod_zip_archive(self) -> None:
        archive_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Select COD ZIP archive",
            str(Path.home()),
            "ZIP archive (*.zip);;All files (*.*)",
        )
        if not archive_path:
            return
        target_root = self.local_phase_cache.root / "cod_bulk_cif"
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self._extract_and_index_cif_zip(Path(archive_path), target_root, source="COD")
        except Exception as exc:
            QMessageBox.warning(self, "Index COD ZIP failed", str(exc))
            return
        finally:
            self.unsetCursor()
        self._refresh_database_rows()
        QMessageBox.information(self, "Index COD ZIP", f"Indexed {count} COD CIF files.")

    def _download_cod_archive_from_url(self) -> None:
        url, ok = QInputDialog.getText(
            self,
            "Download COD archive",
            "COD ZIP archive URL:",
        )
        if not ok or not url.strip():
            return
        output_dir = self.local_phase_cache.root / "downloads"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / Path(url.strip().rstrip("/")).name
        if output_path.suffix.lower() != ".zip":
            output_path = output_path.with_suffix(".zip")
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            with urlopen(url.strip(), timeout=300) as response:
                with output_path.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
        except Exception as exc:
            QMessageBox.warning(self, "Download COD archive failed", str(exc))
            return
        finally:
            self.unsetCursor()
        QMessageBox.information(self, "Download COD archive", f"Saved archive:\n{output_path}")

    def _clear_cod_cache(self) -> None:
        if not self._confirm_clear_database("Clear COD local/bulk", "COD local/bulk"):
            return
        try:
            self.local_phase_cache.clear_cod_cache()
            self.settings.setValue("sources/cod_local", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/cod_local", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear COD local/bulk failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear COD local/bulk", "COD local cache was cleared.")

    def _extract_and_index_cif_zip(self, archive_path: Path, target_root: Path, source: str) -> int:
        target_root.mkdir(parents=True, exist_ok=True)
        count = 0
        with ZipFile(archive_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    continue
                if member_path.suffix.lower() != ".cif":
                    continue
                target_path = target_root / member_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source_handle, target_path.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)
                self.local_phase_cache.index_cif(target_path, source=source, entry_id=target_path.stem)
                count += 1
        return count

    def _update_rruff_database(self) -> None:
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self.rruff.update_powder_database(RRUFF_POWDER_XY_PROCESSED_URL, remove_archive=True)
            self.settings.setValue("sources/rruff", True)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/rruff", True)
        except Exception as exc:
            QMessageBox.warning(self, "Update RRUFF failed", str(exc))
            return
        finally:
            self.unsetCursor()
        self._refresh_database_rows()
        QMessageBox.information(self, "Update RRUFF", f"Updated and indexed {count} RRUFF reference patterns.")

    def _clear_rruff_database(self) -> None:
        if not self._confirm_clear_database("Clear RRUFF", "RRUFF"):
            return
        try:
            self.rruff.clear()
            self.settings.setValue("sources/rruff", False)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/rruff", False)
        except Exception as exc:
            QMessageBox.warning(self, "Clear RRUFF failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear RRUFF", "RRUFF local data was cleared and disabled for search.")

    def _choose_match_pdf2_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select PDF-2 folder",
            str(self.match_pdf2.root if self.match_pdf2.root.exists() else Path.home()),
        )
        if not folder:
            return
        selected_root = Path(folder)
        if not (selected_root / "summary.dat").exists():
            QMessageBox.warning(
                self,
                "Select PDF-2 folder",
                "The selected folder does not contain summary.dat.\n\nSelect a PDF-2 folder that contains summary.dat.",
            )
            return
        self.match_pdf2.set_root(selected_root)
        self.settings.setValue("match_pdf2/root", str(selected_root))
        self.settings.setValue("sources/match_pdf2", True)
        if self.database_panel is not None:
            self.database_panel.set_source_checked("sources/match_pdf2", True)
        self._refresh_database_rows()
        self._start_match_pdf2_preload()
        QMessageBox.information(self, "Select PDF-2 folder", f"PDF-2 library selected:\n{selected_root}")

    def _refresh_match_pdf2_database(self) -> None:
        if not self.match_pdf2.is_configured():
            QMessageBox.warning(
                self,
                "Refresh PDF-2 failed",
                "PDF-2 is not configured. Choose the folder that contains summary.dat first.",
            )
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            count = self.match_pdf2.refresh()
            self.settings.setValue("sources/match_pdf2", True)
            if self.database_panel is not None:
                self.database_panel.set_source_checked("sources/match_pdf2", True)
        except Exception as exc:
            QMessageBox.warning(self, "Refresh PDF-2 failed", str(exc))
            return
        finally:
            self.unsetCursor()
        self._refresh_database_rows()
        QMessageBox.information(self, "Refresh PDF-2", f"Loaded {count} PDF-2 cards.")

    def _clear_match_pdf2_database(self) -> None:
        response = QMessageBox.warning(
            self,
            "Clear PDF-2",
            "This will clear the loaded PDF-2 card cache and disable it for search.\n\n"
            "The installed Match files in Program Files will not be deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        self.match_pdf2.clear()
        self.settings.setValue("sources/match_pdf2", False)
        if self.database_panel is not None:
            self.database_panel.set_source_checked("sources/match_pdf2", False)
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear PDF-2", "PDF-2 was cleared from memory and disabled for search.")

    def _clear_materials_project_cache(self) -> None:
        if not self._confirm_clear_database("Clear Materials Project", "Materials Project cached structures"):
            return
        try:
            self.local_phase_cache.clear_materials_project_cache()
            self.settings.setValue("materials_project/enabled", False)
            if self.database_panel is not None:
                self.database_panel.set_materials_project_checked(False)
                self.database_panel.set_materials_project_status(self._materials_project_status_text())
        except Exception as exc:
            QMessageBox.warning(self, "Clear Materials Project failed", str(exc))
            return
        self._refresh_database_rows()
        QMessageBox.information(self, "Clear Materials Project", "Materials Project local cache was cleared.")

    def _search_pdf2_text(self) -> None:
        query = self.search_input.text().strip() if self.search_input is not None else ""
        if not query and self.name_input is not None:
            query = self.name_input.text().strip()
        if not query and self.formula_sum_input is not None:
            query = self.formula_sum_input.text().strip()
        if not query:
            self._set_candidate_rows([["", "", "", "Enter name, formula, DOI, or entry id", "", ""]])
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = self.candidate_search_service.search_text(query, self._candidate_search_options())
        finally:
            self.unsetCursor()
        if rows:
            self._set_candidate_rows(rows)
            return

        self._set_candidate_rows([["", "", "", f"No saved/COD/CCDC/MP entries found for: {query}", "", ""]])

    def _search_from_controls(self) -> None:
        ccdc_query = self.ccdc_doi_input.text().strip() if self.ccdc_doi_input is not None else ""
        if ccdc_query:
            if self.search_input is not None:
                self.search_input.setText(ccdc_query)
            self._search_pdf2_text()
            return
        if not self.selected_elements:
            self._search_pdf2_text()
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            rows = self.candidate_search_service.search_elements(
                list(self.selected_element_order),
                self._candidate_search_options(),
            )
        finally:
            self.unsetCursor()
        if self.search_input is not None and self.formula_sum_input is not None:
            self.search_input.setText(self.formula_sum_input.text().strip())
        if not rows:
            self._set_candidate_rows([["", "", "", "No entries for selected elements", "", ""]])
            return
        self._set_candidate_rows(rows)

    def _candidate_search_options(self) -> CandidateSearchOptions:
        return CandidateSearchOptions(
            local_sources=self._local_cache_sources(),
            excluded_elements=self._excluded_elements(),
            cod_online_enabled=self._cod_online_enabled(),
            rruff_enabled=self._rruff_enabled(),
            match_pdf2_enabled=self._match_pdf2_enabled(),
            materials_project_enabled=self._materials_project_enabled(),
            structural_data_enabled=self._structural_data_enabled(),
            reference_patterns_enabled=self._reference_patterns_enabled(),
            material_class_allowed=self._material_class_allowed,
        )

    def _materials_project_enabled(self) -> bool:
        return (
            self._structural_data_enabled()
            and bool(self.settings.value("materials_project/enabled", False, type=bool))
            and self.materials_project.status().configured
        )

    def _local_cache_sources(self) -> list[str]:
        sources = []
        if self._source_enabled("sources/user_library", True):
            sources.extend(["USER", "CCDC", "COD"])
        if self._source_enabled("sources/cod_local", True):
            sources.append("COD")
        if self._materials_project_enabled():
            sources.append("MP")
        return list(dict.fromkeys(sources))

    def _cod_online_enabled(self) -> bool:
        return self._structural_data_enabled() and self._source_enabled("sources/cod_online", True)

    def _rruff_enabled(self) -> bool:
        return self._reference_patterns_enabled() and self._source_enabled("sources/rruff", False)

    def _match_pdf2_enabled(self) -> bool:
        return self._source_enabled("sources/match_pdf2", self.match_pdf2.is_configured()) and self.match_pdf2.is_configured()

    def _structural_data_enabled(self) -> bool:
        return self.structural_data_checkbox is None or self.structural_data_checkbox.isChecked()

    def _reference_patterns_enabled(self) -> bool:
        return self.reference_patterns_checkbox is None or self.reference_patterns_checkbox.isChecked()

    def _source_enabled(self, setting_key: str, default: bool) -> bool:
        return bool(self.settings.value(setting_key, default, type=bool))

    def _material_class_allowed(self, formula: str) -> bool:
        if self.inorganics_checkbox is None or self.organics_checkbox is None:
            return True
        allow_inorganic = self.inorganics_checkbox.isChecked()
        allow_organic = self.organics_checkbox.isChecked()
        if allow_inorganic and allow_organic:
            return True
        if not allow_inorganic and not allow_organic:
            return False
        elements = formula_elements(formula)
        is_organic = {"C", "H"}.issubset(elements)
        return (is_organic and allow_organic) or ((not is_organic) and allow_inorganic)

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
        rows = [normalize_candidate_row(row) for row in rows]
        rows = self._rank_candidate_rows_by_peak_probability(rows)
        self.candidate_table.set_rows(rows, normalize_candidate_row)
        if rows:
            self._update_compound_card(self._candidate_row_values(0))

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


class RefinementWindow(AnalysisWindow):
    def __init__(self, project: Project) -> None:
        super().__init__(project, "Refinement: Le Bail / Rietveld")

        plot = self._plot_widget("Refinement workspace: observed / calculated / difference / HKL")
        plot.setLabel("bottom", "2theta")
        plot.setLabel("left", "Intensity")
        pattern = self._active_pattern()
        if pattern is not None:
            try:
                data = load_xy(pattern.source_path)
                plot.plot(data[:, 0], data[:, 1], pen=pg.mkPen("#202124", width=1.0), name="Observed")
            except Exception:
                pass

        rows = [
            ["Mode", "Le Bail / Rietveld"],
            ["Patterns in project", str(len(project.patterns))],
            ["Phases in project", str(len(project.phases))],
            ["Refinements in project", str(len(project.refinements))],
        ]
        self.center_layout.addWidget(plot, 4)
        self.center_layout.addWidget(self._table(["Parameter", "Value"], rows), 1)

        self.right_tabs.addTab(self._workflow_tab(), "Main")
        self.right_tabs.addTab(self._layer_tab(), "View")
        self.right_tabs.addTab(self._settings_tab(), "Settings")

    def _workflow_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        mode = QComboBox()
        mode.addItems(["Le Bail", "Rietveld"])
        layout.addWidget(QLabel("Refinement mode"))
        layout.addWidget(mode)
        for label in ["Select pattern", "Select phases", "Background", "Profile", "Cell", "Atoms"]:
            layout.addWidget(QPushButton(label))
        layout.addStretch(1)
        return widget

    def _layer_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for label in ["Observed", "Calculated", "Difference", "Phase contributions", "HKL ticks"]:
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            layout.addWidget(checkbox)
        layout.addStretch(1)
        return widget

    def _settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        wavelength = QComboBox()
        wavelength.addItems(["Cu-Ka", "Co-Ka", "Mo-Ka", "Custom"])
        profile = QComboBox()
        profile.addItems(["Pseudo-Voigt", "Thompson-Cox-Hastings", "Gaussian"])
        layout.addRow("Wavelength", wavelength)
        layout.addRow("Profile", profile)
        return widget


class StructureWindow(AnalysisWindow):
    def __init__(self, project: Project) -> None:
        super().__init__(project, "Structure analysis")

        toolbar = QToolBar()
        for label in ["a", "b", "c", "a*", "b*", "c*", "Rotate", "Move", "Zoom", "Export"]:
            toolbar.addAction(label)

        viewport = QLabel("Structure viewport\n\nVESTA-like view for original and refined structures")
        viewport.setAlignment(Qt.AlignmentFlag.AlignCenter)
        viewport.setStyleSheet("background: white; border: 1px solid #cfd3d7; font-size: 24px;")

        rows = [[structure.name, structure.origin, structure.source_path] for structure in project.structures]
        if not rows:
            rows = [["No structures yet", "", "import CIF or run refinement later"]]

        self.center_layout.addWidget(toolbar)
        self.center_layout.addWidget(viewport, 4)
        self.center_layout.addWidget(self._table(["Structure", "Origin", "Source"], rows), 1)

        self.right_tabs.addTab(self._tools_tab(), "Tools")
        self.right_tabs.addTab(self._style_tab(), "Style")
        self.right_tabs.addTab(self._objects_tab(), "Objects")

    def _tools_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for label in ["Show models", "Only asymmetric unit", "Unit cell", "Bonds", "Polyhedra", "Labels"]:
            layout.addWidget(QCheckBox(label))
        layout.addWidget(QPushButton("Boundary"))
        layout.addWidget(QPushButton("Orientation"))
        layout.addStretch(1)
        return widget

    def _style_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for label in ["Ball-and-stick", "Space-filling", "Polyhedral", "Wireframe", "Stick"]:
            layout.addWidget(QCheckBox(label))
        layout.addStretch(1)
        return widget

    def _objects_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for item in self.project.structures:
            checkbox = QCheckBox(item.name)
            checkbox.setChecked(True)
            layout.addWidget(checkbox)
        layout.addStretch(1)
        return widget


class ThermalWindow(AnalysisWindow):
    def __init__(self, project: Project) -> None:
        super().__init__(project, "Thermal / composition analysis")

        plot = self._plot_widget("Thermal analysis: parameters, fits, alpha")
        plot.setLabel("bottom", "T or x")
        plot.setLabel("left", "Parameter / alpha")

        rows = [
            ["T / x", "a", "b", "c", "V", "alpha11", "alpha33", "alphaV"],
            ["", "", "", "", "", "", "", ""],
        ]
        self.center_layout.addWidget(plot, 4)
        self.center_layout.addWidget(
            self._table(["Variable", "a", "b", "c", "V", "alpha11", "alpha33", "alphaV"], rows[1:]),
            1,
        )

        self.right_tabs.addTab(self._main_tab(), "Main")
        self.right_tabs.addTab(self._view_tab(), "View")
        self.right_tabs.addTab(self._settings_tab(), "Settings")

    def _main_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QPushButton("Build series from refinements"))
        layout.addWidget(QPushButton("Paste table"))
        layout.addWidget(QPushButton("Calculate alpha"))
        layout.addWidget(QPushButton("Export figure/table"))
        layout.addStretch(1)
        return widget

    def _view_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        for label in ["a", "b", "c", "V", "alpha11", "alpha22", "alpha33", "alphaV", "Fit", "Residuals"]:
            checkbox = QCheckBox(label)
            checkbox.setChecked(label in {"a", "c", "V", "Fit"})
            layout.addWidget(checkbox)
        layout.addStretch(1)
        return widget

    def _settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        degree = QComboBox()
        degree.addItems(["1", "2", "3", "4", "5"])
        variable = QComboBox()
        variable.addItems(["Temperature", "Composition", "Pressure", "Time"])
        layout.addRow("Variable", variable)
        layout.addRow("Polynomial degree", degree)
        return widget
