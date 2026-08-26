"""Canonical, translation-aware topology for inorganic structural polyhedra."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

import networkx as nx
import numpy as np

from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph, Translation
from crystal_viewer.core.site_orbits import symmetry_object_orbits

if TYPE_CHECKING:
    from crystal_viewer.analysis.hierarchy import HierarchyReport
    from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence
    from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class TopologyComponent:
    id: str
    polyhedron_ids: tuple[str, ...]
    periodic_rank: int
    classification: str
    closure_translations: tuple[Translation, ...]
    directions: tuple[Translation, ...]
    plane_normal: Translation | None
    connection_counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TopologyFamily:
    id: str
    component_ids: tuple[str, ...]
    classification: str
    periodic_rank: int
    directions: tuple[Translation, ...]
    plane_normal: Translation | None
    building_units: tuple[str, ...]
    connection_counts: tuple[tuple[str, int], ...]
    representation: str = "structural"
    distance_range: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class CationTopologyEdge:
    first: str
    second: str
    translation: Translation
    mode: str
    distance: float
    shared_sites: tuple[int, ...] = ()
    connection_kind: str = "nearest"


@dataclass(frozen=True, slots=True)
class InorganicTopologyReport:
    components: tuple[TopologyComponent, ...]
    families: tuple[TopologyFamily, ...]
    structural_polyhedron_ids: frozenset[str]
    warnings: tuple[str, ...]
    interpretable: bool
    cation_components: tuple[TopologyComponent, ...] = ()
    cation_families: tuple[TopologyFamily, ...] = ()
    cation_edges: tuple[CationTopologyEdge, ...] = ()
    cation_polyhedron_ids: frozenset[str] = frozenset()


def _primitive(vector: Translation) -> Translation:
    values = tuple(int(value) for value in vector)
    divisor = math.gcd(*(abs(value) for value in values))
    if divisor:
        values = tuple(value // divisor for value in values)
    first_nonzero = next((value for value in values if value), 0)
    if first_nonzero < 0:
        values = tuple(-value for value in values)
    return values


def _independent_directions(
    closures: tuple[Translation, ...],
) -> tuple[Translation, ...]:
    candidates = sorted({_primitive(value) for value in closures if any(value)})
    selected: list[Translation] = []
    rank = 0
    for candidate in candidates:
        trial = np.asarray([*selected, candidate], dtype=float)
        trial_rank = int(np.linalg.matrix_rank(trial))
        if trial_rank > rank:
            selected.append(candidate)
            rank = trial_rank
    return tuple(selected)


def _plane_normal(directions: tuple[Translation, ...]) -> Translation | None:
    if len(directions) != 2:
        return None
    normal = np.cross(
        np.asarray(directions[0], dtype=int),
        np.asarray(directions[1], dtype=int),
    )
    return _primitive(tuple(int(value) for value in normal))


def _canonical_edge(
    first: str,
    second: str,
    translation: Translation,
) -> tuple[str, str, Translation]:
    if first < second:
        return first, second, translation
    reverse = tuple(-value for value in translation)
    if first > second:
        return second, first, reverse
    return first, second, min(translation, reverse)


def _cell_supports_voronoi(matrix: np.ndarray) -> bool:
    """Return whether pymatgen's periodic Voronoi search is numerically safe."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        return False
    try:
        singular_values = np.linalg.svd(matrix, compute_uv=False)
    except np.linalg.LinAlgError:
        return False
    largest = float(singular_values[0])
    smallest = float(singular_values[-1])
    return largest > 0.0 and smallest > largest * 1e-12


def _cation_polyhedra(structure, polyhedra) -> dict[str, object]:
    from pymatgen.core import Element

    result = {}
    seen_centres: set[int] = set()
    for identifier, polyhedron in sorted(polyhedra.items()):
        if polyhedron.center_index in seen_centres:
            continue
        site = structure.sites[polyhedron.center_index]
        elements = tuple(
            component.element
            for component in site.components
            if component.occupancy > 0.0
        )
        try:
            is_metal = bool(elements) and all(Element(value).is_metal for value in elements)
        except (TypeError, ValueError):
            is_metal = False
        if is_metal:
            result[identifier] = polyhedron
            seen_centres.add(polyhedron.center_index)
    return result


