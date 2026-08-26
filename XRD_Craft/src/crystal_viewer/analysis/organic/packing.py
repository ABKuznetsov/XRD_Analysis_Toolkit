from __future__ import annotations

import hashlib
import math
from collections import deque
from dataclasses import dataclass

import networkx as nx
import numpy as np
from pymatgen.core import Element

from crystal_viewer.analysis.organic.components import ComponentReport
from crystal_viewer.analysis.organic.contacts import ContactKind, ContactReport
from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph
from crystal_viewer.core.chemistry import site_elements
from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class PackingSettings:
    interaction_kinds: frozenset[ContactKind] = frozenset(
        {ContactKind.HYDROGEN_BOND, ContactKind.PI_STACK, ContactKind.CH_PI}
    )
    grid_spacing: float = 0.35
    maximum_grid_points: int = 2_000_000

    def validate(self) -> None:
        if not math.isfinite(self.grid_spacing) or self.grid_spacing <= 0.0:
            raise ValueError("grid spacing must be finite and positive")
        if self.maximum_grid_points <= 0:
            raise ValueError("maximum_grid_points must be positive")


@dataclass(frozen=True, slots=True)
class PackingAssembly:
    id: str
    component_ids: tuple[str, ...]
    contact_ids: tuple[str, ...]
    periodic_rank: int
    classification: str
    orbit_key: str


@dataclass(frozen=True, slots=True)
class VoidRegion:
    id: str
    volume_fraction: float
    periodic_rank: int
    classification: str = "geometric void"


@dataclass(frozen=True, slots=True)
class PackingReport:
    assemblies: tuple[PackingAssembly, ...]
    voids: tuple[VoidRegion, ...]
    effective_grid_spacing: float
    complete: bool = True
    warnings: tuple[str, ...] = ()
    method_version: str = "organic-packing-v1"


def _assembly_classification(rank: int) -> str:
    return ("finite motif", "chain", "layer", "3D assembly")[min(3, rank)]


def _assemblies(
    components: ComponentReport,
    contacts: ContactReport,
    settings: PackingSettings,
) -> tuple[PackingAssembly, ...]:
    allowed = tuple(
        contact
        for contact in contacts.contacts
        if contact.kind in settings.interaction_kinds and contact.confidence >= 0.75
    )
    graph = nx.MultiGraph()
    component_ids = {component.id for component in components.components}
    for contact in allowed:
        if not {contact.first_component_id, contact.second_component_id} <= component_ids:
            continue
        graph.add_edge(
            contact.first_component_id,
            contact.second_component_id,
            first=contact.first_component_id,
            second=contact.second_component_id,
            translation=contact.image,
            contact_id=contact.id,
        )
    results: list[PackingAssembly] = []
    for number, nodes in enumerate(nx.connected_components(graph), start=1):
        node_ids = tuple(sorted(nodes))
        subgraph = graph.subgraph(nodes)
        contact_ids = tuple(sorted(data["contact_id"] for *_, data in subgraph.edges(data=True, keys=True)))
        periodic = PeriodicPolyhedronGraph(subgraph).components()[0]
        payload = repr((node_ids, contact_ids, periodic.translation_rank)).encode("utf-8")
        results.append(
            PackingAssembly(
                f"PA{number}",
                node_ids,
                contact_ids,
                periodic.translation_rank,
                _assembly_classification(periodic.translation_rank),
                hashlib.sha256(payload).hexdigest()[:20],
            )
        )
    return tuple(results)


def _vdw_radius(structure: CrystalStructure, index: int) -> float:
    symbols = site_elements(structure.sites[index])
    radii: list[float] = []
    for symbol in symbols:
        try:
            radius = Element(symbol).van_der_waals_radius
            if radius is not None:
                radii.append(float(radius))
        except (TypeError, ValueError):
            pass
    return max(radii, default=1.8)


