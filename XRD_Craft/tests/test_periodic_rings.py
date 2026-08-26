from __future__ import annotations

import networkx as nx

from crystal_viewer.analysis.rings import RingSearchLimits, find_shortest_path_rings


def _edge(
    graph: nx.MultiGraph,
    first: str,
    second: str,
    translation: tuple[int, int, int] = (0, 0, 0),
) -> None:
    graph.add_edge(first, second, first=first, second=second, translation=translation)


def test_zero_translation_ring_crossing_cell_boundary_is_retained() -> None:
    graph = nx.MultiGraph()
    _edge(graph, "P1", "P2", (1, 0, 0))
    _edge(graph, "P2", "P3", (0, 0, 0))
    _edge(graph, "P3", "P1", (-1, 0, 0))

    result = find_shortest_path_rings(graph, RingSearchLimits(maximum_ring_size=3))

    assert len(result.rings) == 1
    assert result.rings[0].size == 3
    assert set(result.rings[0].member_ids) == {"P1", "P2", "P3"}


def test_nonzero_translation_winding_cycle_is_not_a_finite_ring() -> None:
    graph = nx.MultiGraph()
    _edge(graph, "P1", "P2", (1, 0, 0))
    _edge(graph, "P2", "P3", (0, 0, 0))
    _edge(graph, "P3", "P1", (0, 0, 0))

    result = find_shortest_path_rings(graph, RingSearchLimits(maximum_ring_size=3))

    assert result.rings == ()


def test_cycle_with_diagonal_shortcut_is_rejected_in_favour_of_shortest_path_rings() -> None:
    graph = nx.MultiGraph()
    _edge(graph, "P1", "P2")
    _edge(graph, "P2", "P3")
    _edge(graph, "P3", "P4")
    _edge(graph, "P4", "P1")
    _edge(graph, "P1", "P3")

    result = find_shortest_path_rings(graph, RingSearchLimits(maximum_ring_size=4))

    assert sorted(ring.size for ring in result.rings) == [3, 3]


def test_rotated_reversed_and_parallel_traversals_do_not_duplicate_a_ring() -> None:
    graph = nx.MultiGraph()
    _edge(graph, "P1", "P2")
    _edge(graph, "P1", "P2")
    _edge(graph, "P2", "P3")
    _edge(graph, "P3", "P1")

    result = find_shortest_path_rings(graph, RingSearchLimits(maximum_ring_size=3))

    assert len(result.rings) == 1


def test_ring_search_budget_returns_provisional_results_with_explicit_reason() -> None:
    graph = nx.complete_graph(8, create_using=nx.MultiGraph)
    for first, second, key in graph.edges(keys=True):
        graph[first][second][key].update(first=first, second=second, translation=(0, 0, 0))

    result = find_shortest_path_rings(
        graph,
        RingSearchLimits(maximum_ring_size=6, maximum_states=5, maximum_seconds=5.0),
    )

    assert result.complete is False
    assert result.states_examined == 5
    assert result.stop_reasons == ("maximum_states",)
