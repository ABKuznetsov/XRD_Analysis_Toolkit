"""Translation-aware topology of coordination polyhedra.

The rank is calculated from lattice translations accumulated around graph
cycles.  A translation attached only to a spanning-tree edge is a choice of
periodic image, not evidence of an infinite chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx
import numpy as np

if TYPE_CHECKING:
    from crystal_viewer.analysis.hierarchy import HierarchyReport


Translation = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class PeriodicEdge:
    first: object
    second: object
    translation: Translation
    shared_sites: tuple[int, ...] = ()
    kind: str = "corner"


@dataclass(frozen=True, slots=True)
class PeriodicComponent:
    node_ids: tuple[object, ...]
    translation_rank: int
    classification: str
    closure_translations: tuple[Translation, ...] = ()


class PeriodicPolyhedronGraph:
    """Classify connected components of a quotient periodic multigraph."""

    def __init__(self, graph: nx.MultiGraph | None = None) -> None:
        self.graph = graph.copy() if graph is not None else nx.MultiGraph()

    @classmethod
    def from_hierarchy(cls, report: "HierarchyReport") -> "PeriodicPolyhedronGraph":
        graph = nx.MultiGraph()
        graph.add_nodes_from(polyhedron.id for polyhedron in report.polyhedra)
        for connection in report.polyhedron_connections:
            graph.add_edge(
                connection.first,
                connection.second,
                first=connection.first,
                second=connection.second,
                translation=connection.translation,
                kind=connection.kind,
                shared_sites=tuple(
                    ligand.site_index for ligand in connection.shared_ligands
                ),
            )
        return cls(graph)

    @staticmethod
    def _translation(
        edge_u: object,
        edge_v: object,
        source: object,
        target: object,
        data: dict[str, object],
    ) -> np.ndarray:
        raw = data.get("translation", (0, 0, 0))
        vector = np.asarray(raw, dtype=int)
        first = data.get("first", edge_u)
        second = data.get("second", edge_v)
        if source == target:
            return vector
        if source == first and target == second:
            return vector
        if source == second and target == first:
            return -vector
        if source == edge_u and target == edge_v:
            return vector
        return -vector

    def _component(self, nodes: set[object]) -> PeriodicComponent:
        subgraph = self.graph.subgraph(nodes)
        root = next(iter(nodes))
        offsets: dict[object, np.ndarray] = {root: np.zeros(3, dtype=int)}
        tree_edges: set[tuple[object, object, object]] = set()
        stack = [root]

        while stack:
            source = stack.pop()
            for _, target, key, data in subgraph.edges(source, keys=True, data=True):
                if target in offsets:
                    continue
                step = self._translation(source, target, source, target, data)
                offsets[target] = offsets[source] + step
                tree_edges.add((source, target, key))
                tree_edges.add((target, source, key))
                stack.append(target)

        closures: list[Translation] = []
        for edge_u, edge_v, key, data in subgraph.edges(keys=True, data=True):
            if (edge_u, edge_v, key) in tree_edges:
                continue
            step = self._translation(edge_u, edge_v, edge_u, edge_v, data)
            closure = offsets[edge_u] + step - offsets[edge_v]
            closures.append(tuple(int(value) for value in closure))

        nonzero = [vector for vector in closures if any(vector)]
        rank = int(np.linalg.matrix_rank(np.asarray(nonzero, dtype=float))) if nonzero else 0
        cycle_dimension = subgraph.number_of_edges() - subgraph.number_of_nodes() + 1
        zero_cycle_count = max(0, cycle_dimension - rank)
        classification = self._classification(len(nodes), rank, zero_cycle_count)
        return PeriodicComponent(
            node_ids=tuple(sorted(nodes, key=str)),
            translation_rank=rank,
            classification=classification,
            closure_translations=tuple(closures),
        )

    @staticmethod
    def _classification(node_count: int, rank: int, zero_cycle_count: int) -> str:
        if rank >= 3:
            return "framework"
        if rank == 2:
            return "layer"
        if rank == 1:
            return "ribbon" if zero_cycle_count else "chain"
        if node_count == 1:
            return "island"
        if node_count == 2 and zero_cycle_count == 0:
            return "dimer"
        if zero_cycle_count > 2:
            return "polycyclic cluster"
        if zero_cycle_count == 2:
            return "double-ring cluster"
        if zero_cycle_count == 1:
            return "ring"
        return "cluster"

    def components(self) -> tuple[PeriodicComponent, ...]:
        return tuple(
            self._component(set(nodes))
            for nodes in nx.connected_components(self.graph)
        )
