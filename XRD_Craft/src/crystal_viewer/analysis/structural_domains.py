"""Chemically filtered, translation-aware structural domains."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

import networkx as nx

from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph

if TYPE_CHECKING:
    from crystal_viewer.analysis.hierarchy import (
        CoordinationPolyhedron,
        PolyhedronConnection,
    )
    from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence


@dataclass(frozen=True, slots=True)
class StructuralDomain:
    """One connected structural-polyhedron component in the periodic graph."""

    id: str
    polyhedron_ids: tuple[str, ...]
    atom_indices: tuple[int, ...]
    periodic_rank: int
    classification: str
    role_confidence: float
    nested_ring_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _identifier_key(identifier: str) -> tuple[int, int | str]:
    suffix = identifier[1:] if identifier.startswith("P") else identifier
    try:
        return (0, int(suffix))
    except ValueError:
        return (1, identifier)


def derive_structural_domains(
    polyhedra: Iterable[CoordinationPolyhedron],
    connections: Iterable[PolyhedronConnection],
    roles: Iterable[PolyhedronRoleEvidence],
) -> tuple[StructuralDomain, ...]:
    """Return periodic domains after removing interstitial/ambiguous centres.

    Translation labels remain attached to quotient-graph edges, so a domain
    crossing a unit-cell boundary is not split into unrelated finite pieces.
    """
    polyhedron_by_id = {item.id: item for item in polyhedra}
    role_items = tuple(roles)
    role_by_center = {item.center_index: item for item in role_items}
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
            for item in polyhedron_by_id.values()
        },
    )
    structural_ids = {
        item.id
        for item in polyhedron_by_id.values()
        if item.center_index in primary_centres
    }

    graph = nx.MultiGraph()
    graph.add_nodes_from(sorted(structural_ids, key=_identifier_key))
    for connection in connections:
        if connection.first not in structural_ids or connection.second not in structural_ids:
            continue
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

    components = sorted(
        PeriodicPolyhedronGraph(graph).components(),
        key=lambda item: min(_identifier_key(str(node)) for node in item.node_ids),
    )
    domains: list[StructuralDomain] = []
    for index, component in enumerate(components, start=1):
        identifiers = tuple(sorted((str(node) for node in component.node_ids), key=_identifier_key))
        members = [polyhedron_by_id[identifier] for identifier in identifiers]
        atom_indices = sorted(
            {
                atom_index
                for member in members
                for atom_index in (
                    member.center_index,
                    *(ligand.site_index for ligand in member.ligands),
                )
            }
        )
        evidence = [role_by_center[member.center_index] for member in members]
        confidence = math.fsum(item.confidence for item in evidence) / len(evidence)
        warnings = tuple(
            dict.fromkeys(warning for item in evidence for warning in item.warnings)
        )
        domains.append(
            StructuralDomain(
                id=f"D{index}",
                polyhedron_ids=identifiers,
                atom_indices=tuple(atom_indices),
                periodic_rank=component.translation_rank,
                classification=component.classification,
                role_confidence=confidence,
                warnings=warnings,
            )
        )
    return tuple(domains)


__all__ = ["StructuralDomain", "derive_structural_domains"]
