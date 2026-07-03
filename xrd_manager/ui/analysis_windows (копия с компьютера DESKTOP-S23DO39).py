from __future__ import annotations

from dataclasses import dataclass, replace
import re
import shutil
from types import SimpleNamespace
from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
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

from xrd_manager.core.pattern import Pattern
from xrd_manager.core.project import Project
from xrd_manager.finder import FinderCandidateInput, FinderInput, FinderService
from xrd_manager.io.cif_loader import create_phase_from_cif
from xrd_manager.io.xy_loader import load_xy
from xrd_manager.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    CalculatedPatternService,
    calculated_profile_from_peaks,
    radiation_lines_from_wavelength,
)
from xrd_manager.services.ccdc_service import CcdcService, extract_doi
from xrd_manager.services.cod_online_service import CodOnlineService, formula_elements
from xrd_manager.services.local_phase_cache import LocalPhaseCache
from xrd_manager.services.materials_project_service import MaterialsProjectService
from xrd_manager.ui.pattern_plot_helpers import (
    add_hkl_labels,
    calculate_profile_for_structure,
    ensure_right_legend,
    estimate_background,
    estimate_profile_fwhm,
    plot_hkl_sticks,
    plot_hkl_ticks,
    plot_profile,
    scale_profile_to_reference,
)
from xrd_manager.ui.project_tree import ProjectTree
from xrd_manager.ui.xrd_plot import create_xrd_plot_widget


@dataclass(slots=True)
class PhaseAlignmentEstimate:
    zero_shift: float = 0.0
    cell_scale: float = 1.0
    matched_peaks: int = 0
    total_peaks: int = 0
    score: float = float("inf")
    status: str = "unmatched"


def _periodic_table_positions() -> list[tuple[str, int, int]]:
    return [
        ("H", 1, 1), ("He", 1, 18),
        ("Li", 2, 1), ("Be", 2, 2),
        ("B", 2, 13), ("C", 2, 14), ("N", 2, 15), ("O", 2, 16), ("F", 2, 17), ("Ne", 2, 18),
        ("Na", 3, 1), ("Mg", 3, 2),
        ("Al", 3, 13), ("Si", 3, 14), ("P", 3, 15), ("S", 3, 16), ("Cl", 3, 17), ("Ar", 3, 18),
        ("K", 4, 1), ("Ca", 4, 2), ("Sc", 4, 3), ("Ti", 4, 4), ("V", 4, 5),
        ("Cr", 4, 6), ("Mn", 4, 7), ("Fe", 4, 8), ("Co", 4, 9), ("Ni", 4, 10),
        ("Cu", 4, 11), ("Zn", 4, 12), ("Ga", 4, 13), ("Ge", 4, 14), ("As", 4, 15),
        ("Se", 4, 16), ("Br", 4, 17), ("Kr", 4, 18),
        ("Rb", 5, 1), ("Sr", 5, 2), ("Y", 5, 3), ("Zr", 5, 4), ("Nb", 5, 5),
        ("Mo", 5, 6), ("Tc", 5, 7), ("Ru", 5, 8), ("Rh", 5, 9), ("Pd", 5, 10),
        ("Ag", 5, 11), ("Cd", 5, 12), ("In", 5, 13), ("Sn", 5, 14), ("Sb", 5, 15),
        ("Te", 5, 16), ("I", 5, 17), ("Xe", 5, 18),
        ("Cs", 6, 1), ("Ba", 6, 2), ("La", 6, 3), ("Hf", 6, 4), ("Ta", 6, 5),
        ("W", 6, 6), ("Re", 6, 7), ("Os", 6, 8), ("Ir", 6, 9), ("Pt", 6, 10),
        ("Au", 6, 11), ("Hg", 6, 12), ("Tl", 6, 13), ("Pb", 6, 14), ("Bi", 6, 15),
        ("Po", 6, 16), ("At", 6, 17), ("Rn", 6, 18),
        ("Fr", 7, 1), ("Ra", 7, 2), ("Ac", 7, 3), ("Rf", 7, 4), ("Db", 7, 5),
        ("Sg", 7, 6), ("Bh", 7, 7), ("Hs", 7, 8), ("Mt", 7, 9), ("Ds", 7, 10),
        ("Rg", 7, 11), ("Cn", 7, 12), ("Nh", 7, 13), ("Fl", 7, 14), ("Mc", 7, 15),
        ("Lv", 7, 16), ("Ts", 7, 17), ("Og", 7, 18),
    ]


def _lanthanides() -> list[str]:
    return ["Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu"]


def _actinides() -> list[str]:
    return ["Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr"]


def _element_style(symbol: str) -> str:
    return _element_state_style("neutral")


def _element_state_style(state: str) -> str:
    palette = {
        "neutral": ("#24272b", "#4a525a", "#d8dde3"),
        "required": ("#1e7f73", "#40c4ad", "#eefcf9"),
        "excluded": ("#7c304f", "#d06491", "#fff4f8"),
        "any": ("#315f92", "#69a7e8", "#f3f9ff"),
        "optional": ("#765b22", "#d8b75a", "#fff8df"),
    }
    background, border, color = palette.get(state, palette["neutral"])
    return (
        "QPushButton {"
        f"background: {background}; border: 1px solid {border}; color: {color};"
        "padding: 0px; font-weight: 600; border-radius: 2px;"
        "}"
    )


def _element_sort_key(symbol: str) -> int:
    order = [item[0] for item in _periodic_table_positions()] + _lanthanides() + _actinides()
    try:
        return order.index(symbol)
    except ValueError:
        return len(order)


class ElementFilterButton(QPushButton):
    leftClicked = Signal(str)
    rightClicked = Signal(str)

    def __init__(self, symbol: str) -> None:
        super().__init__(symbol)
        self.symbol = symbol

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(self.symbol)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.leftClicked.emit(self.symbol)
            event.accept()
            return
        super().mousePressEvent(event)


