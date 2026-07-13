from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QWidget

from xrd_finder.ui.theme import action_button_style


class FinderActionBar(QWidget):
    smoothRequested = Signal()
    cropRequested = Signal()
    subtractBackgroundRequested = Signal()
    resetDataRequested = Signal()
    searchRequested = Signal()
    autoSearchRequested = Signal()
    resetViewRequested = Signal()
    patternDisplayModeChanged = Signal(str)
    patternOffsetPercentChanged = Signal(int)
    normalizePatternsChanged = Signal(bool)
    autoRefineCellsChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.search_input = QLineEdit()
        self.pattern_display_mode = QComboBox()
        self.pattern_offset_slider = QSlider()
        self.pattern_offset_value = QLabel()
        self.auto_refine_cells_checkbox = QCheckBox("Refine cell")
        self.normalize_patterns_checkbox = QCheckBox("Normalize")
        self._build_ui()

    def search_text(self) -> str:
        return self.search_input.text().strip()

    def set_search_text(self, text: str) -> None:
        self.search_input.setText(text)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.smooth_button = QPushButton("Smooth")
        self.smooth_button.setToolTip("Smooth observed XRD curve")
        self.smooth_button.setStyleSheet(action_button_style("#2367a5", "#5a9bd8"))
        self.smooth_button.clicked.connect(self.smoothRequested)

        self.background_button = QPushButton("Remove background")
        self.background_button.setToolTip("Estimate and subtract background")
        self.background_button.setStyleSheet(action_button_style("#8a5a16", "#c68a2e"))
        self.background_button.clicked.connect(self.subtractBackgroundRequested)

        self.crop_button = QPushButton("Crop XRD")
        self.crop_button.setToolTip("Set displayed 2theta range for one or more XRD patterns")
        self.crop_button.setStyleSheet(action_button_style("#3f5f82", "#7296bd"))
        self.crop_button.clicked.connect(self.cropRequested)

        reset_data_button = QPushButton("Reset data")
        reset_data_button.setToolTip("Restore the original observed pattern")
        reset_data_button.setStyleSheet(action_button_style("#6f45a3", "#9972ca"))
        reset_data_button.clicked.connect(self.resetDataRequested)

        self.auto_search_button = QPushButton("Auto search")
        self.auto_search_button.setToolTip(
            "Find and rank phase candidates from the active XRD pattern.\n"
            "Selected elements are used as composition constraints."
        )
        self.auto_search_button.setStyleSheet(action_button_style("#00695c", "#26a69a"))
        self.auto_search_button.clicked.connect(self.autoSearchRequested)
        self.auto_refine_cells_checkbox.setToolTip(
            "Automatically refine unit-cell parameters when a phase is added.\n"
            "Turn off for faster first-pass viewing; the Pawley button in the card still works."
        )
        self.auto_refine_cells_checkbox.setChecked(False)
        self.auto_refine_cells_checkbox.toggled.connect(self.autoRefineCellsChanged)

        reset_button = QPushButton("Reset view")
        reset_button.setToolTip("Show the full XRD range and reset plot zoom")
        reset_button.setStyleSheet(action_button_style("#5f6368", "#8a8d91"))
        reset_button.clicked.connect(self.resetViewRequested)

        self.pattern_display_mode.addItems(["One", "All selected"])
        self.pattern_display_mode.setToolTip(
            "One: show only the active XRD pattern.\n"
            "All selected: show all checked XRD patterns from the project tree."
        )
        self.pattern_display_mode.currentTextChanged.connect(self.patternDisplayModeChanged)

        self.pattern_offset_slider.setOrientation(Qt.Orientation.Horizontal)
        self.pattern_offset_slider.setRange(0, 150)
        self.pattern_offset_slider.setValue(10)
        self.pattern_offset_slider.setFixedWidth(150)
        self.pattern_offset_slider.setToolTip(
            "Vertical offset between selected XRD patterns.\n"
            "The value is a percent of the previous pattern height."
        )
        self.pattern_offset_value.setMinimumWidth(38)
        self.pattern_offset_value.setText("10%")
        self.pattern_offset_slider.valueChanged.connect(self._set_offset_value)
        self.pattern_offset_slider.valueChanged.connect(self.patternOffsetPercentChanged)
        self.normalize_patterns_checkbox.setToolTip("Normalize observed XRD patterns to Imax = 100 for display and phase search.")
        self.normalize_patterns_checkbox.toggled.connect(self.normalizePatternsChanged)

        layout.addWidget(self.smooth_button)
        layout.addWidget(self.background_button)
        layout.addWidget(self.crop_button)
        layout.addWidget(reset_data_button)
        layout.addWidget(self.auto_search_button)
        layout.addWidget(self.auto_refine_cells_checkbox)
        layout.addWidget(QLabel("Show"))
        layout.addWidget(self.pattern_display_mode)
        layout.addWidget(QLabel("Offset"))
        layout.addWidget(self.pattern_offset_slider)
        layout.addWidget(self.pattern_offset_value)
        layout.addWidget(self.normalize_patterns_checkbox)
        layout.addStretch(1)

        self.search_input.setPlaceholderText("Formula / elements / phase name")
        self.search_input.returnPressed.connect(self.searchRequested)
        self.search_input.hide()
        layout.addWidget(reset_button)

    def offset_percent(self) -> int:
        return self.pattern_offset_slider.value()

    def set_auto_search_busy(self, busy: bool) -> None:
        self.auto_search_button.setEnabled(not busy)
        self.auto_search_button.setText("Searching..." if busy else "Auto search")

    def _set_offset_value(self, value: int) -> None:
        self.pattern_offset_value.setText(f"{value}%")
