from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyReport,
    PeriodicSiteRef,
    PolyhedronConnection,
)
from crystal_viewer.analysis.descriptors.builders import build_descriptors
from crystal_viewer.analysis.inorganic_topology import (
    _cell_supports_voronoi,
    build_inorganic_topology,
)
from crystal_viewer.analysis.projection_match import projection_candidates
from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence
from crystal_viewer.core.model import AtomSite, CrystalStructure, UnitCell
from crystal_viewer.core.document import StructureDocument


def test_voronoi_guard_rejects_numerically_unusable_cells() -> None:
    assert _cell_supports_voronoi(np.eye(3))
    assert not _cell_supports_voronoi(np.diag((1e-150, 10.0, 10.0)))
    assert not _cell_supports_voronoi(np.zeros((3, 3)))
    assert not _cell_supports_voronoi(np.diag((1.0, 1.0, np.inf)))


def _structure() -> CrystalStructure:
    sites = [
        AtomSite("Si1", "Si", (0.0, 0.0, 0.0)),
        AtomSite("Na1", "Na", (0.5, 0.5, 0.5)),
        AtomSite("Si2", "Si", (0.25, 0.25, 0.25)),
        AtomSite("O1", "O", (0.1, 0.0, 0.0)),
    ]
    return CrystalStructure("test", UnitCell(5.0, 5.0, 5.0), sites, sites)


def _polyhedron(identifier: str, center_index: int, element: str) -> CoordinationPolyhedron:
    return CoordinationPolyhedron(
        id=identifier,
        center_index=center_index,
        center_element=element,
        ligand_element="O",
        ligands=(PeriodicSiteRef(3),),
        bond_lengths=(1.6,),
        vertex_coordinates=((0.5, 0.0, 0.0),),
        distortion=0.0,
        angle_dispersion=0.0,
    )


def _connection(
    first: str,
    second: str,
    translation: tuple[int, int, int] = (0, 0, 0),
) -> PolyhedronConnection:
    return PolyhedronConnection(
        first,
        second,
        (PeriodicSiteRef(3),),
        "corner",
        True,
        translation,
    )


def _role(center_index: int, role: str) -> PolyhedronRoleEvidence:
    return PolyhedronRoleEvidence(center_index, role, 0.8, 0.9, "test")


def test_interstitial_bridge_does_not_join_structural_components() -> None:
    hierarchy = HierarchyReport(
        polyhedra=[
            _polyhedron("P1", 0, "Si"),
            _polyhedron("P2", 1, "Na"),
            _polyhedron("P3", 2, "Si"),
        ],
        polyhedron_connections=[
            _connection("P1", "P2"),
            _connection("P2", "P3"),
        ],
    )

    report = build_inorganic_topology(
        _structure(),
        hierarchy,
        (_role(0, "structural"), _role(1, "interstitial"), _role(2, "structural")),
    )

    assert [item.polyhedron_ids for item in report.components] == [("P1",), ("P3",)]
    assert [item.classification for item in report.components] == ["island", "island"]
    assert report.structural_polyhedron_ids == frozenset({"P1", "P3"})


def test_periodic_chain_reports_primitive_direction() -> None:
    hierarchy = HierarchyReport(
        polyhedra=[_polyhedron("P1", 0, "Si")],
        polyhedron_connections=[_connection("P1", "P1", (2, 0, 0))],
    )

    report = build_inorganic_topology(
        _structure(), hierarchy, (_role(0, "structural"),)
    )

    component = report.components[0]
    assert component.periodic_rank == 1
    assert component.classification == "chain"
    assert component.directions == ((1, 0, 0),)


def test_space_group_equivalent_components_form_one_family() -> None:
    sites = [
        AtomSite("Si1", "Si", (0.0, 0.0, 0.0)),
        AtomSite("Si1·2", "Si", (0.5, 0.0, 0.0)),
        AtomSite("O1", "O", (0.1, 0.0, 0.0)),
    ]
    structure = CrystalStructure(
        "symmetric",
        UnitCell(5.0, 5.0, 5.0),
        [sites[0], sites[2]],
        sites,
        symmetry_operations=["x,y,z", "x+1/2,y,z"],
    )
    hierarchy = HierarchyReport(
        polyhedra=[
            CoordinationPolyhedron(
                "P1", 0, "Si", "O", (PeriodicSiteRef(2),), (1.6,),
                ((0.5, 0.0, 0.0),), 0.0, 0.0,
            ),
            CoordinationPolyhedron(
                "P2", 1, "Si", "O", (PeriodicSiteRef(2),), (1.6,),
                ((3.0, 0.0, 0.0),), 0.0, 0.0,
            ),
        ]
    )

    report = build_inorganic_topology(
        structure,
        hierarchy,
        (_role(0, "structural"), _role(1, "structural")),
    )

    assert len(report.components) == 2
    assert len(report.families) == 1
    assert report.families[0].component_ids == ("TC1", "TC2")