def _cation_edges(structure, hierarchy, cation_polyhedra) -> tuple[CationTopologyEdge, ...]:
    by_key: dict[tuple[str, str, Translation], CationTopologyEdge] = {}
    cell_matrix = np.asarray(structure.cell.matrix, dtype=float)

    def distance(first: str, second: str, translation: Translation) -> float:
        first_site = structure.sites[cation_polyhedra[first].center_index]
        second_site = structure.sites[cation_polyhedra[second].center_index]
        delta = (
            np.asarray(second_site.fractional, dtype=float)
            + np.asarray(translation, dtype=float)
            - np.asarray(first_site.fractional, dtype=float)
        )
        return float(np.linalg.norm(delta @ cell_matrix))

    for connection in hierarchy.polyhedron_connections:
        if connection.first not in cation_polyhedra or connection.second not in cation_polyhedra:
            continue
        first, second, translation = _canonical_edge(
            connection.first,
            connection.second,
            tuple(int(value) for value in connection.translation),
        )
        by_key[(first, second, translation)] = CationTopologyEdge(
            first,
            second,
            translation,
            "shared-ligand",
            distance(first, second, translation),
            tuple(sorted(item.site_index for item in connection.shared_ligands)),
            str(connection.kind),
        )

    if not cation_polyhedra:
        return ()
    if not _cell_supports_voronoi(cell_matrix):
        return tuple(by_key[key] for key in sorted(by_key))
    try:
        from pymatgen.analysis.local_env import VoronoiNN
        from pymatgen.core import Lattice, Structure

        identifiers = tuple(cation_polyhedra)
        species = []
        fractional = []
        for identifier in identifiers:
            site = structure.sites[cation_polyhedra[identifier].center_index]
            species.append(
                next(
                    component.element
                    for component in site.components
                    if component.occupancy > 0.0
                )
            )
            fractional.append(site.fractional)
        packing = Structure(Lattice(cell_matrix), species, fractional)
        finder = VoronoiNN(tol=0.05, allow_pathological=True)
        for source, first_identifier in enumerate(identifiers):
            for neighbour in finder.get_nn_info(packing, source):
                target = int(neighbour["site_index"])
                raw_image = np.asarray(neighbour.get("image", (0, 0, 0)), dtype=float)
                image = tuple(int(value) for value in np.rint(raw_image))
                second_identifier = identifiers[target]
                if first_identifier == second_identifier and image == (0, 0, 0):
                    continue
                first, second, translation = _canonical_edge(
                    first_identifier, second_identifier, image
                )
                key = (first, second, translation)
                if key in by_key:
                    continue
                by_key[key] = CationTopologyEdge(
                    first,
                    second,
                    translation,
                    "geometric",
                    distance(first, second, translation),
                )
    except (ArithmeticError, KeyError, TypeError, ValueError, RuntimeError):
        pass
    return tuple(by_key[key] for key in sorted(by_key))


def _components(graph: nx.MultiGraph, prefix: str) -> list[TopologyComponent]:
    raw_components = sorted(
        PeriodicPolyhedronGraph(graph).components(),
        key=lambda item: tuple(str(value) for value in item.node_ids),
    )
    result = []
    for number, raw in enumerate(raw_components, start=1):
        identifiers = tuple(str(value) for value in raw.node_ids)
        directions = _independent_directions(raw.closure_translations)
        subgraph = graph.subgraph(raw.node_ids)
        connection_counts = tuple(
            sorted(
                Counter(
                    str(data.get("mode", data.get("kind", "corner")))
                    for *_, data in subgraph.edges(data=True)
                ).items()
            )
        )
        result.append(
            TopologyComponent(
                id=f"{prefix}{number}",
                polyhedron_ids=identifiers,
                periodic_rank=raw.translation_rank,
                classification=raw.classification,
                closure_translations=raw.closure_translations,
                directions=directions,
                plane_normal=_plane_normal(directions),
                connection_counts=connection_counts,
            )
        )
    return result


