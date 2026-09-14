from __future__ import annotations

import math

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QWidget,
)

from xrd_finder.ui.plot_view_settings import PLOT_ASPECTS


def d_spacing_from_two_theta(two_theta: float, wavelength: float) -> float | None:
    angle = float(two_theta)
    radiation = float(wavelength)
    if not math.isfinite(angle) or not math.isfinite(radiation) or angle <= 0.0 or radiation <= 0.0:
        return None
    sine = math.sin(math.radians(angle / 2.0))
    if sine <= 0.0:
        return None
    return radiation / (2.0 * sine)


class FinderPlotControlBar(QWidget):
    patternDisplayModeChanged = Signal(str)
    plotAspectModeChanged = Signal(str)
    patternOffsetPercentChanged = Signal(int)
    normalizePatternsChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("finderPlotControlBar")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 0)
        layout.setSpacing(6)

        self.pattern_display_mode = QComboBox()
        self.pattern_display_mode.addItems(["One", "All selected"])
        self.pattern_display_mode.setMinimumWidth(82)
        self.pattern_display_mode.setMaximumWidth(112)
        self.pattern_display_mode.setToolTip(
            "One: show only the active XRD pattern.\n"
            "All selected: show all checked XRD patterns from the project tree."
        )
        self.pattern_display_mode.currentTextChanged.connect(self.patternDisplayModeChanged)

        self.plot_aspect_mode = QComboBox()
        self.plot_aspect_mode.addItems(PLOT_ASPECTS.keys())
        self.plot_aspect_mode.setMinimumWidth(68)
        self.plot_aspect_mode.setMaximumWidth(100)
        self.plot_aspect_mode.setToolTip(
            "Set the plot canvas proportions without changing the application window size."
        )
        self.plot_aspect_mode.currentTextChanged.connect(self.plotAspectModeChanged)

        self.normalize_patterns_checkbox = QCheckBox("Norm.")
        self.normalize_patterns_checkbox.setToolTip(
            "Normalize observed XRD patterns to Imax = 100 for display and phase search."
        )
        self.normalize_patterns_checkbox.toggled.connect(self.normalizePatternsChanged)

        self.pattern_offset_slider = QSlider(Qt.Orientation.Horizontal)
        self.pattern_offset_slider.setRange(0, 150)
        self.pattern_offset_slider.setValue(10)
        self.pattern_offset_slider.setMinimumWidth(60)
        self.pattern_offset_slider.setMaximumWidth(100)
        self.pattern_offset_slider.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self.pattern_offset_slider.setToolTip(
            "Vertical offset between selected XRD patterns, as a percent of the previous pattern height."
        )
        self.pattern_offset_value = QLabel("10%")
        self.pattern_offset_value.setMinimumWidth(32)
        self.pattern_offset_slider.valueChanged.connect(self._set_offset_value)
        self.pattern_offset_slider.valueChanged.connect(self.patternOffsetPercentChanged)

        self.cursor_position_status_label = QLabel()
        self.cursor_position_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.cursor_position_status_label.setStyleSheet(
            "background: #20262d; border: 1px solid #3b4652; border-radius: 3px; "
            "color: #d7e3f4; font-weight: 700; padding: 3px 8px;"
        )
        self.cursor_position_status_label.setMinimumHeight(24)
        self.cursor_position_status_label.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Fixed,
        )
        self.set_cursor_readout()

        layout.addWidget(QLabel("XRD:"))
        layout.addWidget(self.pattern_display_mode)
        layout.addWidget(QLabel("Format:"))
        layout.addWidget(self.plot_aspect_mode)
        layout.addWidget(self.normalize_patterns_checkbox)
        layout.addSpacing(4)
        layout.addWidget(QLabel("Offset"))
        layout.addWidget(self.pattern_offset_slider)
        layout.addWidget(self.pattern_offset_value)
        layout.addStretch(1)
        layout.addWidget(self.cursor_position_status_label)

    def set_cursor_readout(
        self,
        *,
        two_theta: float | None = None,
        intensity: float | None = None,
        d_spacing: float | None = None,
    ) -> None:
        if two_theta is None or intensity is None:
            text = "2theta: -    I: -    d: -"
        else:
            d_text = "-" if d_spacing is None else f"{d_spacing:.3f} A"
            text = f"2theta: {two_theta:.3f} deg    I: {intensity:.3g}    d: {d_text}"
        self.cursor_position_status_label.setText(text)

    def _set_offset_value(self, value: int) -> None:
        self.pattern_offset_value.setText(f"{value}%")
