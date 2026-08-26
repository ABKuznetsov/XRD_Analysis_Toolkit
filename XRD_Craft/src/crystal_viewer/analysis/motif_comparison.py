"""Explainable node scoring and bounded deterministic motif matching."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import combinations, combinations_with_replacement
import math
from numbers import Real
import time
from typing import Iterable, Mapping

import networkx as nx

from crystal_viewer.analysis.motif_graph import (
    MotifEdge,
    MotifGraph,
    MotifNode,
    OccupancyDistribution,
    build_motif_graph,
)
from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph
from crystal_viewer.core.document import StructureDocument


BOND_LENGTH_RMS_TOLERANCE = 0.15
DISTORTION_TOLERANCE = 0.10
# Ideal regular octahedral and trigonal-prismatic environments differ by
# approximately 0.0782 in this descriptor. Keep that archetype change outside
# the candidate gate while allowing smaller within-archetype distortions.
ANGLE_DISPERSION_TOLERANCE = 0.05
MOTIF_ALGORITHM_VERSION = "motif-comparison-v2"
_monotonic = time.monotonic


@dataclass(frozen=True, slots=True)
class NodeSimilarity:
    """Independent score components for one compatible pair of motif nodes."""

    topology: float
    geometry: float
    chemistry: float
    total: float


@dataclass(frozen=True, slots=True)
class MatchLimits:
    """Hard bounds for one deterministic motif search."""

    max_states: int = 50_000
    max_seconds: float = 1.5
    max_nodes: int = 96

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_states, bool)
            or not isinstance(self.max_states, int)
            or self.max_states < 0
        ):
            raise ValueError("max_states must be a non-negative integer")
        if (
            isinstance(self.max_nodes, bool)
            or not isinstance(self.max_nodes, int)
            or self.max_nodes < 0
        ):
            raise ValueError("max_nodes must be a non-negative integer")
        if (
            isinstance(self.max_seconds, bool)
            or not isinstance(self.max_seconds, Real)
            or not math.isfinite(self.max_seconds)
            or self.max_seconds < 0.0
        ):
            raise ValueError("max_seconds must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class MotifMatch:
    """One connected common motif, ordered in document-ID space."""

    id: str
    classification: str
    periodic_rank: int
    node_pairs: tuple[tuple[str, str], ...]
    edge_pairs: tuple[tuple[str, str], ...]
    edge_kinds: tuple[str, ...]
    topology_score: float
    geometry_score: float
    chemistry_score: float
    total_score: float


@dataclass(frozen=True, slots=True)
class AtomSubstitution:
    """Different center-site chemistry inside a matched node pair."""

    match_id: str
    first_node_id: str
    second_node_id: str
    first_site_index: int | None
    second_site_index: int | None
    first_element: str
    second_element: str
    first_occupancies: OccupancyDistribution
    second_occupancies: OccupancyDistribution


@dataclass(frozen=True, slots=True)
class UnmatchedNode:
    """A motif node outside the selected connected common subgraph."""

    side: str
    node_id: str
    kind: str
    element: str
    site_index: int | None
    unit_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MotifComparisonReport:
    """Immutable, explicit result of a bounded motif comparison."""

    first_document_id: str
    second_document_id: str
    matches: tuple[MotifMatch, ...]
    substitutions: tuple[AtomSubstitution, ...]
    unmatched_first: tuple[UnmatchedNode, ...]
    unmatched_second: tuple[UnmatchedNode, ...]
    approximate: bool
    states_explored: int
    limit_reasons: tuple[str, ...] = ()
    graph_complete: bool = True
    result_interpretable: bool = True
    ambiguous: bool = False
    equivalent_best_count: int = 1
    ambiguity_reason: str = ""

    @property
    def unmatched_nodes(self) -> tuple[UnmatchedNode, ...]:
        return self.unmatched_first + self.unmatched_second

    @property
    def exact(self) -> bool:
        return (
            self.graph_complete
            and self.result_interpretable
            and not self.approximate
            and not self.ambiguous
        )


@dataclass(frozen=True, slots=True)
class _SearchResult:
    mapping: tuple[tuple[str, str], ...]
    edge_pairs: tuple[tuple[str, str], ...]
    similarities: tuple[NodeSimilarity, ...]
    periodic_rank: int
    equivalent_best_count: int = 1


@dataclass(frozen=True, slots=True)
class _EdgePairing:
    pairs: tuple[tuple[str, str], ...]
    periodic_rank: int


@dataclass(slots=True)
class _SearchBudget:
    limits: MatchLimits
    deadline: float
    states_explored: int = 0
    limit_reasons: set[str] = field(default_factory=set)
    stopped: bool = False

    def check_time(self) -> bool:
        if _monotonic() >= self.deadline:
            self.limit_reasons.add("max_seconds")
            self.stopped = True
            return False
        return True

    def active(self) -> bool:
        return self.check_time() and not self.stopped

    def consume_state(self) -> bool:
        if not self.active():
            return False
        if self.states_explored >= self.limits.max_states:
            self.limit_reasons.add("max_states")
            self.stopped = True
            return False
        self.states_explored += 1
        return True

    def allow_graph_node(self, node_count: int) -> bool:
        if not self.active():
            return False
        if node_count >= self.limits.max_nodes:
            self.limit_reasons.add("max_nodes")
            return False
        return True


def _rms_difference(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if not first:
        return 0.0
    differences = (
        first_value - second_value
        for first_value, second_value in zip(sorted(first), sorted(second), strict=True)
    )
    return math.hypot(*differences) / math.sqrt(len(first))


def _clamp_unit(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return min(1.0, max(0.0, value))


def _normalized_distribution(
    values: Iterable[tuple[str, float]],
) -> dict[str, float]:
    finite_weights = [
        (element, weight)
        for element, weight in values
        if math.isfinite(weight) and weight > 0.0
    ]
    if not finite_weights:
        return {}

    scale = max(weight for _, weight in finite_weights)
    scaled_by_element: dict[str, list[float]] = {}
    for element, weight in finite_weights:
        scaled_by_element.setdefault(element, []).append(weight / scale)
    element_weights = {
        element: math.fsum(scaled_by_element[element])
        for element in sorted(scaled_by_element)
    }
    total = math.fsum(element_weights.values())
    if total <= 0.0:
        return {}
    return {
        element: element_weights[element] / total
        for element in sorted(element_weights)
    }


def _distribution_similarity(
    first: Iterable[tuple[str, float]],
    second: Iterable[tuple[str, float]],
) -> float:
    first_distribution = _normalized_distribution(first)
    second_distribution = _normalized_distribution(second)
    if not first_distribution and not second_distribution:
        return 1.0
    if first_distribution == second_distribution:
        return 1.0
    elements = sorted(first_distribution.keys() | second_distribution.keys())
    overlap = math.fsum(
        min(first_distribution.get(element, 0.0), second_distribution.get(element, 0.0))
        for element in elements
    )
    return _clamp_unit(overlap)


def _log_total_weight(values: Iterable[tuple[str, float]]) -> float | None:
    """Return log(sum(weights)) without overflowing on finite CIF values."""
    logarithms = [
        math.log(weight)
        for _, weight in values
        if math.isfinite(weight) and weight > 0.0
    ]
    if not logarithms:
        return None
    maximum = max(logarithms)
    return maximum + math.log(math.fsum(math.exp(value - maximum) for value in logarithms))


def _occupancy_magnitude_similarity(
    first: Iterable[tuple[str, float]],
    second: Iterable[tuple[str, float]],
) -> float:
    """Compare vacancy/overoccupancy while remaining finite and symmetric."""
    first_log = _log_total_weight(first)
    second_log = _log_total_weight(second)
    if first_log is None and second_log is None:
        return 1.0
    if first_log is None:
        second_total = math.exp(second_log) if second_log is not None and second_log <= 0.0 else 1.0
        return _clamp_unit(1.0 - second_total)
    if second_log is None:
        first_total = math.exp(first_log) if first_log <= 0.0 else 1.0
        return _clamp_unit(1.0 - first_total)
    maximum_log = max(first_log, second_log)
    minimum_log = min(first_log, second_log)
    if maximum_log <= 0.0:
        return _clamp_unit(1.0 - abs(math.exp(first_log) - math.exp(second_log)))
    return _clamp_unit(math.exp(minimum_log - maximum_log))


def _center_similarity(first: MotifNode, second: MotifNode) -> float:
    first_distribution = _center_distribution(first)
    second_distribution = _center_distribution(second)
    return _clamp_unit(
        math.fsum(
            (
                0.5 * _distribution_similarity(first_distribution, second_distribution),
                0.5
                * _occupancy_magnitude_similarity(
                    first_distribution,
                    second_distribution,
                ),
            )
        )
    )


def _center_distribution(node: MotifNode) -> OccupancyDistribution:
    if _normalized_distribution(node.occupancies):
        return node.occupancies
    return ((node.center_element, 1.0),)


def _ligand_distribution(node: MotifNode) -> tuple[tuple[str, float], ...]:
    return tuple((element, 1.0) for element in node.ligand_elements)


def _chemistry_similarity(first: MotifNode, second: MotifNode) -> float:
    center_similarity = _center_similarity(first, second)
    ligand_similarity = _distribution_similarity(
        _ligand_distribution(first), _ligand_distribution(second)
    )
    return _clamp_unit(
        math.fsum((0.5 * center_similarity, 0.5 * ligand_similarity))
    )


def score_nodes(first: MotifNode, second: MotifNode) -> NodeSimilarity | None:
    """Score two nodes, rejecting incompatible topology or geometry first.

    Geometry uses the RMS difference of sorted normalized bond lengths plus
    absolute differences in distortion and angular dispersion. Each descriptor
    has an independent hard tolerance; the surviving score is one minus the
    RMS of those three deviations after scaling by their tolerances.

    Chemistry is the mean overlap of center-site occupancy distributions and
    ligand-element distributions. It changes the score but cannot bypass a
    failed topology or geometry gate.

    A zero-coordination node, including an isolated interstitial, has valid
    empty bond geometry. Positive coordination requires exactly one normalized
    bond length per neighbor; malformed vectors are rejected.
    """
    if first.kind != second.kind:
        return None
    if first.coordination_number != second.coordination_number:
        return None
    if first.coordination_number < 0:
        return None
    if (
        len(first.normalized_bond_lengths) != first.coordination_number
        or len(second.normalized_bond_lengths) != second.coordination_number
    ):
        return None

    geometry_values = (
        *first.normalized_bond_lengths,
        *second.normalized_bond_lengths,
        first.distortion,
        second.distortion,
        first.angle_dispersion,
        second.angle_dispersion,
    )
    if not all(math.isfinite(value) for value in geometry_values):
        return None

    bond_rms = _rms_difference(
        first.normalized_bond_lengths,
        second.normalized_bond_lengths,
    )
    distortion_delta = abs(first.distortion - second.distortion)
    angle_delta = abs(first.angle_dispersion - second.angle_dispersion)
    if (
        bond_rms > BOND_LENGTH_RMS_TOLERANCE
        or distortion_delta > DISTORTION_TOLERANCE
        or angle_delta > ANGLE_DISPERSION_TOLERANCE
    ):
        return None

    scaled_geometry_differences = (
        bond_rms / BOND_LENGTH_RMS_TOLERANCE,
        distortion_delta / DISTORTION_TOLERANCE,
        angle_delta / ANGLE_DISPERSION_TOLERANCE,
    )
    combined_geometry_difference = math.sqrt(
        math.fsum(value**2 for value in scaled_geometry_differences)
        / len(scaled_geometry_differences)
    )
    topology = 1.0
    geometry = _clamp_unit(1.0 - combined_geometry_difference)
    chemistry = _chemistry_similarity(first, second)
    total = _clamp_unit(
        math.fsum((0.55 * topology, 0.30 * geometry, 0.15 * chemistry))
    )
    return NodeSimilarity(
        topology=topology,
        geometry=geometry,
        chemistry=chemistry,
        total=total,
    )


def _node_order(node: MotifNode) -> tuple[int, str]:
    if node.unit_ids:
        priority = 0
    elif node.kind == "polyhedron":
        priority = 1
    else:
        priority = 2
    return priority, node.id


def _bounded_node_ids(graph: MotifGraph, maximum: int) -> tuple[str, ...]:
    return tuple(
        node.id
        for node in sorted(graph.nodes.values(), key=_node_order)[:maximum]
    )


def _edge_semantic_key(
    edge: MotifEdge,
) -> tuple[str, str, str, tuple[int, int, int], tuple[int, ...]]:
    if edge.first <= edge.second:
        first = edge.first
        second = edge.second
        translation = edge.translation
    else:
        first = edge.second
        second = edge.first
        translation = tuple(-value for value in edge.translation)
    return (
        first,
        second,
        edge.kind,
        translation,
        tuple(sorted(edge.shared_site_indices)),
    )


def _edge_semantic_label(edge: MotifEdge) -> str:
    first, second, kind, translation, shared_sites = _edge_semantic_key(edge)
    translation_label = ",".join(str(value) for value in translation)
    shared_label = ",".join(str(value) for value in shared_sites)
    return f"{first}>{second}|{kind}|{translation_label}|{shared_label}"


def _edge_lookup(
    graph: MotifGraph,
    budget: _SearchBudget,
) -> dict[tuple[str, str], tuple[MotifEdge, ...]] | None:
    if not budget.active():
        return None
    grouped: dict[tuple[str, str], list[MotifEdge]] = {}
    for index, edge in enumerate(graph.edges.values()):
        if index % 256 == 0 and not budget.active():
            return None
        key = tuple(sorted((edge.first, edge.second)))
        grouped.setdefault(key, []).append(edge)
    result = {
        key: tuple(
            sorted(
                edges,
                key=lambda edge: (_edge_semantic_key(edge), edge.id),
            )
        )
        for key, edges in grouped.items()
    }
    budget.check_time()
    return result


def _periodic_rank(
    graph: MotifGraph,
    node_ids: Iterable[str],
    edge_ids: Iterable[str],
    budget: _SearchBudget,
) -> int | None:
    if not budget.active():
        return None
    network = nx.MultiGraph()
    network.add_nodes_from(node_ids)
    for index, edge_id in enumerate(edge_ids):
        if index % 256 == 0 and not budget.active():
            return None
        edge = graph.edges[edge_id]
        network.add_edge(
            edge.first,
            edge.second,
            key=edge.id,
            first=edge.first,
            second=edge.second,
            translation=edge.translation,
            kind=edge.kind,
        )
    components = PeriodicPolyhedronGraph(network).components()
    rank = max(
        (component.translation_rank for component in components),
        default=0,
    )
    budget.check_time()
    return rank


def _edge_group_signature(edge: MotifEdge, *, self_loop: bool) -> tuple[str, int]:
    return edge.kind, int(self_loop and any(edge.translation))


def _edge_pair_groups(
    mapping: Mapping[str, str],
    source_edges: Mapping[tuple[str, str], tuple[MotifEdge, ...]],
    target_edges: Mapping[tuple[str, str], tuple[MotifEdge, ...]],
    budget: _SearchBudget,
) -> tuple[tuple[tuple[MotifEdge, ...], tuple[MotifEdge, ...]], ...] | None:
    groups = []
    source_ids = tuple(sorted(mapping))
    for first, second in combinations_with_replacement(source_ids, 2):
        if not budget.active():
            return None
        source_group = source_edges.get(tuple(sorted((first, second))), ())
        target_first = mapping[first]
        target_second = mapping[second]
        target_group = target_edges.get(
            tuple(sorted((target_first, target_second))),
            (),
        )
        self_loop = first == second
        source_by_signature: dict[tuple[str, int], list[MotifEdge]] = {}
        target_by_signature: dict[tuple[str, int], list[MotifEdge]] = {}
        for edge in source_group:
            source_by_signature.setdefault(
                _edge_group_signature(edge, self_loop=self_loop),
                [],
            ).append(edge)
        for edge in target_group:
            target_by_signature.setdefault(
                _edge_group_signature(edge, self_loop=self_loop),
                [],
            ).append(edge)
        for signature in sorted(
            source_by_signature.keys() & target_by_signature.keys()
        ):
            groups.append(
                (
                    tuple(source_by_signature[signature]),
                    tuple(target_by_signature[signature]),
                )
            )
    budget.check_time()
    return tuple(groups)


def _edge_pairs_for_mapping(
    mapping: Mapping[str, str],
    source_graph: MotifGraph,
    target_graph: MotifGraph,
    source_edges: Mapping[tuple[str, str], tuple[MotifEdge, ...]],
    target_edges: Mapping[tuple[str, str], tuple[MotifEdge, ...]],
    budget: _SearchBudget,
) -> _EdgePairing | None:
    source_ids = tuple(sorted(mapping))
    groups = _edge_pair_groups(
        mapping,
        source_edges,
        target_edges,
        budget,
    )
    if groups is None:
        return _EdgePairing((), 0) if len(mapping) == 1 else None

    def connected(edge_pairs: Iterable[tuple[str, str]]) -> bool:
        if len(mapping) <= 1:
            return True
        network = nx.Graph()
        network.add_nodes_from(source_ids)
        for source_edge_id, _ in edge_pairs:
            edge = source_graph.edges[source_edge_id]
            if edge.first != edge.second:
                network.add_edge(edge.first, edge.second)
        return nx.is_connected(network)

    parents = {node_id: node_id for node_id in source_ids}

    def find(node_id: str) -> str:
        while parents[node_id] != node_id:
            parents[node_id] = parents[parents[node_id]]
            node_id = parents[node_id]
        return node_id

    fallback = []
    for source_group, target_group in groups:
        edge = source_group[0]
        first_root = find(edge.first)
        second_root = find(edge.second)
        if first_root == second_root:
            continue
        parents[first_root] = second_root
        fallback.append((source_group[0].id, target_group[0].id))
    fallback_pairing = _EdgePairing(tuple(fallback), 0)
    if not connected(fallback):
        budget.check_time()
        return None

    capacities = tuple(
        min(len(source_group), len(target_group))
        for source_group, target_group in groups
    )
    suffix_capacity = [0] * (len(groups) + 1)
    for index in range(len(groups) - 1, -1, -1):
        suffix_capacity[index] = suffix_capacity[index + 1] + capacities[index]

    def group_choices(
        group_index: int,
        remaining: int,
    ) -> Iterable[tuple[tuple[tuple[str, str], ...], int]]:
        source_group, target_group = groups[group_index]
        maximum = min(capacities[group_index], remaining)
        minimum = max(0, remaining - suffix_capacity[group_index + 1])
        for count in range(maximum, minimum - 1, -1):
            if not budget.active():
                return
            for source_subset in combinations(source_group, count):
                if not budget.active():
                    return
                for target_subset in combinations(target_group, count):
                    if not budget.active():
                        return
                    pairs = tuple(
                        (source.id, target.id)
                        for source, target in zip(source_subset, target_subset)
                    )
                    yield pairs, count

    def selections(
        total: int,
    ) -> Iterable[tuple[tuple[str, str], ...]]:
        if not groups:
            if total == 0 and budget.active():
                yield ()
            return

        # Explicit depth-first frames keep dense mappings independent of
        # Python's recursion limit while preserving the deterministic order.
        stack = [(0, total, iter(group_choices(0, total)))]
        selected_parts: list[tuple[tuple[str, str], ...]] = []
        while stack:
            if not budget.active():
                return
            group_index, remaining, choices = stack[-1]
            try:
                pairs, count = next(choices)
            except StopIteration:
                stack.pop()
                if selected_parts and len(selected_parts) == len(stack):
                    selected_parts.pop()
                continue

            next_remaining = remaining - count
            next_index = group_index + 1
            if next_index == len(groups):
                if next_remaining == 0:
                    yield tuple(
                        pair
                        for part in (*selected_parts, pairs)
                        for pair in part
                    )
                continue

            selected_parts.append(pairs)
            stack.append(
                (
                    next_index,
                    next_remaining,
                    iter(group_choices(next_index, next_remaining)),
                )
            )

    maximum_edges = sum(capacities)
    for edge_count in range(maximum_edges, len(fallback), -1):
        for selected in selections(edge_count):
            if not budget.consume_state():
                return fallback_pairing
            if not connected(selected):
                continue
            selected_source_rank = _periodic_rank(
                source_graph,
                source_ids,
                (source_edge_id for source_edge_id, _ in selected),
                budget,
            )
            if selected_source_rank is None:
                return fallback_pairing
            selected_target_rank = _periodic_rank(
                target_graph,
                mapping.values(),
                (target_edge_id for _, target_edge_id in selected),
                budget,
            )
            if selected_target_rank is None:
                return fallback_pairing
            if selected_source_rank == selected_target_rank:
                budget.check_time()
                return _EdgePairing(selected, selected_source_rank)
    budget.check_time()
    return fallback_pairing


def _normalized_mapping(
    mapping: Mapping[str, str],
    *,
    source_is_first: bool,
) -> tuple[tuple[str, str], ...]:
    if source_is_first:
        pairs = mapping.items()
    else:
        pairs = ((target, source) for source, target in mapping.items())
    return tuple(sorted(pairs))


def _normalized_edge_pairs(
    edge_pairs: Iterable[tuple[str, str]],
    *,
    source_is_first: bool,
) -> tuple[tuple[str, str], ...]:
    if source_is_first:
        pairs = edge_pairs
    else:
        pairs = ((target, source) for source, target in edge_pairs)
    return tuple(sorted(pairs))


def _search_common_motif(
    source_graph: MotifGraph,
    target_graph: MotifGraph,
    source_ids: tuple[str, ...],
    target_ids: tuple[str, ...],
    budget: _SearchBudget,
    *,
    source_is_first: bool,
) -> _SearchResult | None:

    candidates: dict[str, tuple[tuple[str, NodeSimilarity], ...]] = {}
    similarities: dict[tuple[str, str], NodeSimilarity] = {}
    for source_id in source_ids:
        compatible = []
        for target_id in target_ids:
            if not budget.active():
                return None
            score = score_nodes(
                source_graph.nodes[source_id],
                target_graph.nodes[target_id],
            )
            if not budget.check_time():
                return None
            if score is not None:
                compatible.append((target_id, score))
                similarities[(source_id, target_id)] = score
        candidates[source_id] = tuple(
            sorted(compatible, key=lambda item: (-item[1].total, item[0]))
        )

    if not candidates:
        budget.check_time()
        return None

    emergency_best: _SearchResult | None = None
    for source_id in source_ids:
        compatible_targets = candidates.get(source_id, ())
        if compatible_targets:
            target_id, similarity = compatible_targets[0]
            emergency_best = _SearchResult(
                mapping=((source_id, target_id),),
                edge_pairs=(),
                similarities=(similarity,),
                periodic_rank=0,
            )
            break

    source_edge_lookup = _edge_lookup(source_graph, budget)
    target_edge_lookup = _edge_lookup(target_graph, budget)
    if source_edge_lookup is None or target_edge_lookup is None:
        return emergency_best
    source_neighbors: dict[str, set[str]] = {node_id: set() for node_id in source_ids}
    for first, second in source_edge_lookup:
        if first == second:
            continue
        if first in source_neighbors and second in source_neighbors:
            source_neighbors[first].add(second)
            source_neighbors[second].add(first)

    target_positions = {node_id: index for index, node_id in enumerate(target_ids)}
    mapping_base = len(target_ids) + 1
    seen: set[int] = set()
    best: _SearchResult | None = None
    equivalent_best_count = 0

    def mapping_state_key(mapping: Mapping[str, str]) -> int:
        value = 0
        for source_id in source_ids:
            target_id = mapping.get(source_id)
            component = 0 if target_id is None else target_positions[target_id] + 1
            value = value * mapping_base + component
        return value

    def objective(result: _SearchResult) -> tuple[int, int, float]:
        result_polyhedra = sum(
            source_graph.nodes[source_id].kind == "polyhedron"
            for source_id, _ in result.mapping
        )
        result_total = math.fsum(score.total for score in result.similarities)
        return (
            result_polyhedra,
            len(result.edge_pairs),
            result_total,
        )

    def visit(mapping: dict[str, str]) -> None:
        nonlocal best, equivalent_best_count
        if budget.stopped:
            return
        state_key = mapping_state_key(mapping)
        if state_key in seen:
            return
        seen.add(state_key)
        if not budget.consume_state():
            return
        edge_pairing = _edge_pairs_for_mapping(
            mapping,
            source_graph,
            target_graph,
            source_edge_lookup,
            target_edge_lookup,
            budget,
        )
        budget.check_time()
        if edge_pairing is None:
            return

        mapping_pairs = tuple(sorted(mapping.items()))
        result = _SearchResult(
            mapping=mapping_pairs,
            edge_pairs=edge_pairing.pairs,
            similarities=tuple(similarities[pair] for pair in mapping_pairs),
            periodic_rank=edge_pairing.periodic_rank,
        )
        result_objective = objective(result)
        best_objective = objective(best) if best is not None else None
        if best_objective is None or result_objective > best_objective:
            best = result
            equivalent_best_count = 1
        elif result_objective == best_objective:
            equivalent_best_count += 1
            if _normalized_mapping(
                dict(result.mapping),
                source_is_first=source_is_first,
            ) < _normalized_mapping(
                dict(best.mapping),
                source_is_first=source_is_first,
            ):
                best = result
        if budget.stopped:
            return

        current_polyhedra = sum(
            source_graph.nodes[source_id].kind == "polyhedron"
            for source_id in mapping
        )
        remaining_polyhedra = sum(
            source_graph.nodes[source_id].kind == "polyhedron"
            and source_id not in mapping
            and any(
                target_id not in mapping.values()
                for target_id, _ in candidates.get(source_id, ())
            )
            for source_id in source_ids
        )
        best_polyhedra = (
            sum(
                source_graph.nodes[source_id].kind == "polyhedron"
                for source_id, _ in best.mapping
            )
            if best is not None
            else 0
        )
        if current_polyhedra + remaining_polyhedra < best_polyhedra:
            return

        frontier = sorted(
            {
                neighbor
                for source_id in mapping
                for neighbor in source_neighbors[source_id]
                if neighbor not in mapping
            },
            key=lambda node_id: _node_order(source_graph.nodes[node_id]),
        )
        used_targets = set(mapping.values())
        for source_id in frontier:
            for target_id, _ in candidates.get(source_id, ()):
                if target_id in used_targets:
                    continue
                extended = dict(mapping)
                extended[source_id] = target_id
                visit(extended)
                if budget.stopped:
                    return

    for source_id in source_ids:
        for target_id, _ in candidates.get(source_id, ()):
            visit({source_id: target_id})
            if budget.stopped:
                break
        if budget.stopped:
            break
    budget.check_time()
    return (
        replace(best, equivalent_best_count=equivalent_best_count)
        if best is not None
        else None
    )


def _normalized_unit_classification(classification: str, rank: int) -> str:
    lowered = classification.casefold()
    if rank >= 3 or "framework" in lowered:
        return "framework"
    if rank == 2 or "layer" in lowered:
        return "layer"
    if rank == 1 or "chain" in lowered or "ribbon" in lowered:
        return "chain"
    if "ring" in lowered:
        return "ring"
    return "island"


def _matched_descriptor(
    node_pairs: tuple[tuple[str, str], ...],
    edge_pairs: tuple[tuple[str, str], ...],
    periodic_rank: int,
) -> tuple[str, int]:
    cycle_dimension = max(0, len(edge_pairs) - len(node_pairs) + 1)
    zero_cycle_count = max(0, cycle_dimension - periodic_rank)
    raw_classification = PeriodicPolyhedronGraph._classification(
        len(node_pairs),
        periodic_rank,
        zero_cycle_count,
    )
    return (
        _normalized_unit_classification(raw_classification, periodic_rank),
        periodic_rank,
    )


def _same_center_chemistry(first: MotifNode, second: MotifNode) -> bool:
    return math.isclose(_center_similarity(first, second), 1.0, abs_tol=1e-12)


def _unmatched_node(side: str, node: MotifNode) -> UnmatchedNode:
    return UnmatchedNode(
        side=side,
        node_id=node.id,
        kind=node.kind,
        element=node.center_element,
        site_index=node.site_index,
        unit_ids=node.unit_ids,
    )


def _reported_topology_score(
    first_graph: MotifGraph,
    second_graph: MotifGraph,
    matched_nodes: int,
    matched_edges: int,
) -> float:
    node_denominator = len(first_graph.nodes) + len(second_graph.nodes)
    node_coverage = (
        2.0 * matched_nodes / node_denominator if node_denominator else 1.0
    )
    edge_denominator = len(first_graph.edges) + len(second_graph.edges)
    edge_coverage = (
        2.0 * matched_edges / edge_denominator if edge_denominator else 1.0
    )
    return _clamp_unit(0.5 * node_coverage + 0.5 * edge_coverage)


def compare_motifs(
    first: StructureDocument,
    second: StructureDocument,
    limits: MatchLimits = MatchLimits(),
) -> MotifComparisonReport:
    """Find the best bounded, deterministic connected common motif.

    A graph-construction failure is deliberately allowed to propagate: an
    incomplete periodic graph must never be presented as scientific absence.
    """
    started_at = _monotonic()
    budget = _SearchBudget(
        limits=limits,
        deadline=started_at + float(limits.max_seconds),
    )
    first_graph = build_motif_graph(first, budget=budget)
    budget.check_time()
    if budget.stopped:
        second_graph = MotifGraph({}, {}, nx.MultiGraph(), complete=False)
    else:
        second_graph = build_motif_graph(second, budget=budget)
        budget.check_time()
    graphs_complete = first_graph.complete and second_graph.complete
    source_is_first = len(first_graph.nodes) <= len(second_graph.nodes)
    source_graph = first_graph if source_is_first else second_graph
    target_graph = second_graph if source_is_first else first_graph
    source_ids = _bounded_node_ids(source_graph, limits.max_nodes)
    target_ids = _bounded_node_ids(target_graph, limits.max_nodes)
    node_limit_hit = (
        len(source_graph.nodes) > limits.max_nodes
        or len(target_graph.nodes) > limits.max_nodes
    )

    result = (
        _search_common_motif(
            source_graph,
            target_graph,
            source_ids,
            target_ids,
            budget,
            source_is_first=source_is_first,
        )
        if graphs_complete and not budget.stopped
        else None
    )
    if node_limit_hit:
        budget.limit_reasons.add("max_nodes")

    matches: tuple[MotifMatch, ...] = ()
    substitutions: tuple[AtomSubstitution, ...] = ()
    node_pairs: tuple[tuple[str, str], ...] = ()
    edge_id_pairs: tuple[tuple[str, str], ...] = ()
    if result is not None:
        source_mapping = dict(result.mapping)
        node_pairs = _normalized_mapping(
            source_mapping,
            source_is_first=source_is_first,
        )
        edge_id_pairs = _normalized_edge_pairs(
            result.edge_pairs,
            source_is_first=source_is_first,
        )
        classification, periodic_rank = _matched_descriptor(
            node_pairs,
            edge_id_pairs,
            result.periodic_rank,
        )
        budget.check_time()
        semantic_edge_rows = []
        for index, (first_edge_id, second_edge_id) in enumerate(edge_id_pairs):
            if index % 256 == 0:
                budget.check_time()
            semantic_edge_rows.append(
                (
                    _edge_semantic_label(first_graph.edges[first_edge_id]),
                    _edge_semantic_label(second_graph.edges[second_edge_id]),
                    first_graph.edges[first_edge_id].kind,
                )
            )
        semantic_edges = tuple(sorted(semantic_edge_rows))
        budget.check_time()
        similarity_count = len(result.similarities)
        topology_score = _reported_topology_score(
            first_graph,
            second_graph,
            len(node_pairs),
            len(edge_id_pairs),
        )
        geometry_score = math.fsum(
            score.geometry for score in result.similarities
        ) / similarity_count
        chemistry_score = math.fsum(
            score.chemistry for score in result.similarities
        ) / similarity_count
        matches = (
            MotifMatch(
                id="M1",
                classification=classification,
                periodic_rank=periodic_rank,
                node_pairs=node_pairs,
                edge_pairs=tuple(
                    (first_edge, second_edge)
                    for first_edge, second_edge, _ in semantic_edges
                ),
                edge_kinds=tuple(kind for _, _, kind in semantic_edges),
                topology_score=topology_score,
                geometry_score=geometry_score,
                chemistry_score=chemistry_score,
                total_score=_clamp_unit(
                    0.55 * topology_score
                    + 0.30 * geometry_score
                    + 0.15 * chemistry_score
                ),
            ),
        )
        substitutions = tuple(
            AtomSubstitution(
                match_id="M1",
                first_node_id=first_id,
                second_node_id=second_id,
                first_site_index=first_graph.nodes[first_id].site_index,
                second_site_index=second_graph.nodes[second_id].site_index,
                first_element=first_graph.nodes[first_id].center_element,
                second_element=second_graph.nodes[second_id].center_element,
                first_occupancies=first_graph.nodes[first_id].occupancies,
                second_occupancies=second_graph.nodes[second_id].occupancies,
            )
            for first_id, second_id in node_pairs
            if not _same_center_chemistry(
                first_graph.nodes[first_id],
                second_graph.nodes[second_id],
            )
        )
        budget.check_time()

    result_is_interpretable = graphs_complete and (result is not None or not budget.stopped)
    if result_is_interpretable:
        matched_first = {first_id for first_id, _ in node_pairs}
        matched_second = {second_id for _, second_id in node_pairs}
        unmatched_first = tuple(
            _unmatched_node("first", first_graph.nodes[node_id])
            for node_id in sorted(first_graph.nodes)
            if node_id not in matched_first
        )
        unmatched_second = tuple(
            _unmatched_node("second", second_graph.nodes[node_id])
            for node_id in sorted(second_graph.nodes)
            if node_id not in matched_second
        )
    else:
        # A graph/search stopped before both structures were examined.  Partial
        # nodes are unknown, never evidence of a scientifically unmatched site.
        unmatched_first = ()
        unmatched_second = ()
    budget.check_time()
    reason_order = ("max_nodes", "max_states", "max_seconds")
    budget.check_time()
    limit_reasons = tuple(
        reason for reason in reason_order if reason in budget.limit_reasons
    )
    return MotifComparisonReport(
        first_document_id=first.id,
        second_document_id=second.id,
        matches=matches,
        substitutions=substitutions,
        unmatched_first=unmatched_first,
        unmatched_second=unmatched_second,
        approximate=bool(limit_reasons),
        states_explored=budget.states_explored,
        limit_reasons=limit_reasons,
        graph_complete=graphs_complete,
        result_interpretable=result_is_interpretable,
        ambiguous=result is not None and result.equivalent_best_count > 1,
        equivalent_best_count=(
            result.equivalent_best_count if result is not None else 0
        ),
        ambiguity_reason=(
            "equivalent_best_mappings"
            if result is not None and result.equivalent_best_count > 1
            else ""
        ),
    )


__all__ = [
    "ANGLE_DISPERSION_TOLERANCE",
    "AtomSubstitution",
    "BOND_LENGTH_RMS_TOLERANCE",
    "DISTORTION_TOLERANCE",
    "MatchLimits",
    "MOTIF_ALGORITHM_VERSION",
    "MotifComparisonReport",
    "MotifMatch",
    "NodeSimilarity",
    "UnmatchedNode",
    "compare_motifs",
    "score_nodes",
]
