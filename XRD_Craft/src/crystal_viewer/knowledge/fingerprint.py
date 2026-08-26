from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict

import networkx as nx

from crystal_viewer.knowledge.model import MotifFingerprint


_OCCUPANCY_SCALE = 1_000_000
_GEOMETRY_SCALE = 10_000


def _canonical_translation(values) -> tuple[int, int, int]:
    translation = tuple(int(value) for value in values)
    reverse = tuple(-value for value in translation)
    return min(translation, reverse)


def _site_composition(site) -> tuple[tuple[str, int], ...]:
    totals: dict[str, float] = defaultdict(float)
    for component in site.components:
        occupancy = float(component.occupancy)
        if math.isfinite(occupancy) and occupancy > 0.0:
            totals[str(component.element)] += occupancy
    return tuple(
        (element, int(round(value * _OCCUPANCY_SCALE)))
        for element, value in sorted(totals.items())
    )


def _ligand_composition(structure, polyhedron) -> tuple[tuple[str, int], ...]:
    totals: dict[str, float] = defaultdict(float)
    if not polyhedron.ligands:
        return ()
    for ligand in polyhedron.ligands:
        for element, occupancy in _site_composition(structure.sites[ligand.site_index]):
            totals[element] += occupancy / _OCCUPANCY_SCALE
    divisor = len(polyhedron.ligands)
    return tuple(
        (element, int(round(value / divisor * _OCCUPANCY_SCALE)))
        for element, value in sorted(totals.items())
    )


def _geometry_signature(polyhedron) -> tuple[tuple[int, ...], int, int]:
    lengths = tuple(float(value) for value in polyhedron.bond_lengths)
    mean = math.fsum(lengths) / len(lengths) if lengths else 0.0
    ratios = (
        tuple(sorted(int(round(value / mean * _GEOMETRY_SCALE)) for value in lengths))
        if mean > 0.0 and math.isfinite(mean)
        else ()
    )
    distortion = int(round(float(polyhedron.distortion) * _GEOMETRY_SCALE))
    angle = int(round(float(polyhedron.angle_dispersion) * _GEOMETRY_SCALE))
    return ratios, distortion, angle


def _topology_label(polyhedron, ring_sizes: tuple[int, ...]) -> str:
    rings = ",".join(str(value) for value in ring_sizes) or "-"
    return f"V|cn={polyhedron.coordination_number}|rings={rings}"


def _expanded_topology_hash(polyhedra, connections, ring_by_id) -> str:
    graph = nx.Graph()
    for polyhedron in polyhedra:
        graph.add_node(
            ("vertex", polyhedron.id),
            label=_topology_label(polyhedron, ring_by_id.get(polyhedron.id, ())),
        )
    for index, connection in enumerate(connections):
        translation = _canonical_translation(connection.translation)
        edge_node = ("edge", index)
        graph.add_node(
            edge_node,
            label=(
                f"E|{connection.kind}|{translation}|"
                f"shared={len(connection.shared_ligands)}|"
                f"loop={connection.first == connection.second}"
            ),
        )
        graph.add_edge(edge_node, ("vertex", connection.first))
        graph.add_edge(edge_node, ("vertex", connection.second))
    return nx.weisfeiler_lehman_graph_hash(graph, node_attr="label", iterations=5)


def build_motif_fingerprint(document, domain_id: str) -> MotifFingerprint:
    domain = next(
        item for item in document.hierarchy.structural_domains if item.id == domain_id
    )
    identifiers = frozenset(domain.polyhedron_ids)
    polyhedra = tuple(
        item for item in document.hierarchy.polyhedra if item.id in identifiers
    )
    if len(polyhedra) != len(identifiers):
        missing = sorted(identifiers - {item.id for item in polyhedra})
        raise ValueError(f"domain references missing polyhedra: {missing}")
    connections = tuple(
        item
        for item in document.hierarchy.polyhedron_connections
        if item.first in identifiers and item.second in identifiers
    )
    ring_by_id: dict[str, list[int]] = defaultdict(list)
    analysis = getattr(document, "structural_analysis", None)
    for ring in getattr(analysis, "rings", ()):
        members = tuple(str(value) for value in ring.member_ids)
        if set(members).issubset(identifiers):
            for identifier in members:
                ring_by_id[identifier].append(int(ring.size))
    ring_sizes = {
        identifier: tuple(sorted(values)) for identifier, values in ring_by_id.items()
    }

    node_signatures = []
    topology_labels: dict[str, str] = {}
    for polyhedron in polyhedra:
        rings = ring_sizes.get(polyhedron.id, ())
        topology_labels[polyhedron.id] = _topology_label(polyhedron, rings)
        ratios, distortion, angle = _geometry_signature(polyhedron)
        node_signatures.append(
            (
                "node",
                polyhedron.coordination_number,
                _site_composition(document.structure.sites[polyhedron.center_index]),
                _ligand_composition(document.structure, polyhedron),
                ratios,
                distortion,
                angle,
                rings,
            )
        )

    edge_signatures = []
    for connection in connections:
        endpoints = tuple(
            sorted(
                (topology_labels[connection.first], topology_labels[connection.second])
            )
        )
        edge_signatures.append(
            (
                endpoints[0],
                endpoints[1],
                str(connection.kind),
                _canonical_translation(connection.translation),
                len(connection.shared_ligands),
            )
        )

    return MotifFingerprint(
        algorithm="periodic-domain-fingerprint-v1",
        periodic_rank=int(domain.periodic_rank),
        nodes=tuple(sorted(node_signatures, key=repr)),
        edges=tuple(sorted(edge_signatures, key=repr)),
        topology_digest=_expanded_topology_hash(
            polyhedra,
            connections,
            ring_sizes,
        ),
    )


def fingerprint_digest(fingerprint: MotifFingerprint) -> str:
    payload = json.dumps(
        asdict(fingerprint),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["build_motif_fingerprint", "fingerprint_digest"]
