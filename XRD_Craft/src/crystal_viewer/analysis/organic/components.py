from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass

import networkx as nx
import numpy as np
from pymatgen.core import Element

from crystal_viewer.analysis.organic.model import BondLayerReport, ChemicalEdge
from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph
from crystal_viewer.core.chemistry import site_elements
from crystal_viewer.core.model import CrystalStructure


Translation = tuple[int, int, int]
_PI_ELEMENTS = frozenset({"B", "C", "N", "P", "S", "Si", "Ge", "As"})


@dataclass(frozen=True, slots=True)
class MolecularComponent:
    id: str
    atom_indices: tuple[int, ...]
    bond_ids: tuple[str, ...]
    periodic_rank: int
    closure_translations: tuple[Translation, ...]
    formula: str
    confidence: float
    orbit_key: str


@dataclass(frozen=True, slots=True)
class MolecularRing:
    id: str
    component_id: str
    atom_indices: tuple[int, ...]
    planarity_rms: float
    pi_capable: bool
    confidence: float
    warnings: tuple[str, ...] = ()

    @property
    def style_key(self) -> tuple[bool, str]:
        return (self.pi_capable, "uncertain" if self.confidence < 1.0 else "certain")


@dataclass(frozen=True, slots=True)
class PiSystem:
    id: str
    ring_ids: tuple[str, ...]
    centroid_fractional: tuple[float, float, float]
    normal_cartesian: tuple[float, float, float]
    confidence: float


@dataclass(frozen=True, slots=True)
class ComponentReport:
    components: tuple[MolecularComponent, ...]
    rings: tuple[MolecularRing, ...]
    pi_systems: tuple[PiSystem, ...]
    complete: bool = True
    warnings: tuple[str, ...] = ()
    method_version: str = "organic-components-v1"


def _canonical_cycle(nodes: list[int]) -> tuple[int, ...]:
    values = tuple(nodes)
    variants: list[tuple[int, ...]] = []
    for sequence in (values, tuple(reversed(values))):
        variants.extend(sequence[index:] + sequence[:index] for index in range(len(sequence)))
    return min(variants)


def _formula(structure: CrystalStructure, nodes: tuple[int, ...]) -> str:
    counts: Counter[str] = Counter()
    for index in nodes:
        elements = site_elements(structure.sites[index])
        if elements:
            counts[elements[0]] += 1
    order = [symbol for symbol in ("C", "H") if symbol in counts]
    order.extend(sorted(symbol for symbol in counts if symbol not in {"C", "H"}))
    return "".join(symbol + (str(counts[symbol]) if counts[symbol] != 1 else "") for symbol in order)


