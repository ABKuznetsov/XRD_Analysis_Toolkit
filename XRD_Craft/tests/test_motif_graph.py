from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import networkx as nx
import numpy as np
import pytest

import crystal_viewer.analysis.motif_graph as motif_graph_module
from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyReport,
    PeriodicSiteRef,
    PolyhedronConnection,
    StructuralUnit,
)
from crystal_viewer.analysis.motif_graph import (
    LatticeImageSearchError,
    MAX_LATTICE_IMAGE_CANDIDATES,
    build_motif_graph,
)
from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite, CrystalStructure, SiteComponent, UnitCell


def _polyhedron(
    identifier: str,
    center_index: int,
    ligand_indices: tuple[int, ...],
    bond_lengths: tuple[float, ...],
) -> CoordinationPolyhedron:
    return CoordinationPolyhedron(
        id=identifier,
        center_index=center_index,
        center_element="Mo",
        ligand_element="O",
        ligands=tuple(PeriodicSiteRef(index) for index in ligand_indices),
        bond_lengths=bond_lengths,
        vertex_coordinates=tuple((0.0, 0.0, 0.0) for _ in ligand_indices),
        distortion=0.125,
        angle_dispersion=0.25,
    )


def _motif_document() -> StructureDocument:
    sites = [
        AtomSite("Mo1", "Mo", (0.20, 0.50, 0.50)),
        AtomSite(
            "M2",
            "Mo/W",
            (0.60, 0.50, 0.50),
            components=(SiteComponent("W", 0.25), SiteComponent("Mo", 0.75)),
        ),
        AtomSite("Mo3", "Mo", (0.90, 0.10, 0.10)),
        AtomSite("O1", "O", (0.40, 0.50, 0.50)),
        AtomSite("O2", "O", (0.20, 0.68, 0.50)),
        AtomSite("O3", "O", (0.20, 0.32, 0.50)),
        AtomSite("O4", "O", (0.20, 0.50, 0.68)),
        AtomSite("O5", "O", (0.20, 0.50, 0.32)),
        AtomSite("O6", "O", (0.02, 0.50, 0.50)),
        AtomSite(
            "A1",
            "Na/K",
            (0.40, 0.50, 0.65),
            components=(SiteComponent("Na", 0.75), SiteComponent("K", 0.25)),
        ),
        AtomSite("Cfar", "C", (0.90, 0.90, 0.90)),
    ]
    structure = CrystalStructure(
        name="synthetic motif",
        cell=UnitCell(10.0, 10.0, 10.0),
        asymmetric_sites=sites,
        sites=sites,
    )
    first = _polyhedron("P1", 0, (3, 4, 5, 6, 7, 8), (1.8, 1.9, 2.0, 2.1, 2.2, 2.0))
    second = _polyhedron("P2", 1, (3, 4, 5, 6, 7, 8), (2.0, 2.0, 2.0, 2.0, 2.0, 2.0))
    third = _polyhedron("P3", 2, (3, 4, 5, 6, 7, 8), (1.9, 1.9, 1.9, 1.9, 1.9, 1.9))
    connections = [
        PolyhedronConnection(
            "P1", "P2", (PeriodicSiteRef(3),), "corner", True, (1, 0, 0)
        ),
        PolyhedronConnection(
            "P1",
            "P3",
            (PeriodicSiteRef(4), PeriodicSiteRef(5)),
            "edge",
            False,
        ),
        PolyhedronConnection(
            "P2",
            "P3",
            (PeriodicSiteRef(6), PeriodicSiteRef(7), PeriodicSiteRef(8)),
            "face",
            False,
        ),
    ]
    units = [
        StructuralUnit("SU1", ("P1", "P2"), (0, 1, 3), "dimer"),
        StructuralUnit("SU2", ("P1",), (0, 4, 5), "tetrahedral unit"),
    ]
    hierarchy = HierarchyReport(
        polyhedra=[first, second, third],
        polyhedron_connections=connections,
        structural_units=units,
    )
    return StructureDocument.from_structure(structure, hierarchy)


def _single_center_document(
    cell: UnitCell,
    center_fractional: tuple[float, float, float],
    interstitial_fractional: tuple[float, float, float],
    *,
    interstitial_occupancy: float = 1.0,
) -> StructureDocument:
    sites = [
        AtomSite("Mo1", "Mo", center_fractional),
        AtomSite("Na1", "Na", interstitial_fractional, occupancy=interstitial_occupancy),
    ]
    structure = CrystalStructure(
        name="periodic contact",
        cell=cell,
        asymmetric_sites=sites,
        sites=sites,
    )
    polyhedron = _polyhedron("P1", 0, (), ())
    return StructureDocument.from_structure(
        structure,
        HierarchyReport(polyhedra=[polyhedron]),
    )


