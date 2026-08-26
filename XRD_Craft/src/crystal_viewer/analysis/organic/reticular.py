from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import combinations

import networkx as nx
from pymatgen.core import Element

from crystal_viewer.analysis.organic.components import ComponentReport
from crystal_viewer.analysis.organic.model import BondLayerReport, ChemicalEdge
from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph
from crystal_viewer.core.chemistry import site_elements
from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class CoordinationNode:
    id: str
    atom_indices: tuple[int, ...]
    coordination_edge_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class OrganicLinker:
    id: str
    component_id: str
    incident_node_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class SecondaryBuildingUnit:
    id: str
    coordination_node_ids: tuple[str, ...]
    representation: str


@dataclass(frozen=True, slots=True)
class UnderlyingNode:
    id: str
    kind: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnderlyingEdge:
    id: str
    first: str
    second: str
    image: tuple[int, int, int]
    linker_id: str


@dataclass(frozen=True, slots=True)
class ContextComponent:
    id: str
    component_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ReticularAlternative:
    name: str
    graph_digest: str
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReticularReport:
    coordination_nodes: tuple[CoordinationNode, ...]
    linkers: tuple[OrganicLinker, ...]
    sbus: tuple[SecondaryBuildingUnit, ...]
    underlying_nodes: tuple[UnderlyingNode, ...]
    underlying_edges: tuple[UnderlyingEdge, ...]
    guests: tuple[ContextComponent, ...]
    periodic_rank: int
    recommended_representation: str
    alternatives: tuple[ReticularAlternative, ...]
    representation_notes: tuple[str, ...]
    graph_digest: str
    complete: bool = True
    warnings: tuple[str, ...] = ()
    method_version: str = "organic-reticular-v1"

    @property
    def network_object_ids(self) -> frozenset[str]:
        return frozenset(node.id for node in self.underlying_nodes) | frozenset(
            edge.id for edge in self.underlying_edges
        )


def _is_metal(structure: CrystalStructure, index: int) -> bool:
    try:
        return any(Element(symbol).is_metal for symbol in site_elements(structure.sites[index]))
    except ValueError:
        return False


