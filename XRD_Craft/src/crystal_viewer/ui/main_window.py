from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabBar,
    QTabWidget,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from crystal_viewer.analysis.geometry import analyze_atom_group
from crystal_viewer.analysis.morphology_export import export_morphology_csv, export_morphology_json
from crystal_viewer.analysis.morphology_state import (
    load_morphology_state,
    save_morphology_state,
)
from crystal_viewer.analysis.comparison import (
    ComparisonReport,
    cached_compare,
    compare_documents,
)
from crystal_viewer.analysis.motif_comparison import MatchLimits, MotifComparisonReport
from crystal_viewer.analysis.comparison_export import (
    export_comparison_csv,
    export_comparison_json,
)
from crystal_viewer.analysis.hierarchy import (
    HierarchyAnalyzer,
    HierarchyLevel,
    HierarchyReport,
    normalized_rigidity,
    polyhedron_rigidity_index,
)
from crystal_viewer.analysis.passport import build_structural_passport
from crystal_viewer.analysis.structure_profile import (
    RequestedProfile,
    ResolvedProfile,
)
from crystal_viewer.analysis.series import SeriesMechanicsReport, analyze_structure_series
from crystal_viewer.analysis.reporting import (
    StructureReportBuilder,
    export_report_json,
    export_table_csv,
)
from crystal_viewer.analysis.structural_cache import cached_analyze_structure
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.collection import StructureCollection
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import CrystalStructure
from crystal_viewer.core.progressive_load import (
    LoadStage,
    StructureLoadUpdate,
    iter_load_updates,
    iter_reanalysis_updates,
)
from crystal_viewer.core.structure_io import is_supported_structure_path
from crystal_viewer.core.scene import build_scene
from crystal_viewer.core.site_orbits import (
    hierarchy_object_orbits,
    polyhedron_orbits,
    site_orbit_key,
    site_orbits,
)
from crystal_viewer.core.xpff import load_xpff_structures
from crystal_viewer.ui.analysis_workspace import AnalysisWorkspace
from crystal_viewer.ui.compare_workspace import CompareWorkspace
from crystal_viewer.ui.comparison_requests import (
    ComparisonRequestManager,
    QtComparisonExecutor,
)
from crystal_viewer.ui.dual_viewer import DualStructureViewer
from crystal_viewer.ui.hierarchy_tree import HierarchyTree
from crystal_viewer.ui.interpretation_panel import InterpretationPanel
from crystal_viewer.ui.morphology_workspace import MorphologyWorkspace
from crystal_viewer.ui.sites_panel import SitesPanel
from crystal_viewer.ui.structure_load_requests import (
    QtStructureLoadExecutor,
    StructureLoadRequestManager,
)
from crystal_viewer.ui.toolkit_catalog_dialog import ToolkitCatalogController
from crystal_viewer.ui.viewer import StructureViewer
from crystal_viewer.knowledge.resolve import (
    confirm_bond_changes,
    remove_overlay,
    resolve_interpretation,
)