def test_polyhedron_node_keeps_shape_chemistry_and_occupancy() -> None:
    graph = build_motif_graph(_motif_document())

    first = graph.nodes["P1"]
    mixed = graph.nodes["P2"]

    assert first.kind == "polyhedron"
    assert first.coordination_number == 6
    assert first.center_element == "Mo"
    assert first.ligand_elements == ("O", "O", "O", "O", "O", "O")
    assert np.allclose(first.normalized_bond_lengths, (0.9, 0.95, 1.0, 1.05, 1.1, 1.0))
    assert first.distortion == 0.125
    assert first.angle_dispersion == 0.25
    assert first.occupancies == (("Mo", 1.0),)
    assert mixed.occupancies == (("Mo", 0.75), ("W", 0.25))


def test_connections_keep_kind_shared_sites_and_periodic_translation() -> None:
    graph = build_motif_graph(_motif_document())
    connections = {
        (edge.first, edge.second, edge.kind): edge
        for edge in graph.edges.values()
        if edge.kind != "interstitial"
    }

    assert set(connections) == {
        ("P1", "P2", "corner"),
        ("P1", "P3", "edge"),
        ("P2", "P3", "face"),
    }
    corner = connections[("P1", "P2", "corner")]
    assert corner.shared_site_indices == (3,)
    assert corner.translation == (1, 0, 0)
    assert corner.normalized_distance > 0.0


def test_polyhedron_node_keeps_all_structural_unit_memberships() -> None:
    graph = build_motif_graph(_motif_document())

    assert graph.nodes["P1"].unit_ids == ("SU1", "SU2")
    assert graph.nodes["P2"].unit_ids == ("SU1",)
    assert graph.nodes["P3"].unit_ids == ()


def test_mixed_interstitial_polyhedron_is_filtered_by_role_not_combined_label() -> None:
    document = _motif_document()
    mixed = CoordinationPolyhedron(
        id="P4",
        center_index=9,
        center_element="Na/K",
        ligand_element="O",
        ligands=(PeriodicSiteRef(3),),
        bond_lengths=(2.2,),
        vertex_coordinates=((4.0, 5.0, 5.0),),
        distortion=0.0,
        angle_dispersion=0.0,
    )
    document.hierarchy.polyhedra.append(mixed)
    document.structural_analysis = SimpleNamespace(
        polyhedron_roles=(
            PolyhedronRoleEvidence(0, "structural", 0.8, 0.9, "test"),
            PolyhedronRoleEvidence(1, "structural", 0.8, 0.9, "test"),
            PolyhedronRoleEvidence(2, "structural", 0.8, 0.9, "test"),
            PolyhedronRoleEvidence(9, "interstitial", 0.1, 0.9, "test"),
        )
    )

    graph = build_motif_graph(document)

    assert "P4" not in graph.nodes
    assert graph.nodes["I9"].kind == "interstitial"


def test_nearby_non_anion_site_becomes_interstitial_linked_to_motif_geometry() -> None:
    graph = build_motif_graph(_motif_document())
    interstitial = next(node for node in graph.nodes.values() if node.kind == "interstitial")

    assert interstitial.site_index == 9
    assert interstitial.center_element == "Na/K"
    assert interstitial.occupancies == (("K", 0.25), ("Na", 0.75))
    assert {edge.second for edge in graph.edges.values() if edge.first == interstitial.id} == {
        "P1",
        "P2",
        "P3",
    }
    interstitial_edges = [
        edge for edge in graph.edges.values() if edge.first == interstitial.id
    ]
    assert np.allclose(
        [edge.normalized_distance for edge in interstitial_edges],
        [1.5 / (0.75 * 1.66 + 0.25 * 2.03 + 0.66)] * 3,
    )
    assert all(edge.normalized_distance <= 1.18 for edge in interstitial_edges)
    assert not any(node.site_index == 10 for node in graph.nodes.values())


def test_motif_graph_records_and_containers_are_immutable() -> None:
    graph = build_motif_graph(_motif_document())

    with pytest.raises(FrozenInstanceError):
        graph.nodes["P1"].kind = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        graph.nodes["new"] = graph.nodes["P1"]  # type: ignore[index]
    with pytest.raises(nx.NetworkXError):
        graph.graph.add_node("new")


