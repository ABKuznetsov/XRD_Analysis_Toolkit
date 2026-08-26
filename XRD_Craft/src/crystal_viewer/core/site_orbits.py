from __future__ import annotations

from collections import defaultdict

import numpy as np

from crystal_viewer.core.model import CrystalStructure
from crystal_viewer.core.symmetry import apply_operation


def site_orbit_key(label: str) -> str:
    """Return the asymmetric-site label used to generate a symmetry copy."""
    return str(label).split("·", 1)[0]


def site_orbits(structure: CrystalStructure) -> dict[str, tuple[int, ...]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for index, site in enumerate(structure.sites):
        groups[site_orbit_key(site.label)].append(index)
    return {key: tuple(indices) for key, indices in groups.items()}


def polyhedron_orbits(document) -> dict[str, tuple[str, ...]]:
    groups: dict[str, list[str]] = defaultdict(list)
    sites = document.structure.sites
    for polyhedron in document.hierarchy.polyhedra:
        key = site_orbit_key(sites[polyhedron.center_index].label)
        groups[key].append(polyhedron.id)
    return {key: tuple(ids) for key, ids in groups.items()}


def bond_families(document) -> tuple[tuple[str, str], ...]:
    """Return unique bond types expressed through asymmetric-site positions."""
    pairs: set[tuple[str, str]] = set()
    periodic_bonds = getattr(document, "periodic_bonds", None)
    if periodic_bonds is None and document.structural_analysis is not None:
        periodic_bonds = document.structural_analysis.periodic_bonds
    if periodic_bonds is not None:
        for bond in periodic_bonds.bonds:
            first = document.structure.sites[bond.first].element
            second = document.structure.sites[bond.second].element
            pairs.add(tuple(sorted((first, second))))
    if not pairs:
        for polyhedron in document.hierarchy.polyhedra:
            first = document.structure.sites[polyhedron.center_index].element
            for ligand in polyhedron.ligands:
                second = document.structure.sites[ligand.site_index].element
                pairs.add(tuple(sorted((first, second))))
    return tuple(sorted(pairs))


def hierarchy_object_orbits(document, objects) -> tuple[tuple[str, ...], ...]:
    """Group hierarchy objects by space-group action on their center sites."""
    values = tuple(objects)
    if not values:
        return ()
    polyhedra = {item.id: item for item in document.hierarchy.polyhedra}
    anchors = tuple(
        frozenset(
            polyhedra[identifier].center_index
            for identifier in item.polyhedron_ids
            if identifier in polyhedra
        )
        for item in values
    )
    signatures = tuple(
        (
            item.classification,
            int(getattr(item, "periodic_rank", -1)),
            len(anchor),
        )
        for item, anchor in zip(values, anchors, strict=True)
    )
    return symmetry_object_orbits(
        document.structure,
        tuple(item.id for item in values),
        anchors,
        signatures,
    )


def connector_orbits(document) -> tuple[tuple[str, ...], ...]:
    """Group shared-site connectors by kind and crystallographic position."""
    values = tuple(document.hierarchy.connectors)
    if not values:
        return ()
    anchors = tuple(frozenset(item.ligand_indices) for item in values)
    signatures = tuple((item.kind, len(anchor)) for item, anchor in zip(values, anchors, strict=True))
    return symmetry_object_orbits(
        document.structure,
        tuple(item.id for item in values),
        anchors,
        signatures,
    )


def symmetry_object_orbits(
    structure: CrystalStructure,
    identifiers: tuple[str, ...],
    anchors: tuple[frozenset[int], ...],
    signatures: tuple[object, ...],
) -> tuple[tuple[str, ...], ...]:
    parents = list(range(len(identifiers)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parents[second_root] = first_root

    candidates: dict[tuple[object, frozenset[int]], list[int]] = defaultdict(list)
    for index, (signature, anchor) in enumerate(
        zip(signatures, anchors, strict=True)
    ):
        candidates[(signature, anchor)].append(index)
    site_groups: dict[str, list[int]] = defaultdict(list)
    for index, site in enumerate(structure.sites):
        site_groups[site_orbit_key(site.label)].append(index)
    operations = tuple(structure.symmetry_operations) or ("x,y,z",)
    for operation in operations:
        site_map: dict[int, int] = {}
        try:
            targets = tuple(
                np.asarray(apply_operation(operation, site.fractional), dtype=float)
                for site in structure.sites
            )
        except (TypeError, ValueError):
            continue
        for index, (site, target) in enumerate(
            zip(structure.sites, targets, strict=True)
        ):
            matches = site_groups[site_orbit_key(site.label)]
            best = min(
                matches,
                key=lambda candidate: float(
                    np.max(
                        np.abs(
                            (target - np.asarray(structure.sites[candidate].fractional))
                            - np.rint(
                                target
                                - np.asarray(structure.sites[candidate].fractional)
                            )
                        )
                    )
                ),
            )
            delta = target - np.asarray(structure.sites[best].fractional)
            if float(np.max(np.abs(delta - np.rint(delta)))) <= 1e-4:
                site_map[index] = best
        for index, anchor in enumerate(anchors):
            if not anchor or not anchor.issubset(site_map):
                continue
            transformed = frozenset(site_map[value] for value in anchor)
            for equivalent in candidates.get((signatures[index], transformed), ()):
                union(index, equivalent)
    grouped: dict[int, list[str]] = {}
    for index, identifier in enumerate(identifiers):
        grouped.setdefault(find(index), []).append(identifier)
    return tuple(tuple(ids) for ids in grouped.values())
