import pytest

from crystal_viewer.analysis.reporting import (
    Provenance,
    ReportCell,
    ReportRow,
    report_preset,
    table_definition,
)


def test_report_row_keeps_publication_flag_separate_from_value() -> None:
    row = ReportRow(
        id="bond:Al1:O1:1_555",
        cells={"distance": ReportCell(1.734, "1.734", Provenance.CALCULATED)},
        include_in_publication=True,
        object_refs=("polyhedron:P1",),
    )

    assert row.cells["distance"].provenance is Provenance.CALCULATED
    assert row.include_in_publication


def test_report_row_cells_are_immutable() -> None:
    row = ReportRow(
        id="atom:Al1",
        cells={"label": ReportCell("Al1", "Al1", Provenance.REPORTED)},
    )

    with pytest.raises(TypeError):
        row.cells["label"] = ReportCell("Al2", "Al2", Provenance.CURATED)


def test_full_preset_lists_unavailable_stage_b_tables() -> None:
    preset = report_preset("full")

    assert "crystal_data" in preset.table_ids
    assert "bond_valence" in preset.table_ids
    assert table_definition("bond_valence").stage == "B"


def test_catalogue_contains_all_approved_report_families() -> None:
    full = set(report_preset("full").table_ids)

    assert {
        "crystal_data",
        "atomic_sites",
        "bond_lengths",
        "polyhedra",
        "bond_valence",
        "structural_units",
        "degrees_of_freedom",
    } <= full


def test_custom_preset_starts_empty() -> None:
    assert report_preset("custom").table_ids == ()
