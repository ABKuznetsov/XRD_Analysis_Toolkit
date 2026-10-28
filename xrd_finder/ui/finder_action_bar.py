from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from xrd_finder.ui.plot_view_settings import CollapsibleSection
from xrd_finder.ui.theme import is_dark_theme, settings_panel_style


class FinderActionBar(QWidget):
    smoothRequested = Signal()
    cropRequested = Signal()
    subtractBackgroundRequested = Signal()
    searchRequested = Signal()
    instrumentProfileSelected = Signal(str)
    instrumentProfileEditRequested = Signal()
    manualZeroShiftChanged = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.search_input = QLineEdit()
        self.instrument_profile_combo = QComboBox()
        self.instrument_profile_edit_button = QToolButton()
        self.zero_shift_refined_value = QLabel("0.000000")
        self.zero_shift_refined_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.zero_shift_refined_value.setToolTip("Scan-zero displacement from the current refinement")
        self.zero_shift_warning_label = QLabel("")
        self.zero_shift_warning_label.setWordWrap(True)
        self.zero_shift_warning_label.hide()
        self.zero_shift_value = QDoubleSpinBox()
        self.zero_shift_value.setDecimals(6)
        self.zero_shift_value.setRange(-180., 180.)
        self.zero_shift_value.setSingleStep(.01)
        self.zero_shift_value.setToolTip(
            "Additional visual correction to the experimental pattern: "
            "2theta minus refined zero minus visual correction. Zero means no additional correction. "
            "Requires Correct zero. Does not change calculations or peak assignments."
        )
        self.peak_search_tolerance = QDoubleSpinBox()
        self.peak_search_tolerance.setDecimals(4)
        self.peak_search_tolerance.setRange(.0001, 179.)
        self.peak_search_tolerance.setSingleStep(.01)
        # Same starting window as the existing local peak index, not a
        # calibrated instrument uncertainty or a statistical confidence limit.
        self.peak_search_tolerance.setValue(.35)
        self.peak_search_tolerance.setToolTip(
            "Maximum absolute position difference for selected-peak search, in degrees 2theta. "
            "Converted to exact d-spacing intervals using the active wavelength. "
            "Uses refined zero, never the visual correction. This is a search window, not calibration uncertainty."
        )
        self._preprocessing_hosts: dict[str, QWidget] = {}
        self._preprocessing_host_layouts: dict[str, QVBoxLayout] = {}
        self._preprocessing_placeholders: dict[str, QLabel] = {}
        self._preprocessing_sections: dict[str, CollapsibleSection] = {}
        self._current_preprocessing_key: str | None = None
        self._current_preprocessing_panel: QWidget | None = None
        self._build_ui()

    def search_text(self) -> str:
        return self.search_input.text().strip()

    def set_search_text(self, text: str) -> None:
        self.search_input.setText(text)

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.processing_scroll = QScrollArea()
        self.processing_scroll.setWidgetResizable(True)
        self.processing_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("processingBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.processing_scroll.setWidget(body)
        root_layout.addWidget(self.processing_scroll)
        self.setStyleSheet(settings_panel_style(is_dark_theme(self)))

        self.instrument_profile_combo.setMinimumContentsLength(12)
        self.instrument_profile_combo.setMinimumWidth(120)
        self.instrument_profile_combo.setMaximumWidth(170)
        self.instrument_profile_combo.setToolTip("Instrument and radiation profile used for calculated patterns")
        self.instrument_profile_combo.currentIndexChanged.connect(self._emit_instrument_profile)
        self.instrument_profile_edit_button.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        self.instrument_profile_edit_button.setToolTip("Edit instrument profile")
        self.instrument_profile_edit_button.clicked.connect(self.instrumentProfileEditRequested)

        instrument_row = QVBoxLayout()
        instrument_row.setContentsMargins(0, 0, 0, 0)
        instrument_row.setSpacing(6)
        instrument_row.addWidget(QLabel("Active instrument profile"))
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.instrument_profile_combo, 1)
        profile_row.addWidget(self.instrument_profile_edit_button)
        instrument_row.addLayout(profile_row)

        self.smooth_button = self._add_preprocessing_section(
            layout,
            "smooth",
            "Smoothing",
            "Select an active XRD pattern, then expand this section to configure smoothing.",
        )
        self.background_button = self._add_preprocessing_section(
            layout,
            "background",
            "Background",
            "Select an active XRD pattern, then expand this section to estimate background.",
        )
        self.crop_button = self._add_preprocessing_section(
            layout,
            "xrd_crop",
            "Crop XRD",
            "Select imported XRD patterns, then expand this section to edit crop ranges.",
        )
        zero_body = QWidget()
        zero_layout = QFormLayout(zero_body)
        zero_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        zero_layout.addRow("Refined zero [deg]", self.zero_shift_refined_value)
        zero_layout.addRow("Visual correction [deg]", self.zero_shift_value)
        zero_layout.addRow(self.zero_shift_warning_label)
        self.zero_shift_section = CollapsibleSection("Zero shift", zero_body, expanded=False)
        self.zero_shift_value.editingFinished.connect(
            lambda: self.manualZeroShiftChanged.emit(self.zero_shift_value.value())
        )
        layout.addWidget(self.zero_shift_section)
        peak_search_body = QWidget()
        peak_search_layout = QFormLayout(peak_search_body)
        peak_search_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        peak_search_layout.addRow("Tolerance [deg 2theta]", self.peak_search_tolerance)
        layout.addWidget(CollapsibleSection("Peak search", peak_search_body, expanded=False))
        layout.addWidget(self._section_from_layout("Instrument and radiation", instrument_row))
        layout.addStretch(1)

        self.search_input.setPlaceholderText("Formula / elements / phase name")
        self.search_input.returnPressed.connect(self.searchRequested)
        self.search_input.hide()

    def preprocessing_panel_host(self, key: str) -> QWidget | None:
        return self._preprocessing_hosts.get(str(key))

    def show_preprocessing_panel(self, key: str, panel: QWidget, title: str) -> None:
        self.close_preprocessing_panel()
        self._current_preprocessing_key = str(key)
        self._current_preprocessing_panel = panel
        host = self._preprocessing_hosts.get(str(key))
        host_layout = self._preprocessing_host_layouts.get(str(key))
        placeholder = self._preprocessing_placeholders.get(str(key))
        section = self._preprocessing_sections.get(str(key))
        if host is None or host_layout is None:
            return
        if section is not None and not section.toggle.isChecked():
            section.toggle.setChecked(True)
            section._set_expanded(True)
        if placeholder is not None:
            placeholder.hide()
        panel.setParent(host)
        panel.setMinimumWidth(0)
        host_layout.addWidget(panel)
        panel.show()

    def close_preprocessing_panel(self) -> None:
        current_key = self._current_preprocessing_key
        panel = self._current_preprocessing_panel
        if panel is not None:
            host_layout = self._preprocessing_host_layouts.get(str(current_key))
            if host_layout is not None:
                host_layout.removeWidget(panel)
            panel.hide()
            panel.deleteLater()
        placeholder = self._preprocessing_placeholders.get(str(current_key))
        if placeholder is not None:
            placeholder.show()
        section = self._preprocessing_sections.get(str(current_key))
        if section is not None:
            section.toggle.setChecked(False)
            section._set_expanded(False)
        self._current_preprocessing_key = None
        self._current_preprocessing_panel = None

    def current_preprocessing_panel(self) -> QWidget | None:
        return self._current_preprocessing_panel

    def current_preprocessing_key(self) -> str | None:
        return self._current_preprocessing_key

    def set_instrument_profiles(self, profiles: list[tuple[str, str]], active_id: str = "") -> None:
        self.instrument_profile_combo.blockSignals(True)
        try:
            self.instrument_profile_combo.clear()
            for profile_id, name in profiles:
                self.instrument_profile_combo.addItem(name, profile_id)
            index = self.instrument_profile_combo.findData(active_id)
            self.instrument_profile_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.instrument_profile_combo.blockSignals(False)

    def current_instrument_profile_id(self) -> str:
        return str(self.instrument_profile_combo.currentData() or "")

    def _emit_instrument_profile(self, _index: int) -> None:
        profile_id = self.current_instrument_profile_id()
        if profile_id:
            self.instrumentProfileSelected.emit(profile_id)

    def _add_preprocessing_section(
        self,
        layout: QVBoxLayout,
        key: str,
        title: str,
        placeholder_text: str,
    ) -> QToolButton:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(8, 8, 8, 8)
        host_layout.setSpacing(8)
        placeholder = QLabel(placeholder_text)
        placeholder.setObjectName("processingPlaceholder")
        placeholder.setWordWrap(True)
        host_layout.addWidget(placeholder)
        section = CollapsibleSection(title, host, expanded=False)
        section.toggle.clicked.connect(lambda checked, item_key=key: self._preprocessing_section_toggled(item_key, checked))
        self._preprocessing_hosts[key] = host
        self._preprocessing_host_layouts[key] = host_layout
        self._preprocessing_placeholders[key] = placeholder
        self._preprocessing_sections[key] = section
        layout.addWidget(section)
        return section.toggle

    def _section_from_layout(self, title: str, source_layout: QHBoxLayout) -> CollapsibleSection:
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(8)
        content_layout.addLayout(source_layout)
        return CollapsibleSection(title, content, expanded=False)

    def _preprocessing_section_toggled(self, key: str, checked: bool) -> None:
        if not checked:
            return
        QTimer.singleShot(0, lambda item_key=key: self._emit_preprocessing_request(item_key))

    def _emit_preprocessing_request(self, key: str) -> None:
        section = self._preprocessing_sections.get(key)
        if section is None or not section.toggle.isChecked():
            return
        if key == "smooth":
            self.smoothRequested.emit()
        elif key == "background":
            self.subtractBackgroundRequested.emit()
        elif key == "xrd_crop":
            self.cropRequested.emit()