def _orbit_key(
    structure: CrystalStructure,
    nodes: tuple[int, ...],
    edges: tuple[ChemicalEdge, ...],
    rank: int,
) -> str:
    site_keys = sorted(
        structure.sites[index].source_site_key or structure.sites[index].label
        for index in nodes
    )
    edge_keys = sorted(
        (
            structure.sites[edge.first].source_site_key or structure.sites[edge.first].label,
            structure.sites[edge.second].source_site_key or structure.sites[edge.second].label,
            edge.image,
        )
        for edge in edges
    )
    payload = json.dumps((site_keys, edge_keys, rank), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _periodic_component(
    nodes: tuple[int, ...], edges: tuple[ChemicalEdge, ...]
) -> tuple[int, tuple[Translation, ...]]:
    graph = nx.MultiGraph()
    graph.add_nodes_from(nodes)
    for edge in edges:
        graph.add_edge(
            edge.first,
            edge.second,
            first=edge.first,
            second=edge.second,
            translation=edge.image,
        )
    result = PeriodicPolyhedronGraph(graph).components()[0]
    closures = tuple(sorted(set(result.closure_translations)))
    return result.translation_rank, closures


def _ring_geometry(
    structure: CrystalStructure, cycle: tuple[int, ...]
) -> tuple[float, tuple[float, float, float], tuple[float, float, float]]:
    fractional = np.asarray([structure.sites[index].fractional for index in cycle], dtype=float)
    anchor = fractional[0]
    unwrapped = anchor + (fractional - anchor) - np.rint(fractional - anchor)
    cartesian = unwrapped @ structure.cell.matrix
    centroid_cartesian = cartesian.mean(axis=0)
    centered = cartesian - centroid_cartesian
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[-1]
    normal /= max(float(np.linalg.norm(normal)), 1e-15)
    distances = centered @ normal
    rms = float(np.sqrt(np.mean(distances * distances)))
    centroid_fractional = tuple(float(value % 1.0) for value in unwrapped.mean(axis=0))
    return rms, centroid_fractional, tuple(float(value) for value in normal)


def build_components(
    structure: CrystalStructure,
    bonds: BondLayerReport | tuple[ChemicalEdge, ...],
    *,
    maximum_ring_size: int = 12,
) -> ComponentReport:
    if maximum_ring_size < 3:
        raise ValueError("maximum_ring_size must be at least 3.")
    covalent = tuple(bonds.covalent if isinstance(bonds, BondLayerReport) else bonds)
    graph = nx.MultiGraph()
    for index, site in enumerate(structure.sites):
        elements = site_elements(site)
        try:
            is_metal = bool(elements) and all(Element(symbol).is_metal for symbol in elements)
        except ValueError:
            is_metal = False
        if not is_metal:
            graph.add_node(index)
    for edge in covalent:
        graph.add_edge(edge.first, edge.second, key=edge.id, edge=edge)

    components: list[MolecularComponent] = []
    rings: list[MolecularRing] = []
    pi_systems: list[PiSystem] = []
    for component_number, raw_nodes in enumerate(
        sorted(nx.connected_components(graph), key=lambda item: tuple(sorted(item))), start=1
    ):
        nodes = tuple(sorted(raw_nodes))
        component_edges = tuple(
            sorted(
                (data["edge"] for *_, data in graph.subgraph(nodes).edges(data=True, keys=True)),
                key=lambda edge: (edge.first, edge.second, edge.image, edge.id),
            )
        )
        rank, closures = _periodic_component(nodes, component_edges)
        component_id = f"M{component_number}"
        component = MolecularComponent(
            component_id,
            nodes,
            tuple(edge.id for edge in component_edges),
            rank,
            closures,
            _formula(structure, nodes),
            min((edge.confidence for edge in component_edges), default=1.0),
            _orbit_key(structure, nodes, component_edges, rank),
        )
        components.append(component)

        simple = nx.Graph()
        simple.add_nodes_from(nodes)
        simple.add_edges_from((edge.first, edge.second) for edge in component_edges)
        raw_cycles = nx.minimum_cycle_basis(simple)
        canonical_cycles = sorted(
            {
                _canonical_cycle(cycle)
                for cycle in raw_cycles
                if 3 <= len(cycle) <= maximum_ring_size
            }
        )
        confidence_by_pair = {
            frozenset((edge.first, edge.second)): edge.confidence for edge in component_edges
        }
        for cycle in canonical_cycles:
            ring_id = f"R{len(rings) + 1}"
            ring_confidence = min(
                confidence_by_pair.get(frozenset((cycle[index], cycle[(index + 1) % len(cycle)])), 0.0)
                for index in range(len(cycle))
            )
            rms, centroid, normal = _ring_geometry(structure, cycle)
            elements = {
                symbol
                for index in cycle
                for symbol in site_elements(structure.sites[index])[:1]
            }
            pi_capable = bool(elements) and elements <= _PI_ELEMENTS and rms <= 0.12
            warning = ("Ring contains uncertain bond evidence.",) if ring_confidence < 1.0 else ()
            rings.append(
                MolecularRing(
                    ring_id,
                    component_id,
                    cycle,
                    rms,
                    pi_capable,
                    ring_confidence,
                    warning,
                )
            )
            if pi_capable:
                pi_systems.append(
                    PiSystem(f"PI{len(pi_systems) + 1}", (ring_id,), centroid, normal, ring_confidence)
                )

    complete = bonds.complete if isinstance(bonds, BondLayerReport) else True
    warnings = bonds.warnings if isinstance(bonds, BondLayerReport) else ()
    return ComponentReport(tuple(components), tuple(rings), tuple(pi_systems), complete, warnings)


__all__ = [
    "ComponentReport",
    "MolecularComponent",
    "MolecularRing",
    "PiSystem",
    "build_components",
]