def test_skewed_cell_search_finds_cartesian_nearest_image() -> None:
    document = _single_center_document(
        UnitCell(10.0, 10.0, 10.0, gamma=30.0),
        (0.49, 0.49, 0.0),
        (0.0, 0.0, 0.0),
    )

    graph = build_motif_graph(document)
    edge = next(edge for edge in graph.edges.values() if edge.kind == "interstitial")

    assert edge.translation == (-1, 0, 0)
    assert edge.normalized_distance * (1.66 + 1.54) == pytest.approx(
        2.595,
        abs=0.001,
    )


def test_interstitial_edges_preserve_distinct_periodic_motif_images() -> None:
    document = _single_center_document(
        UnitCell(4.0, 4.0, 4.0),
        (0.0, 0.0, 0.0),
        (0.5, 0.0, 0.0),
    )

    graph = build_motif_graph(document)
    edges = [edge for edge in graph.edges.values() if edge.kind == "interstitial"]

    assert len(edges) == 2
    assert {edge.translation for edge in edges} == {(0, 0, 0), (1, 0, 0)}
    assert graph.graph.number_of_edges("I1", "P1") == 2
    assert graph.nodes["I1"].coordination_number == 2


def test_networkx_graph_is_attribute_free_frozen_topology() -> None:
    motif = build_motif_graph(_motif_document())

    assert set(motif.graph.nodes) == set(motif.nodes)
    assert motif.graph.number_of_edges() == len(motif.edges)
    assert all(not attributes for _, attributes in motif.graph.nodes(data=True))
    assert all(
        not attributes
        for *_, attributes in motif.graph.edges(keys=True, data=True)
    )


def test_zero_total_occupancy_site_is_not_an_interstitial() -> None:
    document = _single_center_document(
        UnitCell(4.0, 4.0, 4.0),
        (0.0, 0.0, 0.0),
        (0.5, 0.0, 0.0),
        interstitial_occupancy=0.0,
    )

    graph = build_motif_graph(document)

    assert set(graph.nodes) == {"P1"}
    assert not graph.edges


def test_nearly_degenerate_cell_rejects_excessive_candidate_search() -> None:
    document = _single_center_document(
        UnitCell(10.0, 10.0, 10.0, gamma=0.1),
        (0.49, 0.49, 0.0),
        (0.0, 0.0, 0.0),
    )

    with pytest.raises(LatticeImageSearchError) as captured:
        build_motif_graph(document)

    assert "candidate lattice images exceeds hard limit" in str(captured.value)
    assert str(MAX_LATTICE_IMAGE_CANDIDATES) in str(captured.value)


def test_singular_cell_is_rejected_before_image_enumeration() -> None:
    class SingularCell:
        matrix = np.zeros((3, 3), dtype=float)

    document = _single_center_document(
        SingularCell(),  # type: ignore[arg-type]
        (0.49, 0.49, 0.0),
        (0.0, 0.0, 0.0),
    )

    with pytest.raises(
        LatticeImageSearchError,
        match=r"singular or numerically unusable",
    ):
        build_motif_graph(document)


def test_graph_wide_candidate_budget_rejects_incomplete_multi_contact_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        motif_graph_module,
        "MAX_MOTIF_GRAPH_IMAGE_CANDIDATES",
        3,
        raising=False,
    )

    with pytest.raises(
        LatticeImageSearchError,
        match=r"cumulative candidate budget.*graph construction is incomplete",
    ):
        build_motif_graph(_motif_document())


def test_extreme_finite_anisotropy_is_guarded_before_range_construction() -> None:
    document = _single_center_document(
        UnitCell(1e-150, 10.0, 10.0),
        (0.5, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )

    with pytest.raises(
        LatticeImageSearchError,
        match=r"candidate lattice images exceeds hard limit",
    ):
        build_motif_graph(document)


def test_empty_axis_short_circuits_huge_sibling_axis_without_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reserve_calls: list[int] = []

    class RecordingBudget(motif_graph_module._CandidateBudget):
        def reserve(self, candidate_count: int) -> None:
            reserve_calls.append(candidate_count)
            super().reserve(candidate_count)

    def unexpected_range(*_args: int) -> range:
        pytest.fail("an empty Cartesian product must not construct any ranges")

    monkeypatch.setattr(motif_graph_module, "range", unexpected_range, raising=False)
    budget = RecordingBudget(maximum=0)

    images = motif_graph_module._lattice_images_within_cutoff(
        np.asarray((0.0, 0.5, 0.0)),
        np.diag((1e-150, 10.0, 10.0)),
        3.75,
        budget,
    )

    assert images == ()
    assert reserve_calls == []
    assert budget.consumed == 0