def test_symmetry_rotated_periodic_chains_form_one_family() -> None:
    sites = [
        AtomSite("B1", "B", (0.1, 0.2, 0.0)),
        AtomSite("B1·2", "B", (0.2, 0.1, 0.0)),
        AtomSite("O1", "O", (0.0, 0.0, 0.0)),
    ]
    structure = CrystalStructure(
        "rotated-chains",
        UnitCell(5.0, 5.0, 5.0),
        [sites[0], sites[2]],
        sites,
        symmetry_operations=["x,y,z", "y,x,z"],
    )
    hierarchy = HierarchyReport(
        polyhedra=[
            _polyhedron("P1", 0, "B"),
            _polyhedron("P2", 1, "B"),
        ],
        polyhedron_connections=[
            _connection("P1", "P1", (1, 0, 0)),
            _connection("P2", "P2", (0, 1, 0)),
        ],
    )

    report = build_inorganic_topology(
        structure,
        hierarchy,
        (_role(0, "structural"), _role(1, "structural")),
    )

    assert len(report.components) == 2
    assert {component.directions for component in report.components} == {
        ((1, 0, 0),),
        ((0, 1, 0),),
    }
    assert len(report.families) == 1
    assert report.families[0].component_ids == ("TC1", "TC2")


def test_document_owns_the_canonical_inorganic_topology_report() -> None:
    hierarchy = HierarchyReport(polyhedra=[_polyhedron("P1", 0, "Si")])

    document = StructureDocument.from_structure(
        _structure(),
        hierarchy,
        SimpleNamespace(polyhedron_roles=(_role(0, "structural"),)),
    )

    assert document.inorganic_topology is not None
    assert document.inorganic_topology.interpretable
    assert document.inorganic_topology.components[0].polyhedron_ids == ("P1",)


def test_topology_descriptor_uses_filtered_canonical_families() -> None:
    hierarchy = HierarchyReport(
        polyhedra=[
            _polyhedron("P1", 0, "Si"),
            _polyhedron("P2", 1, "Na"),
            _polyhedron("P3", 2, "Si"),
        ],
        polyhedron_connections=[
            _connection("P1", "P2"),
            _connection("P2", "P3"),
        ],
    )
    document = StructureDocument.from_structure(
        _structure(),
        hierarchy,
        SimpleNamespace(
            polyhedron_roles=(
                _role(0, "structural"),
                _role(1, "interstitial"),
                _role(2, "structural"),
            )
        ),
    )

    descriptor = build_descriptors(document)["topology.component_classes"]

    assert descriptor.value == {
        "classes": {"island": 2},
        "ranks": (0, 0),
        "family_ids": ("TF1", "TF2"),
    }


def test_projection_rank_ignores_periodic_interstitial_network() -> None:
    structural = StructureDocument.from_structure(
        _structure(),
        HierarchyReport(polyhedra=[_polyhedron("P1", 0, "Si")]),
        SimpleNamespace(polyhedron_roles=(_role(0, "structural"),)),
    )
    hierarchy = HierarchyReport(
        polyhedra=[_polyhedron("P1", 0, "Si"), _polyhedron("P2", 1, "Na")],
        polyhedron_connections=[
            _connection("P2", "P2", (1, 0, 0)),
            _connection("P2", "P2", (0, 1, 0)),
        ],
    )
    interstitial_layer = StructureDocument.from_structure(
        _structure(),
        hierarchy,
        SimpleNamespace(
            polyhedron_roles=(_role(0, "structural"), _role(1, "interstitial"))
        ),
    )

    candidates = projection_candidates(structural, interstitial_layer)

    assert candidates[0].score_components["rank_penalty"] == 0.0


def test_cation_network_preserves_shared_ligand_and_cation_distance() -> None:
    sites = [
        AtomSite("Y1", "Y", (0.1, 0.0, 0.0)),
        AtomSite("Y2", "Y", (0.4, 0.0, 0.0)),
        AtomSite("O1", "O", (0.25, 0.0, 0.0)),
    ]
    structure = CrystalStructure("yttrium", UnitCell(10.0, 10.0, 10.0), sites, sites)
    hierarchy = HierarchyReport(
        polyhedra=[
            CoordinationPolyhedron(
                "P1", 0, "Y", "O", (PeriodicSiteRef(2),), (1.5,),
                ((2.5, 0.0, 0.0),), 0.0, 0.0,
            ),
            CoordinationPolyhedron(
                "P2", 1, "Y", "O", (PeriodicSiteRef(2),), (1.5,),
                ((2.5, 0.0, 0.0),), 0.0, 0.0,
            ),
        ],
        polyhedron_connections=[
            PolyhedronConnection(
                "P1", "P2", (PeriodicSiteRef(2),), "corner", True, (0, 0, 0)
            )
        ],
    )

    report = build_inorganic_topology(
        structure,
        hierarchy,
        (_role(0, "structural"), _role(1, "structural")),
    )

    shared = [edge for edge in report.cation_edges if edge.mode == "shared-ligand"]
    assert len(shared) == 1
    assert shared[0].shared_sites == (2,)
    assert shared[0].distance == pytest.approx(3.0)
    assert report.cation_families[0].building_units == ("YO1",)
