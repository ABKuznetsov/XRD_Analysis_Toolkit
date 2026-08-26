from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import networkx as nx
import numpy as np

from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph, Translation
from crystal_viewer.analysis.structural_analysis import RingCandidate


LiftedState = tuple[object, Translation]


@dataclass(frozen=True, slots=True)
class RingSearchLimits:
    maximum_ring_size: int = 12
    maximum_states: int = 50_000
    maximum_seconds: float = 5.0

    def __post_init__(self) -> None:
        if self.maximum_ring_size < 3:
            raise ValueError("maximum_ring_size must be at least 3")
        if self.maximum_states < 1:
            raise ValueError("maximum_states must be positive")
        if self.maximum_seconds <= 0.0:
            raise ValueError("maximum_seconds must be positive")


@dataclass(frozen=True, slots=True)
class RingSearchResult:
    rings: tuple[RingCandidate, ...]
    complete: bool
    states_examined: int
    stop_reasons: tuple[str, ...] = ()


@dataclass(slots=True)
class _Budget:
    limits: RingSearchLimits
    started: float
    states: int = 0
    reason: str = ""

    def take(self) -> bool:
        if self.states >= self.limits.maximum_states:
            self.reason = "maximum_states"
            return False
        if time.monotonic() - self.started >= self.limits.maximum_seconds:
            self.reason = "maximum_seconds"
            return False
        self.states += 1
        return True


def _add(first: Translation, second: Translation) -> Translation:
    return tuple(int(a + b) for a, b in zip(first, second, strict=True))


def _subtract(first: Translation, second: Translation) -> Translation:
    return tuple(int(a - b) for a, b in zip(first, second, strict=True))


def _neighbors(graph: nx.MultiGraph, state: LiftedState):
    node, image = state
    neighbours: set[LiftedState] = set()
    for edge_u, edge_v, _key, data in graph.edges(node, keys=True, data=True):
        target = edge_v if edge_u == node else edge_u
        step = PeriodicPolyhedronGraph._translation(edge_u, edge_v, node, target, data)
        translation = tuple(int(value) for value in np.asarray(step, dtype=int))
        neighbours.add((target, _add(image, translation)))
    yield from sorted(neighbours, key=lambda item: (str(item[0]), item[1]))


def _canonical(states: tuple[LiftedState, ...]) -> tuple[tuple[str, Translation], ...]:
    variants: list[tuple[tuple[str, Translation], ...]] = []
    for sequence in (states, tuple(reversed(states))):
        for offset in range(len(sequence)):
            rotated = sequence[offset:] + sequence[:offset]
            origin = rotated[0][1]
            variants.append(
                tuple((str(node), _subtract(image, origin)) for node, image in rotated)
            )
    return min(variants)


def _has_shorter_path(
    graph: nx.MultiGraph,
    source: LiftedState,
    target: LiftedState,
    maximum_length: int,
    budget: _Budget,
) -> bool | None:
    queue = deque([(source, 0)])
    seen = {source}
    while queue:
        if not budget.take():
            return None
        state, depth = queue.popleft()
        if depth >= maximum_length:
            continue
        for neighbour in _neighbors(graph, state):
            if neighbour == target:
                return True
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, depth + 1))
    return False


def _is_shortest_path_ring(
    graph: nx.MultiGraph,
    states: tuple[LiftedState, ...],
    budget: _Budget,
) -> bool | None:
    size = len(states)
    for first in range(size):
        for second in range(first + 1, size):
            along_ring = min(second - first, size - (second - first))
            if along_ring <= 1:
                continue
            shorter = _has_shorter_path(
                graph,
                states[first],
                states[second],
                along_ring - 1,
                budget,
            )
            if shorter is None:
                return None
            if shorter:
                return False
    return True


def find_shortest_path_rings(
    graph: nx.MultiGraph | PeriodicPolyhedronGraph,
    limits: RingSearchLimits | None = None,
) -> RingSearchResult:
    """Return finite zero-translation shortest-path rings and exact members."""
    limits = limits or RingSearchLimits()
    source_graph = graph.graph if isinstance(graph, PeriodicPolyhedronGraph) else graph
    source_graph = nx.MultiGraph(source_graph)
    budget = _Budget(limits, time.monotonic())
    found: dict[tuple[tuple[str, Translation], ...], RingCandidate] = {}
    size_limited = False

    # Iterative deepening makes the useful small rings available before a
    # periodic graph can spend the whole budget on long lifted walks.
    for target_size in range(3, limits.maximum_ring_size + 1):
        for start_node in sorted(source_graph.nodes, key=str):
            start: LiftedState = (start_node, (0, 0, 0))
            stack: list[tuple[LiftedState, tuple[LiftedState, ...]]] = [(start, (start,))]
            while stack:
                if not budget.take():
                    rings = tuple(found[key] for key in sorted(found))
                    return RingSearchResult(rings, False, budget.states, (budget.reason,))
                state, path = stack.pop()
                for neighbour in _neighbors(source_graph, state):
                    if neighbour == start:
                        if len(path) != target_size:
                            continue
                        canonical = _canonical(path)
                        if canonical in found:
                            continue
                        shortest = _is_shortest_path_ring(source_graph, path, budget)
                        if shortest is None:
                            rings = tuple(found[key] for key in sorted(found))
                            return RingSearchResult(rings, False, budget.states, (budget.reason,))
                        if shortest:
                            found[canonical] = RingCandidate(
                                member_ids=tuple(item[0] for item in canonical),
                                member_images=tuple(item[1] for item in canonical),
                                atom_indices=(),
                                size=len(canonical),
                                composition="",
                                confidence=1.0,
                            )
                        continue
                    if len(path) >= target_size:
                        size_limited = True
                        continue
                    # A finite quotient-ring contains each coordination centre
                    # once. Reusing the same base node in another image creates
                    # winding walks, not a local chemical ring.
                    if any(neighbour[0] == member[0] for member in path):
                        continue
                    # Every ring is enumerated from its smallest node exactly
                    # once; images remain part of the state and canonical key.
                    if str(neighbour[0]) < str(start_node):
                        continue
                    stack.append((neighbour, path + (neighbour,)))

    reasons = ("maximum_ring_size",) if size_limited else ()
    rings = tuple(found[key] for key in sorted(found))
    return RingSearchResult(rings, not size_limited, budget.states, reasons)


__all__ = ["RingSearchLimits", "RingSearchResult", "find_shortest_path_rings"]
