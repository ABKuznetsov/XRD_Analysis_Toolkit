from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from crystal_viewer.analysis.surface_markings import SurfaceMarkingKind
from crystal_viewer.analysis.twin_geometry import TwinAggregate, TwinDomain
from crystal_viewer.ui.striation_table_model import StriationColumn, StriationTableModel
from crystal_viewer.ui.twin_table_model import TwinColumn, TwinTableModel


IDENTITY = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _domain(domain_id: str, state: str, index=None) -> TwinDomain:
    interval = None if index is None else (float(index - 1), float(index))
    return TwinDomain(domain_id, IDENTITY, (0.0, 0.0, 0.0), (), (), state, interval, index)


def test_twin_table_has_one_ordered_row_per_individual_or_lamella() -> None:
    _application()
    contact = TwinTableModel(TwinAggregate((_domain("I", "I"), _domain("II", "II")), (), ()))
    assert contact.rowCount() == 2
    assert contact.data(contact.index(0, TwinColumn.ID)) == "I"
    assert contact.data(contact.index(1, TwinColumn.ID)) == "II"

    lamellae = tuple(
        _domain(f"L{index}", "I" if index % 2 else "II", index)
        for index in range(1, 7)
    )
    polysynthetic = TwinTableModel(TwinAggregate(lamellae, (), ()))
    assert polysynthetic.rowCount() == 6
    assert tuple(
        polysynthetic.data(polysynthetic.index(row, TwinColumn.ORIENTATION))
        for row in range(6)
    ) == ("I", "II", "I", "II", "I", "II")


def test_striation_table_lists_all_families_and_rejects_unavailable_twin_marking() -> None:
    _application()
    model = StriationTableModel(((1, 0, 0), (1, 1, 0)), (), twin_available=False)
    emitted = []
    model.edit_requested.connect(emitted.append)

    assert model.rowCount() == 2
    twin_index = model.index(0, StriationColumn.TYPE)
    assert not model.setData(twin_index, SurfaceMarkingKind.TWIN.value)
    assert "polysynthetic" in model.data(
        model.index(0, StriationColumn.STATE), Qt.ItemDataRole.DisplayRole
    ).lower()

    assert model.setData(twin_index, SurfaceMarkingKind.INDUCTION.value)
    assert emitted[-1].marking.kind is SurfaceMarkingKind.INDUCTION
    assert model.flags(model.index(0, StriationColumn.DENSITY)) & Qt.ItemFlag.ItemIsEditable


def test_striation_table_enables_derived_twin_marking_for_polysynthetic_aggregate() -> None:
    _application()
    model = StriationTableModel(((1, 0, 0),), (), twin_available=True)
    emitted = []
    model.edit_requested.connect(emitted.append)

    assert model.setData(model.index(0, StriationColumn.TYPE), SurfaceMarkingKind.TWIN.value)
    assert emitted[-1].marking.kind is SurfaceMarkingKind.TWIN
    assert model.data(model.index(0, StriationColumn.PROVENANCE)) == "derived-polysynthetic"
