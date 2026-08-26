from __future__ import annotations

from crystal_viewer.analysis.hierarchy import HierarchyReport
from crystal_viewer.analysis.projection_match import projection_candidates
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import CrystalStructure, UnitCell


def _document(name: str, cell: UnitCell) -> StructureDocument:
    structure = CrystalStructure(name, cell, [], [])
    return StructureDocument.from_structure(structure, HierarchyReport())


def test_projection_candidates_match_close_axis_lengths() -> None:
    first = _document("first", UnitCell(5.0, 7.0, 9.0))
    second = _document("second", UnitCell(7.05, 12.0, 5.02))

    candidates = projection_candidates(first, second)

    assert candidates
    assert candidates[0].first_direction in {"a", "b", "c"}
    assert candidates[0].second_direction in {"a", "b", "c"}
    assert "length" in candidates[0].evidence
    assert "length_delta" in candidates[0].score_components


def test_ambiguous_cubic_cells_return_requested_candidates() -> None:
    first = _document("first", UnitCell(5.0, 5.0, 5.0))
    second = _document("second", UnitCell(5.0, 5.0, 5.0))

    assert len(projection_candidates(first, second, limit=3)) == 3
