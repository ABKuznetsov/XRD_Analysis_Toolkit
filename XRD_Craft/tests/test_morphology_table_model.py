from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from crystal_viewer.analysis.morphology import MillerFamily, MorphologyPlane
from crystal_viewer.analysis.morphology_geometry import MorphologyFacet, MorphologyModel
from crystal_viewer.ui.morphology_table_model import MorphologyColumn, MorphologyTableModel
from crystal_viewer.ui.morphology_colors import family_color


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def _model(*, manual: bool = False, area: float = 2.0) -> MorphologyModel:
    family = MillerFamily((1, 0, 0), ((1, 0, 0), (-1, 0, 0)), 5.0, 2, 2.5, "cif-loop")
    plane = MorphologyPlane(family, 1.0, 1.3 if manual else 1.0, manual=manual)
    facet = MorphologyFacet((1, 0, 0), (1, 0, 0), ((1, 0, 0), (1, 1, 0), (1, 0, 1)), (1, 0, 0), area)
    return MorphologyModel(
        (plane,),
        ((1, 0, 0), (1, 1, 0), (1, 0, 1)),
        (facet,) if area else (),
        1.0,
        {(1, 0, 0): area},
        {(1, 0, 0): 1.0 if area else 0.0},
    )


def test_table_exposes_reference_and_current_columns_and_only_intended_edit_flags() -> None:
    _application()
    model = MorphologyTableModel(_model())

    assert model.rowCount() == 1
    assert model.columnCount() == 12
    enabled = model.index(0, MorphologyColumn.ENABLED)
    rho = model.index(0, MorphologyColumn.CURRENT_RHO)
    spacing = model.index(0, MorphologyColumn.D_HKL)
    assert model.flags(enabled) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.flags(rho) & Qt.ItemFlag.ItemIsEditable
    assert not model.flags(spacing) & Qt.ItemFlag.ItemIsEditable
    assert model.data(model.index(0, MorphologyColumn.HKL)) == "(1 0 0)"
    assert model.headerData(
        MorphologyColumn.REFERENCE_FRACTION,
        Qt.Orientation.Horizontal,
    ) == "Reference fraction, %"
    assert model.headerData(
        MorphologyColumn.CURRENT_FRACTION,
        Qt.Orientation.Horizontal,
    ) == "Current fraction, %"


def test_table_reports_primary_origin() -> None:
    _application()
    model = MorphologyTableModel(_model(), primary_families={(1, 0, 0)})

    assert model.data(model.index(0, MorphologyColumn.ORIGIN)) == "primary 80%"


def test_manual_and_non_manifest_states_are_textual() -> None:
    _application()
    manual = MorphologyTableModel(_model(manual=True))
    hidden = MorphologyTableModel(_model(area=0.0))

    assert manual.data(manual.index(0, MorphologyColumn.STATE)) == "manual"
    assert manual.data(manual.index(0, MorphologyColumn.CURRENT_RHO)) == "1.3"
    assert hidden.data(hidden.index(0, MorphologyColumn.STATE)) == "not manifested"


def test_rho_edit_accepts_comma_and_invalid_value_does_not_emit() -> None:
    _application()
    model = MorphologyTableModel(_model())
    edits = []
    model.edit_requested.connect(edits.append)
    index = model.index(0, MorphologyColumn.CURRENT_RHO)

    assert model.setData(index, "1,75", Qt.ItemDataRole.EditRole)
    assert edits[-1].hkl == (1, 0, 0)
    assert edits[-1].rho == 1.75
    before = len(edits)
    assert not model.setData(index, "0", Qt.ItemDataRole.EditRole)
    assert len(edits) == before
    assert "positive" in model.data(index, MorphologyTableModel.ErrorRole).lower()


def test_unchecking_family_emits_disabled_edit() -> None:
    _application()
    model = MorphologyTableModel(_model())
    edits = []
    model.edit_requested.connect(edits.append)
    index = model.index(0, MorphologyColumn.ENABLED)

    assert model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert edits[-1].enabled is False


def test_family_color_is_exposed_as_table_swatch_and_data_role() -> None:
    _application()
    model = MorphologyTableModel(_model(), color_by_family={(1, 0, 0): "#123456"})
    index = model.index(0, MorphologyColumn.HKL)

    expected = "#123456"
    assert model.data(index, MorphologyTableModel.ColorRole) == expected
    decoration = model.data(index, Qt.ItemDataRole.DecorationRole)
    assert isinstance(decoration, QColor)
    assert decoration.name() == expected