def _digest(nodes: tuple[UnderlyingNode, ...], edges: tuple[UnderlyingEdge, ...]) -> str:
    degrees = {node.id: 0 for node in nodes}
    for edge in edges:
        degrees[edge.first] = degrees.get(edge.first, 0) + 1
        degrees[edge.second] = degrees.get(edge.second, 0) + 1
    payload = (
        tuple(sorted((node.kind, degrees[node.id], node.source_ids) for node in nodes)),
        tuple(sorted((edge.first, edge.second, edge.image, edge.linker_id) for edge in edges)),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def build_reticular_network(
    structure: CrystalStructure,
    bonds: BondLayerReport,
    components: ComponentReport,
) -> ReticularReport:
    confident = tuple(edge for edge in bonds.coordination if edge.confidence >= 0.75)
    component_for_atom = {
        atom: component.id
        for component in components.components
        for atom in component.atom_indices
    }
    metal_graph = nx.Graph()
    incident_metals: set[int] = set()
    for edge in confident:
        first_metal = _is_metal(structure, edge.first)
        second_metal = _is_metal(structure, edge.second)
        if first_metal:
            incident_metals.add(edge.first)
        if second_metal:
            incident_metals.add(edge.second)
        if first_metal and second_metal:
            metal_graph.add_edge(edge.first, edge.second)
    for component in components.components:
        symbols = {
            symbol
            for atom in component.atom_indices
            for symbol in site_elements(structure.sites[atom])
        }
        if "C" in symbols:
            continue
        bridged_metals: set[int] = set()
        members = set(component.atom_indices)
        for edge in confident:
            if edge.first in incident_metals and edge.second in members:
                bridged_metals.add(edge.first)
            if edge.second in incident_metals and edge.first in members:
                bridged_metals.add(edge.second)
        metal_graph.add_edges_from(combinations(sorted(bridged_metals), 2))
    metal_graph.add_nodes_from(incident_metals)

    node_for_metal: dict[int, str] = {}
    nodes: list[CoordinationNode] = []
    for number, members in enumerate(
        sorted(nx.connected_components(metal_graph), key=lambda values: tuple(sorted(values))),
        start=1,
    ):
        atom_indices = tuple(sorted(members))
        identifier = f"CN{number}"
        edge_ids = tuple(
            sorted(edge.id for edge in confident if edge.first in members or edge.second in members)
        )
        confidence = min(
            (edge.confidence for edge in confident if edge.id in edge_ids), default=1.0
        )
        nodes.append(CoordinationNode(identifier, atom_indices, edge_ids, confidence))
        node_for_metal.update((index, identifier) for index in members)

    incidences: dict[str, list[tuple[str, tuple[int, int, int], ChemicalEdge]]] = {}
    for edge in confident:
        if edge.first in node_for_metal and edge.second in component_for_atom:
            incidences.setdefault(component_for_atom[edge.second], []).append(
                (node_for_metal[edge.first], edge.image, edge)
            )
        elif edge.second in node_for_metal and edge.first in component_for_atom:
            incidences.setdefault(component_for_atom[edge.first], []).append(
                (node_for_metal[edge.second], tuple(-value for value in edge.image), edge)
            )

    linkers: list[OrganicLinker] = []
    context: list[ContextComponent] = []
    underlying_nodes = [UnderlyingNode(node.id, "coordination node", (node.id,)) for node in nodes]
    underlying_edges: list[UnderlyingEdge] = []
    for component in components.components:
        raw = incidences.get(component.id, [])
        unique = []
        seen = set()
        for node_id, image, edge in sorted(raw, key=lambda item: (item[0], item[1], item[2].id)):
            key = (node_id, image)
            if key not in seen:
                seen.add(key)
                unique.append((node_id, image, edge))
        if len(unique) < 2:
            role = "terminal ligand" if unique else "guest / counterion"
            context.append(ContextComponent(f"CTX{len(context) + 1}", component.id, role))
            continue
        linker_id = f"L{len(linkers) + 1}"
        linker = OrganicLinker(
            linker_id,
            component.id,
            tuple(item[0] for item in unique),
            min(item[2].confidence for item in unique),
        )
        linkers.append(linker)
        if len(unique) == 2:
            first, second = unique
            image = tuple(first[1][axis] - second[1][axis] for axis in range(3))
            underlying_edges.append(
                UnderlyingEdge(
                    f"UE{len(underlying_edges) + 1}", first[0], second[0], image, linker_id
                )
            )
        else:
            underlying_nodes.append(UnderlyingNode(linker_id, "linker", (component.id,)))
            for node_id, image, _edge in unique:
                underlying_edges.append(
                    UnderlyingEdge(
                        f"UE{len(underlying_edges) + 1}", node_id, linker_id, image, linker_id
                    )
                )

    sbus = tuple(
        SecondaryBuildingUnit(
            f"SBU{index}",
            (node.id,),
            "metal cluster" if len(node.atom_indices) > 1 else "single metal centre",
        )
        for index, node in enumerate(nodes, start=1)
    )
    node_tuple = tuple(underlying_nodes)
    edge_tuple = tuple(underlying_edges)
    graph = nx.MultiGraph()
    graph.add_nodes_from(node.id for node in node_tuple)
    for edge in edge_tuple:
        graph.add_edge(
            edge.first, edge.second, first=edge.first, second=edge.second,
            translation=edge.image,
        )
    rank = max(
        (component.translation_rank for component in PeriodicPolyhedronGraph(graph).components()),
        default=0,
    )
    digest = _digest(node_tuple, edge_tuple)
    cluster_nodes = tuple(node for node in nodes if len(node.atom_indices) > 1)
    alternatives = (
        (
            ReticularAlternative(
                "single-metal nodes",
                digest,
                ("Metal cluster can alternatively be split into individual metal centres.",),
            ),
        )
        if cluster_nodes
        else ()
    )
    notes = (
        "Two-connected organic components are contracted to underlying edges.",
        "Higher-connected organic components remain linker nodes.",
        "Terminal ligands, counterions, and guests are retained as context.",
        "No named topology symbol is assigned.",
    )
    warning_items = [*bonds.warnings, *components.warnings]
    if len(confident) != len(bonds.coordination):
        warning_items.append("Low-confidence coordination edges were excluded.")
    warnings = tuple(dict.fromkeys(warning_items))
    return ReticularReport(
        tuple(nodes), tuple(linkers), sbus, node_tuple, edge_tuple, tuple(context), rank,
        "cluster SBUs" if cluster_nodes else "single-metal nodes",
        alternatives, notes, digest, bonds.complete and components.complete, warnings,
    )


__all__ = [
    "ContextComponent", "CoordinationNode", "OrganicLinker", "ReticularAlternative",
    "ReticularReport", "SecondaryBuildingUnit", "UnderlyingEdge", "UnderlyingNode",
    "build_reticular_network",
]