def build_inorganic_topology(
    structure: "CrystalStructure",
    hierarchy: "HierarchyReport",
    roles: Iterable["PolyhedronRoleEvidence"],
) -> InorganicTopologyReport:
    """Build topology only from coordination centres proven structural."""
    polyhedra = {item.id: item for item in hierarchy.polyhedra}
    role_items = tuple(roles)
    from crystal_viewer.analysis.structural_roles import primary_motif_center_indices

    primary_centres = primary_motif_center_indices(
        role_items,
        {
            item.center_index: frozenset(
                {
                    *(f"element:{part}" for part in item.center_element.split("/")),
                    f"coordination:{item.ligand_element}:{item.coordination_number}",
                }
            )
            for item in polyhedra.values()
        },
    )
    structural_ids = frozenset(
        identifier
        for identifier, polyhedron in polyhedra.items()
        if polyhedron.center_index in primary_centres
    )

    graph = nx.MultiGraph()
    graph.add_nodes_from(sorted(structural_ids))
    for connection in hierarchy.polyhedron_connections:
        if connection.first not in structural_ids or connection.second not in structural_ids:
            continue
        graph.add_edge(
            connection.first,
            connection.second,
            first=connection.first,
            second=connection.second,
            translation=connection.translation,
            kind=connection.kind,
            shared_sites=tuple(item.site_index for item in connection.shared_ligands),
        )

    components = _components(graph, "TC")

    component_by_id = {item.id: item for item in components}
    anchors = tuple(
        frozenset(polyhedra[identifier].center_index for identifier in item.polyhedron_ids)
        for item in components
    )
    signatures = tuple(
        (
            item.classification,
            item.periodic_rank,
            item.connection_counts,
            tuple(sorted({polyhedra[value].type_name for value in item.polyhedron_ids})),
        )
        for item in components
    )
    component_orbits = symmetry_object_orbits(
        structure,
        tuple(item.id for item in components),
        anchors,
        signatures,
    )
    families: list[TopologyFamily] = []
    for number, component_ids in enumerate(component_orbits, start=1):
        component = component_by_id[component_ids[0]]
        building_units = tuple(
            sorted(
                {
                    polyhedra[identifier].type_name
                    for component_id in component_ids
                    for identifier in component_by_id[component_id].polyhedron_ids
                }
            )
        )
        families.append(
            TopologyFamily(
                id=f"TF{number}",
                component_ids=component_ids,
                classification=component.classification,
                periodic_rank=component.periodic_rank,
                directions=component.directions,
                plane_normal=component.plane_normal,
                building_units=building_units,
                connection_counts=component.connection_counts,
            )
        )

    cation_polyhedra = _cation_polyhedra(structure, polyhedra)
    cation_edges = _cation_edges(structure, hierarchy, cation_polyhedra)
    cation_graph = nx.MultiGraph()
    cation_graph.add_nodes_from(cation_polyhedra)
    for edge in cation_edges:
        cation_graph.add_edge(
            edge.first,
            edge.second,
            first=edge.first,
            second=edge.second,
            translation=edge.translation,
            mode=edge.mode,
            kind=edge.connection_kind,
            shared_sites=edge.shared_sites,
        )
    cation_components = _components(cation_graph, "CC")
    cation_component_by_id = {item.id: item for item in cation_components}
    cation_anchors = tuple(
        frozenset(cation_polyhedra[value].center_index for value in item.polyhedron_ids)
        for item in cation_components
    )
    cation_signatures = tuple(
        (
            item.classification,
            item.periodic_rank,
            item.connection_counts,
            tuple(sorted({cation_polyhedra[value].type_name for value in item.polyhedron_ids})),
        )
        for item in cation_components
    )
    cation_orbits = symmetry_object_orbits(
        structure,
        tuple(item.id for item in cation_components),
        cation_anchors,
        cation_signatures,
    )
    cation_families = []
    for number, component_ids in enumerate(cation_orbits, start=1):
        component = cation_component_by_id[component_ids[0]]
        identifiers = {
            value
            for component_id in component_ids
            for value in cation_component_by_id[component_id].polyhedron_ids
        }
        relevant_edges = tuple(
            edge
            for edge in cation_edges
            if edge.first in identifiers and edge.second in identifiers
        )
        distances = tuple(edge.distance for edge in relevant_edges)
        cation_families.append(
            TopologyFamily(
                id=f"CF{number}",
                component_ids=component_ids,
                classification=component.classification,
                periodic_rank=component.periodic_rank,
                directions=component.directions,
                plane_normal=component.plane_normal,
                building_units=tuple(
                    sorted({cation_polyhedra[value].type_name for value in identifiers})
                ),
                connection_counts=component.connection_counts,
                representation="cation",
                distance_range=(min(distances), max(distances)) if distances else None,
            )
        )

    warnings = () if components else ("No structural-polyhedron topology could be evaluated.",)
    return InorganicTopologyReport(
        components=tuple(components),
        families=tuple(families),
        structural_polyhedron_ids=structural_ids,
        warnings=warnings,
        interpretable=bool(components),
        cation_components=tuple(cation_components),
        cation_families=tuple(cation_families),
        cation_edges=cation_edges,
        cation_polyhedron_ids=frozenset(cation_polyhedra),
    )


__all__ = [
    "CationTopologyEdge",
    "InorganicTopologyReport",
    "TopologyComponent",
    "TopologyFamily",
    "build_inorganic_topology",
]
