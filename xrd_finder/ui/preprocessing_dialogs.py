from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QHeaderView,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)


BACKGROUND_METHOD_LABELS = {
    "auto": "conservative XRD baseline",
    "auto_physical_model": "auto physical baseline",
    "auto_total_model": "auto physical + amorphous",
    "auto_with_broad": "XRD baseline + broad component",
    "exponential_1": "single-exponential baseline",
    "exponential_2": "double-exponential baseline",
    "exponential_3": "triple-exponential baseline",
    "exponential_1_with_broad": "single-exponential baseline + broad component",
    "exponential_2_with_broad": "double-exponential baseline + broad component",
    "exponential_3_with_broad": "triple-exponential baseline + broad component",
    "arpls": "arPLS",
    "asls": "AsLS",
    "snip": "SNIP",
    "rolling_ball": "rolling ball",
}


def background_method_label(method: str, degree: int | None = None) -> str:
    if method == "polynomial":
        return f"polynomial {degree}" if degree is not None else "polynomial"
    return BACKGROUND_METHOD_LABELS.get(method, method)


class _OddWindowMixin:
    def _odd(self, value: int) -> int:
        value = max(3, int(value))
        return value if value % 2 else value + 1


class _SliderRow(QWidget):
    changed = Signal()
    released = Signal()

    def __init__(self, minimum: int, maximum: int, value: int, suffix: str = "", parent=None) -> None:
        super().__init__(parent)
        self._suffix = suffix
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setTickInterval(max(1, (maximum - minimum) // 8))
        self.value_label = QLabel()
        self.value_label.setMinimumWidth(52)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.slider.valueChanged.connect(self._value_changed)
        self.slider.sliderReleased.connect(self.released)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        self._update_label(value)
        self._apply_enabled_style(True)

    def value(self) -> int:
        return int(self.slider.value())

    def set_value(self, value: int) -> None:
        value = int(value)
        self.slider.setValue(value)
        self._update_label(value)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self.slider.setEnabled(enabled)
        self.value_label.setEnabled(enabled)
        self._apply_enabled_style(enabled)

    def _update_label(self, value: int) -> None:
        self.value_label.setText(f"{int(value)}{self._suffix}")

    def _value_changed(self, value: int) -> None:
        self._update_label(value)
        self.changed.emit()

    def _apply_enabled_style(self, enabled: bool) -> None:
        if enabled:
            self.slider.setStyleSheet("")
            self.value_label.setStyleSheet("")
            return
        self.slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 5px; background: #343a42; border-radius: 2px; }"
            "QSlider::handle:horizontal { width: 15px; margin: -5px 0; border-radius: 7px; background: #59616b; }"
            "QSlider::tick:horizontal { background: #454c55; width: 1px; }"
        )
        self.value_label.setStyleSheet("color: #6f7782;")


class SmoothPanel(QWidget, _OddWindowMixin):
    previewRequested = Signal()
    applyRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, default_window: int, auto_plan=None, parent=None) -> None:
        super().__init__(parent)
        self._default_window = min(self._odd(default_window), 11)
        self._auto_plan = auto_plan
        self.setObjectName("preprocessingPanel")
        self.setMinimumWidth(460)

        self._noise_reduction = _SliderRow(0, 100, 60, "%")
        self._noise_reduction.setToolTip(
            "Blends the original data with an automatically sized peak-preserving filter."
        )

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self.previewRequested)

        self._noise_reduction.changed.connect(self._schedule_preview)
        self._noise_reduction.released.connect(self._flush_preview)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("Noise reduction", self._noise_reduction)

        cancel_button = QPushButton("Cancel")
        apply_button = QPushButton("Apply")
        cancel_button.clicked.connect(self._request_cancel)
        apply_button.clicked.connect(self._request_apply)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        button_row.addWidget(apply_button)

        hint = QLabel(
            "The filter window is selected automatically from the narrowest reliable peaks "
            "to reduce noise while preserving peak position, width and integrated intensity."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa4af;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Smooth the active XRD pattern."))
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addLayout(button_row)

    def _schedule_preview(self, *_args) -> None:
        self._preview_timer.start()

    def _flush_preview(self) -> None:
        if self._preview_timer.isActive():
            self._preview_timer.stop()
        self.previewRequested.emit()

    def _request_apply(self) -> None:
        self._preview_timer.stop()
        self.applyRequested.emit()

    def _request_cancel(self) -> None:
        self._preview_timer.stop()
        self.cancelRequested.emit()

    def window_size(self) -> int:
        return self._default_window

    def noise_reduction(self) -> float:
        return float(self._noise_reduction.value()) / 100.0


class XrdCropPanel(QWidget):
    previewRequested = Signal()
    applyRequested = Signal()
    cancelRequested = Signal()

    def __init__(
        self,
        patterns: list[tuple[str, str, float, float]],
        ranges_by_pattern: dict[str, list[list[float]]],
        active_pattern_id: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._patterns = patterns
        self._ranges_by_pattern = {
            pattern_id: [list(item[:2]) for item in ranges]
            for pattern_id, ranges in ranges_by_pattern.items()
            if isinstance(ranges, list)
        }
        self._current_pattern_id = ""
        self._loading = False
        self.setObjectName("preprocessingPanel")
        self.setMinimumWidth(460)

        self._pattern_combo = QComboBox()
        for pattern_id, name, _xmin, _xmax in patterns:
            self._pattern_combo.addItem(name, pattern_id)
        active_index = max(0, self._pattern_combo.findData(active_pattern_id))
        self._pattern_combo.setCurrentIndex(active_index)
        self._pattern_combo.currentIndexChanged.connect(self._on_pattern_changed)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["From 2theta", "To 2theta"])
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.itemChanged.connect(self._on_table_changed)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(120)

        add_button = QPushButton("Add range")
        remove_button = QPushButton("Remove selected")
        full_button = QPushButton("Full range")
        clear_button = QPushButton("Clear")
        apply_all_button = QPushButton("Apply to all XRD")
        apply_all_button.setToolTip("Copy the current crop ranges to every imported XRD pattern.")
        add_button.clicked.connect(self.add_range)
        remove_button.clicked.connect(self.remove_selected_range)
        full_button.clicked.connect(self.set_full_range)
        clear_button.clicked.connect(self.clear_ranges)
        apply_all_button.clicked.connect(self.apply_current_ranges_to_all)

        action_row = QHBoxLayout()
        action_row.addWidget(add_button)
        action_row.addWidget(remove_button)
        action_row.addWidget(full_button)
        action_row.addWidget(clear_button)
        action_row.addWidget(apply_all_button)

        cancel_button = QPushButton("Cancel")
        apply_button = QPushButton("Apply")
        cancel_button.clicked.connect(self.cancelRequested)
        apply_button.clicked.connect(self.applyRequested)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(cancel_button)
        button_row.addWidget(apply_button)

        hint = QLabel("Use one or more 2theta ranges. Empty ranges mean the full XRD pattern is shown.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa4af;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Crop displayed XRD range."))
        layout.addWidget(self._pattern_combo)
        layout.addWidget(self._table)
        layout.addLayout(action_row)
        layout.addWidget(hint)
        layout.addLayout(button_row)
        self._on_pattern_changed()

    def ranges_by_pattern(self) -> dict[str, list[list[float]]]:
        self._save_current_ranges()
        return {
            pattern_id: [list(item[:2]) for item in ranges]
            for pattern_id, ranges in self._ranges_by_pattern.items()
        }

    def _pattern_bounds(self, pattern_id: str) -> tuple[float, float]:
        for item_id, _name, xmin, xmax in self._patterns:
            if item_id == pattern_id:
                return float(xmin), float(xmax)
        return 0.0, 1.0

    def _current_ranges(self) -> list[list[float]]:
        ranges = []
        for row in range(self._table.rowCount()):
            start_item = self._table.item(row, 0)
            end_item = self._table.item(row, 1)
            try:
                start = float((start_item.text() if start_item is not None else "").strip())
                end = float((end_item.text() if end_item is not None else "").strip())
            except ValueError:
                continue
            if np.isfinite(start) and np.isfinite(end) and end > start:
                ranges.append([start, end])
        ranges.sort(key=lambda item: item[0])
        return ranges

    def _save_current_ranges(self) -> None:
        if self._current_pattern_id:
            self._ranges_by_pattern[self._current_pattern_id] = self._current_ranges()

    def _load_ranges(self, ranges: list[list[float]]) -> None:
        self._loading = True
        try:
            self._table.clearContents()
            self._table.setRowCount(len(ranges))
            for row, values in enumerate(ranges):
                start = float(values[0])
                end = float(values[1])
                self._table.setItem(row, 0, QTableWidgetItem(f"{start:.4g}"))
                self._table.setItem(row, 1, QTableWidgetItem(f"{end:.4g}"))
        finally:
            self._loading = False

    def _on_pattern_changed(self) -> None:
        if self._current_pattern_id:
            self._save_current_ranges()
        self._current_pattern_id = str(self._pattern_combo.currentData() or "")
        self._load_ranges(self._ranges_by_pattern.get(self._current_pattern_id, []))
        if not self._loading:
            self.previewRequested.emit()

    def _on_table_changed(self, _item) -> None:
        if self._loading:
            return
        self._save_current_ranges()
        self.previewRequested.emit()

    def add_range(self) -> None:
        xmin, xmax = self._pattern_bounds(self._current_pattern_id)
        current_ranges = self._current_ranges()
        if current_ranges:
            xmin, xmax = current_ranges[-1]
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(f"{xmin:.4g}"))
        self._table.setItem(row, 1, QTableWidgetItem(f"{xmax:.4g}"))
        self._save_current_ranges()
        self.previewRequested.emit()

    def remove_selected_range(self) -> None:
        rows = sorted({item.row() for item in self._table.selectedItems()}, reverse=True)
        if not rows and self._table.currentRow() >= 0:
            rows = [self._table.currentRow()]
        for row in rows:
            self._table.removeRow(row)
        self._save_current_ranges()
        self.previewRequested.emit()

    def set_full_range(self) -> None:
        xmin, xmax = self._pattern_bounds(self._current_pattern_id)
        self._load_ranges([[xmin, xmax]])
        self._save_current_ranges()
        self.previewRequested.emit()

    def clear_ranges(self) -> None:
        self._load_ranges([])
        self._save_current_ranges()
        self.previewRequested.emit()

    def apply_current_ranges_to_all(self) -> None:
        current_ranges = self._current_ranges()
        for pattern_id, _name, xmin, xmax in self._patterns:
            clipped = []
            for start, end in current_ranges:
                clipped_start = max(float(start), float(xmin))
                clipped_end = min(float(end), float(xmax))
                if clipped_end > clipped_start:
                    clipped.append([clipped_start, clipped_end])
            self._ranges_by_pattern[pattern_id] = clipped
        self._load_ranges(self._ranges_by_pattern.get(self._current_pattern_id, []))
        self.previewRequested.emit()


