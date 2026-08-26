"""Immutable, attributed motif graphs for structure matching."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
import math
from types import MappingProxyType
from typing import Mapping, Protocol

import networkx as nx
import numpy as np

from crystal_viewer.analysis.hierarchy import (
    ANION_ELEMENTS,
    CoordinationPolyhedron,
    HierarchyAnalyzer,
)
from crystal_viewer.core.document import StructureDocument
from crystal_viewer.core.model import AtomSite
from crystal_viewer.core.scene import COVALENT_RADII


SCENE_BOND_TOLERANCE = 1.18
_MINIMUM_BOND_DISTANCE = 0.25
# UI-facing graph construction must never enumerate an unbounded image cloud
# from a malformed or nearly singular CIF cell.
MAX_LATTICE_IMAGE_CANDIDATES = 50_000
# A graph can contain thousands of individually valid contact searches. Bound
# their aggregate work as well as each search to keep document loading finite.
MAX_MOTIF_GRAPH_IMAGE_CANDIDATES = 100_000
_MINIMUM_RELATIVE_CELL_VOLUME = 1e-8

OccupancyDistribution = tuple[tuple[str, float], ...]
Translation = tuple[int, int, int]


class LatticeImageSearchError(ValueError):
    """MotifGraph construction was rejected rather than returned incomplete."""


class MotifGraphBudget(Protocol):
    """Comparison-owned soft limits checked while constructing a graph."""

    def active(self) -> bool: ...

    def allow_graph_node(self, node_count: int) -> bool: ...


class _GraphBuildStopped(RuntimeError):
    """Internal control flow for an explicitly limited partial graph."""


@dataclass(slots=True)
class _CandidateBudget:
    maximum: int
    consumed: int = 0

    def reserve(self, candidate_count: int) -> None:
        projected = self.consumed + candidate_count
        if projected > self.maximum:
            raise LatticeImageSearchError(
                f"Motif graph cumulative candidate budget {projected} exceeds "
                f"hard limit {self.maximum}; graph construction is incomplete "
                "and no MotifGraph was returned."
            )
        self.consumed = projected


@dataclass(frozen=True, slots=True)
class MotifNode:
    id: str
    kind: str
    coordination_number: int
    center_element: str
    ligand_elements: tuple[str, ...]
    normalized_bond_lengths: tuple[float, ...]
    distortion: float
    angle_dispersion: float
    unit_ids: tuple[str, ...]
    occupancies: OccupancyDistribution = ()
    site_index: int | None = None


@dataclass(frozen=True, slots=True)
class MotifEdge:
    id: str
    first: str
    second: str
    kind: str
    shared_site_indices: tuple[int, ...]
    translation: Translation
    normalized_distance: float


@dataclass(frozen=True, slots=True)
class MotifGraph:
    nodes: Mapping[str, MotifNode]
    edges: Mapping[str, MotifEdge]
    graph: nx.MultiGraph
    complete: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", MappingProxyType(dict(self.nodes)))
        object.__setattr__(self, "edges", MappingProxyType(dict(self.edges)))
        object.__setattr__(self, "graph", nx.freeze(self.graph.copy()))


@dataclass(frozen=True, slots=True)
class _Contact:
    site_index: int
    image: Translation
    polyhedron_translation: Translation
    element: str
    distance: float
    normalized_distance: float
    vector: tuple[float, float, float]


def _occupancies(site: AtomSite) -> OccupancyDistribution:
    return tuple(
        sorted(
            ((component.element, float(component.occupancy)) for component in site.components),
            key=lambda item: item[0],
        )
    )


def _site_radius(site: AtomSite) -> float:
    occupied = [(component.element, component.occupancy) for component in site.components if component.occupancy > 0.0]
    total = sum(occupancy for _, occupancy in occupied)
    if total > 0.0:
        return float(
            sum(COVALENT_RADII.get(element, 1.0) * occupancy for element, occupancy in occupied)
            / total
        )
    return float(COVALENT_RADII.get(site.element, 1.0))


def _is_anion_site(site: AtomSite) -> bool:
    elements = {component.element for component in site.components if component.occupancy > 0.0}
    return bool(elements) and elements <= ANION_ELEMENTS


def _normalized_lengths(lengths: tuple[float, ...]) -> tuple[float, ...]:
    mean = float(np.mean(lengths)) if lengths else 0.0
    if mean <= 0.0:
        return tuple(0.0 for _ in lengths)
    return tuple(float(length / mean) for length in lengths)


def _angle_dispersion(vectors: list[tuple[float, float, float]]) -> float:
    if len(vectors) < 2:
        return 0.0
    values = np.asarray(vectors, dtype=float)
    unit_vectors = values / np.maximum(np.linalg.norm(values, axis=1)[:, None], 1e-12)
    angles = [
        np.degrees(np.arccos(np.clip(np.dot(first, second), -1.0, 1.0)))
        for first, second in combinations(unit_vectors, 2)
    ]
    mean = float(np.mean(angles)) if angles else 0.0
    return float(np.std(angles) / mean) if mean else 0.0


def _unit_memberships(document: StructureDocument) -> tuple[dict[str, tuple[str, ...]], dict[int, tuple[str, ...]]]:
    by_polyhedron: dict[str, list[str]] = {}
    by_site: dict[int, list[str]] = {}
    for unit in document.hierarchy.structural_units:
        for polyhedron_id in unit.polyhedron_ids:
            by_polyhedron.setdefault(polyhedron_id, []).append(unit.id)
        for site_index in unit.atom_indices:
            by_site.setdefault(site_index, []).append(unit.id)
    return (
        {key: tuple(sorted(value)) for key, value in by_polyhedron.items()},
        {key: tuple(sorted(value)) for key, value in by_site.items()},
    )


def _motif_polyhedra(document: StructureDocument) -> tuple[CoordinationPolyhedron, ...]:
    analysis = document.structural_analysis
    if analysis is not None and analysis.polyhedron_roles:
        role_by_center = {
            item.center_index: item.role for item in analysis.polyhedron_roles
        }
        return tuple(
            polyhedron
            for polyhedron in document.hierarchy.polyhedra
            if role_by_center.get(polyhedron.center_index) == "structural"
        )
    return tuple(
        polyhedron
        for polyhedron in document.hierarchy.polyhedra
        if not HierarchyAnalyzer.is_interstitial_polyhedron(polyhedron)
    )


def _polyhedron_node(
    document: StructureDocument,
    polyhedron: CoordinationPolyhedron,
    unit_ids: tuple[str, ...],
) -> MotifNode:
    sites = document.structure.sites
    center = sites[polyhedron.center_index]
    return MotifNode(
        id=polyhedron.id,
        kind="polyhedron",
        coordination_number=polyhedron.coordination_number,
        center_element=polyhedron.center_element,
        ligand_elements=tuple(sites[ligand.site_index].element for ligand in polyhedron.ligands),
        normalized_bond_lengths=_normalized_lengths(polyhedron.bond_lengths),
        distortion=float(polyhedron.distortion),
        angle_dispersion=float(polyhedron.angle_dispersion),
        unit_ids=unit_ids,
        occupancies=_occupancies(center),
        site_index=polyhedron.center_index,
    )


def _center_distance(
    document: StructureDocument,
    first: CoordinationPolyhedron,
    second: CoordinationPolyhedron,
    translation: Translation,
) -> float:
    sites = document.structure.sites
    first_site = sites[first.center_index]
    second_site = sites[second.center_index]
    delta = (
        np.asarray(second_site.fractional, dtype=float)
        + np.asarray(translation, dtype=float)
        - np.asarray(first_site.fractional, dtype=float)
    )
    distance = float(np.linalg.norm(delta @ document.structure.cell.matrix))
    radius_sum = _site_radius(first_site) + _site_radius(second_site)
    return distance / max(radius_sum, 1e-12)


def _polyhedron_geometry(
    document: StructureDocument,
    polyhedron: CoordinationPolyhedron,
) -> tuple[tuple[int, Translation], ...]:
    return ((polyhedron.center_index, (0, 0, 0)),) + tuple(
        (ligand.site_index, ligand.image) for ligand in polyhedron.ligands
    )


def _lattice_images_within_cutoff(
    fractional_delta: np.ndarray,
    matrix: np.ndarray,
    cutoff: float,
    budget: _CandidateBudget,
    graph_budget: MotifGraphBudget | None = None,
) -> tuple[tuple[Translation, float, tuple[float, float, float]], ...]:
    """Enumerate every lattice image inside a Cartesian cutoff sphere."""
    if graph_budget is not None and not graph_budget.active():
        raise _GraphBuildStopped
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise LatticeImageSearchError(
            "Cell matrix is singular or numerically unusable for lattice-image "
            "search; graph construction is incomplete and no MotifGraph was returned."
        )
    vector_lengths = np.linalg.norm(matrix, axis=1)
    determinant = float(abs(np.linalg.det(matrix)))
    scale_volume = float(np.prod(vector_lengths))
    relative_volume = determinant / scale_volume if scale_volume > 0.0 else 0.0
    if not np.isfinite(relative_volume) or relative_volume <= _MINIMUM_RELATIVE_CELL_VOLUME:
        raise LatticeImageSearchError(
            "Cell matrix is singular or numerically unusable for lattice-image "
            "search; graph construction is incomplete and no MotifGraph was returned."
        )
    try:
        reciprocal = np.linalg.inv(matrix)
    except np.linalg.LinAlgError as error:
        raise LatticeImageSearchError(
            "Cell matrix is singular or numerically unusable for lattice-image "
            "search; graph construction is incomplete and no MotifGraph was returned."
        ) from error

    # If x = f @ matrix and |x| <= cutoff, Cauchy-Schwarz gives
    # |f_i| <= cutoff * ||column_i(matrix^-1)|| independently for each axis.
    axis_bounds = cutoff * np.linalg.norm(reciprocal, axis=0)
    if not np.all(np.isfinite(axis_bounds)):
        raise LatticeImageSearchError(
            "Cell matrix is singular or numerically unusable for lattice-image "
            "search; graph construction is incomplete and no MotifGraph was returned."
        )
    endpoints = []
    widths = []
    for component, axis_bound in zip(fractional_delta, axis_bounds, strict=True):
        lower = int(np.ceil(-float(component) - float(axis_bound) - 1e-12))
        upper = int(np.floor(-float(component) + float(axis_bound) + 1e-12))
        endpoints.append((lower, upper))
        widths.append(max(0, upper - lower + 1))
    if any(width == 0 for width in widths):
        return ()
    candidate_count = math.prod(widths)
    if candidate_count > MAX_LATTICE_IMAGE_CANDIDATES:
        raise LatticeImageSearchError(
            f"{candidate_count} candidate lattice images exceeds hard limit "
            f"{MAX_LATTICE_IMAGE_CANDIDATES}; graph construction is incomplete "
            "and no MotifGraph was returned."
        )
    budget.reserve(candidate_count)
    ranges = tuple(range(lower, upper + 1) for lower, upper in endpoints)

    images = []
    for index, raw_translation in enumerate(product(*ranges)):
        if index % 256 == 0 and graph_budget is not None and not graph_budget.active():
            raise _GraphBuildStopped
        translation = tuple(int(value) for value in raw_translation)
        vector = (fractional_delta + np.asarray(translation, dtype=float)) @ matrix
        distance = float(np.linalg.norm(vector))
        if _MINIMUM_BOND_DISTANCE < distance <= cutoff + 1e-12:
            images.append(
                (
                    translation,
                    distance,
                    tuple(float(value) for value in vector),
                )
            )
    return tuple(images)


def _contacts_for_polyhedron(
    document: StructureDocument,
    interstitial_index: int,
    polyhedron: CoordinationPolyhedron,
    budget: _CandidateBudget,
    graph_budget: MotifGraphBudget | None = None,
) -> tuple[_Contact, ...]:
    structure = document.structure
    interstitial = structure.sites[interstitial_index]
    interstitial_fractional = np.asarray(interstitial.fractional, dtype=float)
    interstitial_radius = _site_radius(interstitial)
    contacts = []
    for site_index, intrinsic_image in _polyhedron_geometry(document, polyhedron):
        if graph_budget is not None and not graph_budget.active():
            raise _GraphBuildStopped
        target = structure.sites[site_index]
        fractional_delta = (
            np.asarray(target.fractional, dtype=float)
            + np.asarray(intrinsic_image, dtype=float)
            - interstitial_fractional
        )
        radius_sum = interstitial_radius + _site_radius(target)
        cutoff = radius_sum * SCENE_BOND_TOLERANCE
        for polyhedron_translation, distance, vector in _lattice_images_within_cutoff(
            fractional_delta,
            structure.cell.matrix,
            cutoff,
            budget,
            graph_budget,
        ):
            image = tuple(
                int(intrinsic_image[axis] + polyhedron_translation[axis])
                for axis in range(3)
            )
            contacts.append(
                _Contact(
                    site_index=site_index,
                    image=image,
                    polyhedron_translation=polyhedron_translation,
                    element=target.element,
                    distance=distance,
                    normalized_distance=distance / max(radius_sum, 1e-12),
                    vector=vector,
                )
            )
    return tuple(contacts)


def _interstitial_node(
    document: StructureDocument,
    site_index: int,
    contacts: Mapping[tuple[int, Translation], _Contact],
    unit_ids: tuple[str, ...],
) -> MotifNode:
    site = document.structure.sites[site_index]
    ordered = tuple(
        sorted(contacts.values(), key=lambda contact: (contact.site_index, contact.image))
    )
    lengths = tuple(contact.distance for contact in ordered)
    mean = float(np.mean(lengths)) if lengths else 0.0
    distortion = float(np.std(lengths) / mean) if mean else 0.0
    return MotifNode(
        id=f"I{site_index}",
        kind="interstitial",
        coordination_number=len(ordered),
        center_element=site.element,
        ligand_elements=tuple(contact.element for contact in ordered),
        normalized_bond_lengths=_normalized_lengths(lengths),
        distortion=distortion,
        angle_dispersion=_angle_dispersion([contact.vector for contact in ordered]),
        unit_ids=unit_ids,
        occupancies=_occupancies(site),
        site_index=site_index,
    )


def build_motif_graph(
    document: StructureDocument,
    *,
    budget: MotifGraphBudget | None = None,
) -> MotifGraph:
    """Build a scale-normalized motif graph without changing hierarchy data."""
    motif_polyhedra = _motif_polyhedra(document)
    motif_ids = {polyhedron.id for polyhedron in motif_polyhedra}
    polyhedron_lookup = {polyhedron.id: polyhedron for polyhedron in motif_polyhedra}
    unit_by_polyhedron, unit_by_site = _unit_memberships(document)

    nodes: dict[str, MotifNode] = {}
    edges: dict[str, MotifEdge] = {}
    network = nx.MultiGraph()
    candidate_budget = _CandidateBudget(MAX_MOTIF_GRAPH_IMAGE_CANDIDATES)
    complete = True

    try:
        for polyhedron in motif_polyhedra:
            if budget is not None and not budget.allow_graph_node(len(nodes)):
                raise _GraphBuildStopped
            node = _polyhedron_node(
                document,
                polyhedron,
                unit_by_polyhedron.get(polyhedron.id, ()),
            )
            nodes[node.id] = node
            network.add_node(node.id)

        for connection in document.hierarchy.polyhedron_connections:
            if budget is not None and not budget.active():
                raise _GraphBuildStopped
            if connection.first not in nodes or connection.second not in nodes:
                continue
            edge = MotifEdge(
                id=f"E{len(edges) + 1}",
                first=connection.first,
                second=connection.second,
                kind=connection.kind,
                shared_site_indices=tuple(
                    ligand.site_index for ligand in connection.shared_ligands
                ),
                translation=connection.translation,
                normalized_distance=_center_distance(
                    document,
                    polyhedron_lookup[connection.first],
                    polyhedron_lookup[connection.second],
                    connection.translation,
                ),
            )
            edges[edge.id] = edge
            network.add_edge(edge.first, edge.second, key=edge.id)

        motif_center_indices = {polyhedron.center_index for polyhedron in motif_polyhedra}
        for site_index, site in enumerate(document.structure.sites):
            if budget is not None and not budget.active():
                raise _GraphBuildStopped
            total_occupancy = sum(component.occupancy for component in site.components)
            if (
                total_occupancy <= 0.0
                or site_index in motif_center_indices
                or _is_anion_site(site)
            ):
                continue
            if budget is not None and not budget.allow_graph_node(len(nodes)):
                raise _GraphBuildStopped
            contacts_by_image: dict[
                tuple[str, Translation],
                dict[tuple[int, Translation], _Contact],
            ] = {}
            unique_contacts: dict[tuple[int, Translation], _Contact] = {}
            for polyhedron in motif_polyhedra:
                contacts = _contacts_for_polyhedron(
                    document,
                    site_index,
                    polyhedron,
                    candidate_budget,
                    budget,
                )
                if not contacts:
                    continue
                for contact in contacts:
                    image_key = (polyhedron.id, contact.polyhedron_translation)
                    contacts_by_image.setdefault(image_key, {}).setdefault(
                        (contact.site_index, contact.image),
                        contact,
                    )
                    unique_contacts.setdefault((contact.site_index, contact.image), contact)
            if not contacts_by_image:
                continue

            node = _interstitial_node(
                document,
                site_index,
                unique_contacts,
                unit_by_site.get(site_index, ()),
            )
            nodes[node.id] = node
            network.add_node(node.id)

            for (polyhedron_id, translation), contact_lookup in contacts_by_image.items():
                if budget is not None and not budget.active():
                    raise _GraphBuildStopped
                contacts = tuple(contact_lookup.values())
                closest = min(
                    contacts,
                    key=lambda contact: (
                        contact.normalized_distance,
                        contact.distance,
                        contact.site_index,
                        contact.image,
                    ),
                )
                edge = MotifEdge(
                    id=f"E{len(edges) + 1}",
                    first=node.id,
                    second=polyhedron_id,
                    kind="interstitial",
                    shared_site_indices=(closest.site_index,),
                    translation=translation,
                    normalized_distance=closest.normalized_distance,
                )
                edges[edge.id] = edge
                network.add_edge(edge.first, edge.second, key=edge.id)
    except _GraphBuildStopped:
        complete = False

    return MotifGraph(nodes=nodes, edges=edges, graph=network, complete=complete)


__all__ = [
    "LatticeImageSearchError",
    "MAX_LATTICE_IMAGE_CANDIDATES",
    "MAX_MOTIF_GRAPH_IMAGE_CANDIDATES",
    "MotifEdge",
    "MotifGraph",
    "MotifGraphBudget",
    "MotifNode",
    "build_motif_graph",
]
