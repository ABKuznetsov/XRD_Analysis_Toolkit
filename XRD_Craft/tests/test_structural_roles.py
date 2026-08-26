from __future__ import annotations

from math import sqrt

import pytest

from crystal_viewer.analysis.periodic_bonds import PeriodicBond, PeriodicBondResult
from crystal_viewer.analysis.structural_analysis import CoordinationEnvironment
from crystal_viewer.analysis.structural_roles import (
    PolyhedronRoleEvidence,
    classify_polyhedron_roles,
    primary_motif_center_indices,
)
from crystal_viewer.core.model import AtomSite, CrystalStructure, SiteComponent, UnitCell


def _environment(
    element: str,
    distance: float,
    directions: tuple[tuple[float, float, float], ...],
    *,
    components: tuple[SiteComponent, ...] = (),
) -> tuple[CrystalStructure, PeriodicBondResult, tuple[CoordinationEnvironment, ...]]:
    cell = UnitCell(20.0, 20.0, 20.0)
    center = AtomSite(
        "M1",
        element,
        (0.5, 0.5, 0.5),
        components=components,
    )
    sites = [center]
    for index, direction in enumerate(directions, start=1):
        length = sqrt(sum(value * value for value in direction))
        sites.append(
            AtomSite(
                f"O{index}",
                "O",
                tuple(0.5 + distance * value / length / 20.0 for value in direction),
            )
        )
    bonds = PeriodicBondResult(
        tuple(
            PeriodicBond(0, index, (0, 0, 0), distance, 1.0, "crystalnn", 1.0)
            for index in range(1, len(sites))
        ),
        True,
    )
    coordination = (
        CoordinationEnvironment(
            center_index=0,
            neighbor_indices=tuple(range(1, len(sites))),
            neighbor_images=((0, 0, 0),) * (len(sites) - 1),
        ),
    )
    return CrystalStructure(element, cell, sites, sites), bonds, coordination


OCTAHEDRAL = (
    (1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0),
    (0.0, 0.0, 1.0),
    (0.0, 0.0, -1.0),
)
TETRAHEDRAL = (
    (1.0, 1.0, 1.0),
    (-1.0, -1.0, 1.0),
    (-1.0, 1.0, -1.0),
    (1.0, -1.0, -1.0),
)
TRIGONAL = (
    (1.0, 0.0, 0.0),
    (-0.5, sqrt(3.0) / 2.0, 0.0),
    (-0.5, -sqrt(3.0) / 2.0, 0.0),
)


@pytest.mark.parametrize(
    ("element", "distance", "directions"),
    (("Si", 1.62, TETRAHEDRAL), ("B", 1.37, TRIGONAL), ("Mo", 1.95, OCTAHEDRAL)),
)
def test_high_bond_valence_polyhedra_are_structural(
    element: str,
    distance: float,
    directions: tuple[tuple[float, float, float], ...],
) -> None:
    structure, bonds, environments = _environment(element, distance, directions)

    result = classify_polyhedron_roles(structure, bonds, environments)

    assert len(result) == 1
    assert result[0].role == "structural"
    assert result[0].mean_bond_valence >= 0.45
    assert result[0].method == "pymatgen-bond-valence-unordered"


def test_mixed_na_li_octahedron_uses_components_and_is_interstitial() -> None:
    components = (SiteComponent("Na", 0.669), SiteComponent("Li", 0.331))
    structure, bonds, environments = _environment(
        "Na/Li",
        2.45,
        OCTAHEDRAL,
        components=components,
    )

    result = classify_polyhedron_roles(structure, bonds, environments)

    assert len(result) == 1
    assert result[0].role == "interstitial"
    assert result[0].method == "pymatgen-bond-valence-unordered"
    assert 0.0 < result[0].mean_bond_valence < 0.30
    assert result[0].warnings == ()


def test_missing_neighbours_remain_ambiguous() -> None:
    center = AtomSite("M1", "Na", (0.5, 0.5, 0.5))
    structure = CrystalStructure("missing", UnitCell(10.0, 10.0, 10.0), [center], [center])
    environments = (CoordinationEnvironment(0, (), ()),)

    result = classify_polyhedron_roles(
        structure,
        PeriodicBondResult((), True),
        environments,
    )

    assert result[0].role == "ambiguous"
    assert result[0].confidence == 0.0
    assert "neighbour" in " ".join(result[0].warnings).lower()


def test_strength_gap_does_not_split_compatible_mixed_tetrahedra() -> None:
    roles = tuple(
        PolyhedronRoleEvidence(index, "structural", value, 0.9, "test")
        for index, value in enumerate((0.48, 0.49, 0.82, 0.84))
    )
    signatures = {
        0: frozenset(("element:Al", "coordination:O:4")),
        1: frozenset(("element:Al", "coordination:O:4")),
        2: frozenset(("element:Si", "coordination:O:4")),
        3: frozenset(("element:Si", "coordination:O:4")),
    }

    assert primary_motif_center_indices(roles, signatures) == frozenset(range(4))
