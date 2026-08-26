from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec


def _hkl_text(hkl) -> str:
    return "" if hkl is None else " ".join(str(value) for value in hkl)


def _parse_hkl(text: str, field: str):
    parts = text.strip().replace("(", " ").replace(")", " ").replace(",", " ").split()
    if len(parts) != 3:
        raise ValueError(f"{field} must contain three integer indices.")
    try:
        return tuple(int(value) for value in parts)
    except ValueError as error:
        raise ValueError(f"{field} must contain three integer indices.") from error


class TwinEditor(QWidget):
    spec_changed = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        root.addLayout(form)

        self.aggregate_kind = QComboBox()
        for kind, label in (
            (TwinAggregateKind.CONTACT, "Contact"),
            (TwinAggregateKind.PENETRATION, "Penetration"),
            (TwinAggregateKind.POLYSYNTHETIC, "Polysynthetic"),
        ):
            self.aggregate_kind.addItem(label, kind.value)
        form.addRow("Aggregate", self.aggregate_kind)

        self.law_mode = QComboBox()
        for mode, label in (
            (TwinLawMode.REFLECTION, "Reflection K1"),
            (TwinLawMode.TWOFOLD, "Twofold axis"),
            (TwinLawMode.MATRIX, "Reciprocal matrix U"),
        ):
            self.law_mode.addItem(label, mode.value)
        form.addRow("Twin law", self.law_mode)

        self.plane_label = QLabel("K1 (h k l)")
        self.plane_input = QLineEdit("1 0 0")
        form.addRow(self.plane_label, self.plane_input)
        self.axis_label = QLabel("Axis [u v w]")
        self.axis_input = QLineEdit("0 0 1")
        form.addRow(self.axis_label, self.axis_input)

        self.matrix_label = QLabel("U, h′ = U h")
        self.matrix_table = QTableWidget(3, 3)
        self.matrix_table.horizontalHeader().hide()
        self.matrix_table.verticalHeader().hide()
        self.matrix_table.setMaximumHeight(92)
        for row in range(3):
            for column in range(3):
                self.matrix_table.setItem(
                    row,
                    column,
                    QTableWidgetItem("1" if row == column else "0"),
                )
        form.addRow(self.matrix_label, self.matrix_table)

        self.composition_input = QLineEdit()
        self.composition_input.setPlaceholderText("blank = same as reflection K1")
        form.addRow("Composition plane", self.composition_input)
        self.composition_offset = QDoubleSpinBox()
        self.composition_offset.setRange(-1_000_000.0, 1_000_000.0)
        self.composition_offset.setDecimals(6)
        form.addRow("Plane offset", self.composition_offset)

        self.translation_frame = QFrame()
        translation_layout = QHBoxLayout(self.translation_frame)
        translation_layout.setContentsMargins(0, 0, 0, 0)
        self.translation = []
        for name in ("x", "y", "z"):
            translation_layout.addWidget(QLabel(name))
            field = QDoubleSpinBox()
            field.setRange(-1_000_000.0, 1_000_000.0)
            field.setDecimals(6)
            translation_layout.addWidget(field)
            self.translation.append(field)
        form.addRow("Domain II translation", self.translation_frame)

        self.lamella_frame = QFrame()
        lamella_layout = QHBoxLayout(self.lamella_frame)
        lamella_layout.setContentsMargins(0, 0, 0, 0)
        lamella_layout.addWidget(QLabel("Count"))
        self.lamella_count = QSpinBox()
        self.lamella_count.setRange(2, 200)
        self.lamella_count.setValue(8)
        lamella_layout.addWidget(self.lamella_count)
        lamella_layout.addWidget(QLabel("I fraction"))
        self.lamella_ratio = QDoubleSpinBox()
        self.lamella_ratio.setRange(0.01, 0.99)
        self.lamella_ratio.setSingleStep(0.05)
        self.lamella_ratio.setDecimals(3)
        self.lamella_ratio.setValue(0.5)
        lamella_layout.addWidget(self.lamella_ratio)
        form.addRow("Lamellae", self.lamella_frame)

        actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply twin geometry")
        self.clear_button = QPushButton("Remove twin")
        actions.addWidget(self.apply_button)
        actions.addWidget(self.clear_button)
        actions.addStretch()
        root.addLayout(actions)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.error_label)

        self.law_mode.currentIndexChanged.connect(self._update_visibility)
        self.aggregate_kind.currentIndexChanged.connect(self._update_visibility)
        self.apply_button.clicked.connect(self._apply)
        self.clear_button.clicked.connect(lambda: self.spec_changed.emit(None))
        self._update_visibility()

    def _update_visibility(self) -> None:
        mode = TwinLawMode(self.law_mode.currentData())
        self.plane_label.setVisible(mode is TwinLawMode.REFLECTION)
        self.plane_input.setVisible(mode is TwinLawMode.REFLECTION)
        self.axis_label.setVisible(mode is TwinLawMode.TWOFOLD)
        self.axis_input.setVisible(mode is TwinLawMode.TWOFOLD)
        self.matrix_label.setVisible(mode is TwinLawMode.MATRIX)
        self.matrix_table.setVisible(mode is TwinLawMode.MATRIX)
        kind = TwinAggregateKind(self.aggregate_kind.currentData())
        self.translation_frame.setVisible(kind is TwinAggregateKind.PENETRATION)
        self.lamella_frame.setVisible(kind is TwinAggregateKind.POLYSYNTHETIC)

    def _law(self) -> TwinLaw:
        mode = TwinLawMode(self.law_mode.currentData())
        if mode is TwinLawMode.REFLECTION:
            return TwinLaw(mode, plane_hkl=_parse_hkl(self.plane_input.text(), "K1"))
        if mode is TwinLawMode.TWOFOLD:
            return TwinLaw(mode, axis_uvw=_parse_hkl(self.axis_input.text(), "Axis"))
        matrix = []
        for row in range(3):
            values = []
            for column in range(3):
                item = self.matrix_table.item(row, column)
                try:
                    values.append(float(item.text() if item is not None else ""))
                except ValueError as error:
                    raise ValueError("Twin matrix must contain nine finite numbers.") from error
            matrix.append(tuple(values))
        return TwinLaw(mode, reciprocal_matrix=tuple(matrix))

    def _apply(self) -> None:
        try:
            kind = TwinAggregateKind(self.aggregate_kind.currentData())
            composition_text = self.composition_input.text().strip()
            composition = (
                _parse_hkl(composition_text, "Composition plane")
                if composition_text
                else None
            )
            spec = TwinAggregateSpec(
                kind,
                self._law(),
                composition_plane_hkl=composition,
                composition_offset=self.composition_offset.value(),
                second_translation=tuple(field.value() for field in self.translation),
                lamella_count=self.lamella_count.value(),
                lamella_ratio=self.lamella_ratio.value(),
            )
        except (TypeError, ValueError) as error:
            self.set_error(str(error))
            return
        self.set_error("")
        self.spec_changed.emit(spec)

    def set_spec(self, spec: TwinAggregateSpec | None) -> None:
        if spec is None:
            self.set_error("")
            return
        self.aggregate_kind.setCurrentIndex(self.aggregate_kind.findData(spec.kind.value))
        self.law_mode.setCurrentIndex(self.law_mode.findData(spec.law.mode.value))
        self.plane_input.setText(_hkl_text(spec.law.plane_hkl))
        self.axis_input.setText(_hkl_text(spec.law.axis_uvw))
        if spec.law.reciprocal_matrix is not None:
            for row, values in enumerate(spec.law.reciprocal_matrix):
                for column, value in enumerate(values):
                    self.matrix_table.setItem(row, column, QTableWidgetItem(f"{value:g}"))
        self.composition_input.setText(_hkl_text(spec.composition_plane_hkl))
        self.composition_offset.setValue(spec.composition_offset)
        for field, value in zip(self.translation, spec.second_translation, strict=True):
            field.setValue(value)
        self.lamella_count.setValue(spec.lamella_count)
        self.lamella_ratio.setValue(spec.lamella_ratio)
        self._update_visibility()
        self.set_error("")

    def set_selected_family(self, hkl) -> None:
        if hkl is not None:
            self.composition_input.setText(_hkl_text(hkl))

    def set_error(self, text: str) -> None:
        self.error_label.setText(str(text))


__all__ = ["TwinEditor"]