class BackgroundRemovalPanel(QWidget):
    previewRequested = Signal()
    applyRequested = Signal()
    subtractRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, default_degree: int = 10, auto_plan=None, auto_model=None, initial_state=None, parent=None) -> None:
        super().__init__(parent)
        self._default_degree = int(default_degree)
        self._auto_plan = auto_plan
        self._auto_model = auto_model
        self._auto_support_width = float(getattr(auto_model, "support_width_deg", 7.0))
        self._auto_smoothing = float(getattr(auto_model, "smoothing_deg", 4.0))
        self._has_initial_state = isinstance(initial_state, dict)
        self._auto_total_defaults_applied = False
        self._loading_settings = False
        self._active_target = "physical"
        self._target_settings = {
            "physical": {
                "method": "auto",
                "degree": self._default_degree,
                "exponential_terms": int(getattr(auto_model, "exponential_terms", 3)),
                "snip_window": 60,
                "floor_percentile": int(getattr(auto_plan, "floor_percentile", 15)),
            },
            "total": {
                "method": "snip",
                "degree": self._default_degree,
                "exponential_terms": int(getattr(auto_model, "exponential_terms", 3)),
                "snip_window": 120,
                "floor_percentile": int(getattr(auto_plan, "floor_percentile", 15)),
            },
        }
        if self._has_initial_state:
            saved_settings = initial_state.get("target_settings")
            if isinstance(saved_settings, dict):
                for target in ("physical", "total"):
                    if isinstance(saved_settings.get(target), dict):
                        self._target_settings[target].update(saved_settings[target])
            saved_target = str(initial_state.get("active_target", "physical"))
            if saved_target in self._target_settings:
                self._active_target = saved_target
        # The public panel deliberately exposes one automatic physical
        # background workflow. Detailed model controls remain internal so old
        # saved state can still be read without presenting it to the user.
        self._active_target = "physical"
        self.setObjectName("preprocessingPanel")
        self.setMinimumWidth(500)

        self._target = QComboBox()
        self._target.addItem("Physical background", "physical")
        self._target.addItem("Background + amorphous", "total")

        self._method = QComboBox()
        self._method.addItem("Auto conservative baseline", "auto")
        self._method.addItem("Auto physical baseline", "auto_physical_model")
        self._method.addItem("Auto physical + amorphous", "auto_total_model")
        self._method.addItem("Exponential", "exponential")
        self._method.addItem("Polynomial", "polynomial")
        self._method.addItem("AsLS", "asls")
        self._method.addItem("SNIP", "snip")
        self._method.addItem("Rolling ball", "rolling_ball")
        self._method.addItem("Constant floor", "constant")

        self._degree = _SliderRow(2, 30, self._default_degree)
        self._degree.slider.setPageStep(2)
        self._exponential_terms = _SliderRow(1, 3, 3)
        self._snip_window = _SliderRow(8, 240, 60)
        self._snip_window.setToolTip("Larger values follow broader background and amorphous scattering; smaller values stay closer to local valleys.")
        self._floor = _SliderRow(1, 40, 15, "%")
        self._show_background = QCheckBox("Show physical background")
        self._show_background.setChecked(
            bool(initial_state.get("show_background", True)) if isinstance(initial_state, dict) else True
        )
        self._show_total = QCheckBox("Show background + amorphous")
        self._show_total.setChecked(
            bool(initial_state.get("show_total", False)) if isinstance(initial_state, dict) else False
        )
        self._low_angle_cuvette = QCheckBox("Low-angle cuvette (<20 deg)")
        self._low_angle_cuvette.setChecked(
            bool(initial_state.get("low_angle_cuvette", False)) if isinstance(initial_state, dict) else False
        )
        self._low_angle_end = _SliderRow(12, 35, 20)
        self._low_angle_width = _SliderRow(1, 15, 4)
        self._low_angle_strength = _SliderRow(0, 100, 100, "%")
        self._level = _SliderRow(
            -100,
            100,
            int(initial_state.get("background_level", 0)) if isinstance(initial_state, dict) else 0,
            "%",
        )
        self._level.setToolTip("Move left for a lower baseline or right to bring it closer to local minima.")
        self._include_amorphous = QCheckBox("Include amorphous contribution")
        self._include_amorphous.setChecked(
            bool(initial_state.get("show_total", False)) if isinstance(initial_state, dict) else False
        )
        self._amorphous_strength = _SliderRow(
            0,
            100,
            int(initial_state.get("amorphous_strength", 100)) if isinstance(initial_state, dict) else 100,
            "%",
        )
        self._amorphous_strength.setToolTip("Fraction of the broad amorphous component to restore.")
        self._amorphous_strength.setEnabled(self._include_amorphous.isChecked())
        if self._has_initial_state:
            self._low_angle_end.set_value(int(initial_state.get("low_angle_end", 20)))
            self._low_angle_width.set_value(int(initial_state.get("low_angle_width", 4)))
            self._low_angle_strength.set_value(int(initial_state.get("low_angle_strength", 100)))

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(90)
        self._preview_timer.timeout.connect(self._emit_scheduled_preview)

        self._target.currentIndexChanged.connect(self._target_changed)
        self._method.currentIndexChanged.connect(self._method_changed)
        for slider_row in (
            self._degree,
            self._exponential_terms,
            self._snip_window,
            self._floor,
            self._low_angle_end,
            self._low_angle_width,
            self._low_angle_strength,
        ):
            slider_row.changed.connect(self._schedule_preview)
            slider_row.released.connect(self._flush_preview)
        self._level.changed.connect(self._schedule_preview)
        self._level.released.connect(self._flush_preview)
        self._include_amorphous.toggled.connect(self._amorphous_toggled)
        self._amorphous_strength.changed.connect(self._schedule_preview)
        self._amorphous_strength.released.connect(self._flush_preview)
        self._show_background.toggled.connect(self._display_changed)
        self._show_total.toggled.connect(self._display_changed)
        self._low_angle_cuvette.toggled.connect(self._method_changed)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.addRow("Background level", self._level)
        form.addRow("", self._include_amorphous)
        form.addRow("Amorphous contribution", self._amorphous_strength)

        apply_button = QPushButton("Apply")
        cancel_button = QPushButton("Cancel")
        apply_button.clicked.connect(self.applyRequested)
        cancel_button.clicked.connect(self.cancelRequested)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(apply_button)
        button_row.addWidget(cancel_button)

        score_text = ""
        if auto_model is not None and np.isfinite(float(getattr(auto_model, "score", float("inf")))):
            score_text = f" Auto metric: {float(auto_model.score):.4f}."
        hint = QLabel(
            "The background is estimated automatically. Move the slider left for a lower, "
            "more conservative curve or right to bring it closer to local minima. "
            "Negative values are preserved."
            + score_text
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa4af;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Subtract the automatically estimated background."))
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addLayout(button_row)
        self._set_combo_data(self._target, self._active_target)
        self._load_target_settings(self._active_target, emit_preview=False)
        self._method_changed(emit_preview=False)

    def _schedule_preview(self) -> None:
        if self._loading_settings:
            return
        self._preview_timer.start()

    def _emit_scheduled_preview(self) -> None:
        if not self._loading_settings:
            self.previewRequested.emit()

    def _flush_preview(self) -> None:
        if self._loading_settings:
            return
        self._preview_timer.stop()
        self.previewRequested.emit()

    def _target_changed(self, *_args) -> None:
        if self._loading_settings:
            return
        self._store_target_settings(self._active_target)
        target = self.target()
        if target == "total" and not self._auto_total_defaults_applied:
            self._apply_auto_total_defaults()
            self._auto_total_defaults_applied = True
        self._load_target_settings(target, emit_preview=False)
        self._active_target = target
        if target == "total" and not self._show_total.isChecked():
            self._show_total.setChecked(True)
        elif target == "physical" and not self._show_background.isChecked():
            self._show_background.setChecked(True)
        self._method_changed(emit_preview=True)

    def _display_changed(self, *_args) -> None:
        if self._loading_settings:
            return
        if self._show_total.isChecked() and not self._show_background.isChecked():
            previous = self._show_background.blockSignals(True)
            self._show_background.setChecked(True)
            self._show_background.blockSignals(previous)
        self._method_changed(emit_preview=True)

    def _method_changed(self, *_args, emit_preview: bool = True) -> None:
        if not self._loading_settings:
            self._store_target_settings(self.target())
        method = self.method()
        self._degree.setEnabled(method == "polynomial")
        self._exponential_terms.setEnabled(method == "exponential")
        self._snip_window.setEnabled(method == "snip")
        self._floor.setEnabled(method == "constant")
        low_angle_enabled = self.show_physical_background() and self.show_total_background()
        self._low_angle_cuvette.setEnabled(low_angle_enabled)
        low_angle_controls_enabled = low_angle_enabled and bool(self._low_angle_cuvette.isChecked())
        self._low_angle_end.setEnabled(low_angle_controls_enabled)
        self._low_angle_width.setEnabled(low_angle_controls_enabled)
        self._low_angle_strength.setEnabled(low_angle_controls_enabled)
        if emit_preview:
            self.previewRequested.emit()

    def _store_target_settings(self, target: str) -> None:
        self._target_settings[target] = {
            "method": self.method(),
            "degree": self.degree(),
            "exponential_terms": self.exponential_terms(),
            "snip_window": self.snip_window(),
            "floor_percentile": self.floor_percentile(),
        }

    def _load_target_settings(self, target: str, *, emit_preview: bool) -> None:
        settings = self._target_settings.get(target, self._target_settings["physical"])
        self._loading_settings = True
        blockers = [
            QSignalBlocker(self._method),
            QSignalBlocker(self._degree.slider),
            QSignalBlocker(self._exponential_terms.slider),
            QSignalBlocker(self._snip_window.slider),
            QSignalBlocker(self._floor.slider),
        ]
        self._set_combo_data(self._method, settings["method"])
        self._degree.set_value(int(settings["degree"]))
        self._exponential_terms.set_value(int(settings["exponential_terms"]))
        self._snip_window.set_value(int(settings["snip_window"]))
        self._floor.set_value(int(settings["floor_percentile"]))
        for blocker in blockers:
            blocker.unblock()
        self._loading_settings = False
        if emit_preview:
            self.previewRequested.emit()

    def _set_combo_data(self, combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def apply_auto(self) -> None:
        blockers = [
            QSignalBlocker(self._target),
            QSignalBlocker(self._method),
            QSignalBlocker(self._degree.slider),
            QSignalBlocker(self._exponential_terms.slider),
            QSignalBlocker(self._snip_window.slider),
            QSignalBlocker(self._floor.slider),
            QSignalBlocker(self._show_background),
            QSignalBlocker(self._show_total),
            QSignalBlocker(self._low_angle_cuvette),
            QSignalBlocker(self._low_angle_end.slider),
            QSignalBlocker(self._low_angle_width.slider),
            QSignalBlocker(self._low_angle_strength.slider),
        ]
        plan = self._auto_plan
        model = self._auto_model
        method = str(getattr(plan, "method", "auto"))
        floor_percentile = int(getattr(plan, "floor_percentile", 15))
        active_target = self.target()
        if active_target == "total":
            self._target_settings = self._auto_total_target_settings(method, floor_percentile)
            self._target.setCurrentIndex(max(0, self._target.findData("total")))
            self._active_target = "total"
            self._show_background.setChecked(True)
            self._show_total.setChecked(True)
            self._low_angle_cuvette.setChecked(False)
            self._low_angle_end.set_value(20)
            self._low_angle_width.set_value(4)
            self._low_angle_strength.set_value(100)
            settings = self._target_settings["total"]
            self._method.setCurrentIndex(max(0, self._method.findData(str(settings["method"]))))
            self._degree.set_value(int(settings["degree"]))
            self._exponential_terms.set_value(int(settings["exponential_terms"]))
            self._snip_window.set_value(int(settings["snip_window"]))
            self._floor.set_value(int(settings["floor_percentile"]))
            for blocker in blockers:
                blocker.unblock()
            self._method_changed(emit_preview=False)
            self.previewRequested.emit()
            return
        self._target_settings = {
            "physical": {
                "method": method,
                "degree": int(getattr(plan, "degree", self._default_degree)),
                "exponential_terms": int(getattr(model, "exponential_terms", 3)),
                "snip_window": 60,
                "floor_percentile": floor_percentile,
            },
            "total": {
                "method": "snip",
                "degree": int(getattr(plan, "degree", self._default_degree)),
                "exponential_terms": int(getattr(model, "exponential_terms", 3)),
                "snip_window": 120,
                "floor_percentile": floor_percentile,
            },
        }
        self._target.setCurrentIndex(max(0, self._target.findData("physical")))
        self._active_target = "physical"
        method_index = max(0, self._method.findData(method))
        self._method.setCurrentIndex(method_index)
        self._degree.set_value(int(getattr(plan, "degree", self._default_degree)))
        self._exponential_terms.set_value(int(getattr(model, "exponential_terms", 3)))
        self._snip_window.set_value(60)
        self._floor.set_value(floor_percentile)
        self._show_background.setChecked(True)
        self._show_total.setChecked(False)
        self._low_angle_cuvette.setChecked(False)
        self._low_angle_end.set_value(20)
        self._low_angle_width.set_value(4)
        self._low_angle_strength.set_value(100)
        for blocker in blockers:
            blocker.unblock()
        self._method_changed(emit_preview=False)
        self.previewRequested.emit()

    def _apply_auto_total_defaults(self) -> None:
        plan = self._auto_plan
        method = str(getattr(plan, "method", "auto"))
        floor_percentile = int(getattr(plan, "floor_percentile", 15))
        self._target_settings = self._auto_total_target_settings(method, floor_percentile)

    def _auto_total_target_settings(self, physical_method: str, floor_percentile: int) -> dict[str, dict[str, int | str]]:
        model = self._auto_model
        return {
            "physical": {
                "method": "auto_physical_model" if model is not None else physical_method,
                "degree": int(getattr(model, "amorphous_degree", self._default_degree)),
                "exponential_terms": int(getattr(model, "exponential_terms", 3)),
                "snip_window": 60,
                "floor_percentile": int(floor_percentile),
            },
            "total": {
                "method": "auto_total_model" if model is not None else "snip",
                "degree": int(getattr(model, "amorphous_degree", self._default_degree)),
                "exponential_terms": int(getattr(model, "exponential_terms", 3)),
                "snip_window": max(8, int(round(float(getattr(model, "support_width_deg", 7.0)) * 18.0))),
                "floor_percentile": int(floor_percentile),
            },
        }

    def target(self) -> str:
        return str(self._target.currentData())

    def settings_for(self, target: str) -> dict[str, int | str]:
        self._store_target_settings(self.target())
        return dict(self._target_settings.get(target, self._target_settings["physical"]))

    def export_state(self) -> dict[str, object]:
        self._store_target_settings(self.target())
        return {
            "active_target": self.target(),
            "target_settings": {
                "physical": dict(self._target_settings["physical"]),
                "total": dict(self._target_settings["total"]),
            },
            "show_background": self.show_physical_background(),
            "show_total": self.show_total_background(),
            "low_angle_cuvette": bool(self._low_angle_cuvette.isChecked()),
            "low_angle_end": self.low_angle_end(),
            "low_angle_width": self.low_angle_width(),
            "low_angle_strength": self.low_angle_strength(),
            "background_level": int(self._level.value()),
            "amorphous_strength": int(self._amorphous_strength.value()),
        }

    def background_level(self) -> float:
        return float(np.clip(self._level.value() / 100.0, -1.0, 1.0))

    def include_amorphous(self) -> bool:
        return bool(self._include_amorphous.isChecked())

    def amorphous_strength(self) -> float:
        return float(np.clip(self._amorphous_strength.value() / 100.0, 0.0, 1.0))

    def _amorphous_toggled(self, checked: bool) -> None:
        self._amorphous_strength.setEnabled(bool(checked))
        self._schedule_preview()

    def method(self) -> str:
        return str(self._method.currentData())

    def amorphous_method(self) -> str:
        return self.method()

    def degree(self) -> int:
        return int(self._degree.value())

    def floor_percentile(self) -> int:
        return int(self._floor.value())

    def exponential_terms(self) -> int:
        return int(self._exponential_terms.value())

    def snip_window(self) -> int:
        return int(self._snip_window.value())

    def amorphous_degree(self) -> int:
        return 3

    def amorphous_support_width(self) -> float:
        return self._auto_support_width

    def amorphous_smoothing(self) -> float:
        return self._auto_smoothing

    def remove_halo(self) -> bool:
        return self.include_amorphous()

    def estimate_background(self) -> bool:
        return self.show_physical_background()

    def estimate_amorphous(self) -> bool:
        return self.include_amorphous()

    def low_angle_cuvette(self) -> bool:
        return (
            bool(self._low_angle_cuvette.isChecked())
            and self.show_physical_background()
            and self.show_total_background()
        )

    def low_angle_end(self) -> int:
        return int(self._low_angle_end.value())

    def low_angle_width(self) -> int:
        return int(self._low_angle_width.value())

    def low_angle_strength(self) -> float:
        return max(0.0, min(1.0, self._low_angle_strength.value() / 100.0))

    def show_physical_background(self) -> bool:
        return True

    def show_total_background(self) -> bool:
        return self.include_amorphous()

class SmoothDialog(QDialog):
    def __init__(self, default_window: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Smooth XRD pattern")
        self._panel = SmoothPanel(default_window, self)
        self._panel.applyRequested.connect(self.accept)
        self._panel.cancelRequested.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._panel)

    def auto_enabled(self) -> bool:
        return False

    def method(self) -> str:
        return self._panel.method()

    def window_size(self) -> int:
        return self._panel.window_size()

    def polyorder(self) -> int:
        return self._panel.polyorder()

    def gaussian_sigma(self) -> float:
        return self._panel.gaussian_sigma()

    def passes(self) -> int:
        return self._panel.passes()


class BackgroundRemovalDialog(QDialog):
    def __init__(self, default_degree: int = 10, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Remove background")
        self._panel = BackgroundRemovalPanel(default_degree, parent=self)
        self._panel.applyRequested.connect(self.accept)
        self._panel.cancelRequested.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._panel)

    def auto_enabled(self) -> bool:
        return self._panel.method() == "auto"

    def method(self) -> str:
        return self._panel.method()

    def degree(self) -> int:
        return self._panel.degree()
