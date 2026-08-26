from pathlib import Path

import numpy as np

from crystal_viewer.analysis.reporting import Availability, Provenance
from crystal_viewer.analysis.reporting.builder import StructureReportBuilder
from crystal_viewer.analysis.reporting.crystal import (
    build_adp_table,
    build_atomic_sites_table,
    build_crystal_data_table,
    build_refinement_table,
)
from crystal_viewer.core.cif import load_cif


ROOT = Path(__file__).resolve().parents[1]


def test_crystal_table_preserves_reported_cell_token() -> None:
    structure = load_cif(
        ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif",
        expand_symmetry=False,
    )
    table = build_crystal_data_table(structure)

    a_row = next(row for row in table.rows if row.id == "cell:a")
    assert a_row.cells["value"].provenance is Provenance.REPORTED
    assert a_row.cells["value"].display == structure.source_data.raw("_cell_length_a")


def test_atomic_sites_are_asymmetric_not_expanded() -> None:
    structure = load_cif(ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif")
    table = build_atomic_sites_table(structure)

    assert len(table.rows) == len(structure.asymmetric_sites)
    assert {row.cells["label"].display for row in table.rows} == {
        site.label for site in structure.asymmetric_sites
    }


def test_biso_is_reported_and_converted_u_is_calculated() -> None:
    structure = load_cif(
        ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif",
        expand_symmetry=False,
    )
    table = build_adp_table(structure)

    assert table.availability is Availability.AVAILABLE
    row = table.rows[0]
    assert row.cells["parameter"].display == "Biso"
    assert row.cells["reported"].provenance is Provenance.REPORTED
    assert row.cells["reported"].display == "1.000"
    assert row.cells["u_equiv"].provenance is Provenance.CALCULATED
    assert np.isclose(float(row.cells["u_equiv"].value), 1.0 / (8.0 * np.pi**2))


def test_absent_refinement_data_is_explained() -> None:
    structure = load_cif(
        ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif",
        expand_symmetry=False,
    )
    table = build_refinement_table(structure)

    assert table.availability is Availability.UNAVAILABLE
    assert "source CIF" in table.unavailable_reason


def test_builder_is_lazy_and_marks_later_stage_tables_unavailable() -> None:
    structure = load_cif(
        ROOT / "examples" / "gehlenite_Ca2Al2SiO7_average.cif",
        expand_symmetry=False,
    )
    builder = StructureReportBuilder(structure)

    crystal = builder.table("crystal_data")
    assert builder.table("crystal_data") is crystal
    unavailable = builder.table("bond_valence")
    assert unavailable.availability is Availability.UNAVAILABLE
    assert "Stage B" in unavailable.unavailable_reason
    report = builder.build(("crystal_data", "bond_valence"))
    assert tuple(report.tables) == ("crystal_data", "bond_valence")
