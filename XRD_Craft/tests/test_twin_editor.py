from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from crystal_viewer.analysis.twin_law import TwinLaw, TwinLawMode
from crystal_viewer.analysis.twin_state import TwinAggregateKind, TwinAggregateSpec
from crystal_viewer.ui.twin_editor import TwinEditor


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _choose(combo, value: str) -> None:
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_twin_editor_shows_only_fields_relevant_to_law_and_aggregate() -> None:
    _application()
    editor = TwinEditor()

    _choose(editor.law_mode, TwinLawMode.REFLECTION.value)
    assert not editor.plane_input.isHidden()
    assert editor.axis_input.isHidden()
    assert editor.matrix_table.isHidden()

    _choose(editor.law_mode, TwinLawMode.TWOFOLD.value)
    assert editor.plane_input.isHidden()
    assert not editor.axis_input.isHidden()
    assert editor.matrix_table.isHidden()

    _choose(editor.law_mode, TwinLawMode.MATRIX.value)
    assert editor.plane_input.isHidden()
    assert editor.axis_input.isHidden()
    assert not editor.matrix_table.isHidden()
    assert editor.matrix_table.rowCount() == editor.matrix_table.columnCount() == 3

    _choose(editor.aggregate_kind, TwinAggregateKind.CONTACT.value)
    assert not editor.composition_input.isHidden()
    assert editor.translation_frame.isHidden()
    assert editor.lamella_frame.isHidden()
    _choose(editor.aggregate_kind, TwinAggregateKind.PENETRATION.value)
    assert not editor.translation_frame.isHidden()
    assert editor.lamella_frame.isHidden()
    _choose(editor.aggregate_kind, TwinAggregateKind.POLYSYNTHETIC.value)
    assert editor.translation_frame.isHidden()
    assert not editor.lamella_frame.isHidden()


def test_twin_editor_emits_validated_spec_and_invalid_text_is_selectable() -> None:
    _application()
    editor = TwinEditor()
    emitted = []
    editor.spec_changed.connect(emitted.append)
    editor.plane_input.setText("1 1 0")
    editor.composition_input.setText("")

    editor.apply_button.click()

    assert len(emitted) == 1
    assert emitted[0] == TwinAggregateSpec(
        TwinAggregateKind.CONTACT,
        TwinLaw(TwinLawMode.REFLECTION, plane_hkl=(1, 1, 0)),
    )

    editor.plane_input.setText("not an hkl")
    editor.apply_button.click()
    assert len(emitted) == 1
    assert editor.error_label.text()
    assert editor.error_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_set_spec_populates_matrix_and_polysynthetic_controls() -> None:
    _application()
    editor = TwinEditor()
    spec = TwinAggregateSpec(
        TwinAggregateKind.POLYSYNTHETIC,
        TwinLaw(
            TwinLawMode.MATRIX,
            reciprocal_matrix=((0.0, -1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        ),
        composition_plane_hkl=(1, 0, 0),
        lamella_count=12,
        lamella_ratio=0.3,
    )

    editor.set_spec(spec)

    assert editor.law_mode.currentData() == TwinLawMode.MATRIX.value
    assert editor.aggregate_kind.currentData() == TwinAggregateKind.POLYSYNTHETIC.value
    assert editor.matrix_table.item(0, 1).text() == "-1"
    assert editor.lamella_count.value() == 12
    assert editor.lamella_ratio.value() == 0.3
