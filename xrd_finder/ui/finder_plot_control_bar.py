from __future__ import annotations

import math

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QSlider,
    QToolButton,
    QWidget,
)

from xrd_finder.ui.plot_view_settings import PLOT_ASPECTS
from xrd_finder.ui.wrapping_layout import WrappingLayout


def d_spacing_from_two_theta(two_theta: float, wavelength: float) -> float | None:
    angle = float(two_theta)
    radiation = float(wavelength)
    if not math.isfinite(angle) or not math.isfinite(radiation) or angle <= 0.0 or radiation <= 0.0:
        return None
    sine = math.sin(math.radians(angle / 2.0))
    if sine <= 0.0:
        return None
    return radiation / (2.0 * sine)


class PatternDisplayButton(QToolButton):
    """Two display modes, retaining the mode names used by saved projects."""
    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setProperty('plotToggle', True)
        self.setText('One pattern')
        self.toggled.connect(lambda checked: self.setText('All selected' if checked else 'One pattern'))

    def currentText(self):
        return 'All selected' if self.isChecked() else 'One'

    def setCurrentText(self, mode):
        self.setChecked(mode == 'All selected')
        self.setText('All selected' if self.isChecked() else 'One pattern')


class FinderPlotControlBar(QWidget):
    patternDisplayModeChanged = Signal(str)
    plotAspectModeChanged = Signal(str)
    patternOffsetPercentChanged = Signal(int)
    normalizePatternsChanged = Signal(bool)
    zeroCorrectionChanged = Signal(bool)
    allObservedBlackChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("finderPlotControlBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._bar_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._bar_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._bar_layout.setContentsMargins(8, 5, 8, 5)
        self._bar_layout.setSpacing(6)
        self._controls = QWidget(self)
        layout = WrappingLayout(self._controls)
        self._flow_layout = layout

        self.pattern_display_mode = PatternDisplayButton()
        self.pattern_display_mode.setToolTip(
            "One: show only the active XRD pattern.\n"
            "All selected: show all checked XRD patterns from the project tree."
        )
        self.pattern_display_mode.toggled.connect(
            lambda checked: self.patternDisplayModeChanged.emit('All selected' if checked else 'One'))

        self.plot_aspect_mode = QComboBox()
        self.plot_aspect_mode.addItems(PLOT_ASPECTS.keys())
        self.plot_aspect_mode.setMinimumWidth(68)
        self.plot_aspect_mode.setMaximumWidth(100)
        self.plot_aspect_mode.setToolTip(
            "Set the plot canvas proportions without changing the application window size."
        )
        self.plot_aspect_mode.currentTextChanged.connect(self.plotAspectModeChanged)

        self.normalize_patterns_checkbox = self._toggle_button('Normalize')
        self.normalize_patterns_checkbox.setToolTip(
            "Display experimental XRD patterns with Imax = 100. "
            "Fitted phases, peak assignments and search scores are retained."
        )
        self.normalize_patterns_checkbox.toggled.connect(self.normalizePatternsChanged)
        self.correct_zero_checkbox = self._toggle_button("Correct zero")
        self.correct_zero_checkbox.setToolTip(
            "Display this scan and its phase lines on the corrected 2theta scale. "
            "Uses Processing > Zero shift; original data and fitted results are unchanged."
        )
        self.correct_zero_checkbox.toggled.connect(self.zeroCorrectionChanged)
        self.all_observed_black_button = self._toggle_button('All black')
        self.all_observed_black_button.setToolTip(
            'Show all experimental curves in black. Turn off to restore their assigned colors. '
            'Phase markers and calculated curves keep their colors.')
        self.all_observed_black_button.toggled.connect(self.allObservedBlackChanged)

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

        self.cursor_position_status_label = QLabel(self)
        self.cursor_position_status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.cursor_position_status_label.setObjectName('cursorReadout')
        self.cursor_position_status_label.setMinimumHeight(24)
        self.cursor_position_status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.set_cursor_readout()

        for controls in ((self.pattern_display_mode,),
                         (QLabel('Aspect'), self.plot_aspect_mode),
                         (self.normalize_patterns_checkbox,),
                         (QLabel('Offset'), self.pattern_offset_slider, self.pattern_offset_value),
                         (self.correct_zero_checkbox,),
                         (self.all_observed_black_button,)):
            group=QWidget()
            row=QHBoxLayout(group);row.setContentsMargins(0,0,0,0);row.setSpacing(6)
            for control in controls:row.addWidget(control)
            layout.addWidget(group)
        self._bar_layout.addWidget(self._controls, 1)
        self._bar_layout.addWidget(self.cursor_position_status_label, 0, Qt.AlignmentFlag.AlignRight)
        for button in (self.pattern_display_mode, self.normalize_patterns_checkbox,
                       self.correct_zero_checkbox, self.all_observed_black_button):
            button.toggled.connect(lambda _checked: self._update_control_layout())

    @staticmethod
    def _toggle_button(text):
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setProperty('plotToggle', True)
        return button

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_control_layout()

    def _update_control_layout(self) -> None:
        if not hasattr(self, '_flow_layout'):
            return
        density=getattr(self.window(),"_ui_density_factor",1.)
        self._bar_layout.setContentsMargins(round(8*density),round(5*density),round(8*density),round(5*density))
        self._bar_layout.setSpacing(max(1,round(6*density)))
        available=max(1,self.width()-round(16*density)-2)
        self._controls.show()
        show_cursor=True
        self.cursor_position_status_label.show()
        cursor_width=self.cursor_position_status_label.sizeHint().width() if show_cursor else 0
        horizontal=self._flow_layout.sizeHint().width()+cursor_width+round(6*density)<=available
        direction=QBoxLayout.Direction.LeftToRight if horizontal else QBoxLayout.Direction.TopToBottom
        self._bar_layout.setDirection(direction)
        controls_width=available-cursor_width-round(6*density) if horizontal else available
        height=self._flow_layout.heightForWidth(controls_width)
        self._controls.setFixedHeight(height)
        cursor_height=self.cursor_position_status_label.sizeHint().height()
        total=(max(height,cursor_height) if horizontal else height+cursor_height+self._bar_layout.spacing())+round(10*density)+2
        if self.minimumHeight()!=total or self.maximumHeight()!=total:
            self.setFixedHeight(total)
            self.updateGeometry()

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
        self.cursor_position_status_label.setToolTip(text)
        self.setToolTip(text)
        self._update_control_layout()

    def _set_offset_value(self, value: int) -> None:
        self.pattern_offset_value.setText(f"{value}%")
