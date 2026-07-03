from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from xrd_manager.core.project import Project


class RightPanel(QTabWidget):
    pattern_display_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(260)
        self.project: Project | None = None

        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes for selected project object")
        self.addTab(self._main_tab(), "Main")
        self.view_tab = self._view_tab()
        self.addTab(self.view_tab, "View")
        self.addTab(self._settings_tab(), "Settings")

    def set_notes(self, text: str) -> None:
        self.notes.setPlainText(text)

    def set_project(self, project: Project) -> None:
        self.project = project

    def _main_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Notes"))
        layout.addWidget(self.notes)
        return widget

    def _view_tab(self) -> QWidget:
        widget = QWidget()
        self.view_layout = QVBoxLayout(widget)
        self.view_layout.addWidget(QLabel("Pattern view mode"))

        self.single_mode = QRadioButton("Single")
        self.multi_mode = QRadioButton("Multi compare")
        self.single_mode.setChecked(True)
        mode_group = QButtonGroup(widget)
        mode_group.addButton(self.single_mode)
        mode_group.addButton(self.multi_mode)
        self.single_mode.toggled.connect(self._emit_pattern_display)
        self.multi_mode.toggled.connect(self._emit_pattern_display)
        self.view_layout.addWidget(self.single_mode)
        self.view_layout.addWidget(self.multi_mode)

        self.view_layout.addWidget(QLabel("Multi compare offset"))
        self.offset_mode = QComboBox()
        self.offset_mode.addItems(["Pattern height", "Above noise", "Custom"])
        self.offset_mode.currentTextChanged.connect(self._emit_pattern_display)
        self.view_layout.addWidget(self.offset_mode)

        self.custom_offset = QDoubleSpinBox()
        self.custom_offset.setRange(0.0, 1_000_000.0)
        self.custom_offset.setDecimals(2)
        self.custom_offset.setSingleStep(100.0)
        self.custom_offset.setValue(1000.0)
        self.custom_offset.valueChanged.connect(self._emit_pattern_display)
        self.view_layout.addWidget(self.custom_offset)

        self.view_layout.addWidget(QLabel("Context view layers"))
        self.layer_checks: dict[str, QCheckBox] = {}
        for label in ["Observed", "Calculated", "Difference", "Phase contributions", "HKL markers"]:
            checkbox = QCheckBox(label)
            checkbox.setChecked(label in {"Observed", "Calculated"})
            checkbox.toggled.connect(self._emit_pattern_display)
            self.layer_checks[label] = checkbox
            self.view_layout.addWidget(checkbox)
        self.view_layout.addStretch(1)
        return widget

    def _emit_pattern_display(self, *_args: object) -> None:
        self.pattern_display_changed.emit()

    def pattern_view_options(self) -> dict[str, object]:
        return {
            "mode": "multi" if self.multi_mode.isChecked() else "single",
            "offset_mode": self.offset_mode.currentText(),
            "custom_offset": float(self.custom_offset.value()),
            "show_observed": self.layer_checks["Observed"].isChecked(),
            "show_calculated": self.layer_checks["Calculated"].isChecked(),
            "show_hkl": self.layer_checks["HKL markers"].isChecked(),
        }

    def _settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        theme = QComboBox()
        theme.addItems(["Light", "Print", "Dark"])
        layout.addRow("Theme", theme)

        font_size = QSpinBox()
        font_size.setRange(8, 24)
        font_size.setValue(10)
        layout.addRow("Font size", font_size)

        dpi = QSpinBox()
        dpi.setRange(72, 1200)
        dpi.setValue(300)
        layout.addRow("Export DPI", dpi)

        return widget
