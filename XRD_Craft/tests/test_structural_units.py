from __future__ import annotations

from pathlib import Path

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyAnalyzer,
    PeriodicSiteRef,
    PolyhedronConnection,
)
from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence
from crystal_viewer.core.cif import load_cif
from crystal_viewer.core.document import load_document


ROOT = Path(__file__).resolve().parents[1]


def _motif_polyhedron(
    identifier: int,
    coordination: int,
    ligand_sites: tuple[int, ...],
    *,
    element: str = "B",
) -> CoordinationPolyhedron:
    return CoordinationPolyhedron(
        id=f"P{identifier}",
        center_index=identifier - 1,
        center_element=element,
        ligand_element="O",
        ligands=tuple(PeriodicSiteRef(site) for site in ligand_sites),
        bond_lengths=(1.5,) * coordination,
        vertex_coordinates=tuple((float(site), 0.0, 0.0) for site in ligand_sites),
        distortion=0.0,
        angle_dispersion=0.0,
    )


def _motif_connection(
    first: int,
    second: int,
    shared_site: int,
    translation: tuple[int, int, int] = (0, 0, 0),
) -> PolyhedronConnection:
    return PolyhedronConnection(
        first=f"P{first}",
        second=f"P{second}",
        shared_ligands=(PeriodicSiteRef(shared_site),),
        kind="corner",
        flexible=True,
        translation=translation,
    )


def test_generic_strength_gap_recovers_finite_polycyclic_motif_from_periodic_context() -> None:
    """A weak coordination network must not absorb a stronger finite anion motif."""
    polyhedra = [
        _motif_polyhedron(1, 4, (100, 101, 102, 103)),
        _motif_polyhedron(2, 3, (100, 104, 105)),
        _motif_polyhedron(3, 3, (101, 104, 106)),
        _motif_polyhedron(4, 3, (102, 107, 108)),
        _motif_polyhedron(5, 3, (103, 107, 109)),
        _motif_polyhedron(6, 6, (100, 101, 102, 103, 108, 109), element="Y"),
    ]
    connections = [
        _motif_connection(1, 2, 100),
        _motif_connection(1, 3, 101),
        _motif_connection(2, 3, 104),
        _motif_connection(1, 4, 102),
        _motif_connection(1, 5, 103),
        _motif_connection(4, 5, 107),
        _motif_connection(1, 6, 100),
        _motif_connection(1, 6, 101, (1, 0, 0)),
    ]
    roles = tuple(
        PolyhedronRoleEvidence(index, "structural", value, 0.9, "test")
        for index, value in enumerate((0.82, 0.95, 0.96, 0.94, 0.93, 0.46))
    )

    units = HierarchyAnalyzer().build_structural_units(
        polyhedra,
        connections,
        role_evidence=roles,
    )

    assert [(unit.polyhedron_ids, unit.classification, unit.periodic_rank) for unit in units] == [
        (("P1", "P2", "P3", "P4", "P5"), "double-ring cluster · B5O10", 0),
        (("P6",), "coordination context", 0),
    ]


def test_generic_decomposition_finds_borate_rings_without_compound_rules() -> None:
    structure = load_cif(ROOT / "tests" / "data" / "structures" / "lithium_triborate.cif")

    report = HierarchyAnalyzer().analyze(structure)
    rings = [unit for unit in report.structural_units if "ring" in unit.classification]
    interstitial = [
        unit for unit in report.structural_units if unit.classification == "interlayer polyhedron"
    ]

    assert len(rings) == 4
    assert {unit.classification for unit in rings} == {"3-membered ring · B3O7"}
    assert all(len(unit.polyhedron_ids) == 3 for unit in rings)
    assert all(unit.periodic_rank == 0 for unit in rings)
    assert len(interstitial) == 4
    assert all(len(unit.polyhedron_ids) == 1 for unit in interstitial)


def test_loaded_hierarchy_reuses_primary_coordination_memberships() -> None:
    document = load_document(ROOT / "tests" / "data" / "structures" / "lithium_triborate.cif")
    assert document.structural_analysis is not None
    environments = {
        environment.center_index: set(zip(
            environment.neighbor_indices,
            environment.neighbor_images,
            strict=True,
        ))
        for environment in document.structural_analysis.coordination_environments
    }

    for polyhedron in document.hierarchy.polyhedra:
        assert {
            (ligand.site_index, ligand.image) for ligand in polyhedron.ligands
        } == environments[polyhedron.center_index]


def test_loaded_scene_reuses_periodic_bond_graph() -> None:
    document = load_document(ROOT / "tests" / "data" / "structures" / "lithium_triborate.cif")
    assert document.structural_analysis is not None

    scene = document.scene_data(complete_boundary=False)
    rendered = {
        tuple(sorted((scene.atoms[bond.first].site_index, scene.atoms[bond.second].site_index)))
        for bond in scene.bonds
    }
    expected = {
        tuple(sorted((bond.first, bond.second)))
        for bond in document.structural_analysis.periodic_bonds.bonds
        if bond.image == (0, 0, 0)
    }

    assert rendered == expected


def test_shared_analysis_exposes_generic_ring_and_primary_unit_candidates() -> None:
    document = load_document(ROOT / "tests" / "data" / "structures" / "lithium_triborate.cif")
    assert document.structural_analysis is not None

    assert len(document.structural_analysis.rings) == 4
    assert {ring.composition for ring in document.structural_analysis.rings} == {"B3O7"}
    primary_rings = [
        unit
        for unit in document.structural_analysis.structural_units
        if unit.primary and unit.kind == "ring"
    ]
    assert len(primary_rings) == 4
    assert all(unit.complete for unit in primary_rings)
    ring_names = [
        item.descriptor
        for item in document.structural_analysis.nomenclature
        if item.domain_id.startswith("SU")
    ]
    assert ring_names == ["3-membered borate FBB (2 BO3 + 1 BO4)"] * 4
