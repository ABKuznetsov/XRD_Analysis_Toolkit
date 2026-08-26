from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from crystal_viewer.adapters import to_pymatgen
from crystal_viewer.analysis.periodic_bonds import build_periodic_bonds
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.model import AtomSite, CrystalStructure, SiteComponent, UnitCell


ROOT = Path(__file__).resolve().parents[1]


def test_to_pymatgen_preserves_disordered_species_and_triclinic_lattice() -> None:
    site = AtomSite(
        "M1",
        "Na/Li",
        (0.125, 0.25, 0.375),
        occupancy=0.9,
        components=(SiteComponent("Na", 0.6), SiteComponent("Li", 0.3)),
    )
    source = CrystalStructure(
        "mixed",
        UnitCell(4.1, 5.2, 6.3, 81.0, 92.0, 103.0),
        [site],
        [site],
    )

    result = to_pymatgen(source)

    assert result.lattice.abc == pytest.approx((4.1, 5.2, 6.3))
    assert result.lattice.angles == pytest.approx((81.0, 92.0, 103.0))
    assert result[0].frac_coords == pytest.approx((0.125, 0.25, 0.375))
    assert float(result[0].species["Na"]) == pytest.approx(0.6)
    assert float(result[0].species["Li"]) == pytest.approx(0.3)
    assert result[0].properties["label"] == "M1"


def test_to_pymatgen_accepts_reported_overoccupancy_without_mutating_source() -> None:
    oxygen = AtomSite("O1", "O", (0.0, 0.0, 0.0), occupancy=1.024)
    structure = CrystalStructure("overoccupied", UnitCell(5.0, 5.0, 5.0), [oxygen], [oxygen])

    adapted = to_pymatgen(structure)

    assert float(adapted[0].species["O"]) == pytest.approx(1.0)
    assert structure.sites[0].reported_occupancy == pytest.approx(1.024)


def test_crystalnn_builds_one_canonical_periodic_bond_per_contact() -> None:
    structure = load_cif(ROOT / "examples" / "hinged_silicate.cif")

    result = build_periodic_bonds(structure)

    assert result.complete is True
    assert len(result.bonds) == 8
    assert all(bond.first < bond.second for bond in result.bonds)
    assert all(bond.method == "crystalnn" for bond in result.bonds)
    assert all(bond.weight == pytest.approx(1.0) for bond in result.bonds)
    assert {
        (structure.sites[bond.first].element, structure.sites[bond.second].element)
        for bond in result.bonds
    } == {("Si", "O")}


def test_periodic_bond_canonicalization_inverts_the_reverse_image() -> None:
    first = AtomSite("Na1", "Na", (0.05, 0.0, 0.0))
    second = AtomSite("Cl1", "Cl", (0.95, 0.0, 0.0))
    structure = CrystalStructure("boundary", UnitCell(10.0, 10.0, 10.0), [first, second], [first, second])

    class BoundaryFinder:
        def get_nn_info(self, _structure, index: int):
            if index == 0:
                return [{"site_index": 1, "image": (-1, 0, 0), "weight": 0.8}]
            return [{"site_index": 0, "image": (1, 0, 0), "weight": 0.8}]

    result = build_periodic_bonds(structure, neighbor_finder=BoundaryFinder())

    assert len(result.bonds) == 1
    assert result.bonds[0].first == 0
    assert result.bonds[0].second == 1
    assert result.bonds[0].image == (-1, 0, 0)
    assert result.bonds[0].distance == pytest.approx(1.0)


def test_crystalnn_near_zero_alternatives_are_not_promoted_to_bonds() -> None:
    sites = [
        AtomSite("Li1", "Li", (0.0, 0.0, 0.0)),
        AtomSite("O1", "O", (0.2, 0.0, 0.0)),
        AtomSite("B1", "B", (0.3, 0.0, 0.0)),
    ]
    structure = CrystalStructure("weighted", UnitCell(10.0, 10.0, 10.0), sites, sites)

    class WeightedFinder:
        def get_nn_info(self, _structure, index: int):
            if index == 0:
                return [
                    {"site_index": 1, "image": (0, 0, 0), "weight": 0.8},
                    {"site_index": 2, "image": (0, 0, 0), "weight": 0.04},
                ]
            if index == 1:
                return [{"site_index": 0, "image": (0, 0, 0), "weight": 0.8}]
            return [{"site_index": 0, "image": (0, 0, 0), "weight": 0.04}]

    result = build_periodic_bonds(structure, neighbor_finder=WeightedFinder())

    assert [(bond.first, bond.second) for bond in result.bonds] == [(0, 1)]


def test_crystalnn_uses_the_most_probable_discrete_coordination_shell() -> None:
    sites = [AtomSite("Mo1", "Mo", (0.0, 0.0, 0.0))] + [
        AtomSite(f"O{index}", "O", (0.05 * index, 0.0, 0.0))
        for index in range(1, 8)
    ]
    structure = CrystalStructure("shells", UnitCell(20.0, 20.0, 20.0), sites, sites)

    class ShellFinder:
        def get_nn_data(self, _structure, index: int):
            if index:
                return SimpleNamespace(cn_weights={}, cn_nninfo={})
            neighbours = [
                {"site_index": ligand, "image": (0, 0, 0), "weight": 1.0}
                for ligand in range(1, 8)
            ]
            return SimpleNamespace(
                cn_weights={6: 0.7, 7: 0.3},
                cn_nninfo={6: neighbours[:6], 7: neighbours},
            )

    result = build_periodic_bonds(structure, neighbor_finder=ShellFinder())

    assert len(result.bonds) == 6


def test_failed_primary_neighbor_search_uses_component_aware_radius_fallback() -> None:
    center = AtomSite(
        "M1",
        "Na/Li",
        (0.0, 0.0, 0.0),
        components=(SiteComponent("Na", 0.5), SiteComponent("Li", 0.5)),
    )
    oxygen = AtomSite("O1", "O", (0.3, 0.0, 0.0))
    boron = AtomSite("B1", "B", (0.35, 0.0, 0.0))
    structure = CrystalStructure(
        "fallback",
        UnitCell(5.0, 5.0, 5.0),
        [center, oxygen, boron],
        [center, oxygen, boron],
    )

    class FailingFinder:
        def get_nn_info(self, _structure, _index: int):
            raise RuntimeError("unsupported chemistry")

    result = build_periodic_bonds(structure, neighbor_finder=FailingFinder())

    assert result.complete is True
    assert len(result.bonds) == 1
    assert result.bonds[0].method == "radius-fallback"
    assert result.bonds[0].distance == pytest.approx(1.5)
    assert "unsupported chemistry" in " ".join(result.warnings)