REPRESENTATIONS = (
    ("Structure", HierarchyLevel.SITES),
    ("Topology", HierarchyLevel.TOPOLOGY),
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GEHLENITE_DEMO = PROJECT_ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif"
APPLICATION_COMPARISON_LIMITS = MatchLimits(
    max_states=50_000,
    max_seconds=5.0,
    max_nodes=128,
)


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("eyebrow")
    return label


def _metric_card(title: str) -> tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setObjectName("dashboardCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    caption = QLabel(title)
    caption.setObjectName("metricTitle")
    value = QLabel("—")
    value.setObjectName("metricValue")
    value.setWordWrap(True)
    layout.addWidget(caption)
    layout.addWidget(value)
    return frame, caption, value


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CRAFT — Structural Mechanics")
        self.resize(1500, 920)
        self.setAcceptDrops(True)
        self.collection = StructureCollection(max_compared=2)
        self.comparison_limits = APPLICATION_COMPARISON_LIMITS
        self.active_document_id: str | None = None
        self.structure = None
        self.hierarchy = None
        self.series_report: SeriesMechanicsReport | None = None
        self.current_path: Path | None = None
        self._picked_polyhedron_id: str | None = None
        self._picked_scene_object: tuple[str, object] | None = None
        self.analyzer = HierarchyAnalyzer()
        self.scene_rebuild_timer = QTimer(self)
        self.scene_rebuild_timer.setSingleShot(True)
        self.scene_rebuild_timer.setInterval(90)
        self.scene_rebuild_timer.timeout.connect(self._rebuild_scene)
        self._build_ui()
        self._build_actions()
        self._toolkit_catalog = ToolkitCatalogController(
            self,
            QSettings("XRD Analysis Toolkit", "CRAFT"),
        )
        self._initialize_comparison_requests(QtComparisonExecutor(self))
        self._initialize_structure_load_requests(QtStructureLoadExecutor(self))
        self.statusBar().showMessage("Ready · drop a CIF or open a structure")
        self._schedule_toolkit_announcement()

    def _build_ui(self) -> None:
        self.compare_workspace = CompareWorkspace()
        self.compare_workspace.visual_requested.connect(self.show_visual_comparison)
        self.compare_workspace.focus_requested.connect(self._focus_comparison)
        self.compare_workspace.export_csv_requested.connect(self.export_comparison_csv)
        self.compare_workspace.export_json_requested.connect(self.export_comparison_json)
        self.compare_workspace.export_images_requested.connect(self.export_comparison_images)
        self.morphology_workspace = MorphologyWorkspace()
        self.morphology_workspace.cif_files_dropped.connect(self._load_dropped_cifs)
        self.morphology_workspace.save_requested.connect(self.save_morphology_model)
        self.morphology_workspace.open_requested.connect(self.open_morphology_model)
        self.morphology_workspace.export_csv_requested.connect(self.export_morphology_table)
        self.morphology_workspace.export_png_requested.connect(self.export_morphology_image)
        self.morphology_workspace.result_installed.connect(self._update_morphology_actions)
        root = QSplitter(Qt.Orientation.Horizontal)
        root.setChildrenCollapsible(False)
        root.addWidget(self._hierarchy_explorer())
        root.addWidget(self._workspace())
        root.addWidget(self._inspector())
        root.setSizes([285, 930, 285])
        self.structure_workspace = root
        self.analysis_workspace = AnalysisWorkspace()
        self.analysis_workspace.export_csv_requested.connect(self.export_analysis_csv)
        self.analysis_workspace.export_json_requested.connect(self.export_analysis_json)
        self.central_stack = QStackedWidget()
        self.central_stack.addWidget(self.structure_workspace)
        self.central_stack.addWidget(self.analysis_workspace)
        self.setCentralWidget(self.central_stack)
        self._build_output_dock()

    def _hierarchy_explorer(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidePanel")
        panel.setMinimumWidth(255)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(11, 13, 11, 11)
        browser = QWidget()
        browser_layout = QVBoxLayout(browser)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_layout.addWidget(_caption("HIERARCHY EXPLORER"))
        self.tree_filter = QLineEdit()
        self.tree_filter.setPlaceholderText("Filter objects…")
        self.tree_filter.textChanged.connect(self._filter_tree)
        browser_layout.addWidget(self.tree_filter)
        self.object_tree = HierarchyTree()
        self.object_tree.setHeaderHidden(True)
        self.object_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.object_tree.object_selected.connect(self._hierarchy_object_selected)
        self.object_tree.compare_toggled.connect(self._toggle_compare_document)
        self.object_tree.visibility_changed.connect(self._set_document_visibility)
        self.object_tree.customContextMenuRequested.connect(self._tree_context_menu)
        browser_layout.addWidget(self.object_tree, 1)
        self.sites_panel = SitesPanel()
        self.sites_panel.setMinimumHeight(220)
        self.sites_panel.state_changed.connect(self._sites_state_changed)
        self.explorer_splitter = QSplitter(Qt.Orientation.Vertical)
        self.explorer_splitter.setChildrenCollapsible(False)
        self.explorer_splitter.addWidget(browser)
        self.explorer_splitter.addWidget(self.sites_panel)
        self.explorer_splitter.setStretchFactor(0, 1)
        self.explorer_splitter.setStretchFactor(1, 1)
        self.explorer_splitter.setSizes((390, 390))
        layout.addWidget(self.explorer_splitter, 1)
        self.compare_structures_button = QPushButton("Compare structures")
        self.compare_structures_button.setEnabled(False)
        self.compare_structures_button.clicked.connect(self.show_selected_comparison)
        layout.addWidget(self.compare_structures_button)
        return panel

    def _workspace(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(6)
        self.view_tabs = QTabBar()
        self.view_tabs.setObjectName("hierarchyScale")
        self.view_tabs.setExpanding(True)
        for name, level in REPRESENTATIONS:
            index = self.view_tabs.addTab(name)
            self.view_tabs.setTabData(index, level.value)
        morphology_index = self.view_tabs.addTab("Morphology")
        self.view_tabs.setTabData(morphology_index, "morphology")
        self.view_tabs.currentChanged.connect(self._view_tab_changed)
        layout.addWidget(self.view_tabs)
        self.viewer = StructureViewer()
        self.viewer.cif_files_dropped.connect(self._load_dropped_cifs)
        self.viewer.scene_object_picked.connect(self._scene_object_picked)
        self.viewer.scene_selection_cleared.connect(self._scene_selection_cleared)
        self.viewer.edit_context_menu_requested.connect(self._scene_edit_context_menu)
        self.dual_viewer: DualStructureViewer | None = None
        self.viewer_stack = QStackedWidget()
        self.viewer_stack.addWidget(self.viewer)
        self.comparison_mode_tabs = QTabBar()
        self.comparison_mode_tabs.setObjectName("comparisonModeTabs")
        self.comparison_mode_tabs.setExpanding(True)
        self.comparison_mode_tabs.addTab("Visual comparison")
        self.comparison_mode_tabs.addTab("Comparison table")
        self.comparison_mode_tabs.currentChanged.connect(self._comparison_mode_tab_changed)
        self.comparison_mode_tabs.hide()
        layout.addWidget(self.comparison_mode_tabs)
        self.comparison_visual_page = QWidget()
        visual_layout = QVBoxLayout(self.comparison_visual_page)
        visual_layout.setContentsMargins(0, 0, 0, 0)
        visual_layout.setSpacing(6)
        self._structure_summary().hide()
        visual_layout.addWidget(self.viewer_stack, 1)
        self.comparison_mode_stack = QStackedWidget()
        self.comparison_mode_stack.addWidget(self.comparison_visual_page)
        self.comparison_mode_stack.addWidget(self.compare_workspace)
        self.comparison_mode_stack.addWidget(self.morphology_workspace)
        layout.addWidget(self.comparison_mode_stack, 1)
        return center

    def _structure_summary(self) -> QWidget:
        summary = QFrame()
        self.summary_bar = summary
        summary.setObjectName("summaryBar")
        summary.setMaximumHeight(132)
        layout = QVBoxLayout(summary)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.addWidget(_caption("STRUCTURE SUMMARY"))
        grid = QGridLayout()
        self.dashboard_values: dict[str, QLabel] = {}
        cards = (
            ("hierarchy", "Structural passport"),
            ("rigidity", "Rigidity statistics"),
            ("mechanism", "Dominant mechanism"),
            ("nte", "Potential NTE mechanism"),
            ("flexibility", "Predicted flexibility"),
        )
        for index, (key, label) in enumerate(cards):
            frame, _caption_label, value = _metric_card(label)
            self.dashboard_values[key] = value
            grid.addWidget(frame, 0, index)
        layout.addLayout(grid)
        return summary

    def _inspector(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidePanel")
        panel.setMinimumWidth(270)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        self.inspector_tabs = QTabWidget()
        self.inspector_tabs.addTab(self._analysis_inspector(), "Analysis")
        self.inspector_tabs.addTab(self._visualization_inspector(), "Visualization")
        self.inspector_tabs.addTab(self._cell_inspector(), "Cell")
        self.inspector_tabs.addTab(self._selection_inspector(), "Selection")
        self.interpretation_panel = InterpretationPanel()
        self.interpretation_panel.remove_requested.connect(self._remove_interpretation)
        self.interpretation_panel.confirm_bonds_requested.connect(
            self._confirm_interpretation_bonds
        )
        self.inspector_tabs.addTab(self.interpretation_panel, "Interpretation")
        layout.addWidget(self.inspector_tabs)
        return panel

    def _analysis_inspector(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(_caption("SELECTED OBJECT ANALYSIS"))
        self.selected_title = QLabel("Nothing selected")
        self.selected_title.setObjectName("selectedTitle")
        self.selected_analysis = QLabel("Choose an object in the hierarchy tree.")
        self.selected_analysis.setWordWrap(True)
        self.selected_analysis.setTextFormat(Qt.TextFormat.RichText)
        self.selected_analysis.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.selected_title)
        layout.addWidget(self.selected_analysis)
        self.local_environment_caption = _caption("LOCAL BLOCK ENVIRONMENT")
        self.local_environment = QLabel()
        self.local_environment.setObjectName("localEnvironment")
        self.local_environment.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.local_environment.setTextFormat(Qt.TextFormat.RichText)
        self.local_environment.setWordWrap(True)
        self.local_environment_caption.hide()
        self.local_environment.hide()
        layout.addWidget(self.local_environment_caption)
        layout.addWidget(self.local_environment)
        layout.addStretch()
        scroll.setWidget(body)
        return scroll

    def _visualization_inspector(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(2, 4, 2, 2)
        layout.addWidget(_caption("VISUALIZATION"))
        tabs = QTabWidget()
        tabs.setObjectName("visualizationTabs")
        layout.addWidget(tabs)

        self.show_checks: dict[str, QCheckBox] = {}

        def show_checkbox(key: str, label: str) -> QCheckBox:
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._visualization_changed)
            self.show_checks[key] = checkbox
            return checkbox

        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_form = QFormLayout()
        self.render_style_combo = QComboBox()
        self.render_style_combo.addItems(("Publication", "Soft", "Technical"))
        self.render_style_combo.currentTextChanged.connect(self._visualization_changed)
        general_form.addRow("Rendering style", self.render_style_combo)
        self.representation_combo = QComboBox()
        for label, level in REPRESENTATIONS:
            self.representation_combo.addItem(label, level.value)
        self.representation_combo.currentIndexChanged.connect(self._representation_changed)
        general_form.addRow("Hierarchy level", self.representation_combo)
        self.color_combo = QComboBox()
        self.color_combo.addItems(("Automatic", "Element", "Structural unit", "Block", "Rigidity", "Distortion"))
        self.color_combo.currentTextChanged.connect(self._visualization_changed)
        general_form.addRow("Color by", self.color_combo)
        general_layout.addLayout(general_form)
        self.cell_check = QCheckBox("Unit-cell frame")
        self.cell_check.setChecked(True)
        self.cell_check.toggled.connect(self._visualization_changed)
        self.axes_check = QCheckBox("Orientation compass")
        self.axes_check.setChecked(True)
        self.axes_check.toggled.connect(self._visualization_changed)
        self.legend_check = QCheckBox("Publication legend")
        self.legend_check.toggled.connect(self._visualization_changed)
        self.cell_dimensions_check = QCheckBox("Cell dimensions")
        self.cell_dimensions_check.setChecked(False)
        self.cell_dimensions_check.toggled.connect(self._visualization_changed)
        general_layout.addWidget(self.cell_check)
        general_layout.addWidget(self.axes_check)
        general_layout.addWidget(self.legend_check)
        general_layout.addWidget(self.cell_dimensions_check)
        general_layout.addWidget(QLabel("Unit-cell line width"))
        self.cell_line_slider = QSlider(Qt.Orientation.Horizontal)
        self.cell_line_slider.setRange(5, 40)
        self.cell_line_slider.setValue(18)
        self.cell_line_slider.valueChanged.connect(self._visualization_changed)
        general_layout.addWidget(self.cell_line_slider)
        general_layout.addWidget(QLabel("Compass size"))
        self.axes_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.axes_size_slider.setRange(20, 42)
        self.axes_size_slider.setValue(30)
        self.axes_size_slider.valueChanged.connect(self._visualization_changed)
        general_layout.addWidget(self.axes_size_slider)
        general_layout.addStretch()
        tabs.addTab(general, "General")

        atoms = QWidget()
        atoms_layout = QVBoxLayout(atoms)
        atoms_layout.addWidget(show_checkbox("atoms", "Show atoms"))
        atoms_form = QFormLayout()
        self.radius_combo = QComboBox()
        self.radius_combo.addItem("Coordination ionic", "coordination_ionic")
        self.radius_combo.addItem("Covalent", "covalent")
        self.radius_combo.addItem("Uniform", "uniform")
        self.radius_combo.currentIndexChanged.connect(self._visualization_changed)
        atoms_form.addRow("Radius model", self.radius_combo)
        atoms_layout.addLayout(atoms_form)
        atoms_layout.addWidget(QLabel("Atomic scale"))
        self.atom_scale = QSlider(Qt.Orientation.Horizontal)
        self.atom_scale.setRange(45, 180)
        self.atom_scale.setValue(100)
        self.atom_scale.valueChanged.connect(self._visualization_changed)
        atoms_layout.addWidget(self.atom_scale)
        self.labels_check = QCheckBox("Site labels with subscripts")
        self.labels_check.toggled.connect(self._visualization_changed)
        self.boundary_atoms_check = QCheckBox("Complete coordination beyond cell")
        self.boundary_atoms_check.setChecked(True)
        self.boundary_atoms_check.toggled.connect(self._rebuild_scene)
        self.split_occupancy_check = QCheckBox("Split mixed occupancies")
        self.split_occupancy_check.setChecked(True)
        self.split_occupancy_check.toggled.connect(self._visualization_changed)
        self.vacancy_sector_check = QCheckBox("Show vacancy sectors")
        self.vacancy_sector_check.setChecked(True)
        self.vacancy_sector_check.toggled.connect(self._visualization_changed)
        atoms_layout.addWidget(self.labels_check)
        atoms_layout.addWidget(self.boundary_atoms_check)
        atoms_layout.addWidget(self.split_occupancy_check)
        atoms_layout.addWidget(self.vacancy_sector_check)
        atoms_layout.addStretch()
        tabs.addTab(atoms, "Atoms")

        bonds = QWidget()
        bonds_layout = QVBoxLayout(bonds)
        bonds_layout.addWidget(show_checkbox("bonds", "Show bonds"))
        bonds_form = QFormLayout()
        self.bond_style_combo = QComboBox()
        self.bond_style_combo.addItem("Bicolor cylinder", "bicolor")
        self.bond_style_combo.addItem("Unicolor cylinder", "unicolor")
        self.bond_style_combo.currentIndexChanged.connect(self._visualization_changed)
        bonds_form.addRow("Bond style", self.bond_style_combo)
        bonds_layout.addLayout(bonds_form)
        bonds_layout.addWidget(QLabel("Cylinder radius"))
        self.bond_radius_slider = QSlider(Qt.Orientation.Horizontal)
        self.bond_radius_slider.setRange(1, 15)
        self.bond_radius_slider.setValue(5)
        self.bond_radius_slider.valueChanged.connect(self._visualization_changed)
        bonds_layout.addWidget(self.bond_radius_slider)
        bonds_layout.addStretch()
        tabs.addTab(bonds, "Bonds")

        polyhedra = QWidget()
        polyhedra_layout = QVBoxLayout(polyhedra)
        polyhedra_layout.addWidget(show_checkbox("polyhedra", "Show polyhedra"))
        polyhedra_layout.addWidget(show_checkbox("centers", "Show central atoms"))
        self.poly_edges_check = QCheckBox("Show polyhedral edges")
        self.poly_edges_check.setChecked(True)
        self.poly_edges_check.toggled.connect(self._visualization_changed)
        self.spokes_check = QCheckBox("Show center–vertex bonds")
        self.spokes_check.setChecked(True)
        self.spokes_check.toggled.connect(self._visualization_changed)
        polyhedra_layout.addWidget(self.poly_edges_check)
        polyhedra_layout.addWidget(self.spokes_check)
        polyhedra_layout.addWidget(QLabel("Plane opacity"))
        self.poly_opacity = QSlider(Qt.Orientation.Horizontal)
        self.poly_opacity.setRange(8, 95)
        self.poly_opacity.setValue(36)
        self.poly_opacity.valueChanged.connect(self._visualization_changed)
        polyhedra_layout.addWidget(self.poly_opacity)
        polyhedra_layout.addWidget(QLabel("Edge width"))
        self.poly_edge_slider = QSlider(Qt.Orientation.Horizontal)
        self.poly_edge_slider.setRange(5, 45)
        self.poly_edge_slider.setValue(20)
        self.poly_edge_slider.valueChanged.connect(self._visualization_changed)
        polyhedra_layout.addWidget(self.poly_edge_slider)
        polyhedra_layout.addStretch()
        tabs.addTab(polyhedra, "Polyhedra")

        blocks = QWidget()
        blocks_layout = QVBoxLayout(blocks)
        self.pivots_check = QCheckBox("Shared atoms / pivot candidates")
        self.pivots_check.setChecked(False)
        self.pivots_check.toggled.connect(self._visualization_changed)
        self.show_checks["connectors"] = self.pivots_check
        blocks_layout.addWidget(self.pivots_check)
        self.pivot_labels_check = QCheckBox("Pivot labels and angles")
        self.pivot_labels_check.setChecked(False)
        self.pivot_labels_check.toggled.connect(self._visualization_changed)
        blocks_layout.addWidget(self.pivot_labels_check)
        self.adaptive_rigidity_check = QCheckBox("Adaptive rigidity colors (within structure)")
        self.adaptive_rigidity_check.setChecked(True)
        self.adaptive_rigidity_check.toggled.connect(self._visualization_changed)
        blocks_layout.addWidget(self.adaptive_rigidity_check)
        blocks_layout.addWidget(QLabel(
            "Automatic color shows rigidity:\n"
            "red · flexible → green · rigid\n\n"
            "Pivot candidates are geometric only.\n"
            "A structure series is required to\n"
            "confirm RUM-like motion.\n\n"
            "Choose “Block” in Color by to show\n"
            "stable colors by block type."
        ))
        blocks_layout.addStretch()
        tabs.addTab(blocks, "Blocks")

        return body

    def _cell_inspector(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(_caption("CELL"))
        self.cell_summary = QLabel("No structure")
        self.cell_summary.setWordWrap(True)
        layout.addWidget(self.cell_summary)
        layout.addWidget(QLabel("Compound type"))
        self.compound_type_combo = QComboBox()
        self.compound_type_combo.addItem("Auto", RequestedProfile.AUTO.value)
        self.compound_type_combo.addItem("Inorganic", RequestedProfile.INORGANIC.value)
        self.compound_type_combo.addItem(
            "Organic / metal-organic",
            RequestedProfile.ORGANIC_METAL_ORGANIC.value,
        )
        self.compound_type_combo.currentIndexChanged.connect(
            self._profile_requested_changed
        )
        layout.addWidget(self.compound_type_combo)
        self.compound_type_result = QLabel("Detected: not analyzed")
        self.compound_type_result.setWordWrap(True)
        layout.addWidget(self.compound_type_result)
        layout.addWidget(QLabel("Cell bounds (fractional)"))
        bounds_grid = QGridLayout()
        bounds_grid.addWidget(QLabel("Axis"), 0, 0)
        bounds_grid.addWidget(QLabel("Min"), 0, 1)
        bounds_grid.addWidget(QLabel("Max"), 0, 2)
        self.cell_min_spins = []
        self.cell_max_spins = []
        for row, axis in enumerate(("a", "b", "c"), start=1):
            bounds_grid.addWidget(QLabel(axis), row, 0)
            minimum = QDoubleSpinBox()
            maximum = QDoubleSpinBox()
            for spin in (minimum, maximum):
                spin.setRange(-6.0, 6.0)
                spin.setDecimals(3)
                spin.setSingleStep(0.1)
                spin.setAccelerated(False)
                spin.setKeyboardTracking(False)
                spin.valueChanged.connect(self._schedule_scene_rebuild)
            minimum.setValue(0.0)
            maximum.setValue(1.0)
            bounds_grid.addWidget(minimum, row, 1)
            bounds_grid.addWidget(maximum, row, 2)
            self.cell_min_spins.append(minimum)
            self.cell_max_spins.append(maximum)
        layout.addLayout(bounds_grid)
        self.periodic_grid_check = QCheckBox("Periodic cell grid")
        self.periodic_grid_check.setChecked(False)
        self.periodic_grid_check.setToolTip(
            "Draw all unit-cell frames inside the selected Min/Max range"
        )
        self.periodic_grid_check.toggled.connect(self._visualization_changed)
        self.periodic_check = self.periodic_grid_check
        layout.addWidget(self.periodic_grid_check)
        layout.addWidget(QLabel("Bond tolerance"))
        self.bond_tolerance = QDoubleSpinBox()
        self.bond_tolerance.setRange(0.9, 1.6)
        self.bond_tolerance.setSingleStep(0.02)
        self.bond_tolerance.setValue(1.18)
        self.bond_tolerance.valueChanged.connect(self._schedule_scene_rebuild)
        layout.addWidget(self.bond_tolerance)
        layout.addStretch()
        return body

    def _selection_inspector(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(_caption("SELECTION"))
        text = QLabel(
            "Hierarchy tree: select an object\n\n"
            "3D view:\n"
            "• Left drag — rotate\n"
            "• Middle drag — pan\n"
            "• Wheel — zoom\n\n"
            "Direct 3D picking and multi-selection are the next interaction milestone."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addStretch()
        return body

    def _build_output_dock(self) -> None:
        self.output_dock = QDockWidget("Output / Console / History", self)
        tabs = QTabWidget()
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlainText("Crystal Mechanics ready.")
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.history = QPlainTextEdit()
        self.history.setReadOnly(True)
        tabs.addTab(self.output, "Output")
        tabs.addTab(self.console, "Console")
        tabs.addTab(self.history, "History")
        self.output_dock.setWidget(tabs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.output_dock)
        self.output_dock.hide()

    def _open_toolkit_catalog(self) -> None:
        self._toolkit_catalog.open_catalog()

    def _schedule_toolkit_announcement(self) -> None:
        self._toolkit_catalog.schedule_announcement()

    def _build_actions(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        edit_menu = menu_bar.addMenu("Edit")
        view_menu = menu_bar.addMenu("View")
        structure_menu = menu_bar.addMenu("Structure")
        hierarchy_menu = menu_bar.addMenu("Hierarchy")
        analysis_menu = menu_bar.addMenu("Analysis")
        mechanics_menu = menu_bar.addMenu("Mechanics")
        dynamics_menu = menu_bar.addMenu("Dynamics")
        tools_menu = menu_bar.addMenu("Tools")
        window_menu = menu_bar.addMenu("Window")
        help_menu = menu_bar.addMenu("Help")

        new_action = self._menu_action(file_menu, "New Session", self.close_structure, "Ctrl+N")
        open_action = self._menu_action(file_menu, "Open Structure…", self.open_file, "Ctrl+O")
        self._menu_action(file_menu, "Open Project…", enabled=False)
        recent = file_menu.addMenu("Recent Files")
        self._menu_action(recent, "No recent files", enabled=False)
        examples = file_menu.addMenu("Open Example")
        self._menu_action(examples, "Gehlenite — Ca₂Al₂SiO₇", self.open_demo)
        file_menu.addSeparator()
        import_menu = file_menu.addMenu("Import")
        self._menu_action(import_menu, "CIF", self.open_file)
        for label in ("POSCAR / CONTCAR", "SHELX RES / INS", "PDB", "XYZ"):
            self._menu_action(import_menu, label, self.open_file)
        export_menu = file_menu.addMenu("Export")
        snapshot_action = self._menu_action(export_menu, "Image…", self.save_screenshot, "Ctrl+Shift+S")
        for label in ("Animation", "Video", "STL", "GLTF", "OBJ"):
            self._menu_action(export_menu, label, enabled=False)
        self._menu_action(export_menu, "Current Analysis Table (CSV)…", self.export_analysis_csv)
        self._menu_action(export_menu, "Analysis Report (JSON)…", self.export_analysis_json)
        self.morphology_csv_action = self._menu_action(
            export_menu, "Morphology CSV…", self.export_morphology_table, enabled=False
        )
        self.morphology_json_action = self._menu_action(
            export_menu, "Morphology JSON…", self.export_morphology_json, enabled=False
        )
        self.morphology_png_action = self._menu_action(
            export_menu, "Morphology PNG…", self.export_morphology_image, enabled=False
        )
        file_menu.addSeparator()
        self.open_morphology_action = self._menu_action(
            file_menu, "Open Morphology Model…", self.open_morphology_model, enabled=False
        )
        self.save_morphology_action = self._menu_action(
            file_menu, "Save Morphology Model…", self.save_morphology_model, enabled=False
        )
        file_menu.addSeparator()
        self._menu_action(file_menu, "Save Project", enabled=False)
        self._menu_action(file_menu, "Save Project As…", enabled=False)
        file_menu.addSeparator()
        self._menu_action(file_menu, "Close Structure", self.close_structure)
        self._menu_action(file_menu, "Close Project", enabled=False)
        file_menu.addSeparator()
        self._menu_action(file_menu, "Preferences…", enabled=False)
        self._menu_action(file_menu, "Exit", self.close, "Ctrl+Q")

        for label in ("Undo", "Redo"):
            self._menu_action(edit_menu, label, enabled=False)
        edit_menu.addSeparator()
        for label in ("Copy Image", "Copy Structure", "Copy Selection"):
            self._menu_action(edit_menu, label, enabled=False)
        edit_menu.addSeparator()
        self._menu_action(edit_menu, "Find Object…", lambda: self.tree_filter.setFocus(), "Ctrl+F")
        self._menu_action(edit_menu, "Rename Block", enabled=False)

        representation = view_menu.addMenu("Representation")
        for label, level in REPRESENTATIONS:
            self._menu_action(representation, label, lambda _checked=False, value=level: self._show_level(value))
        camera = view_menu.addMenu("Camera")
        for label, callback in (
            ("Front", lambda: self._camera("front")),
            ("Back", lambda: self._camera("back")),
            ("Left", lambda: self._camera("left")),
            ("Right", lambda: self._camera("right")),
            ("Top", lambda: self._camera("top")),
            ("Bottom", lambda: self._camera("bottom")),
            ("Along a", lambda: self._command_viewer().view_axis("a")),
            ("Along b", lambda: self._command_viewer().view_axis("b")),
            ("Along c", lambda: self._command_viewer().view_axis("c")),
        ):
            self._menu_action(camera, label, callback)
        projection = view_menu.addMenu("Projection")
        self._menu_action(projection, "Perspective", lambda: self._command_viewer().plotter.disable_parallel_projection())
        self._menu_action(projection, "Orthographic", lambda: self._command_viewer().plotter.enable_parallel_projection())
        show = view_menu.addMenu("Show")
        for label, checkbox in (
            ("Unit Cell", self.cell_check),
            ("Axes", self.axes_check),
            ("Labels", self.labels_check),
        ):
            action = self._menu_action(show, label, checkable=True)
            action.setChecked(checkbox.isChecked())
            action.toggled.connect(checkbox.setChecked)
        connectors_action = self._menu_action(show, "Shared atoms / pivot candidates", checkable=True)
        connectors_action.setChecked(False)
        connectors_action.toggled.connect(lambda checked: self._set_show_check("connectors", checked))
        for label in ("Hydrogen", "Symmetry"):
            self._menu_action(show, label, enabled=False)
        color_menu = view_menu.addMenu("Color")
        for label in ("Element", "Structural unit", "Block", "Rigidity", "Motion", "Distortion"):
            enabled = label != "Motion" or self.series_report is not None
            self._menu_action(
                color_menu,
                f"By {label}",
                lambda _checked=False, value=label: self._set_color_mode(value),
                enabled=enabled,
            )
        view_menu.addSeparator()
        for label in ("Lighting", "Background", "Stereo"):
            self._menu_action(view_menu, label, enabled=False)
        self._menu_action(view_menu, "Fullscreen", self._toggle_fullscreen, "Ctrl+Shift+F")

        self._menu_action(structure_menu, "Supercell…", lambda: self.inspector_tabs.setCurrentIndex(2))
        for label in ("Wrap Atoms", "Primitive Cell", "Conventional Cell", "Expand Coordination"):
            self._menu_action(structure_menu, label, enabled=False)
        self._menu_action(structure_menu, "Recalculate Polyhedra", self._rebuild_hierarchy)
        self._menu_action(structure_menu, "Recalculate Bonds", self._rebuild_hierarchy)
        measure = structure_menu.addMenu("Measure")
        for label in ("Distance", "Angle", "Torsion", "Plane", "Volume", "Surface"):
            self._menu_action(measure, label, enabled=False)
        structure_menu.addSeparator()
        self._menu_action(structure_menu, "Hide from View", self._hide_selected, "Delete")
        self._menu_action(structure_menu, "Isolate Selected", self._isolate_selected)
        self._menu_action(structure_menu, "Restore Hidden Objects", self._restore_scene)

        for label in (
            "Detect Polyhedra",
            "Build Structural Units",
            "Detect Rigid Blocks",
            "Detect Shared Sites",
            "Generate Skeleton",
            "Generate Topology",
        ):
            self._menu_action(hierarchy_menu, label, self._rebuild_hierarchy)
        hierarchy_menu.addSeparator()
        self._menu_action(hierarchy_menu, "Rebuild Hierarchy", self._rebuild_hierarchy)
        for label in ("Edit Hierarchy", "Merge Blocks", "Split Block", "Lock Block", "Unlock Block"):
            self._menu_action(hierarchy_menu, label, enabled=False)
        hierarchy_menu.addSeparator()
        self._menu_action(hierarchy_menu, "Hierarchy Statistics", lambda: self.summary_bar.show())

        self._menu_action(analysis_menu, "Open Analysis Workspace", self.show_analysis_workspace, "Ctrl+Shift+A")
        self._menu_action(analysis_menu, "Return to Structure", self.show_structure_workspace, "Ctrl+Shift+V")
        analysis_menu.addSeparator()
        for label in ("Standard Structure Paper", "Inorganic / Mineral", "CRAFT Mechanics", "Full Report"):
            self._menu_action(analysis_menu, label, self.show_analysis_workspace)

        for label in (
            "Polyhedron Distortion",
            "Bond Statistics",
            "Angle Statistics",
            "Coordination",
            "Connectivity",
            "Ring Analysis",
            "Network Analysis",
            "Void Analysis",
            "Packing",
        ):
            self._menu_action(mechanics_menu, label, lambda: self.inspector_tabs.setCurrentIndex(0))
        mechanics_menu.addSeparator()
        for label in ("Rigidity Analysis", "Connector Flexibility", "DOF Analysis", "Framework Statistics"):
            self._menu_action(mechanics_menu, label, lambda: self.summary_bar.show())
        mechanics_menu.addSeparator()
        for label in ("Crystal Complexity", "Hierarchy Metrics"):
            self._menu_action(mechanics_menu, label, lambda: self.summary_bar.show())
        for label in ("Topological Fingerprint", "Block Fingerprint", "Structure Descriptor"):
            self._menu_action(mechanics_menu, label, enabled=False)

        for label in ("Compare Structures", "Temperature Series", "Pressure Series", "Composition Series"):
            self._menu_action(dynamics_menu, label, self.open_series)
        dynamics_menu.addSeparator()
        self.dynamics_motion_actions = []
        for label in ("Rigid Block Motion", "Rotation", "Translation", "Shear", "Connector Angles"):
            self.dynamics_motion_actions.append(
                self._menu_action(
                    dynamics_menu,
                    label,
                    lambda: self.output_dock.show(),
                    enabled=self.series_report is not None,
                )
            )
        dynamics_menu.addSeparator()
        for label in ("Animation", "Timeline", "Export Motion"):
            self._menu_action(dynamics_menu, label, enabled=False)

        for label in ("Database Browser", "CIF Validator", "Symmetry Finder", "Cell Transformation", "Coordinate Converter", "Tolerance Settings", "Plugin Manager"):
            self._menu_action(tools_menu, label, enabled=False)
        self._menu_action(tools_menu, "Python Console", lambda: self.output_dock.show())

        window_menu.addAction(self.output_dock.toggleViewAction())
        summary_action = self._menu_action(window_menu, "Summary", checkable=True)
        summary_action.setChecked(True)
        summary_action.toggled.connect(self.summary_bar.setVisible)
        self._menu_action(window_menu, "Reset Layout", lambda: self.statusBar().showMessage("Default layout restored"))
        self._menu_action(window_menu, "Tile Windows", enabled=False)

        for label in ("User Guide", "Tutorials", "Hot Keys"):
            self._menu_action(help_menu, label, enabled=False)
        self._menu_action(help_menu, "Open Gehlenite Example", self.open_demo)
        self._menu_action(help_menu, "More XRD tools…", self._open_toolkit_catalog)
        self._menu_action(help_menu, "About CRAFT", self._about)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        series_action = QAction("Open Series…", self)
        series_action.triggered.connect(self.open_series)
        open_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        series_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        snapshot_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        toolbar.addActions((open_action, series_action, snapshot_action))
        toolbar.addSeparator()
        for axis in ("a", "b", "c"):
            action = QAction(axis, self)
            action.triggered.connect(lambda _checked=False, value=axis: self._command_viewer().view_axis(value))
            toolbar.addAction(action)
        toolbar.addSeparator()
        fit_action = QAction("Fit", self)
        fit_action.triggered.connect(lambda: self._command_viewer().plotter.reset_camera())
        toolbar.addAction(fit_action)
        zoom_in_action = QAction("Zoom +", self)
        zoom_in_action.triggered.connect(lambda: self._command_viewer().zoom(1.2))
        toolbar.addAction(zoom_in_action)
        zoom_out_action = QAction("Zoom −", self)
        zoom_out_action.triggered.connect(lambda: self._command_viewer().zoom(1.0 / 1.2))
        toolbar.addAction(zoom_out_action)
        toolbar.addSeparator()
        self.edit_mode_action = QAction("Select", self)
        self.edit_mode_action.setCheckable(True)
        self.edit_mode_action.setShortcut(QKeySequence("E"))
        self.edit_mode_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.edit_mode_action.setToolTip(
            "Selection mode (E); hold A/B/P/U/R to choose the object type"
        )
        self.edit_mode_action.toggled.connect(
            lambda checked: self._command_viewer().set_edit_mode(checked)
        )
        if "viewer" in self.__dict__:
            self.viewer.edit_mode_changed.connect(self.edit_mode_action.setChecked)
        toolbar.addAction(self.edit_mode_action)
        toolbar.addSeparator()
        hide_action = QAction("Hide", self)
        hide_action.setToolTip("Hide selected hierarchy objects from the view; CIF stays unchanged")
        hide_action.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        hide_action.triggered.connect(self._hide_selected)
        toolbar.addAction(hide_action)
        isolate_action = QAction("Isolate", self)
        isolate_action.triggered.connect(self._isolate_selected)
        toolbar.addAction(isolate_action)
        restore_action = QAction("Restore", self)
        restore_action.triggered.connect(self._restore_scene)
        toolbar.addAction(restore_action)
        toolbar.addWidget(QLabel("  Hierarchy level  "))
        self.toolbar_view_combo = QComboBox()
        for label, level in REPRESENTATIONS:
            self.toolbar_view_combo.addItem(label, level.value)
        self.toolbar_view_combo.currentIndexChanged.connect(
            lambda index: self._show_level(HierarchyLevel(self.toolbar_view_combo.itemData(index)))
        )
        toolbar.addWidget(self.toolbar_view_combo)
        self.addToolBar(toolbar)
        self._update_morphology_actions()

    def _update_morphology_actions(self, *_args) -> None:
        has_structure = self.structure is not None
        has_result = has_structure and self.morphology_workspace.current_model is not None
        for action in (
            self.open_morphology_action,
            self.save_morphology_action,
        ):
            action.setEnabled(has_structure)
        for action in (
            self.morphology_csv_action,
            self.morphology_json_action,
            self.morphology_png_action,
        ):
            action.setEnabled(has_result)

    def _menu_action(
        self,
        menu,
        text: str,
        callback=None,
        shortcut: str | None = None,
        enabled: bool = True,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.setEnabled(enabled)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(shortcut)
        if callback is not None:
            action.triggered.connect(callback)
        menu.addAction(action)
        return action

    def close_structure(self) -> None:
        self.structure = None
        self.hierarchy = None
        self.series_report = None
        self.current_path = None
        self.object_tree.clear()
        self.selected_title.setText("Nothing selected")
        self.selected_analysis.setText("Choose an object in the hierarchy tree.")
        self._clear_local_environment()
        self.cell_summary.setText("No structure")
        for value in self.dashboard_values.values():
            value.setText("—")
        self.viewer.structure = None
        self.viewer.scene = None
        self.viewer.hierarchy = None
        self.viewer.reset_visibility(redraw=False)
        self.viewer.redraw()
        self.morphology_workspace.viewer.clear()
        self.morphology_workspace.current_model = None
        self.morphology_workspace.current_calculation = None
        self._update_morphology_actions()
        self.statusBar().showMessage("New empty session")

    def closeEvent(self, event: QCloseEvent) -> None:
        MainWindow._close_comparison_requests(self)
        MainWindow._close_structure_load_requests(self)
        self.morphology_workspace.close_requests()
        super().closeEvent(event)

    def _camera(self, direction: str) -> None:
        viewer = self._command_viewer()
        mapping = {
            "front": (viewer.plotter.view_xz, False),
            "back": (viewer.plotter.view_xz, True),
            "left": (viewer.plotter.view_yz, False),
            "right": (viewer.plotter.view_yz, True),
            "top": (viewer.plotter.view_xy, False),
            "bottom": (viewer.plotter.view_xy, True),
        }
        callback, negative = mapping[direction]
        callback(negative=negative)
        viewer.plotter.reset_camera()

    def _command_viewer(self) -> StructureViewer:
        if self.dual_viewer is not None and self.viewer_stack.currentWidget() is self.dual_viewer:
            return self.dual_viewer.active_viewer or self.dual_viewer.left
        return self.viewer

    def _set_show_check(self, key: str, checked: bool) -> None:
        self.show_checks[key].setChecked(checked)

    def _set_color_mode(self, label: str) -> None:
        index = self.color_combo.findText(label)
        if index >= 0:
            self.color_combo.setCurrentIndex(index)

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _rebuild_hierarchy(self) -> None:
        if self.structure is None:
            return
        self.hierarchy = self.analyzer.analyze(self.structure)
        self._rebuild_scene(reset_camera=False)
        self._refresh_models()
        self.statusBar().showMessage("Mechanical hierarchy rebuilt")

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About CRAFT",
            "CRAFT — Crystal Representation, Analysis, Frameworks & Topology\n\n"
            "Hierarchy-first structural mechanics for crystals.\n"
            "Atoms → polyhedra → structural units → rigid blocks → connectors → topology.",
        )

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open crystal structure",
            "",
            "Crystal structures (*.cif *.xpff *.res *.ins *.vasp *.pdb *.xyz POSCAR CONTCAR);;"
            "CIF files (*.cif);;XRD Finder projects (*.xpff);;SHELX files (*.res *.ins);;"
            "VASP files (*.vasp POSCAR CONTCAR);;PDB files (*.pdb);;XYZ files (*.xyz);;All files (*)",
        )
        if path:
            self.load_path(path)

    def open_demo(self) -> None:
        self.load_path(GEHLENITE_DEMO)

    def open_series(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open structure series", "", "CIF files (*.cif)")
        if len(paths) >= 2:
            self.load_series(paths)

    def load_path(self, path: str | Path) -> None:
        source_path = Path(path).expanduser().resolve()
        generation = getattr(self, "_structure_load_generation", 0) + 1
        self._structure_load_generation = generation
        signature = (generation, str(source_path))
        self._active_structure_load_signature = signature
        self._structure_load_document_ids = {
            key: value
            for key, value in getattr(self, "_structure_load_document_ids", {}).items()
            if key[0] == signature
        }
        self.series_report = None
        self.current_path = source_path
        self.statusBar().showMessage(f"Reading {source_path.name}…")
        manager = getattr(self, "_structure_load_requests", None)
        if manager is None:
            try:
                for update in iter_load_updates(source_path):
                    MainWindow._structure_load_progress(self, signature, update)
            except BaseException as error:
                MainWindow._structure_load_failed(self, signature, error)
            else:
                MainWindow._structure_load_ready(self, signature)
            return

        def work(progressed) -> None:
            for update in iter_load_updates(source_path):
                progressed(update)

        manager.request(
            signature,
            work,
        )

    def _initialize_structure_load_requests(self, executor) -> None:
        self._accept_structure_load_results = True
        self._structure_load_generation = 0
        self._structure_load_document_ids: dict[tuple[object, int], str] = {}
        self._structure_load_requests = StructureLoadRequestManager(
            executor,
            lambda signature, update: MainWindow._structure_load_progress(
                self, signature, update
            ),
            lambda signature: MainWindow._structure_load_ready(self, signature),
            lambda signature, error: MainWindow._structure_load_failed(
                self, signature, error
            ),
        )

    def _close_structure_load_requests(self, timeout_ms: int = 100) -> bool:
        self._accept_structure_load_results = False
        manager = getattr(self, "_structure_load_requests", None)
        return True if manager is None else manager.close(timeout_ms)

    def _structure_load_progress(
        self,
        signature: tuple[object, ...],
        update: StructureLoadUpdate,
    ) -> None:
        if (
            not getattr(self, "_accept_structure_load_results", True)
            or signature != getattr(self, "_active_structure_load_signature", signature)
        ):
            return
        key = (signature, update.structure_index)
        if update.stage is LoadStage.PARSED:
            document = StructureDocument.from_preview(update.structure)
            if update.structure_count > 1:
                document.id = f"{document.id}-{update.structure_index + 1}"
            self.collection.add(document)
            self._structure_load_document_ids[key] = document.id
            self.active_document_id = document.id
            self.structure = document.structure
            self.hierarchy = document.hierarchy
            update_actions = getattr(self, "_update_morphology_actions", None)
            if update_actions is not None:
                update_actions()
            self._rebuild_scene(reset_camera=True)
            self._refresh_loading_models(document)
        else:
            document_id = self._structure_load_document_ids.get(key)
            document = self.collection.documents.get(document_id or "")
            if document is None:
                return
            if update.organic_bundle is not None:
                previous_bonds = document.periodic_bonds
                document.install_organic_bundle(update.organic_bundle)
                if document.id == self.active_document_id:
                    self.structure = document.structure
                    self.hierarchy = document.hierarchy
                    if document.periodic_bonds is not previous_bonds:
                        self._rebuild_scene(reset_camera=False)
                    self._refresh_loading_models(document)
                else:
                    self._fill_hierarchy_tree()
            elif update.snapshot is None:
                return
            else:
                previous_hierarchy = document.hierarchy
                previous_bonds = document.periodic_bonds
                document.install_analysis_snapshot(update.snapshot)
                if document.id == self.active_document_id:
                    self.structure = document.structure
                    self.hierarchy = document.hierarchy
                    topology_visible = (
                        getattr(getattr(self, "viewer", None), "level", None)
                        == HierarchyLevel.TOPOLOGY
                    )
                    scene_changed = (
                        update.snapshot.hierarchy is not previous_hierarchy
                        or update.snapshot.periodic_bonds is not previous_bonds
                        or (update.stage is LoadStage.TOPOLOGY and topology_visible)
                    )
                    if scene_changed:
                        self._rebuild_scene(reset_camera=False)
                    if update.stage is LoadStage.TOPOLOGY:
                        self._refresh_models()
                        if self.comparison_mode_stack.currentWidget() is self.morphology_workspace:
                            self.morphology_workspace.set_document(document)
                    else:
                        self._refresh_loading_models(document)
                else:
                    self._fill_hierarchy_tree()
        labels = {
            LoadStage.PARSED: "Atoms ready · calculating bonds…",
            LoadStage.BONDS: "Bonds ready · calculating polyhedra…",
            LoadStage.POLYHEDRA: "Polyhedra ready · calculating structural units…",
            LoadStage.UNITS: "Structural units ready · calculating topology…",
            LoadStage.TOPOLOGY: "Structure analysis ready",
            LoadStage.BONDS_PROFILE: "Bonds and profile ready · finding molecules…",
            LoadStage.COMPONENTS: "Molecules and rings ready · finding contacts…",
            LoadStage.CONTACTS: "Contacts ready · analyzing packing…",
            LoadStage.PACKING: "Packing analysis ready",
            LoadStage.RETICULAR: "Reticular analysis ready",
        }
        position = (
            f" ({update.structure_index + 1}/{update.structure_count})"
            if update.structure_count > 1
            else ""
        )
        self.statusBar().showMessage(f"{update.source_path.name}{position} · {labels[update.stage]}")

    def _refresh_loading_models(self, document: StructureDocument) -> None:
        self._fill_hierarchy_tree()
        self.sites_panel.set_document(document)
        self._fill_cell()
        self._fill_dashboard()

    def _structure_load_ready(self, signature: tuple[object, ...]) -> None:
        if signature != getattr(self, "_active_structure_load_signature", signature):
            return
        count = sum(1 for key in self._structure_load_document_ids if key[0] == signature)
        count_note = f" · {count} structures" if count > 1 else ""
        name = Path(str(signature[-1])).name
        self.statusBar().showMessage(f"Loaded {name}{count_note} · mechanical hierarchy ready")

    def _structure_load_failed(
        self,
        signature: tuple[object, ...],
        error: BaseException,
    ) -> None:
        if signature != getattr(self, "_active_structure_load_signature", signature):
            return
        name = Path(str(signature[-1])).name
        self.statusBar().showMessage(f"Cannot open {name}: {error}")

    def _register_document(
        self,
        structure: CrystalStructure,
        hierarchy: HierarchyReport,
        structural_analysis=None,
    ) -> StructureDocument:
        document = StructureDocument.from_structure(
            structure,
            hierarchy,
            structural_analysis,
        )
        self.collection.add(document)
        self.active_document_id = document.id
        self.structure = document.structure
        self.hierarchy = document.hierarchy
        update_actions = getattr(self, "_update_morphology_actions", None)
        if update_actions is not None:
            update_actions()
        return document

    def load_series(self, paths: list[str] | tuple[str, ...]) -> None:
        try:
            structures = [load_cif(path) for path in paths]
            hierarchy = self.analyzer.analyze(structures[0])
            report = analyze_structure_series(
                structures,
                hierarchy,
                [Path(path).stem for path in paths],
            )
        except Exception as error:
            QMessageBox.critical(self, "Cannot analyze series", str(error))
            return
        self.structure = structures[0]
        self.hierarchy = hierarchy
        self.series_report = report
        for action in self.dynamics_motion_actions:
            action.setEnabled(True)
        self.current_path = Path(paths[0])
        self._rebuild_scene(reset_camera=True)
        self._refresh_models()
        self.output_dock.show()
        self.statusBar().showMessage(f"Mechanics {report.start_label} → {report.end_label}")

    def _refresh_models(self) -> None:
        self._fill_hierarchy_tree()
        document = self.collection.documents.get(self.active_document_id or "")
        if document is not None:
            self.sites_panel.set_document(document)
        self._fill_cell()
        self._fill_dashboard()
        self._fill_dynamics()
        self._fill_output()
        self.analysis_report = StructureReportBuilder(self.structure).build()
        self.analysis_workspace.set_report(self.analysis_report)

    def show_analysis_workspace(self) -> None:
        if self.structure is None:
            QMessageBox.information(self, "Structural Analysis", "Open a CIF structure first.")
            return
        self.central_stack.setCurrentWidget(self.analysis_workspace)
        self.statusBar().showMessage("Structural analysis workspace")

    def show_structure_workspace(self) -> None:
        self.central_stack.setCurrentWidget(self.structure_workspace)
        self.statusBar().showMessage("3D structure workspace")

    def export_analysis_csv(self, table_id: str | None = None) -> None:
        report = getattr(self, "analysis_report", None)
        if report is None:
            QMessageBox.information(self, "Export analysis", "Open a CIF structure first.")
            return
        if not isinstance(table_id, str) or not table_id:
            current = self.analysis_workspace.catalogue.currentItem()
            table_id = current.data(0, Qt.ItemDataRole.UserRole) if current is not None else ""
        if not table_id or table_id not in report.tables:
            QMessageBox.information(self, "Export analysis", "Select an available table first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export analysis table",
            f"{table_id}.csv",
            "CSV files (*.csv)",
        )
        if path:
            try:
                table = report.table(table_id)
                model = self.analysis_workspace._models.get(table_id)
                if model is not None:
                    table = replace(table, rows=tuple(model.rows))
                export_table_csv(table, path)
            except ValueError as error:
                QMessageBox.warning(self, "Cannot export table", str(error))

    def export_analysis_json(self) -> None:
        report = getattr(self, "analysis_report", None)
        if report is None:
            QMessageBox.information(self, "Export analysis", "Open a CIF structure first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export structural analysis report",
            "structure-analysis.json",
            "JSON files (*.json)",
        )
        if path:
            selected_ids = self.analysis_workspace.selected_table_ids()
            selected_tables = {
                table_id: report.tables[table_id]
                for table_id in selected_ids
                if table_id in report.tables
            }
            export_report_json(replace(report, tables=selected_tables), path)

    def save_morphology_model(self) -> None:
        if self.structure is None:
            self.statusBar().showMessage("Open a CIF structure before saving morphology")
            return
        source = self.current_path or self.structure.source_path
        default = (
            str(Path(source).with_suffix(".morphology.json"))
            if source is not None
            else f"{self.structure.name}.morphology.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save morphology model",
            default,
            "Morphology JSON (*.morphology.json *.json)",
        )
        if not path:
            return
        try:
            save_morphology_state(path, self.structure, self.morphology_workspace.state)
        except (OSError, TypeError, ValueError) as error:
            self.morphology_workspace.show_error(str(error))
            return
        self.statusBar().showMessage(f"Saved morphology model: {Path(path).name}")

    def open_morphology_model(self) -> None:
        if self.structure is None:
            self.statusBar().showMessage("Open a CIF structure before loading morphology")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open morphology model",
            "",
            "Morphology JSON (*.morphology.json *.json)",
        )
        if not path:
            return
        try:
            loaded = load_morphology_state(path, self.structure)
        except (OSError, TypeError, ValueError) as error:
            self.morphology_workspace.show_error(str(error))
            return
        if not loaded.compatible:
            self.morphology_workspace.offer_incompatible_state(loaded.state, loaded.message)
            return
        document = self.collection.documents.get(self.active_document_id)
        if document is None:
            return
        document.morphology_state = loaded.state
        self.morphology_workspace.set_document(document)
        self.statusBar().showMessage(f"Loaded morphology model: {Path(path).name}")

    def export_morphology_table(self) -> None:
        model = self.morphology_workspace.current_model
        if model is None:
            self.morphology_workspace.show_error("No valid morphology result is available for export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export morphology table",
            "morphology.csv",
            "CSV files (*.csv)",
        )
        if path:
            try:
                calculation = self.morphology_workspace.current_calculation
                export_morphology_csv(
                    path,
                    model,
                    reference_model=(None if calculation is None else calculation.reference_model),
                    state=self.morphology_workspace.state,
                    color_by_family=(None if calculation is None else calculation.color_by_family),
                    aggregate=(None if calculation is None else calculation.twin_aggregate),
                )
            except OSError as error:
                self.morphology_workspace.show_error(str(error))

    def export_morphology_json(self) -> None:
        model = self.morphology_workspace.current_model
        if model is None:
            self.morphology_workspace.show_error("No valid morphology result is available for export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export morphology data",
            "morphology.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        calculation = self.morphology_workspace.current_calculation
        try:
            export_morphology_json(
                path,
                model,
                state=self.morphology_workspace.state,
                reference_model=(None if calculation is None else calculation.reference_model),
                color_by_family=(None if calculation is None else calculation.color_by_family),
                aggregate=(None if calculation is None else calculation.twin_aggregate),
            )
        except (OSError, TypeError, ValueError) as error:
            self.morphology_workspace.show_error(str(error))

    def export_morphology_image(self) -> None:
        if self.morphology_workspace.current_model is None:
            self.morphology_workspace.show_error("No valid morphology result is available for export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export morphology image",
            "morphology.png",
            "PNG images (*.png)",
        )
        if path:
            try:
                self.morphology_workspace.viewer.export_png(path)
            except (OSError, RuntimeError) as error:
                self.morphology_workspace.show_error(str(error))

    def _fill_hierarchy_tree(self) -> None:
        self.object_tree.set_collection(self.collection)
        self.compare_structures_button.setEnabled(
            len(self.collection.documents) > 1 and len(self.collection.compared_ids) == 2
        )

    @staticmethod
    def _color_icon(color: str) -> QIcon:
        pixmap = QPixmap(12, 12)
        pixmap.fill(QColor(color))
        return QIcon(pixmap)

    def _filter_tree(self, text: str) -> None:
        needle = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            child_match = any(visit(item.child(index)) for index in range(item.childCount()))
            search_text = item.data(0, HierarchyTree.SearchTextRole) or item.text(0)
            own_match = not needle or needle in str(search_text).lower()
            visible = own_match or child_match
            item.setHidden(not visible)
            if needle and child_match:
                item.setExpanded(True)
            return visible

        for index in range(self.object_tree.topLevelItemCount()):
            visit(self.object_tree.topLevelItem(index))

    def _activate_document(self, document_id: str) -> None:
        if document_id == self.active_document_id:
            return
        document = self.collection.documents.get(document_id)
        if document is None:
            return
        self.active_document_id = document_id
        self.structure = document.structure
        self.hierarchy = document.hierarchy
        self.series_report = None
        self.current_path = document.structure.source_path
        self.sites_panel.set_document(document)
        update_actions = getattr(self, "_update_morphology_actions", None)
        if update_actions is not None:
            update_actions()
        self._rebuild_scene(reset_camera=True)
        self._fill_cell()
        self._fill_dashboard()
        self._fill_dynamics()
        self._fill_output()
        self.analysis_report = StructureReportBuilder(self.structure).build()
        self.analysis_workspace.set_report(self.analysis_report)
        if self.comparison_mode_stack.currentWidget() is self.morphology_workspace:
            self.morphology_workspace.set_document(document)

    def _assign_visual_slot(self, slot: str, document_id: str) -> None:
        self.collection.assign_visual(slot, document_id)
        pair = self.collection.visual_pair()
        if pair is not None:
            self._show_visual_pair(pair)
        self.statusBar().showMessage(f"Structure {slot}: {self.collection.documents[document_id].structure.name}")

    def show_single_document(self, document_id: str) -> None:
        self._activate_document(document_id)
        MainWindow._set_sites_comparison_locked(self, False)
        self.viewer_stack.setCurrentWidget(self.viewer)

    def _set_sites_comparison_locked(self, locked: bool) -> None:
        panel = getattr(self, "sites_panel", None)
        if panel is not None:
            panel.set_comparison_locked(locked)

    def _comparison_mode_tab_changed(self, index: int) -> None:
        if index == 1:
            self.show_compare_workspace()
            return
        self.comparison_mode_stack.setCurrentWidget(self.comparison_visual_page)

    def _set_comparison_mode(self, widget: QWidget, tab_index: int) -> None:
        self.comparison_mode_stack.setCurrentWidget(widget)
        self.comparison_mode_tabs.blockSignals(True)
        self.comparison_mode_tabs.setCurrentIndex(tab_index)
        self.comparison_mode_tabs.blockSignals(False)

    def _set_comparison_tabs_visible(self, visible: bool) -> None:
        self.comparison_mode_tabs.setVisible(visible)

    def _initialize_comparison_requests(self, executor) -> None:
        self._accept_comparison_results = True
        self._comparison_requests = ComparisonRequestManager(
            executor,
            lambda signature, bundle: MainWindow._comparison_ready(
                self, signature, bundle
            ),
            lambda signature, error: MainWindow._comparison_failed(
                self, signature, error
            ),
        )

    def _close_comparison_requests(self, timeout_ms: int = 100) -> bool:
        self._accept_comparison_results = False
        manager = getattr(self, "_comparison_requests", None)
        return True if manager is None else manager.close(timeout_ms)

    @staticmethod
    def _compute_comparison_bundle(
        documents: tuple[StructureDocument, StructureDocument],
        limits: MatchLimits,
    ) -> tuple[ComparisonReport, MotifComparisonReport]:
        motif_report = cached_compare(*documents, limits=limits)
        report = compare_documents(documents, motif_report=motif_report)
        return report, motif_report

    def _request_comparison_bundle(
        self,
        documents: tuple[StructureDocument, StructureDocument],
    ) -> None:
        signature = MainWindow._comparison_signature(self, documents)
        manager = getattr(self, "_comparison_requests", None)
        if manager is None:
            try:
                bundle = MainWindow._comparison_bundle(self, documents)
            except BaseException as error:
                MainWindow._comparison_failed(self, signature, error)
            else:
                MainWindow._comparison_ready(self, signature, bundle)
            return
        limits = getattr(self, "comparison_limits", APPLICATION_COMPARISON_LIMITS)
        manager.request(
            signature,
            lambda: MainWindow._compute_comparison_bundle(documents, limits),
        )

    def _comparison_is_current(self, signature: tuple[object, ...]) -> bool:
        pair = self.collection.visual_pair()
        return (
            pair is not None
            and signature == MainWindow._comparison_signature(self, pair)
        )

    @staticmethod
    def _comparison_outcome_status(motif_report: object) -> str:
        if bool(getattr(motif_report, "exact", False)):
            return "Exact comparison ready"
        if bool(getattr(motif_report, "approximate", False)):
            reasons = tuple(getattr(motif_report, "limit_reasons", ()))
            suffix = f" · {', '.join(reasons)}" if reasons else ""
            return f"Approximate comparison ready{suffix}"
        if bool(getattr(motif_report, "ambiguous", False)):
            return "Non-exact comparison ready · ambiguous"
        return "Comparison ready"

    def _set_comparison_status(self, text: str, *, loading: bool = False) -> None:
        dual_viewer = getattr(self, "dual_viewer", None)
        set_dual_status = getattr(dual_viewer, "set_comparison_status", None)
        if callable(set_dual_status):
            set_dual_status(text)
        workspace = getattr(self, "compare_workspace", None)
        set_workspace_status = getattr(
            workspace,
            "set_loading" if loading else "set_status",
            None,
        )
        if callable(set_workspace_status):
            set_workspace_status(text)
        self.statusBar().showMessage(text)

    def _comparison_ready(
        self,
        signature: tuple[object, ...],
        bundle: tuple[ComparisonReport, MotifComparisonReport],
    ) -> None:
        if not getattr(self, "_accept_comparison_results", True):
            return
        if not MainWindow._comparison_is_current(self, signature):
            return
        report, motif_report = bundle
        self._active_comparison_signature = signature
        self._active_comparison_bundle = bundle
        self.compare_workspace.set_report(report)
        dual_viewer = getattr(self, "dual_viewer", None)
        active_ids = (
            getattr(getattr(dual_viewer, "first_document", None), "id", None),
            getattr(getattr(dual_viewer, "second_document", None), "id", None),
        )
        if active_ids == report.document_ids:
            set_motif_report = getattr(dual_viewer, "set_motif_report", None)
            if (
                callable(set_motif_report)
                and getattr(
                    self,
                    "_installed_comparison_visual_signature",
                    None,
                )
                != signature
            ):
                set_motif_report(motif_report)
                self._installed_comparison_visual_signature = signature
        MainWindow._set_comparison_status(
            self,
            MainWindow._comparison_outcome_status(motif_report),
        )

    def _comparison_failed(
        self,
        signature: tuple[object, ...],
        error: BaseException,
    ) -> None:
        if not getattr(self, "_accept_comparison_results", True):
            return
        if not MainWindow._comparison_is_current(self, signature):
            return
        MainWindow._set_comparison_status(
            self,
            f"Comparison failed: {error}",
        )

    def _show_visual_pair(
        self,
        pair: tuple[StructureDocument, StructureDocument],
    ) -> None:
        dual_viewer = self._ensure_dual_viewer() if self.dual_viewer is None else self.dual_viewer
        dual_viewer.set_pair(*pair)
        MainWindow._set_sites_comparison_locked(self, True)
        self._installed_comparison_visual_signature = None
        MainWindow._apply_dual_label_settings(self, dual_viewer)
        self.viewer_stack.setCurrentWidget(dual_viewer)
        self.central_stack.setCurrentWidget(self.structure_workspace)
        self._set_comparison_tabs_visible(True)
        self._set_comparison_mode(self.comparison_visual_page, 0)
        MainWindow._set_comparison_status(self, "Comparing structures…", loading=True)
        MainWindow._request_comparison_bundle(self, pair)

    def _comparison_bundle(
        self,
        documents: tuple[StructureDocument, StructureDocument],
    ) -> tuple[ComparisonReport, MotifComparisonReport]:
        limits = getattr(self, "comparison_limits", APPLICATION_COMPARISON_LIMITS)
        signature = MainWindow._comparison_signature(self, documents)
        if signature == getattr(self, "_active_comparison_signature", None):
            return self._active_comparison_bundle
        motif_report = cached_compare(*documents, limits=limits)
        report = compare_documents(documents, motif_report=motif_report)
        bundle = (report, motif_report)
        self._active_comparison_signature = signature
        self._active_comparison_bundle = bundle
        return bundle

    def _comparison_signature(
        self,
        documents: tuple[StructureDocument, StructureDocument],
    ) -> tuple[object, ...]:
        limits = getattr(self, "comparison_limits", APPLICATION_COMPARISON_LIMITS)
        return (
            documents[0].id,
            documents[0].content_identity(),
            documents[1].id,
            documents[1].content_identity(),
            limits,
        )

    def show_visual_comparison(self) -> None:
        pair = self.collection.visual_pair()
        if pair is None:
            QMessageBox.information(self, "Visual comparison", "Assign structures to both A and B first.")
            return
        self._show_visual_pair(pair)

    def _ensure_dual_viewer(self) -> DualStructureViewer:
        if self.dual_viewer is None:
            self.dual_viewer = DualStructureViewer()
            self.dual_viewer.table_requested.connect(self.show_compare_workspace)
            self.dual_viewer.pair_swapped.connect(self._dual_pair_swapped)
            dropped = getattr(self.dual_viewer, "cif_files_dropped", None)
            if dropped is not None:
                dropped.connect(self._load_dropped_cifs)
            self.viewer_stack.addWidget(self.dual_viewer)
        return self.dual_viewer

    def _dual_pair_swapped(self, first_id: str, second_id: str) -> None:
        first = self.collection.documents.get(first_id)
        second = self.collection.documents.get(second_id)
        if first is None or second is None:
            return
        self.collection.assign_visual("A", first_id)
        self.collection.assign_visual("B", second_id)
        self._installed_comparison_visual_signature = None
        MainWindow._set_comparison_status(self, "Comparing structures…", loading=True)
        MainWindow._request_comparison_bundle(self, (first, second))

    @staticmethod
    def _apply_dual_label_settings(window, dual_viewer: DualStructureViewer) -> None:
        dual_viewer.set_show_labels(
            window.labels_check.isChecked(),
            window.pivot_labels_check.isChecked(),
        )

    def _toggle_compare_document(self, document_id: str, enabled: bool) -> None:
        try:
            self.collection.set_compared(document_id, enabled)
        except ValueError as error:
            self.statusBar().showMessage(str(error))
        self.compare_structures_button.setEnabled(
            len(self.collection.documents) > 1 and len(self.collection.compared_ids) == 2
        )

    def show_selected_comparison(self) -> None:
        documents = self.collection.compared_documents()
        if len(documents) != 2:
            QMessageBox.information(self, "Compare structures", "Select exactly two structures in the tree.")
            return
        self.collection.assign_visual("A", documents[0].id)
        self.collection.assign_visual("B", documents[1].id)
        self._show_visual_pair(documents)
        self.object_tree.set_collection(self.collection)

    def show_compare_workspace(self) -> None:
        documents = self.collection.visual_pair()
        if documents is None:
            selected_documents = self.collection.compared_documents()
            if len(selected_documents) != 2:
                QMessageBox.information(self, "Comparison table", "Select exactly two structures in the tree.")
                return
            documents = selected_documents
            self.collection.assign_visual("A", documents[0].id)
            self.collection.assign_visual("B", documents[1].id)
        self.central_stack.setCurrentWidget(self.structure_workspace)
        MainWindow._set_sites_comparison_locked(self, True)
        self._set_comparison_tabs_visible(self.collection.visual_pair() is not None)
        self._set_comparison_mode(self.compare_workspace, 1)
        MainWindow._set_comparison_status(self, "Comparing structures…", loading=True)
        MainWindow._request_comparison_bundle(self, documents)

    def _focus_comparison(self, command) -> None:
        dual_viewer = self._ensure_dual_viewer() if self.dual_viewer is None else self.dual_viewer
        pair = self.collection.visual_pair()
        if pair is not None:
            current_pair = (
                getattr(dual_viewer, "first_document", None),
                getattr(dual_viewer, "second_document", None),
            )
            if current_pair != pair:
                dual_viewer.set_pair(*pair)
                self._installed_comparison_visual_signature = None
                MainWindow._set_comparison_status(
                    self,
                    "Comparing structures…",
                    loading=True,
                )
                MainWindow._request_comparison_bundle(self, pair)
        MainWindow._apply_dual_label_settings(self, dual_viewer)
        MainWindow._set_sites_comparison_locked(self, True)
        self.central_stack.setCurrentWidget(self.structure_workspace)
        self.viewer_stack.setCurrentWidget(dual_viewer)
        self._set_comparison_tabs_visible(self.collection.visual_pair() is not None)
        self._set_comparison_mode(self.comparison_visual_page, 0)
        dual_viewer.focus(command)

    def export_comparison_csv(self) -> None:
        report = getattr(self.compare_workspace, "report", None)
        if report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export comparison", "structure-comparison.csv", "CSV files (*.csv)")
        if path:
            export_comparison_csv(report, path)

    def export_comparison_json(self) -> None:
        report = getattr(self.compare_workspace, "report", None)
        if report is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export comparison", "structure-comparison.json", "JSON files (*.json)")
        if path:
            export_comparison_json(report, path)

    def export_comparison_images(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export comparison images", "structure-comparison.png", "PNG images (*.png)")
        if not path:
            return
        target = Path(path)
        dual_viewer = self._ensure_dual_viewer() if self.dual_viewer is None else self.dual_viewer
        dual_viewer.save_images(
            target.with_name(f"{target.stem}-A.png"),
            target.with_name(f"{target.stem}-B.png"),
        )

    def _set_document_visibility(
        self,
        document_id: str,
        kind: str,
        object_id: object,
        visible: bool,
    ) -> None:
        document = self.collection.documents.get(document_id)
        if document is None:
            return
        attributes = {
            "atom": "hidden_atom_indices",
            "polyhedron": "hidden_polyhedron_ids",
            "unit": "hidden_unit_ids",
            "block": "hidden_block_ids",
            "connector": "hidden_connector_ids",
        }
        attribute = attributes.get(kind)
        if attribute is None:
            return
        hidden = getattr(document.visual, attribute)
        value = int(object_id) if kind == "atom" else str(object_id)
        hidden.discard(value) if visible else hidden.add(value)
        if document_id == self.active_document_id:
            viewer_hidden = getattr(self.viewer, attribute)
            viewer_hidden.discard(value) if visible else viewer_hidden.add(value)
            self.viewer.redraw(reset_camera=False)

    def _hierarchy_object_selected(
        self,
        document_id: str,
        kind: str,
        object_id: object,
    ) -> None:
        self._picked_scene_object = None
        self._picked_polyhedron_id = None
        self.viewer.selected_scene_object = None
        self.viewer.selected_polyhedron_id = None
        self._activate_document(document_id)
        if self.hierarchy is None:
            return
        if kind == "level":
            self._show_level(HierarchyLevel(object_id))
        elif kind == "category":
            category = str(object_id)
            self.sites_panel.set_category(category)
            self.viewer.edit_default_kind = {
                "atoms": "atom",
                "bonds": "bond",
                "polyhedra": "polyhedron",
                "units": "unit",
                "blocks": "block",
            }.get(category, self.viewer.edit_default_kind)
            self._show_level(
                HierarchyLevel.TOPOLOGY if category == "topology" else HierarchyLevel.SITES
            )
        elif kind == "block":
            self._show_level(HierarchyLevel.RIGID_BLOCKS)
            self._analyze_block(str(object_id))
        elif kind == "connector":
            self._show_level(HierarchyLevel.FRAMEWORK)
            self._analyze_connector(str(object_id))
        elif kind == "polyhedron":
            self._show_level(HierarchyLevel.POLYHEDRA)
            self._analyze_polyhedron(str(object_id))
        elif kind == "unit":
            self._show_level(HierarchyLevel.STRUCTURAL_UNITS)
            self._analyze_unit(str(object_id))
        elif kind == "interpretation":
            self._show_interpretation(str(object_id))
        elif kind == "atom":
            self._show_level(HierarchyLevel.ATOMS)
            self._analyze_atom(int(object_id))
        elif kind == "cell":
            self._analyze_cell()

    @staticmethod
    def _level_node(label: str, level: HierarchyLevel) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, ("level", level.value))
        return item

    def _object_selected(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if current is None or self.hierarchy is None:
            return
        payload = current.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        if len(payload) == 3:
            self._hierarchy_object_selected(*payload)
        else:
            kind, object_id = payload
            if self.active_document_id is not None:
                self._hierarchy_object_selected(self.active_document_id, kind, object_id)

    def _analyze_block(self, block_id: str) -> None:
        block = next(item for item in self.hierarchy.blocks if item.id == block_id)
        block_polyhedra = [
            polyhedron
            for polyhedron in self.hierarchy.polyhedra
            if polyhedron.id in block.polyhedron_ids
        ]
        distortion_values = [polyhedron.distortion * 100.0 for polyhedron in block_polyhedra]
        angle_spread_values = [polyhedron.angle_dispersion * 100.0 for polyhedron in block_polyhedra]
        rigidity_by_type: dict[str, list[float]] = {}
        for polyhedron in block_polyhedra:
            rigidity_by_type.setdefault(polyhedron.type_name, []).append(
                normalized_rigidity(polyhedron_rigidity_index(polyhedron))
            )
        component_text = "<br>".join(
            f"{type_name}: {np.mean(values):.3f} × {len(values)}"
            for type_name, values in sorted(rigidity_by_type.items())
        )
        geometry = analyze_atom_group(self.structure, block.atom_indices)
        composition = Counter(self.structure.sites[index].element for index in block.atom_indices)
        connections = [
            connector for connector in self.hierarchy.connectors
            if block.id in {connector.first_block, connector.second_block}
        ]
        series_block = None
        if self.series_report:
            series_block = next((item for item in self.series_report.blocks if item.block_id == block.id), None)
        motion = (
            f"Rotation: {series_block.motion.rotation_degrees:+.3f}°<br>"
            f"Translation: {series_block.motion.translation:.4f} Å<br>"
            f"Internal strain: {series_block.motion.distortion_percent:.3f}%"
            if series_block else "Rotation: —<br>Translation: —<br>Strain: —"
        )
        rigidity = (
            f"Series confidence: {series_block.rigidity_confidence:.3f}<br>"
            f"Internal RMSD: {series_block.motion.rmsd:.4f} Å"
            if series_block else (
                f"Chemical index |V|/(CN·r): {block.rigidity_index:.3f}<br>"
                f"Normalized prior: {block.rigidity_score:.3f}<br>"
                + (f"Components:<br>{component_text}<br>" if component_text else "")
                + (
                    "Bond-length dispersion: "
                    f"mean {np.mean(distortion_values):.3f}% · "
                    f"range {min(distortion_values):.3f}–{max(distortion_values):.3f}%<br>"
                    if distortion_values else ""
                )
                + (
                    "Angular spread: "
                    f"mean {np.mean(angle_spread_values):.3f}% · "
                    f"range {min(angle_spread_values):.3f}–{max(angle_spread_values):.3f}%<br>"
                    if angle_spread_values else ""
                )
                + "BVS / symmetry / energy: not evaluated<br>"
                + "Series evidence: not loaded"
            )
        )
        self.selected_title.setText(f"Rigid Block {block.id}")
        self.selected_analysis.setText(
            "<b>⚛ Composition</b><br>"
            f"{len(block.atom_indices)} atoms<br>"
            + "<br>".join(f"{count} {element}" for element, count in sorted(composition.items()))
            + "<br><br><b>◇ Geometry</b><br>"
            f"Volume: {geometry.volume:.3f} Å³<br>"
            f"Surface: {geometry.surface_area:.3f} Å²<br>"
            f"Center: ({geometry.center[0]:.3f}, {geometry.center[1]:.3f}, {geometry.center[2]:.3f}) Å<br>"
            f"Bounding box: {geometry.bounding_box[0]:.2f} × {geometry.bounding_box[1]:.2f} × {geometry.bounding_box[2]:.2f} Å"
            "<br><br><b>⬢ Rigidity</b><br>"
            + rigidity
            + "<br><br><b>⇄ Connectivity</b><br>"
            + ("<br>".join(f"{item.id}: {item.first_block} ↔ {item.second_block}" for item in connections) or "Isolated")
            + "<br><br><b>↻ Motion</b><br>"
            + motion
        )
        self._show_local_environment(block.id, connections)
        self.inspector_tabs.setCurrentIndex(0)

    def _show_local_environment(self, block_id: str, connections) -> None:
        if not connections:
            self._clear_local_environment()
            return
        colors = self.viewer._block_colors()
        rows = []
        for connector in connections:
            other = (
                connector.second_block
                if connector.first_block == block_id
                else connector.first_block
            )
            first, pivot, second = self.viewer._connector_points(connector)
            angle = self.viewer._connector_angle(first, pivot, second)
            shared_label = self.structure.sites[connector.ligand_indices[0]].label
            rows.append(
                "<tr>"
                f"<td><b style='color:{colors[block_id]}'>■ {block_id}</b></td>"
                f"<td>· {connector.id} · shared {shared_label} · {angle:.1f}° ·</td>"
                f"<td><span style='color:{colors[other]}'>■</span> {other}</td>"
                "</tr>"
            )
        self.local_environment.setText(
            "<table cellspacing='4' align='center'>" + "".join(rows) + "</table>"
        )
        self.local_environment_caption.show()
        self.local_environment.show()

    def _clear_local_environment(self) -> None:
        self.local_environment.clear()
        self.local_environment_caption.hide()
        self.local_environment.hide()

    def _analyze_connector(self, connector_id: str) -> None:
        self._clear_local_environment()
        connector = next(item for item in self.hierarchy.connectors if item.id == connector_id)
        series_item = None
        if self.series_report:
            series_item = next((item for item in self.series_report.connectors if item.connector_id == connector.id), None)
        motion = (
            f"{series_item.start_angle:.3f}° → {series_item.end_angle:.3f}°<br>"
            f"Δ angle: {series_item.angle_change:+.3f}°"
            if series_item else "Angle change: —<br>Load a structure series."
        )
        self.selected_title.setText(f"Shared site {connector.id}")
        self.selected_analysis.setText(
            f"<b>Connectivity</b><br>{connector.first_block} ↔ {connector.second_block}<br>"
            f"Type: {connector.kind}<br>Shared atoms: {len(connector.ligand_indices)}<br>"
            "<i>This is a geometric pivot candidate, not a confirmed hinge.</i>"
            f"<br><br><b>Motion</b><br>{motion}"
        )
        self.inspector_tabs.setCurrentIndex(0)

    def _analyze_polyhedron(self, polyhedron_id: str) -> None:
        self._clear_local_environment()
        item = next(polyhedron for polyhedron in self.hierarchy.polyhedra if polyhedron.id == polyhedron_id)
        lengths = ", ".join(f"{value:.3f}" for value in item.bond_lengths)
        self.selected_title.setText(f"Polyhedron {item.id} — {item.type_name}")
        self.selected_analysis.setText(
            f"<b>Geometry</b><br>Coordination number: {item.coordination_number}<br>"
            f"Bond lengths: {lengths} Å<br>Bond-length distortion: {item.distortion * 100:.3f}%"
            f"<br>Angular spread: {item.angle_dispersion * 100:.3f}%"
        )

    def _analyze_unit(self, unit_id: str) -> None:
        self._clear_local_environment()
        item = next(unit for unit in self.hierarchy.structural_units if unit.id == unit_id)
        self.selected_title.setText(f"Structural Unit {item.id}")
        self.selected_analysis.setText(
            f"<b>Type</b><br>{item.classification}<br><br>"
            f"<b>Composition</b><br>{len(item.atom_indices)} atoms<br>"
            f"{len(item.polyhedron_ids)} polyhedra"
        )

    def _show_interpretation(self, domain_id: str) -> None:
        document = self.collection.documents.get(self.active_document_id or "")
        if document is None:
            return
        self._selected_interpretation_domain_id = domain_id
        self.interpretation_panel.set_resolved(
            resolve_interpretation(document, domain_id)
        )
        self.inspector_tabs.setCurrentIndex(
            self.inspector_tabs.indexOf(self.interpretation_panel)
        )

    def _remove_interpretation(self) -> None:
        document = self.collection.documents.get(self.active_document_id or "")
        if document is None:
            return
        domain_id = getattr(self, "_selected_interpretation_domain_id", None)
        remove_overlay(document)
        self._fill_hierarchy_tree()
        if domain_id is not None:
            self._show_interpretation(domain_id)

    def _confirm_interpretation_bonds(self) -> None:
        document = self.collection.documents.get(self.active_document_id or "")
        if document is None:
            return
        try:
            confirm_bond_changes(document)
        except Exception as error:
            self.interpretation_panel.status_label.setText(str(error))
            return
        self.structure = document.structure
        self.hierarchy = document.hierarchy
        self._rebuild_scene(reset_camera=False)
        self._refresh_models()
        domain_id = getattr(self, "_selected_interpretation_domain_id", None)
        if domain_id is not None and any(
            item.id == domain_id for item in document.hierarchy.structural_domains
        ):
            self._show_interpretation(domain_id)

    def _analyze_cell(self) -> None:
        self._clear_local_environment()
        self.selected_title.setText("Unit Cell")
        self.selected_analysis.setText(self.cell_summary.text().replace("\n", "<br>"))
        self.inspector_tabs.setCurrentIndex(2)

    def _analyze_atom(self, site_index: int) -> None:
        self._clear_local_environment()
        site = self.structure.sites[site_index]
        cartesian = self.structure.cartesian_positions[site_index]
        components = "<br>".join(
            f"{component.element}: {component.occupancy:.3f}"
            for component in site.components
        )
        vacancy = (
            f"<br>Vacancy: {site.vacancy_fraction:.3f}"
            if site.vacancy_fraction > 1e-6
            else ""
        )
        self.selected_title.setText(f"Atom {site.label}")
        self.selected_analysis.setText(
            f"<b>⚛ Element</b><br>{site.element}<br><br>"
            f"<b>◇ Fractional coordinates</b><br>"
            f"{site.fractional[0]:.5f}, {site.fractional[1]:.5f}, {site.fractional[2]:.5f}<br><br>"
            f"<b>◇ Cartesian coordinates</b><br>"
            f"{cartesian[0]:.4f}, {cartesian[1]:.4f}, {cartesian[2]:.4f} Å<br><br>"
            f"<b>Site occupancy</b><br>{site.occupancy:.3f}<br>"
            f"{components}{vacancy}"
        )
        self.inspector_tabs.setCurrentIndex(0)

    def _tree_context_menu(self, position) -> None:
        if not self.object_tree.selectedItems():
            return
        menu = QMenu(self)
        menu.addAction("Hide from View", self._hide_selected)
        menu.addAction("Isolate Selected", self._isolate_selected)
        menu.addSeparator()
        menu.addAction("Restore All Hidden Objects", self._restore_scene)
        menu.exec(self.object_tree.viewport().mapToGlobal(position))

    def _selected_payloads(self) -> list[tuple[str, object, QTreeWidgetItem]]:
        payloads = []
        for item in self.object_tree.selectedItems():
            payload = item.data(0, Qt.ItemDataRole.UserRole)
            if not payload:
                continue
            kind, object_id = (payload[1], payload[2]) if len(payload) == 3 else payload
            if kind in {"atom", "polyhedron", "unit", "block", "connector"}:
                payloads.append((kind, object_id, item))
        return payloads

    def _hide_selected(self) -> None:
        payloads = []
        if getattr(self, "_picked_scene_object", None):
            kind, object_id = self._picked_scene_object
            document = self.collection.documents.get(self.active_document_id or "")
            identifiers: tuple[object, ...] = (object_id,)
            if document is not None and kind == "atom":
                key = site_orbit_key(document.structure.sites[int(object_id)].label)
                identifiers = tuple(site_orbits(document.structure).get(key, (object_id,)))
            elif document is not None and kind == "polyhedron":
                polyhedron = next(
                    item for item in document.hierarchy.polyhedra
                    if item.id == str(object_id)
                )
                key = site_orbit_key(
                    document.structure.sites[polyhedron.center_index].label
                )
                identifiers = tuple(
                    polyhedron_orbits(document).get(key, (object_id,))
                )
            elif document is not None and kind in {"unit", "block"}:
                objects = (
                    document.hierarchy.structural_units
                    if kind == "unit"
                    else document.hierarchy.blocks
                )
                identifiers = next(
                    (
                        tuple(orbit)
                        for orbit in hierarchy_object_orbits(document, tuple(objects))
                        if str(object_id) in orbit
                    ),
                    (object_id,),
                )
            payloads = [(kind, identifier, None) for identifier in identifiers]
        else:
            payloads = self._selected_payloads()
        if not payloads and getattr(self, "_picked_polyhedron_id", None):
            payloads = [("polyhedron", self._picked_polyhedron_id, None)]
        if not payloads:
            self.statusBar().showMessage("Select an atom, polyhedron, unit, block or connector first")
            return
        document = self.collection.documents.get(self.active_document_id or "")
        hidden_attributes = {
            "atom": "hidden_atom_indices",
            "bond": "hidden_bond_families",
            "polyhedron": "hidden_polyhedron_ids",
            "unit": "hidden_unit_ids",
            "block": "hidden_block_ids",
            "connector": "hidden_connector_ids",
        }
        for kind, object_id, item in payloads:
            self.viewer.hide_object(kind, object_id, redraw=False)
            if document is not None:
                attribute = hidden_attributes.get(kind)
                if attribute is not None:
                    value = (
                        int(object_id)
                        if kind == "atom"
                        else tuple(object_id)
                        if kind == "bond"
                        else str(object_id)
                    )
                    getattr(document.visual, attribute).add(value)
            if item is not None:
                font = item.font(0)
                font.setStrikeOut(True)
                item.setFont(0, font)
        self._picked_polyhedron_id = None
        self._picked_scene_object = None
        if document is not None and hasattr(self, "sites_panel"):
            self.sites_panel.set_document(document)
        self.viewer.redraw(reset_camera=False)
        self.statusBar().showMessage(f"Hidden from scene: {len(payloads)} object(s) · CIF unchanged")

    def _polyhedron_picked(self, polyhedron_id: str) -> None:
        self._picked_polyhedron_id = polyhedron_id
        if self.active_document_id is not None:
            self._hierarchy_object_selected(
                self.active_document_id,
                "polyhedron",
                polyhedron_id,
            )
        self.statusBar().showMessage(
            f"Selected {polyhedron_id} · press Delete or Hide to remove it from the scene"
        )

    def _scene_object_picked(self, kind: str, object_id: object) -> None:
        self._picked_scene_object = (kind, object_id)
        self._picked_polyhedron_id = str(object_id) if kind == "polyhedron" else None
        self.viewer.edit_default_kind = kind
        if "object_tree" in self.__dict__:
            self.object_tree.clearSelection()
        self.sites_panel.select_object(kind, object_id)
        if kind == "atom":
            self._analyze_atom(int(object_id))
        elif kind == "polyhedron":
            self._analyze_polyhedron(str(object_id))
        elif kind == "unit":
            self._analyze_unit(str(object_id))
        elif kind == "block":
            self._analyze_block(str(object_id))
        self.statusBar().showMessage(
            f"Selected {kind}: {object_id} · Delete hides · Esc clears"
        )

    def _scene_selection_cleared(self) -> None:
        self._picked_scene_object = None
        self._picked_polyhedron_id = None

    def _scene_edit_context_menu(self, global_position) -> None:
        menu = QMenu(self)
        selected = getattr(self, "_picked_scene_object", None)
        hide_action = menu.addAction("Hide selected", self._hide_selected)
        isolate_action = menu.addAction("Isolate selected", self._isolate_selected)
        color_action = menu.addAction("Change color…", self._change_picked_color)
        hide_action.setEnabled(selected is not None)
        isolate_action.setEnabled(selected is not None)
        color_action.setEnabled(
            selected is not None and selected[0] in {"atom", "polyhedron", "unit", "block"}
        )
        menu.addSeparator()
        menu.addAction("Restore all", self._restore_scene)
        menu.exec(global_position)

    def _change_picked_color(self) -> None:
        selected = getattr(self, "_picked_scene_object", None)
        if selected is None:
            return
        kind, _object_id = selected
        table = self.sites_panel.current_table()
        row = table.currentRow()
        if row < 0 or table.item(row, 1) is None:
            return
        color = QColorDialog.getColor(
            table.item(row, 1).foreground().color(), self, "Object color"
        )
        if not color.isValid():
            return
        key = self.sites_panel._key(table, row)
        {
            "atom": self.sites_panel.set_atom_color,
            "polyhedron": self.sites_panel.set_polyhedron_color,
            "unit": self.sites_panel.set_unit_color,
            "block": self.sites_panel.set_block_color,
        }[kind](key, color.name())

    def _isolate_selected(self) -> None:
        payloads = []
        if getattr(self, "_picked_scene_object", None):
            kind, object_id = self._picked_scene_object
            payloads = [(kind, object_id, None)]
        else:
            payloads = self._selected_payloads()
        if not payloads:
            self.statusBar().showMessage("Select one hierarchy object to isolate")
            return
        kind, object_id, _item = payloads[0]
        self.viewer.isolate_object(kind, object_id)
        document = self.collection.documents.get(self.active_document_id or "")
        if document is not None:
            for attribute in (
                "hidden_atom_indices",
                "hidden_bond_orbits",
                "hidden_bond_families",
                "hidden_polyhedron_ids",
                "hidden_unit_ids",
                "hidden_block_ids",
                "hidden_connector_ids",
                "hidden_topology_family_ids",
                "shown_unit_ids",
                "shown_block_ids",
            ):
                setattr(document.visual, attribute, set(getattr(self.viewer, attribute)))
            self.sites_panel.set_document(document)
        self.statusBar().showMessage(f"Isolated {object_id} · CIF unchanged")

    def _restore_scene(self) -> None:
        document = self.collection.documents.get(self.active_document_id or "")
        if document is not None:
            document.visual.hidden_atom_indices.clear()
            document.visual.hidden_bond_orbits.clear()
            document.visual.hidden_bond_families.clear()
            document.visual.hidden_polyhedron_ids.clear()
            document.visual.hidden_unit_ids.clear()
            document.visual.hidden_block_ids.clear()
            document.visual.hidden_connector_ids.clear()
            document.visual.hidden_topology_family_ids.clear()
            document.visual.shown_unit_ids.clear()
            document.visual.shown_block_ids.clear()
            self.sites_panel.set_document(document)
            self.viewer.apply_visual_state(document.visual, redraw=True)
        else:
            self.viewer.reset_visibility(redraw=True)

        def restore_item(item: QTreeWidgetItem) -> None:
            font = item.font(0)
            font.setStrikeOut(False)
            item.setFont(0, font)
            for child_index in range(item.childCount()):
                restore_item(item.child(child_index))

        for index in range(self.object_tree.topLevelItemCount()):
            restore_item(self.object_tree.topLevelItem(index))
        self.statusBar().showMessage("All hidden hierarchy objects restored")

    def _show_level(self, level: HierarchyLevel) -> None:
        if self.comparison_mode_stack.currentWidget() is self.morphology_workspace:
            self.comparison_mode_stack.setCurrentWidget(self.comparison_visual_page)
            self._set_comparison_tabs_visible(self.collection.visual_pair() is not None)
        if self.dual_viewer is not None and self.viewer_stack.currentWidget() is self.dual_viewer:
            self.dual_viewer.set_level(level)
        else:
            document = self.collection.documents.get(self.active_document_id or "")
            if document is not None:
                document.visual.level = level
            self.viewer.set_level(level)
        for index in range(self.representation_combo.count()):
            if self.representation_combo.itemData(index) == level.value:
                self.representation_combo.blockSignals(True)
                self.representation_combo.setCurrentIndex(index)
                self.representation_combo.blockSignals(False)
                break
        for index in range(self.toolbar_view_combo.count()):
            if self.toolbar_view_combo.itemData(index) == level.value:
                self.toolbar_view_combo.blockSignals(True)
                self.toolbar_view_combo.setCurrentIndex(index)
                self.toolbar_view_combo.blockSignals(False)
                break
        tab_levels = [self.view_tabs.tabData(index) for index in range(self.view_tabs.count())]
        if level.value in tab_levels:
            self.view_tabs.blockSignals(True)
            self.view_tabs.setCurrentIndex(tab_levels.index(level.value))
            self.view_tabs.blockSignals(False)

    def _representation_changed(self, index: int) -> None:
        self._show_level(HierarchyLevel(self.representation_combo.itemData(index)))

    def _sites_state_changed(self) -> None:
        document = self.collection.documents.get(self.active_document_id or "")
        if document is None:
            return
        self.viewer.apply_visual_state(document.visual, redraw=True)

    def _view_tab_changed(self, index: int) -> None:
        value = self.view_tabs.tabData(index)
        if value == "morphology":
            self._show_morphology()
            return
        self._show_level(HierarchyLevel(value))

    def _show_morphology(self) -> None:
        document = self.collection.documents.get(self.active_document_id)
        if document is None:
            self.statusBar().showMessage("Open a CIF structure before calculating morphology")
            return
        self.central_stack.setCurrentWidget(self.structure_workspace)
        self._set_comparison_tabs_visible(False)
        self.comparison_mode_stack.setCurrentWidget(self.morphology_workspace)
        self.morphology_workspace.set_document(document)
        update_actions = getattr(self, "_update_morphology_actions", None)
        if update_actions is not None:
            update_actions()
        self.statusBar().showMessage("BFDH morphology workspace")

    def _visualization_changed(self, _value=None) -> None:
        self.viewer.set_render_style(self.render_style_combo.currentText())
        self.viewer.radius_model = self.radius_combo.currentData()
        self.viewer.show_cell = self.cell_check.isChecked()
        periodic_grid = getattr(self, "periodic_grid_check", None)
        self.viewer.show_periodic_cell_grid = (
            periodic_grid.isChecked() if periodic_grid is not None else False
        )
        self.viewer.show_axes = self.axes_check.isChecked()
        self.viewer.show_cell_dimensions = self.cell_dimensions_check.isChecked()
        self.viewer.cell_line_width = self.cell_line_slider.value() / 10.0
        self.viewer.axes_size = self.axes_size_slider.value() / 100.0
        self.viewer.atom_scale = self.atom_scale.value() / 100.0
        self.viewer.bond_radius = self.bond_radius_slider.value() / 100.0
        self.viewer.bond_style = self.bond_style_combo.currentData()
        self.viewer.polyhedron_opacity = self.poly_opacity.value() / 100.0
        self.viewer.polyhedron_edge_radius = self.poly_edge_slider.value() / 1000.0
        self.viewer.show_polyhedron_edges = self.poly_edges_check.isChecked()
        self.viewer.show_polyhedron_spokes = self.spokes_check.isChecked()
        self.viewer.color_by = self.color_combo.currentText().lower().replace(" ", "_")
        self.sites_panel.set_color_mode(self.viewer.color_by)
        self.viewer.adaptive_rigidity_scale = self.adaptive_rigidity_check.isChecked()
        self.viewer.show_labels = self.labels_check.isChecked()
        self.viewer.split_mixed_occupancies = self.split_occupancy_check.isChecked()
        self.viewer.show_vacancy_sectors = self.vacancy_sector_check.isChecked()
        self.viewer.show_connector_labels = self.pivot_labels_check.isChecked()
        self.viewer.show_legend = self.legend_check.isChecked()
        self.viewer.show_atoms = self.show_checks["atoms"].isChecked()
        self.viewer.show_bonds = self.show_checks["bonds"].isChecked()
        self.viewer.show_polyhedra = self.show_checks["polyhedra"].isChecked()
        self.viewer.show_centers = self.show_checks["centers"].isChecked()
        self.viewer.show_connectors = self.show_checks["connectors"].isChecked()
        self.viewer.redraw(reset_camera=False)
        if self.dual_viewer is not None and self.viewer_stack.currentWidget() is self.dual_viewer:
            MainWindow._apply_dual_label_settings(self, self.dual_viewer)

    def _schedule_scene_rebuild(self, _value=None) -> None:
        """Coalesce spin-box changes so rendering cannot queue extra arrow repeats."""
        self.scene_rebuild_timer.start()

    def _rebuild_scene(self, _value=None, reset_camera: bool = False) -> None:
        if not self.structure:
            return
        if hasattr(self, "cell_min_spins"):
            bounds = tuple(
                (minimum.value(), maximum.value())
                for minimum, maximum in zip(
                    self.cell_min_spins, self.cell_max_spins, strict=True
                )
            )
            if any(minimum >= maximum for minimum, maximum in bounds):
                self.statusBar().showMessage(
                    "Cell bounds require Min < Max for every axis"
                )
                return
            settings = {"bounds": bounds}
        else:
            settings = {"repeat": tuple(spin.value() for spin in self.repeat_spins)}
        settings.update({
            "bond_tolerance": self.bond_tolerance.value(),
            "include_bonds": True,
            "complete_boundary": self.boundary_atoms_check.isChecked(),
        })
        document = self.collection.documents.get(self.active_document_id or "")
        if document is not None and document.structure is self.structure:
            scene = document.scene_data(**settings)
        else:
            scene = build_scene(self.structure, **settings)
        if document is not None and document.structure is self.structure:
            self.viewer.set_document(
                document,
                reset_camera=reset_camera,
                scene=scene,
            )
        else:
            self.viewer.set_data(
                self.structure,
                scene,
                self.hierarchy,
                reset_camera=reset_camera,
            )

    def _fill_cell(self) -> None:
        cell = self.structure.cell
        self.cell_summary.setText(
            f"Space group: {self.structure.space_group or 'unknown'}\n"
            f"a = {cell.a:.5f} Å   α = {cell.alpha:.3f}°\n"
            f"b = {cell.b:.5f} Å   β = {cell.beta:.3f}°\n"
            f"c = {cell.c:.5f} Å   γ = {cell.gamma:.3f}°\n"
            f"V = {cell.volume:.4f} Å³"
        )
        document = self.collection.documents.get(self.active_document_id or "")
        requested = (
            document.requested_profile
            if document is not None
            else RequestedProfile.AUTO
        )
        combo = getattr(self, "compound_type_combo", None)
        if combo is not None:
            combo.blockSignals(True)
            index = combo.findData(requested.value)
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)
        result = getattr(self, "compound_type_result", None)
        if result is None:
            return
        decision = document.profile_decision if document is not None else None
        if decision is None:
            result.setText("Detected: not analyzed")
            result.setToolTip("")
            return
        names = {
            ResolvedProfile.INORGANIC: "Inorganic",
            ResolvedProfile.MOLECULAR: "Molecular organic",
            ResolvedProfile.RETICULAR: "MOF / reticular",
        }
        result.setText(
            f"Detected: {names[decision.resolved]} · {decision.confidence.value} confidence"
        )
        evidence = ["Evidence:", *(f"• {item}" for item in decision.reasons)]
        if decision.warnings:
            evidence.extend(("", "Warnings:", *(f"• {item}" for item in decision.warnings)))
        result.setToolTip("\n".join(evidence))

    def _profile_requested_changed(self, index: int) -> None:
        document = self.collection.documents.get(self.active_document_id or "")
        combo = getattr(self, "compound_type_combo", None)
        if document is None or combo is None or index < 0:
            return
        try:
            requested = RequestedProfile(str(combo.itemData(index)))
        except ValueError:
            return
        if (
            requested is document.requested_profile
            and document.profile_decision is not None
        ):
            return
        document.begin_reanalysis(requested)
        self.structure = document.structure
        self.hierarchy = document.hierarchy
        generation = getattr(self, "_structure_load_generation", 0) + 1
        self._structure_load_generation = generation
        source_path = document.structure.source_path or Path(document.structure.name)
        signature = (generation, "profile", requested.value, str(source_path))
        self._active_structure_load_signature = signature
        self._structure_load_document_ids = {(signature, 0): document.id}
        self._rebuild_scene(reset_camera=False)
        self._refresh_loading_models(document)
        labels = {
            RequestedProfile.AUTO: "automatic detection",
            RequestedProfile.INORGANIC: "inorganic",
            RequestedProfile.ORGANIC_METAL_ORGANIC: "organic / metal-organic",
        }
        self.statusBar().showMessage(f"Reanalyzing as {labels[requested]}…")

        def work(progressed) -> None:
            for update in iter_reanalysis_updates(
                document.structure,
                source_path,
                requested,
            ):
                progressed(update)

        manager = getattr(self, "_structure_load_requests", None)
        if manager is None:
            for update in iter_reanalysis_updates(
                document.structure,
                source_path,
                requested,
            ):
                MainWindow._structure_load_progress(self, signature, update)
            MainWindow._structure_load_ready(self, signature)
        else:
            manager.request(signature, work)

    def _fill_dashboard(self) -> None:
        passport = build_structural_passport(self.structure, self.hierarchy, self.series_report)
        self.dashboard_values["hierarchy"].setText(
            "<table cellspacing='5'><tr>"
            f"<td><b style='font-size:18px'>{passport.atoms}</b><br><small>Atoms</small></td>"
            f"<td><b style='font-size:18px'>{passport.polyhedra}</b><br><small>Polyhedra</small></td>"
            f"<td><b style='font-size:18px'>{passport.structural_units}</b><br><small>Units</small></td>"
            f"<td><b style='font-size:18px'>{passport.rigid_blocks}</b><br><small>Blocks</small></td>"
            f"<td><b style='font-size:18px'>{passport.connectors}</b><br><small>Shared sites</small></td>"
            "</tr></table>"
        )
        scores = [block.rigidity_score for block in self.hierarchy.blocks] or [0.0]
        self.dashboard_values["rigidity"].setText(
            f"Mean {sum(scores) / len(scores):.2f}\nMin {min(scores):.2f}   Max {max(scores):.2f}"
        )
        self.dashboard_values["mechanism"].setText(passport.dominant_mechanism)
        self.dashboard_values["flexibility"].setText(passport.predicted_flexibility)
        self.dashboard_values["nte"].setText(passport.nte_mechanism)

    def _fill_dynamics(self) -> None:
        if not self.series_report:
            return
        report = self.series_report
        block_lines = [
            f"{item.block_id}: rotation {item.motion.rotation_degrees:+.3f}°, "
            f"translation {item.motion.translation:.4f} Å, distortion {item.motion.distortion_percent:.3f}%"
            for item in report.blocks
        ]
        connector_lines = [
            f"{item.connector_id}: {item.start_angle:.3f}° → {item.end_angle:.3f}° "
            f"(Δ {item.angle_change:+.3f}°)"
            for item in report.connectors
        ]
        text = f"{report.start_label} → {report.end_label}\n\nBLOCK MOTION\n" + "\n".join(block_lines)
        text += "\n\nCONNECTOR / HINGE MOTION\n" + ("\n".join(connector_lines) or "No connectors")
        self.console.setPlainText(text)

    def _fill_output(self) -> None:
        summary = self.hierarchy.summary()
        self.output.setPlainText(
            "Mechanical hierarchy analysis completed.\n"
            f"Polyhedra: {summary['polyhedra']}\n"
            f"Structural units: {summary['structural_units']}\n"
            f"Rigid-block candidates: {summary['structural_blocks']}\n"
            f"Shared sites: {summary['flexible_connectors']}\n"
            "Ready."
        )
        self.history.appendPlainText(f"Opened {self.current_path}")

    def save_screenshot(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save snapshot", "crystal-mechanics.png", "PNG image (*.png)")
        if path:
            self.viewer.save_screenshot(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        if any(is_supported_structure_path(path) for path in paths):
            event.acceptProposedAction()

    def _load_dropped_cifs(self, paths) -> None:
        for path in paths:
            self.load_path(path)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if is_supported_structure_path(url.toLocalFile())
        ]
        MainWindow._load_dropped_cifs(self, paths)
        if paths:
            event.acceptProposedAction()
