from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter, QVBoxLayout, QWidget

from xrd_finder.ui.element_filter import PeriodicTableWidget
from xrd_finder.ui.layout_state import SplitterLayoutState
from xrd_finder.ui.theme import command_button_style


class CompositionPanel(QWidget):
    requiredElementToggled = Signal(str)
    optionalElementToggled = Signal(str)
    searchRequested = Signal()
    resetRequested = Signal()

    def __init__(self, match_table: QWidget, layout_state: SplitterLayoutState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        layout_state.register("composition_splitter", self.splitter)
        outer_layout.addWidget(self.splitter)

        self.element_table = PeriodicTableWidget()
        self.name_input = QLineEdit()
        self.elem_count_input = QLineEdit()
        self.formula_sum_input = QLineEdit()
        self.element_gate_label = QLabel("Gate: none")
        self.ccdc_doi_input = QLineEdit()
        self.inorganics_checkbox = QCheckBox("Inorganic")
        self.organics_checkbox = QCheckBox("Organic")
        self.structural_data_checkbox = QCheckBox("Structural data")
        self.reference_patterns_checkbox = QCheckBox("Experimental/reference patterns")
        self.rank_by_probability_checkbox = QCheckBox("Rank by peak match")

        self._build_element_panel()
        self._build_controls_panel(match_table)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([260, 390])

    def _build_element_panel(self) -> None:
        element_panel = QWidget()
        element_layout = QVBoxLayout(element_panel)
        element_layout.setContentsMargins(0, 0, 0, 0)
        element_layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Element filters"))
        top_row.addStretch(1)
        element_layout.addLayout(top_row)

        self.element_table.leftClicked.connect(self.requiredElementToggled)
        self.element_table.rightClicked.connect(self.optionalElementToggled)
        element_layout.addWidget(self.element_table, 1)
        self.splitter.addWidget(element_panel)

    def _build_controls_panel(self, match_table: QWidget) -> None:
        controls_panel = QWidget()
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

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

        data_mode_row = QHBoxLayout()
        self.structural_data_checkbox.setChecked(True)
        self.structural_data_checkbox.setToolTip("Include sources with CIF or atomic coordinates that can be calculated.")
        self.reference_patterns_checkbox.setChecked(True)
        self.reference_patterns_checkbox.setToolTip("Include RRUFF and PDF-2 diffraction-line cards as reference overlays.")
        self.rank_by_probability_checkbox.setChecked(True)
        self.rank_by_probability_checkbox.setToolTip(
            "Estimate whether locally available structural candidates have peaks present in the active XRD pattern."
        )
        data_mode_row.addWidget(self.structural_data_checkbox)
        data_mode_row.addWidget(self.reference_patterns_checkbox)
        data_mode_row.addWidget(self.rank_by_probability_checkbox)
        data_mode_row.addStretch(1)
        controls_layout.addLayout(data_mode_row)

        actions = QHBoxLayout()
        search_button = QPushButton("Find")
        search_button.setMinimumHeight(34)
        search_button.setToolTip("Search candidate phases using the selected required/optional elements and enabled databases.")
        search_button.setStyleSheet(command_button_style("#0b8043", "#35a96c"))
        search_button.clicked.connect(self.searchRequested)

        reset_button = QPushButton("Reset table")
        reset_button.setMinimumHeight(34)
        reset_button.setToolTip(
            "Cancel Auto search, clear element filters, and reset the candidate list.\n"
            "Selected phases and their calculated fit are preserved."
        )
        reset_button.setStyleSheet(command_button_style("#5f6368", "#8a8d91"))
        reset_button.clicked.connect(self.resetRequested)

        actions.addWidget(search_button)
        actions.addWidget(reset_button)
        controls_layout.addLayout(actions)

        controls_layout.addWidget(QLabel("Selected candidates"))
        controls_layout.addWidget(match_table, 1)
        self.splitter.addWidget(controls_panel)
