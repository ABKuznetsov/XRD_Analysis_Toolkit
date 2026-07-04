from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QWidget


def _action_button_style(background: str, border: str) -> str:
    return (
        "QPushButton {"
        f"background: {background}; border: 1px solid {border}; color: #ffffff;"
        "border-radius: 5px; padding: 6px 12px; font-weight: 700;"
        "}"
        "QPushButton:pressed { padding-top: 7px; padding-bottom: 5px; }"
    )


class FinderActionBar(QWidget):
    smoothRequested = Signal()
    subtractBackgroundRequested = Signal()
    resetDataRequested = Signal()
    searchRequested = Signal()
    resetViewRequested = Signal()
    patternDisplayModeChanged = Signal(str)
    patternOffsetPercentChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.search_input = QLineEdit()
        self.pattern_display_mode = QComboBox()
        self.pattern_offset_slider = QSlider()
        self.pattern_offset_value = QLabel()
        self._build_ui()

    def search_text(self) -> str:
        return self.search_input.text().strip()

    def set_search_text(self, text: str) -> None:
        self.search_input.setText(text)

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        smooth_button = QPushButton("Smooth")
        smooth_button.setToolTip("Smooth observed XRD curve")
        smooth_button.setStyleSheet(_action_button_style("#2367a5", "#5a9bd8"))
        smooth_button.clicked.connect(self.smoothRequested)

        background_button = QPushButton("Remove background")
        background_button.setToolTip("Estimate and subtract background")
        background_button.setStyleSheet(_action_button_style("#8a5a16", "#c68a2e"))
        background_button.clicked.connect(self.subtractBackgroundRequested)

        reset_data_button = QPushButton("Reset data")
        reset_data_button.setToolTip("Restore the original observed pattern")
        reset_data_button.setStyleSheet(_action_button_style("#6f45a3", "#9972ca"))
        reset_data_button.clicked.connect(self.resetDataRequested)

        reset_button = QPushButton("Reset view")
        reset_button.setToolTip("Show the full XRD range and reset plot zoom")
        reset_button.setStyleSheet(_action_button_style("#5f6368", "#8a8d91"))
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

        layout.addWidget(smooth_button)
        layout.addWidget(background_button)
        layout.addWidget(reset_data_button)
        layout.addWidget(QLabel("Show"))
        layout.addWidget(self.pattern_display_mode)
        layout.addWidget(QLabel("Offset"))
        layout.addWidget(self.pattern_offset_slider)
        layout.addWidget(self.pattern_offset_value)
        layout.addStretch(1)

        self.search_input.setPlaceholderText("Formula / elements / phase name")
        self.search_input.returnPressed.connect(self.searchRequested)
        self.search_input.hide()
        layout.addWidget(reset_button)

    def offset_percent(self) -> int:
        return self.pattern_offset_slider.value()

    def _set_offset_value(self, value: int) -> None:
        self.pattern_offset_value.setText(f"{value}%")
