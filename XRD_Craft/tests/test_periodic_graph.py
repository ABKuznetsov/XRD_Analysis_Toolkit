from __future__ import annotations

import networkx as nx

from crystal_viewer.analysis.hierarchy import (
    CoordinationPolyhedron,
    HierarchyAnalyzer,
    HierarchyReport,
    PeriodicSiteRef,
    PolyhedronConnection,
)
from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph


def _one_node_graph(*translations: tuple[int, int, int]) -> nx.MultiGraph:
    graph = nx.MultiGraph()
    graph.add_node("P1")
    for translation in translations:
        graph.add_edge(
            "P1",
            "P1",
            translation=translation,
            kind="corner",
            shared_sites=(2,),
        )
    return graph


def test_translation_rank_classifies_periodic_chain() -> None:
    component = PeriodicPolyhedronGraph(
        _one_node_graph((1, 0, 0))
    ).components()[0]

    assert component.translation_rank == 1
    assert component.classification == "chain"


def test_translation_rank_classifies_layer_and_framework() -> None:
    layer = PeriodicPolyhedronGraph(
        _one_node_graph((1, 0, 0), (0, 1, 0))
    ).components()[0]
    framework = PeriodicPolyhedronGraph(
        _one_node_graph((1, 0, 0), (0, 1, 0), (0, 0, 1))
    ).components()[0]

    assert layer.translation_rank == 2
    assert layer.classification == "layer"
    assert framework.translation_rank == 3
    assert framework.classification == "framework"


def test_single_cross_boundary_edge_is_a_dimer_not_a_chain() -> None:
    graph = nx.MultiGraph()
    graph.add_edge(
        "P1",
        "P2",
        translation=(1, 0, 0),
        kind="corner",
        shared_sites=(2,),
    )

    component = PeriodicPolyhedronGraph(graph).components()[0]

    assert component.translation_rank == 0
    assert component.classification == "dimer"


def test_zero_translation_cycle_is_a_ring() -> None:
    graph = nx.MultiGraph()
    graph.add_edge("P1", "P2", translation=(0, 0, 0))
    graph.add_edge("P2", "P3", translation=(0, 0, 0))
    graph.add_edge("P3", "P1", translation=(0, 0, 0))

    component = PeriodicPolyhedronGraph(graph).components()[0]

    assert component.translation_rank == 0
    assert component.classification == "ring"


def test_two_cycles_sharing_a_vertex_are_a_double_ring_cluster() -> None:
    graph = nx.MultiGraph()
    graph.add_edges_from(
        (
            ("P1", "P2"),
            ("P2", "P3"),
            ("P3", "P1"),
            ("P1", "P4"),
            ("P4", "P5"),
            ("P5", "P1"),
        )
    )

    component = PeriodicPolyhedronGraph(graph).components()[0]

    assert component.translation_rank == 0
    assert component.classification == "double-ring cluster"


def _polyhedron(identifier: str, ligand_image: tuple[int, int, int]) -> CoordinationPolyhedron:
    return CoordinationPolyhedron(
        id=identifier,
        center_index=int(identifier[1:]) - 1,
        center_element="Si",
        ligand_element="O",
        ligands=(PeriodicSiteRef(2, ligand_image),),
        bond_lengths=(1.62,),
        vertex_coordinates=((0.0, 0.0, 0.0),),
        distortion=0.0,
        angle_dispersion=0.0,
    )


def test_polyhedron_connection_retains_relative_lattice_translation() -> None:
    first = _polyhedron("P1", (1, 0, 0))
    second = _polyhedron("P2", (0, 0, 0))

    connection = HierarchyAnalyzer().connect_polyhedra([first, second])[0]

    assert connection.translation == (1, 0, 0)


def test_hierarchy_connections_build_translation_aware_graph() -> None:
    first = _polyhedron("P1", (1, 0, 0))
    second = _polyhedron("P2", (0, 0, 0))
    connections = HierarchyAnalyzer().connect_polyhedra([first, second])
    report = HierarchyReport(polyhedra=[first, second], polyhedron_connections=connections)

    graph = PeriodicPolyhedronGraph.from_hierarchy(report)
    edge_data = next(iter(graph.graph.edges(data=True)))[2]

    assert edge_data["translation"] == (1, 0, 0)
    assert graph.components()[0].classification == "dimer"


def test_structural_unit_uses_periodic_cycle_rank() -> None:
    first = _polyhedron("P1", (0, 0, 0))
    second = _polyhedron("P2", (0, 0, 0))
    connections = [
        PolyhedronConnection(
            "P1", "P2", (PeriodicSiteRef(2),), "corner", True, (0, 0, 0)
        ),
        PolyhedronConnection(
            "P1", "P2", (PeriodicSiteRef(3),), "corner", True, (1, 0, 0)
        ),
    ]

    unit = HierarchyAnalyzer().build_structural_units([first, second], connections)[0]

    assert unit.periodic_rank == 1
    assert unit.classification == "chain"
