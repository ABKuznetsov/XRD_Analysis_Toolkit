from __future__ import annotations

from PySide6.QtCore import Qt

from crystal_viewer.analysis import comparison
from crystal_viewer.analysis.comparison import (
    ComparisonCell,
    ComparisonReport,
    ComparisonRow,
    ComparisonState,
)
from crystal_viewer.ui.compare_table_model import CompareTableModel


def _cell(
    document_id: str,
    display: str,
    state: ComparisonState = ComparisonState.SIMILAR,
    raw: object = None,
) -> ComparisonCell:
    return ComparisonCell(document_id, display, state, raw)


def _row(
    descriptor_id: str,
    title: str,
    section: str,
    second_state: ComparisonState = ComparisonState.SIMILAR,
) -> ComparisonRow:
    return ComparisonRow(
        descriptor_id,
        title,
        section,
        (
            _cell("a", "1", ComparisonState.SIMILAR, 1.0),
            _cell("b", "2", second_state, 2.0),
        ),
        method_id="method-v1",
    )


def _report() -> ComparisonReport:
    return ComparisonReport(
        document_ids=("a", "b"),
        document_titles=("Structure A", "Structure B"),
        rows=(
            _row("cell.a", "Cell a", "Crystal data"),
            _row("cell.volume", "Volume", "Crystal data", ComparisonState.DIFFERENT),
        ),
    )


def _report_with_all_sections() -> ComparisonReport:
    return ComparisonReport(
        document_ids=("a", "b"),
        document_titles=("Structure A", "Structure B"),
        rows=(
            _row("cell.a", "Cell a", "Crystal data", ComparisonState.DIFFERENT),
            _row("coordination.polyhedron_counts", "Polyhedra", "Coordination"),
            _row("motif.shared", "Shared motif", "Structural Motifs"),
            _row(
                "connections.shared",
                "Shared connections",
                "Connections and Interstitial Atoms",
            ),
            _row("topology.component_classes", "Topology", "Topology"),
            _row("occupancy.out_of_range", "Occupancy warnings", "Crystal data"),
        ),
    )


def test_model_has_descriptor_column_plus_structure_columns() -> None:
    report = _report()
    model = CompareTableModel(report)

    assert model.columnCount() == len(report.document_ids) + 1
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Structure A"


def test_sections_are_root_rows_and_descriptors_are_children() -> None:
    model = CompareTableModel(_report_with_all_sections())

    assert model.rowCount() == 6
    section = model.index(0, 0)
    child = model.index(0, 0, section)

    assert model.data(section) == "Unit Cell"
    assert model.rowCount(section) == 1
    assert model.comparison_row(child).descriptor_id == "cell.a"
    assert model.parent(child) == section


def test_show_differences_filters_rows_and_removes_empty_sections() -> None:
    model = CompareTableModel(_report_with_all_sections())

    model.set_show_differences_only(True)

    assert model.rowCount() == 1
    section = model.index(0, 0)
    assert model.data(section) == "Unit Cell"
    assert model.rowCount(section) == 1
    assert model.comparison_row(model.index(0, 0, section)).has_difference


def test_section_heading_exposes_difference_count_and_summary() -> None:
    model = CompareTableModel(_report())
    section_name = model.index(0, 0)
    section_summary = model.index(0, 1)

    assert model.data(section_name, model.SectionSummaryRole) == comparison.SectionSummary(
        name="Unit Cell",
        difference_count=1,
        summary="2 characteristics compared",
    )
    assert model.data(section_summary) == "1 difference · 2 characteristics compared"


def test_cell_roles_expose_state_and_raw_value() -> None:
    model = CompareTableModel(_report())
    section = model.index(0, 0)
    index = model.index(1, 2, section)

    assert model.data(index, model.StateRole) is ComparisonState.DIFFERENT
    assert model.data(index, model.RawValueRole) == 2.0
    assert model.data(index, Qt.ItemDataRole.BackgroundRole) is not None
    assert model.comparison_row(index).descriptor_id == "cell.volume"
