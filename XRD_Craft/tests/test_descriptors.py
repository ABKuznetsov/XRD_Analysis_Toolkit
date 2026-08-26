from __future__ import annotations

import pytest

from crystal_viewer.analysis.descriptors.builders import build_descriptors
from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyReport,
    PeriodicSiteRef,
)
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell


@pytest.fixture
def mo_o6_document() -> StructureDocument:
    sites = [AtomSite("Mo1", "Mo", (0.0, 0.0, 0.0))]
    sites.extend(
        AtomSite(f"O{number}", "O", (0.1 * number, 0.0, 0.0))
        for number in range(1, 7)
    )
    structure = CrystalStructure(
        name="synthetic-MoO6",
        cell=UnitCell(10.0, 10.0, 10.0),
        asymmetric_sites=sites,
        sites=sites,
    )
    vertices = (
        (1.2, 0.0, 0.0),
        (-0.8, 0.0, 0.0),
        (0.2, 1.0, 0.0),
        (0.2, -1.0, 0.0),
        (0.2, 0.0, 1.0),
        (0.2, 0.0, -1.0),
    )
    polyhedron = CoordinationPolyhedron(
        id="P1",
        center_index=0,
        center_element="Mo",
        ligand_element="O",
        ligands=tuple(PeriodicSiteRef(index) for index in range(1, 7)),
        bond_lengths=(1.7, 1.8, 1.9, 2.0, 2.1, 2.4),
        vertex_coordinates=vertices,
        distortion=0.0,
        angle_dispersion=0.0,
    )
    return StructureDocument.from_structure(
        structure,
        HierarchyReport(polyhedra=[polyhedron]),
    )


def test_mo_5_plus_1_descriptor_uses_sorted_six_distances(
    mo_o6_document: StructureDocument,
) -> None:
    values = build_descriptors(mo_o6_document, strong_5_plus_1_gap=0.25)
    gap = values["mo_o.d6_minus_d5"].value

    assert gap.count == 1
    assert gap.values == pytest.approx((0.30,))
    assert values["mo_o.strong_5_plus_1_fraction"].value == pytest.approx(1.0)


def test_off_centering_is_distance_from_ligand_centroid(
    mo_o6_document: StructureDocument,
) -> None:
    value = build_descriptors(mo_o6_document)["mo_o.off_centering"].value

    assert value.mean == pytest.approx(0.20)


def test_descriptor_builder_reports_cell_counts_warnings_and_caches(
    mo_o6_document: StructureDocument,
) -> None:
    first = build_descriptors(mo_o6_document)
    second = build_descriptors(mo_o6_document)

    assert first is second
    assert first["cell.a"].value == 10.0
    assert first["coordination.polyhedron_counts"].value == {"MoO6": 1}
    assert first["occupancy.out_of_range"].value == "none"


def test_descriptor_cache_rebuilds_after_document_content_changes(
    mo_o6_document: StructureDocument,
) -> None:
    mo_o6_document.structure.cell = UnitCell(5.0, 6.0, 7.0)
    initial = build_descriptors(mo_o6_document)

    mo_o6_document.structure.cell = UnitCell(9.0, 6.0, 7.0)
    changed = build_descriptors(mo_o6_document)
    reused = build_descriptors(mo_o6_document)

    assert initial["cell.a"].value == 5.0
    assert changed["cell.a"].value == 9.0
    assert changed is not initial
    assert reused is changed


def test_unit_cell_descriptors_include_angles_space_group_and_c_over_a(
    mo_o6_document: StructureDocument,
) -> None:
    mo_o6_document.structure.cell = UnitCell(
        10.0,
        12.0,
        15.0,
        alpha=88.0,
        beta=91.0,
        gamma=92.0,
    )
    mo_o6_document.structure.space_group = "P 21/c"

    values = build_descriptors(mo_o6_document)

    assert values["cell.alpha"].value == 88.0
    assert values["cell.beta"].value == 91.0
    assert values["cell.gamma"].value == 92.0
    assert values["cell.alpha"].unit == "°"
    assert values["cell.space_group"].value == "P 21/c"
    assert values["cell.c_over_a"].title == "c/a ratio"
    assert values["cell.c_over_a"].value == pytest.approx(1.5)
    assert {
        values[identifier].section
        for identifier in (
            "cell.alpha",
            "cell.beta",
            "cell.gamma",
            "cell.space_group",
            "cell.c_over_a",
        )
    } == {"Unit Cell"}
