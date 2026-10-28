from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from xrd_finder.ui.element_filter import PeriodicTableWidget
from xrd_finder.ui.layout_state import SplitterLayoutState
from xrd_finder.ui.wrapping_layout import WrappingLayout


class CompositionPanel(QWidget):
    requiredElementToggled = Signal(str)
    excludedElementToggled = Signal(str)
    elementsPainted = Signal(list, str)
    exclusionModeToggleRequested = Signal()
    searchRequested = Signal()
    resetRequested = Signal()

    def __init__(self, match_table: QWidget, layout_state: SplitterLayoutState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        layout_state.register("composition_splitter", self.splitter)
        outer_layout.addWidget(self.splitter)

        self.element_table = PeriodicTableWidget()
        self.name_input = QLineEdit()
        self.elem_count_input = QLineEdit()
        self.formula_sum_input = QLineEdit()
        self.element_gate_label = QLabel("Chemical filter: none")
        self.ccdc_doi_input = QLineEdit()
        self.inorganics_checkbox = QCheckBox("Inorganic")
        self.organics_checkbox = QCheckBox("Organic")
        self.structural_data_checkbox = QCheckBox("Include structures")
        self.reference_patterns_checkbox = QCheckBox("Reference patterns")
        self.rank_by_probability_checkbox = QCheckBox("Rank by XRD match")

        self._build_element_panel()
        self._build_controls_panel(match_table)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([260, 390])

    def _build_element_panel(self) -> None:
        element_panel = QWidget()
        element_panel.setObjectName('compositionElements')
        element_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        element_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        element_layout = QVBoxLayout(element_panel)
        element_layout.setContentsMargins(5, 4, 5, 4)
        element_layout.setSpacing(3)

        top_row = QHBoxLayout()
        title = QLabel('Element filters')
        title.setProperty('uiRole', 'sectionTitle')
        title.setStyleSheet('font-size: 11px;')
        top_row.addWidget(title)
        top_row.addStretch(1)
        element_layout.addLayout(top_row)

        self.element_table.leftClicked.connect(self.requiredElementToggled)
        self.element_table.rightClicked.connect(self.excludedElementToggled)
        self.element_table.elementsPainted.connect(self.elementsPainted)
        self.element_table.modeToggleRequested.connect(self.exclusionModeToggleRequested)
        element_layout.addWidget(self.element_table, 1)
        self.splitter.addWidget(element_panel)

    def _build_controls_panel(self, match_table: QWidget) -> None:
        controls_panel = QWidget()
        controls_panel.setObjectName('compositionControls')
        controls_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        controls_panel.setStyleSheet(
            'QWidget#compositionControls QCheckBox, QWidget#compositionControls QLineEdit { font-size: 12px; }'
            'QWidget#compositionControls QLineEdit { min-height: 20px; }'
            'QWidget#compositionControls QPushButton { font-size: 12px; min-height: 22px; }'
        )
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(6, 4, 6, 4)
        controls_layout.setSpacing(5)
        self.element_gate_label.setProperty('uiRole', 'muted')
        self.element_gate_label.setStyleSheet('font-size: 11px;')

        self.name_input.hide()
        self.elem_count_input.hide()
        self.formula_sum_input.hide()
        controls_layout.addWidget(self.element_gate_label)

        self.ccdc_doi_input.setPlaceholderText("CCDC DOI / CSD refcode")
        self.ccdc_doi_input.returnPressed.connect(self.searchRequested)
        controls_layout.addWidget(self.ccdc_doi_input)

        material_row = QHBoxLayout()
        self.inorganics_checkbox.setChecked(True)
        self.organics_checkbox.setChecked(False)
        material_row.addWidget(self.inorganics_checkbox)
        material_row.addWidget(self.organics_checkbox)
        material_row.addStretch(1)
        controls_layout.addLayout(material_row)

        data_mode_row = WrappingLayout(spacing=10)
        self.structural_data_checkbox.setChecked(True)
        self.structural_data_checkbox.setToolTip("Include entries from crystallographic structure databases. CIF files may be downloaded or prepared after retrieval.")
        self.reference_patterns_checkbox.setChecked(False)
        self.reference_patterns_checkbox.setToolTip(
            "Include enabled experimental/reference databases such as RRUFF and PDF-2."
        )
        self.rank_by_probability_checkbox.setChecked(True)
        self.rank_by_probability_checkbox.setToolTip(
            "Estimate whether locally available structural candidates have peaks present in the active XRD pattern."
        )
        data_mode_row.addWidget(self.structural_data_checkbox)
        data_mode_row.addWidget(self.rank_by_probability_checkbox)
        controls_layout.addLayout(data_mode_row)
        controls_layout.addWidget(self.reference_patterns_checkbox)

        actions = QHBoxLayout()
        search_button = self.search_button = QPushButton("Search database")
        search_button.setMinimumHeight(30)
        search_button.setToolTip("Search candidate phases using required and absent elements and enabled databases.")
        search_button.setProperty('searchMode', 'search')
        search_button.clicked.connect(self.searchRequested)

        reset_button = self.reset_button = QPushButton("Clear search")
        reset_button.setMinimumHeight(30)
        reset_button.setToolTip(
            "Cancel the current search, clear element filters, and reset the candidate list.\n"
            "Selected phases and their calculated fit are preserved."
        )
        reset_button.clicked.connect(self.resetRequested)

        actions.addWidget(search_button)
        actions.addWidget(reset_button)
        controls_layout.addLayout(actions)

        title = QLabel('Selected phases')
        title.setProperty('uiRole', 'sectionTitle')
        title.setStyleSheet('font-size: 11px;')
        controls_layout.addWidget(title)
        controls_layout.addWidget(match_table, 1)
        self.splitter.addWidget(controls_panel)

    def set_search_mode(self, mode: str) -> None:
        search, reset = {
            "search": ("Search database", "Clear search"),
            "auto": ("Identify phases", "Clear search"),
            "peaks": ("Peak search", "Clear search"),
        }[mode]
        self.search_button.setText(search)
        self.search_button.setProperty('searchMode', mode)
        self.search_button.style().unpolish(self.search_button)
        self.search_button.style().polish(self.search_button)
        self.search_button.update()
        self.reset_button.setText(reset)
        self.search_button.setToolTip({
            "search": "Search phase candidates using element filters and enabled databases.",
            "auto": "Detect peaks in the active XRD pattern and search local databases.",
            "peaks": "Search local databases using only the manually selected peaks.",
        }[mode])
        self.reset_button.setToolTip(
            f"{reset}: cancel the current search and clear its chemical filters and candidate results. "
            "Accepted phases and pattern processing are preserved."
        )
