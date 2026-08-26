from __future__ import annotations

import pytest

from crystal_viewer.analysis.hierarchy import CoordinationPolyhedron, PeriodicSiteRef
from crystal_viewer.analysis.nomenclature import assign_nomenclature
from crystal_viewer.analysis.structural_domains import StructuralDomain


def _polyhedron(identifier: int, element: str, coordination: int) -> CoordinationPolyhedron:
    return CoordinationPolyhedron(
        id=f"P{identifier}",
        center_index=identifier - 1,
        center_element=element,
        ligand_element="O",
        ligands=tuple(PeriodicSiteRef(100 + identifier * 10 + index) for index in range(coordination)),
        bond_lengths=(1.6,) * coordination,
        vertex_coordinates=((0.0, 0.0, 0.0),) * coordination,
        distortion=0.0,
        angle_dispersion=0.0,
    )


@pytest.mark.parametrize(
    ("classification", "rank", "count", "descriptor"),
    (
        ("island", 0, 1, "nesosilicate"),
        ("dimer", 0, 2, "sorosilicate"),
        ("ring", 0, 3, "cyclosilicate"),
        ("chain", 1, 3, "inosilicate"),
        ("ribbon", 1, 3, "inosilicate"),
        ("layer", 2, 3, "phyllosilicate"),
        ("framework", 3, 3, "tectosilicate"),
    ),
)
def test_silicate_vocabulary_names_only_derived_topology(
    classification: str,
    rank: int,
    count: int,
    descriptor: str,
) -> None:
    members = tuple(f"P{index}" for index in range(1, count + 1))
    domain = StructuralDomain("D1", members, (), rank, classification, 0.9)
    polyhedra = tuple(_polyhedron(index, "Si", 4) for index in range(1, count + 1))

    assignment = assign_nomenclature(domain, polyhedra, ())

    assert assignment is not None
    assert assignment.vocabulary == "silicate"
    assert assignment.descriptor == descriptor
    assert (domain.polyhedron_ids, domain.periodic_rank, domain.classification) == (
        members,
        rank,
        classification,
    )


def test_borate_ring_reports_bo3_bo4_membership_and_size() -> None:
    domain = StructuralDomain("D1", ("P1", "P2", "P3"), (), 0, "ring", 0.9)
    polyhedra = (_polyhedron(1, "B", 3), _polyhedron(2, "B", 3), _polyhedron(3, "B", 4))

    assignment = assign_nomenclature(domain, polyhedra, ())

    assert assignment is not None
    assert assignment.vocabulary == "borate"
    assert assignment.descriptor == "3-membered borate FBB (2 BO3 + 1 BO4)"


def test_borate_double_ring_is_named_as_a_fundamental_building_block() -> None:
    domain = StructuralDomain(
        "D1",
        ("P1", "P2", "P3", "P4", "P5"),
        (),
        0,
        "double-ring cluster",
        0.9,
    )
    polyhedra = (
        _polyhedron(1, "B", 4),
        *(_polyhedron(index, "B", 3) for index in range(2, 6)),
    )

    assignment = assign_nomenclature(domain, polyhedra, ())

    assert assignment is not None
    assert assignment.descriptor == "borate FBB — double-ring cluster (4 BO3 + 1 BO4)"


def test_unsupported_chemistry_keeps_generic_name() -> None:
    domain = StructuralDomain("D1", ("P1",), (), 0, "island", 0.9)

    assert assign_nomenclature(domain, (_polyhedron(1, "Mo", 6),), ()) is None