def _grid_shape(
    structure: CrystalStructure, settings: PackingSettings
) -> tuple[tuple[int, int, int], float, bool]:
    lengths = np.linalg.norm(structure.cell.matrix, axis=1)
    shape = np.maximum(1, np.floor(lengths / settings.grid_spacing).astype(int))
    reduced = False
    points = int(np.prod(shape, dtype=np.int64))
    if points > settings.maximum_grid_points:
        scale = (points / settings.maximum_grid_points) ** (1.0 / 3.0)
        shape = np.maximum(1, np.floor(shape / scale).astype(int))
        while int(np.prod(shape, dtype=np.int64)) > settings.maximum_grid_points:
            shape[int(np.argmax(shape))] -= 1
        reduced = True
    effective = float(np.max(lengths / shape))
    return tuple(int(value) for value in shape), effective, reduced


def _voids(
    structure: CrystalStructure, settings: PackingSettings
) -> tuple[tuple[VoidRegion, ...], float, tuple[str, ...]]:
    shape, effective, reduced = _grid_shape(structure, settings)
    axes = [(np.arange(size, dtype=float) + 0.5) / size for size in shape]
    fractional = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    occupied = np.zeros(shape, dtype=bool)
    for index, site in enumerate(structure.sites):
        delta = fractional - np.asarray(site.fractional, dtype=float)
        delta -= np.rint(delta)
        cartesian = delta @ structure.cell.matrix
        occupied |= np.einsum("...i,...i->...", cartesian, cartesian) <= _vdw_radius(
            structure, index
        ) ** 2

    visited = np.zeros(shape, dtype=bool)
    potential = np.zeros((*shape, 3), dtype=np.int32)
    regions: list[tuple[int, int]] = []
    directions = ((0, -1), (0, 1), (1, -1), (1, 1), (2, -1), (2, 1))
    for raw_start in np.argwhere(~occupied & ~visited):
        start = tuple(int(value) for value in raw_start)
        if visited[start]:
            continue
        visited[start] = True
        queue = deque([start])
        count = 0
        closures: list[tuple[int, int, int]] = []
        while queue:
            current = queue.popleft()
            count += 1
            for axis, step in directions:
                raw = list(current)
                raw[axis] += step
                translation = np.zeros(3, dtype=np.int32)
                if raw[axis] < 0:
                    raw[axis] += shape[axis]
                    translation[axis] = -1
                elif raw[axis] >= shape[axis]:
                    raw[axis] -= shape[axis]
                    translation[axis] = 1
                neighbour = tuple(raw)
                if occupied[neighbour]:
                    continue
                candidate = potential[current] + translation
                if not visited[neighbour]:
                    visited[neighbour] = True
                    potential[neighbour] = candidate
                    queue.append(neighbour)
                else:
                    closure = candidate - potential[neighbour]
                    if np.any(closure):
                        closures.append(tuple(int(value) for value in closure))
        rank = int(np.linalg.matrix_rank(np.asarray(closures, dtype=float))) if closures else 0
        regions.append((count, rank))

    total = int(np.prod(shape, dtype=np.int64))
    regions.sort(key=lambda item: (-item[0], -item[1]))
    result = tuple(
        VoidRegion(f"V{index}", count / total, rank)
        for index, (count, rank) in enumerate(regions, start=1)
    )
    warnings = (
        (f"Void grid was coarsened to {effective:.3f} Å to respect the point limit.",)
        if reduced
        else ()
    )
    return result, effective, warnings


def build_packing(
    structure: CrystalStructure,
    components: ComponentReport,
    contacts: ContactReport,
    settings: PackingSettings = PackingSettings(),
) -> PackingReport:
    settings.validate()
    assemblies = _assemblies(components, contacts, settings)
    voids, effective, void_warnings = _voids(structure, settings)
    warnings = tuple(dict.fromkeys((*components.warnings, *contacts.warnings, *void_warnings)))
    return PackingReport(
        assemblies,
        voids,
        effective,
        components.complete and contacts.complete,
        warnings,
    )


__all__ = [
    "PackingAssembly",
    "PackingReport",
    "PackingSettings",
    "VoidRegion",
    "build_packing",
]