class AnalysisWindow(QDialog):
    project_changed = Signal()

    def __init__(self, project: Project, title: str) -> None:
        super().__init__()
        self.project = project
        self.setWindowTitle(f"{title} - {project.name}")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.resize(1300, 820)

        self.tree = ProjectTree()
        self.tree.set_project(project)
        self.tree.object_open_requested.connect(self._open_project_object)
        self.tree.pattern_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())
        self.tree.phase_selection_changed.connect(lambda _ids: self._on_project_tree_selection_changed())

        self.sidebar = QWidget()
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(6)
        import_button = QPushButton("Import XRD / CIF")
        import_button.clicked.connect(self._import_scientific_files)
        sidebar_layout.addWidget(import_button)
        sidebar_layout.addWidget(self.tree, 1)

        self.center = QWidget()
        self.center_layout = QVBoxLayout(self.center)
        self.center_layout.setContentsMargins(6, 6, 6, 6)

        self.right_tabs = QTabWidget()
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

    def _import_scientific_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import XRD data or CIF structure",
            "",
            "XRD and structure files (*.xy *.txt *.dat *.csv *.xye *.cif);;XRD patterns (*.xy *.txt *.dat *.csv *.xye);;CIF structures (*.cif);;All files (*.*)",
        )
        if not paths:
            return

        imported = False
        errors: list[str] = []
        for path in paths:
            source = Path(path)
            suffix = source.suffix.lower()
            try:
                if suffix == ".cif":
                    phase, structure = create_phase_from_cif(source)
                    self.project.phases.append(phase)
                    self.project.structures.append(structure)
                else:
                    self.project.patterns.append(Pattern.create(name=source.stem, source_path=str(source)))
                imported = True
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")

        if imported:
            self.tree.set_project(self.project)
            self._on_project_tree_selection_changed()
            if hasattr(self, "_refresh_project_phase_candidates"):
                self._refresh_project_phase_candidates()
        if errors:
            QMessageBox.warning(self, "Import", "\n".join(errors[:5]))

    def _on_project_tree_selection_changed(self) -> None:
        pass

    def _active_pattern(self):
        checked = self.tree.checked_pattern_ids()
        if checked:
            for pattern in self.project.patterns:
                if pattern.id == checked[0]:
                    return pattern
        return self.project.patterns[0] if self.project.patterns else None

    def _plot_widget(self, title: str = "", xrd_navigation: bool = False) -> pg.PlotWidget:
        plot = create_xrd_plot_widget()
        if title:
            plot.setTitle(title, color="#111111", size="13pt")
        return plot

    def _table(self, headers: list[str], rows: list[list[str]]) -> QTableWidget:
        table = QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                table.setItem(row_index, col_index, QTableWidgetItem(value))
        table.resizeColumnsToContents()
        return table


class PhaseFinderWindow(AnalysisWindow):
    def __init__(self, project: Project) -> None:
        super().__init__(project, "Phase Finder")
        self.resize(1500, 850)
        self.right_tabs.setMinimumWidth(460)
        self._element_widgets: list[QWidget] = []
        self._element_buttons: dict[str, QPushButton] = {}
        self.element_states: dict[str, str] = {}
        self.selected_elements: set[str] = set()
        self.selected_element_order: list[str] = []
        self.exclude_all_other_elements = False
        self._last_formula_text = ""
        self.settings = QSettings("Xrdfinder", "Standalone")
        self.cod_online = CodOnlineService()
        self.ccdc = CcdcService()
        self.local_phase_cache = LocalPhaseCache()
        self.materials_project = MaterialsProjectService(
            str(self.settings.value("materials_project/api_key", "", type=str) or "")
        )
        self.calculated_pattern_service = CalculatedPatternService()
        self.finder_service = FinderService(self.calculated_pattern_service)
        self.search_input: QLineEdit | None = None
        self.name_input: QLineEdit | None = None
        self.elem_count_input: QLineEdit | None = None
        self.formula_sum_input: QLineEdit | None = None
        self.ccdc_doi_input: QLineEdit | None = None
        self.mp_api_key_input: QLineEdit | None = None
        self.mp_status_label: QLabel | None = None
        self.database_table: QTableWidget | None = None
        self.inorganics_checkbox: QCheckBox | None = None
        self.organics_checkbox: QCheckBox | None = None
        self.local_cache_checkbox: QCheckBox | None = None
        self.cod_online_checkbox: QCheckBox | None = None
        self.use_materials_project_checkbox: QCheckBox | None = None
        self.plot_layers: dict[str, list] = {
            "observed": [],
            "calculated_profile": [],
            "peak_positions": [],
            "hkl": [],
            "candidate_markers": [],
        }
        self.grid_visible = True
        self.legend_item = None
        self.active_overlay_entry_id: str | None = None
        self.match_candidates: list[dict[str, str]] = []
        self.match_structures: dict[str, object] = {}
        self.match_scales: dict[str, float] = {}
        self.match_quantities: dict[str, float] = {}
        self.match_iic: dict[str, float] = {}
        self.match_zero_shifts: dict[str, float] = {}
        self.match_cell_scales: dict[str, float] = {}
        self.match_alignment_scores: dict[str, str] = {}

        self.center_layout.addWidget(self._finder_action_bar())

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
        self.candidate_table = self._candidate_table(candidate_rows)
        self.match_table = self._match_table()
        candidate_panel = QWidget()
        candidate_layout = QVBoxLayout(candidate_panel)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.setSpacing(4)
        candidate_layout.addWidget(QLabel("Candidate list"))
        candidate_layout.addWidget(self.candidate_table, 1)
        self.center_layout.addWidget(candidate_panel, 1)

        self.right_tabs.addTab(self._composition_tab(), "Elements")
        self.right_tabs.addTab(self._simple_tab(["Use selected pattern", "Auto mark peaks", "Show candidates"]), "Peaks/Ranges")
        self.right_tabs.addTab(self._database_tab(), "References")
        self._apply_default_phase_filter()

    def _finder_action_bar(self) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        smooth_button = QPushButton("Smooth")
        smooth_button.setToolTip("Smooth observed XRD curve")
        smooth_button.clicked.connect(self._smooth_active_pattern_plot)
        background_button = QPushButton("Remove background")
        background_button.setToolTip("Estimate and subtract background")
        background_button.clicked.connect(self._subtract_active_background_plot)
        reset_button = QPushButton("Reset view")
        reset_button.clicked.connect(lambda: self.match_plot.autoRange() if hasattr(self, "match_plot") else None)

        layout.addWidget(smooth_button)
        layout.addWidget(background_button)
        layout.addStretch(1)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Formula / elements / phase name")
        self.search_input.returnPressed.connect(self._search_pdf2_text)
        layout.addWidget(self.search_input, 2)
        layout.addWidget(reset_button)
        return wrapper

    def _smooth_active_pattern_plot(self) -> None:
        data = self._active_observed_data()
        if data is None:
            return
        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)
        window = max(5, min(31, len(y) // 80 * 2 + 1))
        kernel = np.ones(window, dtype=float) / window
        smooth_y = np.convolve(y, kernel, mode="same")
        self._replace_observed_curve(x, smooth_y, "Observed smoothed")

    def _subtract_active_background_plot(self) -> None:
        data = self._active_observed_data()
        if data is None:
            return
        x = np.asarray(data[:, 0], dtype=float)
        y = np.asarray(data[:, 1], dtype=float)
        background = self._estimate_background(x, y)
        corrected = np.clip(y - background, 0.0, None)
        self._replace_observed_curve(x, corrected, "Observed - background")

    def _replace_observed_curve(self, x: np.ndarray, y: np.ndarray, name: str) -> None:
        for item in self.plot_layers.get("observed", []):
            self.match_plot.removeItem(item)
        self.plot_layers["observed"] = [
            self.match_plot.plot(x, y, pen=pg.mkPen("#202124", width=1.0), name=name)
        ]
        self.match_plot.setXRange(float(np.nanmin(x)), float(np.nanmax(x)), padding=0.02)
        self.match_plot.setYRange(float(np.nanmin(y)), float(np.nanmax(y)), padding=0.08)

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
        self._refresh_observed_pattern_plot()
        if self.match_candidates:
            self._recalculate_match_profile()
        elif self.active_overlay_entry_id:
            candidate = self._selected_candidate_row()
            if candidate is not None:
                self.active_overlay_entry_id = None
                self._calculate_candidate_overlay(candidate, show_errors=False)

    def _active_observed_data(self):
        pattern = self._active_pattern()
        if pattern is None:
            return None
        try:
            return load_xy(pattern.source_path)
        except Exception:
            return None

    def _refresh_observed_pattern_plot(self) -> None:
        for item in self.plot_layers.get("observed", []):
            self.match_plot.removeItem(item)
        self.plot_layers["observed"] = []
        data = self._active_observed_data()
        if data is None:
            return
        pattern = self._active_pattern()
        name = pattern.name if pattern is not None else "Observed"
        observed_item = self.match_plot.plot(
            data[:, 0],
            data[:, 1],
            pen=pg.mkPen("#202124", width=1.0),
            name=f"Observed: {name}",
        )
        self.plot_layers["observed"].append(observed_item)
        self.match_plot.setXRange(float(np.nanmin(data[:, 0])), float(np.nanmax(data[:, 0])), padding=0.02)
        self.match_plot.setYRange(float(np.nanmin(data[:, 1])), float(np.nanmax(data[:, 1])), padding=0.08)

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
        scale.currentTextChanged.connect(self._set_element_scale)
        top_row.addWidget(scale)
        outer_layout.addLayout(top_row)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(2)

        for group in range(1, 19):
            label = QLabel(str(group))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background: #202328; border: 1px solid #3d444d; color: #9aa4af;")
            label.setFixedSize(22, 18)
            self._element_widgets.append(label)
            grid.addWidget(label, 0, group)

        for period in range(1, 8):
            label = QLabel(f"P{period}")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("background: #202328; border: 1px solid #3d444d; color: #9aa4af;")
            label.setFixedSize(22, 18)
            self._element_widgets.append(label)
            grid.addWidget(label, period, 0)

        for symbol, period, group in _periodic_table_positions():
            button = ElementFilterButton(symbol)
            button.setFixedSize(22, 18)
            button.setStyleSheet(_element_state_style("excluded"))
            button.setToolTip(symbol)
            button.leftClicked.connect(self._toggle_required_element)
            button.rightClicked.connect(self._toggle_required_element)
            self._element_buttons[symbol] = button
            self._element_widgets.append(button)
            grid.addWidget(button, period, group)

        lanth_label = QLabel("L")
        lanth_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lanth_label.setStyleSheet("background: #202328; border: 1px solid #3d444d; color: #9aa4af;")
        lanth_label.setFixedSize(22, 18)
        act_label = QLabel("A")
        act_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        act_label.setStyleSheet("background: #202328; border: 1px solid #3d444d; color: #9aa4af;")
        act_label.setFixedSize(22, 18)
        self._element_widgets.extend([lanth_label, act_label])
        grid.addWidget(lanth_label, 9, 3)
        grid.addWidget(act_label, 10, 3)

        for index, symbol in enumerate(_lanthanides()):
            button = ElementFilterButton(symbol)
            button.setFixedSize(22, 18)
            button.setStyleSheet(_element_state_style("excluded"))
            button.setToolTip(symbol)
            button.leftClicked.connect(self._toggle_required_element)
            button.rightClicked.connect(self._toggle_required_element)
            self._element_buttons[symbol] = button
            self._element_widgets.append(button)
            grid.addWidget(button, 9, 4 + index)

        for index, symbol in enumerate(_actinides()):
            button = ElementFilterButton(symbol)
            button.setFixedSize(22, 18)
            button.setStyleSheet(_element_state_style("excluded"))
            button.setToolTip(symbol)
            button.leftClicked.connect(self._toggle_required_element)
            button.rightClicked.connect(self._toggle_required_element)
            self._element_buttons[symbol] = button
            self._element_widgets.append(button)
            grid.addWidget(button, 10, 4 + index)

        layout.addLayout(grid)
        panel.setMaximumHeight(230)
        outer_layout.addWidget(panel)

        self.name_input = QLineEdit()
        self.name_input.hide()
        self.elem_count_input = QLineEdit()
        self.elem_count_input.hide()
        self.formula_sum_input = QLineEdit()
        self.formula_sum_input.hide()
        self.element_gate_label = QLabel("Gate: none")
        outer_layout.addWidget(self.element_gate_label)
        self.ccdc_doi_input = QLineEdit()
        self.ccdc_doi_input.setPlaceholderText("CCDC DOI")
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
        self.local_cache_checkbox = QCheckBox("User library")
        self.local_cache_checkbox.setChecked(True)
        self.local_cache_checkbox.hide()
        self.cod_online_checkbox = QCheckBox("COD online")
        self.cod_online_checkbox.setChecked(True)
        self.cod_online_checkbox.hide()

        actions = QHBoxLayout()
        search_button = QPushButton("Find")
        search_button.clicked.connect(self._search_from_controls)
        reset_button = QPushButton("Reset table")
        reset_button.clicked.connect(self._reset_selected_elements)
        actions.addWidget(search_button)
        actions.addWidget(reset_button)
        outer_layout.addLayout(actions)
        outer_layout.addWidget(QLabel("Selected candidates"))
        outer_layout.addWidget(self.match_table, 1)
        return widget

    def _candidate_table(self, rows: list[list[str]]) -> QTableWidget:
        table = self._table(
            [
                "Source",
                "Entry",
                "Formula",
                "Phase",
                "I/Ic*",
                "Notes",
            ],
            rows,
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(190)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table.setAlternatingRowColors(True)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_candidate_context_menu)
        table.cellClicked.connect(lambda row, _column: self._preview_candidate_row(row))
        table.cellDoubleClicked.connect(lambda _row, _column: self._add_selected_candidate_to_match_list())
        return table

    def _match_table(self) -> QTableWidget:
        table = self._table(
            ["Color", "Formula", "Scale", "Quant. (%)", "I/Ic*"],
            [],
        )
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(190)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        table.setAlternatingRowColors(True)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_match_context_menu)
        return table

    def _show_candidate_context_menu(self, point) -> None:
        row = self.candidate_table.rowAt(point.y())
        if row >= 0:
            self.candidate_table.selectRow(row)
        menu = QMenu(self)
        menu.addAction("Add to working set", self._add_selected_candidate_to_match_list)
        menu.addAction("Calculate pattern overlay", self._calculate_selected_cif_overlay)
        menu.addAction("Export CIF...", self._export_selected_cif)
        menu.exec(self.candidate_table.viewport().mapToGlobal(point))

    def _show_match_context_menu(self, point) -> None:
        row = self.match_table.rowAt(point.y())
        if row >= 0:
            self.match_table.selectRow(row)
        menu = QMenu(self)
        menu.addAction("Recalculate selected profile", self._recalculate_match_profile)
        menu.addAction("Remove selected phase", self._remove_selected_match_candidate)
        menu.addAction("Clear working set", self._clear_match_list)
        menu.exec(self.match_table.viewport().mapToGlobal(point))

    def _show_plot_context_menu(self, point) -> None:
        menu = QMenu(self)
        menu.addAction("Export image...", self._export_plot_image)
        menu.addAction("Export selected CIF...", self._export_selected_cif)
        menu.addSeparator()
        menu.addAction("Full pattern", self._full_pattern_range)
        grid_action = menu.addAction("Grid")
        grid_action.setCheckable(True)
        grid_action.setChecked(self.grid_visible)
        grid_action.toggled.connect(self._set_grid_visible)
        legend_action = menu.addAction("Legend")
        legend_action.setCheckable(True)
        legend_action.setChecked(self.legend_item is not None)
        legend_action.toggled.connect(self._set_legend_visible)
        menu.addAction(self._layer_action("Observed profile", "observed"))
        menu.addAction(self._layer_action("Calculated profile", "calculated_profile"))
        menu.addAction(self._layer_action("Peak positions", "peak_positions"))
        menu.addAction(self._layer_action("Miller indices (hkl)", "hkl"))
        menu.addSeparator()
        menu.addAction("Hide calculated overlay", lambda: self._set_calculated_visible(False))
        menu.addAction("Show calculated overlay", lambda: self._set_calculated_visible(True))
        menu.addAction("Clear calculated overlay", self._clear_calculated_overlay)
        menu.exec(self.match_plot.mapToGlobal(point))

    def _export_plot_image(self) -> None:
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export image",
            "xrd_finder_plot.png",
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg)",
        )
        if not path:
            return
        if not re.search(r"\.(png|jpe?g)$", path, flags=re.IGNORECASE):
            path += ".png"
        if not self.match_plot.grab().save(path):
            QMessageBox.warning(self, "Export image", "Could not save current plot image.")

    def _export_selected_cif(self) -> None:
        candidate = self._selected_export_candidate()
        if candidate is None:
            QMessageBox.information(self, "Export CIF", "Select a candidate or a working phase first.")
            return
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
            default_name,
            "CIF structure (*.cif)",
        )
        if not path:
            return
        if not path.lower().endswith(".cif"):
            path += ".cif"
        try:
            shutil.copy2(source, path)
        except Exception as exc:
            QMessageBox.warning(self, "Export CIF", str(exc))

    def _selected_export_candidate(self) -> dict[str, str] | None:
        candidate = self._selected_candidate_row()
        if candidate is not None and self._candidate_source(candidate):
            return candidate
        row = self.match_table.currentRow()
        if 0 <= row < len(self.match_candidates):
            return self.match_candidates[row]
        return None

    def _layer_action(self, label: str, layer: str, checked: bool | None = None, enabled: bool = True):
        action = self._make_action(label)
        action.setCheckable(True)
        action.setEnabled(enabled)
        action.setChecked(self._layer_visible(layer) if checked is None else checked)
        if enabled:
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
        self._set_layer_visible("peak_positions", visible)
        self._set_layer_visible("hkl", visible)

    def _clear_calculated_overlay(self) -> None:
        for layer in ["calculated_profile", "peak_positions", "hkl"]:
            for item in self.plot_layers.get(layer, []):
                self.match_plot.removeItem(item)
            self.plot_layers[layer] = []
        self.active_overlay_entry_id = None

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

    def _full_pattern_range(self) -> None:
        data = self._active_observed_data()
        if data is not None:
            try:
                self.match_plot.setXRange(float(np.nanmin(data[:, 0])), float(np.nanmax(data[:, 0])), padding=0.02)
                self.match_plot.setYRange(float(np.nanmin(data[:, 1])), float(np.nanmax(data[:, 1])), padding=0.08)
                return
            except Exception:
                pass
        self.match_plot.enableAutoRange()

    def _selected_candidate_row(self) -> dict[str, str] | None:
        row = self.candidate_table.currentRow()
        if row < 0:
            return None
        return self._candidate_row_values(row)

    def _candidate_row_values(self, row: int) -> dict[str, str]:
        headers = [
            self.candidate_table.horizontalHeaderItem(column).text()
            for column in range(self.candidate_table.columnCount())
        ]
        values = {}
        for column, header in enumerate(headers):
            item = self.candidate_table.item(row, column)
            values[header] = item.text().strip() if item is not None else ""
        return values

    def _candidate_rows(self) -> list[dict[str, str]]:
        rows = []
        for row in range(self.candidate_table.rowCount()):
            candidate = self._candidate_row_values(row)
            if candidate.get("Entry") and self._candidate_source(candidate) in {"COD", "USER", "MP", "CCDC"}:
                rows.append(candidate)
        return rows

    def _preview_candidate_row(self, row: int) -> None:
        candidate = self._candidate_row_values(row)
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
        if source in {"COD", "USER", "CCDC"} and entry_id:
            cached_path = self.local_phase_cache.cif_path(source, entry_id)
            if cached_path is not None:
                return cached_path
            raise ValueError("CIF is not in the user phase library. Save or import it first.")
        if source == "MP" and entry_id:
            cached_path = self.local_phase_cache.cif_path("MP", entry_id)
            if cached_path is not None:
                return cached_path
            target_dir = self.local_phase_cache.root / "materials_project_cif"
            cif_path = self.materials_project.download_cif(entry_id, target_dir)
            self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=entry_id)
            return cif_path
        raise ValueError("Select a saved COD, CCDC, USER, or Materials Project row with an entry id.")

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
        self._calculate_candidate_overlay(candidate, show_errors=True)

    def _download_selected_candidate_to_cache(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Download CIF", "Select a COD or Materials Project row first.")
            return
        source = self._candidate_source(candidate)
        if source in {"COD", "USER", "CCDC"}:
            QMessageBox.information(self, "Download CIF", "This CIF is already in the user phase library.")
            return
        if source not in {"COD", "MP"} or not candidate.get("Entry"):
            QMessageBox.information(self, "Download CIF", "Only COD online or Materials Project rows can be saved to the user phase library.")
            return
        try:
            if source == "COD":
                entry = self._candidate_to_cod_entry(candidate)
                cif_path = self.local_phase_cache.download_cod_entry(entry, self.cod_online)
                saved_id = entry.cod_id
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
        from xrd_manager.services.cod_online_service import CodEntry

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
                self._recalculate_match_profile()
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
                self._recalculate_match_profile()
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
            self._recalculate_match_profile()
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

    def _recalculate_match_profile(self) -> None:
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
                )
            )
        except Exception as exc:
            QMessageBox.warning(self, "Finder calculation failed", str(exc))
            self._update_match_table()
            return

        x = np.asarray(result.pattern_x, dtype=float)
        background = np.asarray(result.background, dtype=float)
        calculated_total = np.asarray(result.calculated_total, dtype=float)
        observed_ymax = float(np.nanmax(result.pattern_y)) if result.pattern_y else 100.0
        colors = ["#d93025", "#1a73e8", "#188038", "#f9ab00", "#8e24aa", "#7b1fa2"]
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
            color = colors[index % len(colors)]
            profile = np.asarray(candidate_result.profile, dtype=float)
            self.match_scales[key] = float(candidate_result.scale)
            self.match_quantities[key] = float(candidate_result.quantity_percent)
            self.match_iic[key] = self._estimate_theoretical_iic(profile)
            self.match_zero_shifts[key] = float(result.global_zero_shift)
            self.match_cell_scales[key] = 1.0
            self.match_alignment_scores[key] = (
                f"{candidate_result.status} {candidate_result.matched_peaks}/{candidate_result.total_peaks}"
            )
            contribution_item = plot_profile(
                self.match_plot,
                x,
                background + profile,
                color,
                f"phase {self._candidate_phase_name(candidate) or candidate.get('Entry')}",
                width=1.5,
            )
            self.plot_layers["calculated_profile"].append(contribution_item)
            baseline = float(np.nanpercentile(background, 50))
            peak_scale = max(observed_ymax - baseline, observed_ymax, 1.0)
            tick_baseline = baseline - peak_scale * 0.04 * index
            tick_peaks = [
                SimpleNamespace(two_theta=float(peak_two_theta))
                for peak_two_theta in candidate_result.peak_two_theta
            ]
            tick_item = plot_hkl_ticks(self.match_plot, tick_peaks, color, tick_baseline, peak_scale)
            self.plot_layers["peak_positions"].append(tick_item)

        background_item = plot_profile(
            self.match_plot,
            x,
            background,
            "#9aa0a6",
            "background",
            width=1.2,
        )
        sum_item = plot_profile(
            self.match_plot,
            x,
            calculated_total,
            "#0b8043",
            "calculated total",
            width=1.9,
        )
        self.plot_layers["calculated_profile"].append(background_item)
        self.plot_layers["calculated_profile"].append(sum_item)
        self.match_plot.setTitle(
            f"Phase Finder: {len(result.candidates)} selected phase profile | "
            f"FWHM {result.fwhm:.3g} | zero {result.global_zero_shift:+.4f}",
            color="#111111",
            size="13pt",
        )
        self._update_match_table()

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
        prominence = max(float(np.nanmax(y)) * 0.025, float(np.nanstd(y)) * 3.0, 1.0)
        peak_indices, _properties = find_peaks(y, prominence=prominence, distance=max(3, len(y) // 900))
        if len(peak_indices) > 120:
            heights = y[peak_indices]
            keep = np.argsort(heights)[-120:]
            peak_indices = peak_indices[keep]
        return np.sort(np.asarray(x, dtype=float)[peak_indices])

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
        best_zero = 0.0
        best_scale = 1.0
        best_score = float("inf")
        allow_cell_scale = self._allows_isotropic_cell_scale(structure)
        cell_grid = np.linspace(0.992, 1.008, 81) if allow_cell_scale else np.array([1.0])
        for cell_scale in cell_grid:
            residuals = []
            weights = []
            for peak, obs_tt in pairs:
                shifted_tt = self._two_theta_for_scaled_d(peak.d, cell_scale, wavelength)
                if shifted_tt is None:
                    continue
                residuals.append(obs_tt - shifted_tt)
                weights.append(max(float(getattr(peak, "intensity", 1.0)), 1.0))
            if not residuals:
                continue
            residuals = np.asarray(residuals, dtype=float)
            weights = np.asarray(weights, dtype=float)
            zero_shift = float(np.average(residuals, weights=weights))
            centered = residuals - zero_shift
            score = float(np.average(np.abs(centered), weights=weights))
            if score < best_score:
                best_score = score
                best_zero = zero_shift
                best_scale = float(cell_scale)
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
        if not allow_cell_scale:
            status = f"{status} zero-only"
        return PhaseAlignmentEstimate(
            zero_shift=float(np.clip(best_zero, -0.5, 0.5)),
            cell_scale=float(np.clip(best_scale, 0.992, 1.008)) if allow_cell_scale else 1.0,
            matched_peaks=len(pairs),
            total_peaks=total_peaks,
            score=best_score,
            status=status,
        )

    def _allows_isotropic_cell_scale(self, structure) -> bool:
        cell = getattr(structure, "cell", None)
        if cell is None:
            return False
        lengths = [getattr(cell, name, None) for name in ("a", "b", "c")]
        angles = [getattr(cell, name, None) for name in ("alpha", "beta", "gamma")]
        if any(value is None for value in lengths + angles):
            return False
        lengths = [float(value) for value in lengths]
        angles = [float(value) for value in angles]
        mean_length = float(np.mean(lengths))
        if mean_length <= 0:
            return False
        cubic_lengths = (max(lengths) - min(lengths)) <= mean_length * 0.02
        right_angles = all(abs(angle - 90.0) <= 0.5 for angle in angles)
        return cubic_lengths and right_angles

    def _two_theta_for_scaled_d(self, d_spacing: float, cell_scale: float, wavelength: float) -> float | None:
        d_scaled = float(d_spacing) * float(cell_scale)
        if d_scaled <= 0:
            return None
        argument = wavelength / (2.0 * d_scaled)
        if not 0.0 < argument < 1.0:
            return None
        return float(np.rad2deg(2.0 * np.arcsin(argument)))

    def _adjust_peaks_for_alignment(self, peaks, zero_shift: float, cell_scale: float, structure):
        wavelength = radiation_lines_from_wavelength(
            getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH
        )[0][0]
        adjusted = []
        for peak in peaks:
            two_theta = self._two_theta_for_scaled_d(peak.d, cell_scale, wavelength)
            if two_theta is None:
                continue
            adjusted.append(replace(peak, d=float(peak.d) * cell_scale, two_theta=two_theta + zero_shift))
        return adjusted

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

    def _update_match_table(self) -> None:
        self.match_table.setRowCount(len(self.match_candidates))
        colors = ["red", "blue", "green", "orange", "purple", "violet"]
        for row, candidate in enumerate(self.match_candidates):
            key = self._candidate_key(candidate)
            values = [
                colors[row % len(colors)],
                candidate.get("Formula", ""),
                f"{self.match_scales.get(key, 0.0):.3g}",
                f"{self.match_quantities.get(key, 0.0):.1f}",
                f"{self.match_iic.get(key, 0.0):.3g}",
            ]
            for column, value in enumerate(values):
                self.match_table.setItem(row, column, QTableWidgetItem(value))
        self.match_table.resizeColumnsToContents()
        self.match_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def _calculate_candidate_overlay(self, candidate: dict[str, str], show_errors: bool) -> None:
        entry_id = candidate.get("Entry", "")
        if entry_id and entry_id == self.active_overlay_entry_id:
            return
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            self._calculate_structure_overlay(structure)
            self.active_overlay_entry_id = entry_id or None
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Calculate pattern failed", str(exc))

    def _calculate_structure_overlay(self, structure) -> None:
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
        peaks = self._adjust_peaks_for_alignment(peaks, alignment.zero_shift, alignment.cell_scale, structure)
        wavelength = getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH
        x, y = calculated_profile_from_peaks(peaks, x_grid, fwhm=profile_fwhm, wavelength=wavelength)
        if observed_ymax is not None:
            baseline = float(np.nanpercentile(background, 50))
            y = scale_profile_to_reference(y, max(observed_ymax - baseline, 1.0))
            background_item = plot_profile(
                self.match_plot,
                x,
                background,
                "#9aa0a6",
                "background",
                width=0.8,
            )
            self.plot_layers["calculated_profile"].append(background_item)
        calc_item = plot_profile(
            self.match_plot,
            x,
            y + background,
            "#d93025",
            f"calculated total {structure.name}",
            width=1.8,
        )
        self.plot_layers["calculated_profile"].append(calc_item)
        marker_top = observed_ymax if observed_ymax is not None else float(np.nanmax(y) if np.nanmax(y) > 0 else 100.0)
        baseline = float(np.nanpercentile(background, 50))
        peak_scale = (marker_top - baseline) if marker_top > baseline else marker_top
        stick_item = plot_hkl_sticks(
            self.match_plot,
            peaks,
            "#1a73e8",
            baseline,
            peak_scale,
            label=f"peaks {structure.name}",
            width=1.8,
        )
        tick_item = plot_hkl_ticks(self.match_plot, peaks, "#d93025", baseline, peak_scale)
        self.plot_layers["peak_positions"].extend([stick_item, tick_item])
        self.plot_layers["hkl"].extend(
            add_hkl_labels(
                self.match_plot,
                peaks,
                "#b3261e",
                baseline,
                peak_scale,
                above_peaks=True,
                limit=45,
            )
        )
        self.match_plot.setXRange(float(np.nanmin(x_grid)), float(np.nanmax(x_grid)), padding=0.02)
        if observed_ymin is not None and observed_ymax is not None:
            self.match_plot.setYRange(min(observed_ymin, baseline - peak_scale * 0.05), observed_ymax, padding=0.08)
        self.match_plot.setTitle(
            f"Phase Finder: calculated overlay for {structure.name} ({len(peaks)} peaks, FWHM {profile_fwhm:.3g}, {alignment.status} {alignment.matched_peaks}/{alignment.total_peaks})",
            color="#111111",
            size="13pt",
        )

    def _database_tab(self) -> QWidget:
        mp_status = self.materials_project.status()
        widget = QWidget()
        layout = QVBoxLayout(widget)

        local_row = self.local_phase_cache.status_row()
        rows = [
            [
                "User phase library",
                local_row[1],
                local_row[2],
                local_row[3],
                local_row[4],
                "sqlite+cif",
                local_row[6],
            ],
            [
                "COD online",
                "optional",
                "download CIF to user library",
                "",
                "",
                "web export",
                "crystallography.net/cod",
            ],
            [
                "CCDC DOI",
                "optional",
                "paste DOI in search line",
                "",
                "",
                "web export",
                "ccdc.cam.ac.uk/structures",
            ],
        ]
        rows.append(
            [
                "Materials Project",
                "yes" if mp_status.configured else "not configured",
                mp_status.label,
                "",
                "",
                "api",
                "user API key",
            ]
        )
        self.database_table = self._table(
            ["Source", "Available", "Label", "Files", "Size MB", "Mode", "Location"],
            rows,
        )
        layout.addWidget(self.database_table)

        self.use_materials_project_checkbox = QCheckBox("Use Materials Project in phase search")
        self.use_materials_project_checkbox.setChecked(
            bool(self.settings.value("materials_project/enabled", False, type=bool))
        )
        layout.addWidget(self.use_materials_project_checkbox)

        self.mp_status_label = QLabel(self._materials_project_status_text())
        layout.addWidget(self.mp_status_label)

        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        self.mp_api_key_input = QLineEdit()
        self.mp_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.mp_api_key_input.setPlaceholderText("Materials Project API key")
        self.mp_api_key_input.setText(self.materials_project.api_key)
        save_key = QPushButton("Save API key")
        save_key.clicked.connect(self._save_materials_project_settings)
        key_layout.addWidget(self.mp_api_key_input, 1)
        key_layout.addWidget(save_key)
        layout.addWidget(key_row)

        build_index = QPushButton("Rebuild user phase library index")
        build_index.clicked.connect(self._build_local_phase_cache_index)
        layout.addWidget(build_index)

        layout.addWidget(QLabel("Data sources"))
        layout.addWidget(
            QLabel(
                "Standalone phase search uses the user phase library plus optional exports from COD online "
                "and Materials Project."
            )
        )
        layout.addStretch(1)
        return widget

    def _show_database_settings_tab(self) -> None:
        for index in range(self.right_tabs.count()):
            if self.right_tabs.tabText(index) == "References":
                self.right_tabs.setCurrentIndex(index)
                return

    def _materials_project_status_text(self) -> str:
        status = self.materials_project.status()
        enabled = self.settings.value("materials_project/enabled", False, type=bool)
        enabled_text = "enabled" if enabled else "disabled"
        return f"Materials Project: {status.label}; search {enabled_text}."

    def _save_materials_project_settings(self) -> None:
        api_key = self.mp_api_key_input.text().strip() if self.mp_api_key_input is not None else ""
        enabled = bool(self.use_materials_project_checkbox and self.use_materials_project_checkbox.isChecked())
        self.settings.setValue("materials_project/api_key", api_key)
        self.settings.setValue("materials_project/enabled", enabled)
        self.materials_project = MaterialsProjectService(api_key)
        if self.mp_status_label is not None:
            self.mp_status_label.setText(self._materials_project_status_text())
        self._refresh_materials_project_database_row()

    def _refresh_materials_project_database_row(self) -> None:
        if self.database_table is None:
            return
        status = self.materials_project.status()
        for row in range(self.database_table.rowCount()):
            name_item = self.database_table.item(row, 0)
            if name_item is None or name_item.text() != "Materials Project":
                continue
            values = [
                "Materials Project",
                "yes" if status.configured else "not configured",
                status.label,
                "",
                "",
                "api",
                "user API key",
            ]
            for column, value in enumerate(values):
                self.database_table.setItem(row, column, QTableWidgetItem(value))
            self.database_table.resizeColumnsToContents()
            return

    def _build_local_phase_cache_index(self) -> None:
        try:
            count = self.local_phase_cache.build_index()
        except Exception as exc:
            QMessageBox.warning(self, "Build local index failed", str(exc))
            return
        QMessageBox.information(self, "Build local index", f"Indexed {count} saved CIF files.")

    def _search_pdf2_text(self) -> None:
        query = self.search_input.text().strip() if self.search_input is not None else ""
        if not query and self.name_input is not None:
            query = self.name_input.text().strip()
        if not query and self.formula_sum_input is not None:
            query = self.formula_sum_input.text().strip()
        if not query:
            self._set_candidate_rows([["", "", "", "Enter name, formula, DOI, or entry id", "", ""]])
            return

        rows = []
        doi = extract_doi(query)
        if doi:
            try:
                entry = self._download_ccdc_doi_to_cache(doi)
                rows.extend(self._cache_rows([entry]))
            except Exception as exc:
                rows.append(["CCDC", doi, "", "CCDC CIF not available", "", str(exc)])

        if self._local_cache_enabled():
            rows.extend(self._cache_rows(self._search_local_cache(text=query)))

        if self._cod_online_enabled():
            try:
                cod_entries = self.cod_online.search_text(query=query, limit=100)
                cod_entries = self._filter_cod_entries(cod_entries)
                self.local_phase_cache.upsert_cod_entries(cod_entries)
                errors = self._download_cod_entries_to_cache(cod_entries)
                rows = self._dedupe_candidate_rows(rows + self._cache_rows(self._search_local_cache(text=query)))
                if errors:
                    rows.append(["COD", "", "", f"{errors} COD CIF downloads failed", "", ""])
            except Exception:
                pass

        if self._materials_project_enabled():
            try:
                mp_entries = self.materials_project.search_text(query=query, limit=80)
                self._download_mp_entries_to_cache(mp_entries)
                rows = self._dedupe_candidate_rows(rows + self._cache_rows(self._search_local_cache(text=query)))
            except Exception as exc:
                if not rows:
                    rows.append(["MP", "", "", "Materials Project search failed", "", str(exc)])

        if rows:
            self._set_candidate_rows(
                self._dedupe_candidate_rows(self._filter_candidate_rows_by_excluded_elements(rows))
            )
            return

        self._set_candidate_rows([["", "", "", f"No saved/COD/MP entries found for: {query}", "", ""]])

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
        rows = []
        if self._local_cache_enabled():
            rows.extend(self._cache_rows(self._search_local_cache(elements=list(self.selected_element_order))))
        if self._cod_online_enabled():
            try:
                cod_entries = self.cod_online.search_elements(
                    list(self.selected_element_order),
                    excluded_elements=self._excluded_elements(),
                    limit=100,
                )
                cod_entries = self._filter_cod_entries(cod_entries)
                self.local_phase_cache.upsert_cod_entries(cod_entries)
                errors = self._download_cod_entries_to_cache(cod_entries)
                rows = self._cache_rows(self._search_local_cache(elements=list(self.selected_element_order)))
                if errors:
                    rows.append(["", "COD", "", "", f"{errors} COD CIF downloads failed", "", "", "", "", ""])
            except Exception as exc:
                rows.append(["", "COD", "", "", f"COD search failed: {exc}", "", "", "", "", ""])
        if self._materials_project_enabled():
            try:
                mp_entries = self.materials_project.search_elements(
                    list(self.selected_element_order),
                    limit=80,
                )
                self._download_mp_entries_to_cache(mp_entries)
                rows = self._dedupe_candidate_rows(
                    rows + self._cache_rows(self._search_local_cache(elements=list(self.selected_element_order)))
                )
            except Exception as exc:
                rows.append(["MP", "", "", "Materials Project search failed", "", str(exc)])
        if self.search_input is not None and self.formula_sum_input is not None:
            self.search_input.setText(self.formula_sum_input.text().strip())
        rows = self._filter_candidate_rows_by_excluded_elements(rows)
        if not rows:
            self._set_candidate_rows([["", "", "", "No entries for selected elements", "", ""]])
            return
        self._set_candidate_rows(self._dedupe_candidate_rows(rows))

    def _materials_project_enabled(self) -> bool:
        return bool(self.settings.value("materials_project/enabled", False, type=bool)) and self.materials_project.status().configured

    def _local_cache_enabled(self) -> bool:
        return self.local_cache_checkbox is None or self.local_cache_checkbox.isChecked()

    def _cod_online_enabled(self) -> bool:
        return self.cod_online_checkbox is None or self.cod_online_checkbox.isChecked()

    def _cache_rows(self, entries) -> list[list[str]]:
        return [
            [
                entry.source,
                entry.entry_id,
                self._display_formula(entry.formula),
                entry.name or self._display_formula(entry.formula),
                "",
                entry.source_text or entry.spacegroup,
            ]
            for entry in entries
        ]

    def _display_formula(self, formula: str) -> str:
        parts = re.findall(r"[A-Z][a-z]?[0-9.]*", formula or "")
        return " ".join(parts) if parts else formula

    def _search_local_cache(
        self,
        text: str = "",
        elements: list[str] | None = None,
    ):
        return self.local_phase_cache.search(
            text=text,
            elements=elements,
            excluded_elements=self._excluded_elements(),
            limit=100,
        )

    def _download_cod_entries_to_cache(self, entries) -> int:
        errors = 0
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            for entry in entries:
                try:
                    self.local_phase_cache.download_cod_entry(entry, self.cod_online)
                except Exception:
                    errors += 1
        finally:
            self.unsetCursor()
        return errors

    def _download_mp_entries_to_cache(self, entries) -> int:
        errors = 0
        if not entries:
            return errors
        target_dir = self.local_phase_cache.root / "materials_project_cif"
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            for entry in entries:
                try:
                    cif_path = self.materials_project.download_cif(entry.material_id, target_dir)
                    self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=entry.material_id)
                except Exception:
                    errors += 1
        finally:
            self.unsetCursor()
        return errors

    def _download_ccdc_doi_to_cache(self, doi: str):
        target_dir = self.local_phase_cache.root / "ccdc_cif"
        cif_path = self.ccdc.download_cif_by_doi(doi, target_dir)
        entry_id = cif_path.stem
        self.local_phase_cache.index_cif(cif_path, source="CCDC", entry_id=entry_id)
        entry = self.local_phase_cache.get("CCDC", entry_id)
        if entry is None:
            raise ValueError("CCDC CIF was downloaded but could not be indexed.")
        return entry

    def _dedupe_candidate_rows(self, rows: list[list[str]]) -> list[list[str]]:
        unique = []
        seen = set()
        for row in rows:
            normalized = self._normalize_candidate_row(row)
            key = tuple(value.strip().lower() for value in normalized[:4])
            if key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        return unique

    def _cod_rows(self, entries) -> list[list[str]]:
        return [
            [
                "COD",
                entry.cod_id,
                entry.formula,
                entry.name or entry.mineral,
                "",
                entry.source or entry.spacegroup,
            ]
            for entry in entries
        ]

    def _materials_project_rows(self, entries) -> list[list[str]]:
        if not self._materials_project_enabled():
            return []
        return [
            [
                "MP",
                entry.material_id,
                entry.formula,
                entry.name,
                "",
                entry.energy_above_hull or entry.spacegroup or "Materials Project",
            ]
            for entry in entries
        ]

    def _filter_candidate_rows_by_excluded_elements(self, rows: list[list[str]]) -> list[list[str]]:
        excluded = set(self._excluded_elements())
        filtered = []
        for row in rows:
            normalized = self._normalize_candidate_row(row)
            formula = normalized[2] if len(normalized) > 2 else ""
            if excluded and formula and formula_elements(formula) & excluded:
                continue
            if formula and not self._material_class_allowed(formula):
                continue
            filtered.append(row)
        return filtered

    def _filter_cod_entries(self, entries):
        return [
            entry
            for entry in entries
            if self._material_class_allowed(entry.formula)
        ]

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
        for element in self._element_buttons:
            self._set_element_state(element, "excluded")
        if self.inorganics_checkbox is not None:
            self.inorganics_checkbox.setChecked(True)
        if self.organics_checkbox is not None:
            self.organics_checkbox.setChecked(False)
        self._update_element_fields()

    def _toggle_required_element(self, element: str) -> None:
        self.exclude_all_other_elements = True
        current = self.element_states.get(element, "excluded")
        self._set_element_state(element, "excluded" if current == "required" else "required")
        if not any(state == "required" for state in self.element_states.values()):
            for symbol in self._element_buttons:
                self._set_element_state(symbol, "excluded")
        self._update_element_fields()

    def _reset_selected_elements(self) -> None:
        for element in list(self.element_states):
            self._set_element_state(element, "excluded")
        self.element_states.clear()
        self.selected_element_order.clear()
        self.exclude_all_other_elements = True
        for element in self._element_buttons:
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
        for element in sorted(self.selected_elements, key=_element_sort_key):
            if element not in self.selected_element_order:
                self.selected_element_order.append(element)
        formula = " ".join(self.selected_element_order)
        if self.elem_count_input is not None:
            self.elem_count_input.setText(str(len(self.selected_elements)))
        if self.formula_sum_input is not None:
            self.formula_sum_input.setText(formula)
        if hasattr(self, "element_gate_label") and self.element_gate_label is not None:
            self.element_gate_label.setText(f"Gate: {formula or 'none'}")
        if self.name_input is not None:
            excluded = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: _element_sort_key(item[0]))
                if state == "excluded"
            ]
            optional = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: _element_sort_key(item[0]))
                if state == "optional"
            ]
            any_elements = [
                element
                for element, state in sorted(self.element_states.items(), key=lambda item: _element_sort_key(item[0]))
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
        button = self._element_buttons.get(element)
        if button is None:
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
        button.setStyleSheet(_element_state_style(state))

    def _excluded_elements(self) -> list[str]:
        if not self.selected_elements:
            return []
        if self.exclude_all_other_elements:
            return [
                element
                for element in self._element_buttons
                if element not in self.selected_elements
                and self.element_states.get(element, "neutral") not in {"optional", "any"}
            ]
        return [element for element, state in self.element_states.items() if state == "excluded"]

    def _format_entry_first_peak(self, entry) -> str:
        return ""

    def _search_pdf2_candidates(self) -> None:
        if self.selected_elements:
            self._search_from_controls()
        else:
            self._search_pdf2_text()

    def _set_candidate_rows(self, rows: list[list[str]]) -> None:
        self.candidate_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            normalized_row = self._normalize_candidate_row(row)
            for col_index, value in enumerate(normalized_row[: self.candidate_table.columnCount()]):
                self.candidate_table.setItem(row_index, col_index, QTableWidgetItem(value))
        self.candidate_table.resizeColumnsToContents()
        self.candidate_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def _normalize_candidate_row(self, row: list[str]) -> list[str]:
        if len(row) == 6:
            return row
        if len(row) >= 10:
            return [
                row[1],
                row[2],
                row[3],
                row[4],
                row[8],
                row[9],
            ]
        if len(row) >= 5:
            return ["", "", "", row[4], "", ""]
        return (row + [""] * 6)[:6]

    def _format_first_peak_two_theta(self, candidate) -> str:
        return ""

    def _draw_candidate_markers(self, candidates) -> None:
        for item in self.plot_layers.get("candidate_markers", []):
            self.match_plot.removeItem(item)
        self.plot_layers["candidate_markers"] = []

    def _set_element_scale(self, value: str) -> None:
        factor = int(value.removesuffix("%")) / 100
        width = round(22 * factor)
        height = round(18 * factor)
        font_size = max(6, round(7 * factor))
        for widget in self._element_widgets:
            widget.setFixedSize(width, height)
            font = widget.font()
            font.setPointSize(font_size)
            widget.setFont(font)

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
