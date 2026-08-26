from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from typing import TYPE_CHECKING

import networkx as nx
import numpy as np

from crystal_viewer.core.model import CrystalStructure
from crystal_viewer.core.chemistry import COVALENT_RADII

if TYPE_CHECKING:
    from crystal_viewer.analysis.structural_domains import StructuralDomain
    from crystal_viewer.analysis.structural_analysis import StructuralAnalysis
    from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence

ANION_ELEMENTS = frozenset({"O", "F", "Cl", "Br", "I", "S", "Se", "N"})

COMMON_OXIDATION_STATES = {
    "B": 3, "Si": 4, "Al": 3, "Al/Si": 3.5, "Mg": 2, "Ca": 2, "Na": 1, "K": 1,
    "Sr": 2, "Ba": 2, "Y": 3, "Tb": 3, "Dy": 3, "Ti": 4, "Zr": 4,
    "Nb": 5, "Mo": 6, "W": 6, "P": 5, "Fe": 3,
}

COORDINATION_IONIC_RADII = {
    ("Li", 4): 0.59,
    ("Li", 6): 0.76,
    ("Li", 8): 0.92,
    ("B", 3): 0.15,
    ("Si", 4): 0.26,
    ("Al", 4): 0.39,
    ("Al/Si", 4): 0.325,
    ("Al", 6): 0.535,
    ("Mg", 6): 0.72,
    ("Ti", 6): 0.605,
    ("Zr", 6): 0.72,
    ("Na", 6): 1.02,
    ("Na", 8): 1.18,
    ("Ca", 6): 1.00,
    ("Ca", 8): 1.12,
    ("K", 8): 1.51,
    ("K", 9): 1.55,
    ("Sr", 8): 1.26,
    ("Sr", 9): 1.31,
    ("Ba", 8): 1.42,
    ("Y", 6): 0.90,
    ("Tb", 6): 0.923,
    ("Dy", 6): 0.912,
}

# Highly coordinated electropositive cations normally occupy cavities between
# anionic motifs. Their coordination polyhedra are useful display objects, but
# must not glue a whole motif graph together through shared ligands.
INTERSTITIAL_ELEMENTS = frozenset({"Li", "Na", "K", "Rb", "Cs", "Ca", "Sr", "Ba"})


def polyhedron_rigidity_index(polyhedron: "CoordinationPolyhedron") -> float:
    """Chemical rigidity prior used by Structure Builder: |V| / (CN · r_ion)."""
    coordination = max(polyhedron.coordination_number, 1)
    oxidation = abs(float(COMMON_OXIDATION_STATES.get(polyhedron.center_element, 1)))
    radius = COORDINATION_IONIC_RADII.get(
        (polyhedron.center_element, coordination),
        COVALENT_RADII.get(polyhedron.center_element, 1.0),
    )
    return oxidation / (coordination * max(float(radius), 1e-6))


def normalized_rigidity(index: float) -> float:
    """Map the unbounded chemical index to a transparent 0–1 display scale."""
    index = max(float(index), 0.0)
    return index / (1.0 + index)


class HierarchyLevel(StrEnum):
    SITES = "sites"
    ATOMS = "atoms"
    BONDS = "bonds"
    POLYHEDRA = "polyhedra"
    STRUCTURAL_UNITS = "structural_units"
    RIGID_BLOCKS = "rigid_blocks"
    FRAMEWORK = "framework"
    TOPOLOGY = "topology"


@dataclass(frozen=True, slots=True)
class PeriodicSiteRef:
    site_index: int
    image: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True, slots=True)
class CoordinationPolyhedron:
    id: str
    center_index: int
    center_element: str
    ligand_element: str
    ligands: tuple[PeriodicSiteRef, ...]
    bond_lengths: tuple[float, ...]
    vertex_coordinates: tuple[tuple[float, float, float], ...]
    distortion: float
    angle_dispersion: float

    @property
    def coordination_number(self) -> int:
        return len(self.ligands)

    @property
    def type_name(self) -> str:
        center = f"({self.center_element})" if "/" in self.center_element else self.center_element
        return f"{center}{self.ligand_element}{self.coordination_number}"


@dataclass(frozen=True, slots=True)
class PolyhedronConnection:
    first: str
    second: str
    shared_ligands: tuple[PeriodicSiteRef, ...]
    kind: str
    flexible: bool
    translation: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True, slots=True)
class StructuralUnit:
    id: str
    polyhedron_ids: tuple[str, ...]
    atom_indices: tuple[int, ...]
    classification: str
    periodic_rank: int = 0


@dataclass(frozen=True, slots=True)
class StructuralBlock:
    id: str
    polyhedron_ids: tuple[str, ...]
    atom_indices: tuple[int, ...]
    classification: str
    rigidity_score: float
    rigidity_index: float


@dataclass(frozen=True, slots=True)
class FlexibleConnector:
    id: str
    first_block: str
    second_block: str
    first_polyhedron: str
    second_polyhedron: str
    kind: str
    ligand_indices: tuple[int, ...]
    pivot_coordinates: tuple[tuple[float, float, float], ...]


@dataclass(slots=True)
class HierarchyReport:
    polyhedra: list[CoordinationPolyhedron] = field(default_factory=list)
    polyhedron_connections: list[PolyhedronConnection] = field(default_factory=list)
    structural_units: list[StructuralUnit] = field(default_factory=list)
    blocks: list[StructuralBlock] = field(default_factory=list)
    connectors: list[FlexibleConnector] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    structural_domains: list[StructuralDomain] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        return {
            "polyhedra": len(self.polyhedra),
            "structural_units": len(self.structural_units),
            "structural_blocks": len(self.blocks),
            "flexible_connectors": len(self.connectors),
        }


class HierarchyAnalyzer:
    """
    First-pass hierarchy detector.

    The deliberate geometric assumption is that edge/face-sharing polyhedra
    form a rigid-block candidate, while a corner-shared atom is a possible
    rotational pivot. Only a structure series or a RUM calculation can promote
    that geometric candidate to an experimentally supported mechanism.
    """

    def __init__(
        self,
        bond_tolerance: float = 1.22,
        min_coordination: int = 3,
        rigid_shared_ligands: int = 2,
    ) -> None:
        self.bond_tolerance = bond_tolerance
        self.min_coordination = min_coordination
        self.rigid_shared_ligands = rigid_shared_ligands

    def analyze(
        self,
        structure: CrystalStructure,
        structural_analysis: "StructuralAnalysis | None" = None,
        *,
        coordination_environments=None,
        polyhedron_roles: "tuple[PolyhedronRoleEvidence, ...] | None" = None,
    ) -> HierarchyReport:
        shared_environments = (
            structural_analysis.coordination_environments
            if structural_analysis is not None
            else coordination_environments
        )
        polyhedra = (
            self.detect_polyhedra_from_environments(
                structure,
                shared_environments,
            )
            if shared_environments is not None
            else self.detect_polyhedra(structure)
        )
        connections = self.connect_polyhedra(polyhedra)
        role_evidence = (
            structural_analysis.polyhedron_roles
            if structural_analysis is not None
            else polyhedron_roles
        )
        return self.assemble(
            structure,
            polyhedra,
            connections,
            role_evidence=role_evidence,
        )

    def assemble(
        self,
        structure: CrystalStructure,
        polyhedra: list[CoordinationPolyhedron],
        connections: list[PolyhedronConnection],
        *,
        role_evidence: "tuple[PolyhedronRoleEvidence, ...] | None" = None,
    ) -> HierarchyReport:
        """Build upper hierarchy levels from already calculated polyhedra."""
        from crystal_viewer.analysis.structural_domains import derive_structural_domains

        domains = (
            list(derive_structural_domains(polyhedra, connections, role_evidence))
            if role_evidence is not None
            else []
        )
        structural_units = self.build_structural_units(
            polyhedra,
            connections,
            role_evidence=role_evidence,
            structural_domains=domains,
        )
        blocks = self.build_blocks(polyhedra, structural_units)
        connectors = self.build_connectors(structure, polyhedra, connections, blocks)
        warnings = []
        if not polyhedra:
            warnings.append("No coordination polyhedra detected; check oxidation/anion assignment or bond tolerance.")
        if len(polyhedra) and not connections:
            warnings.append("Polyhedra are isolated in the current unit-cell representation.")
        return HierarchyReport(
            polyhedra=polyhedra,
            polyhedron_connections=connections,
            structural_units=structural_units,
            blocks=blocks,
            connectors=connectors,
            warnings=warnings,
            structural_domains=domains,
        )

    def detect_polyhedra_from_environments(
        self,
        structure: CrystalStructure,
        environments,
    ) -> list[CoordinationPolyhedron]:
        """Project the shared primary bond memberships into hierarchy objects."""
        polyhedra: list[CoordinationPolyhedron] = []
        matrix = structure.cell.matrix
        for environment in environments:
            if len(environment.neighbor_indices) < self.min_coordination:
                continue
            center_index = environment.center_index
            center = structure.sites[center_index]
            center_frac = np.asarray(center.fractional, dtype=float)
            center_cart = structure.cell.frac_to_cart(center_frac)
            ligands: list[PeriodicSiteRef] = []
            vertices: list[tuple[float, float, float]] = []
            lengths: list[float] = []
            for ligand_index, image in zip(
                environment.neighbor_indices,
                environment.neighbor_images,
                strict=True,
            ):
                ligand = structure.sites[ligand_index]
                delta = (
                    np.asarray(ligand.fractional, dtype=float)
                    + np.asarray(image, dtype=float)
                    - center_frac
                )
                vertex = center_cart + delta @ matrix
                ligands.append(PeriodicSiteRef(ligand_index, image))
                vertices.append(tuple(float(value) for value in vertex))
                lengths.append(float(np.linalg.norm(delta @ matrix)))
            vectors = np.asarray(vertices, dtype=float) - center_cart
            unit_vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1)[:, None], 1e-12)
            angles = [
                np.degrees(np.arccos(np.clip(np.dot(first, second), -1.0, 1.0)))
                for first, second in combinations(unit_vectors, 2)
            ]
            polyhedra.append(
                CoordinationPolyhedron(
                    id=f"P{len(polyhedra) + 1}",
                    center_index=center_index,
                    center_element=center.element,
                    ligand_element=structure.sites[environment.neighbor_indices[0]].element,
                    ligands=tuple(ligands),
                    bond_lengths=tuple(lengths),
                    vertex_coordinates=tuple(vertices),
                    distortion=float(np.std(lengths) / np.mean(lengths)) if np.mean(lengths) else 0.0,
                    angle_dispersion=(
                        float(np.std(angles) / np.mean(angles))
                        if angles and np.mean(angles)
                        else 0.0
                    ),
                )
            )
        return polyhedra

    def detect_polyhedra(self, structure: CrystalStructure) -> list[CoordinationPolyhedron]:
        matrix = structure.cell.matrix
        polyhedra = []
        for center_index, center in enumerate(structure.sites):
            if center.element in ANION_ELEMENTS:
                continue
            center_frac = np.asarray(center.fractional, dtype=float)
            center_cart = structure.cell.frac_to_cart(center_frac)
            candidates: list[tuple[float, PeriodicSiteRef, tuple[float, float, float]]] = []
            for ligand_index, ligand in enumerate(structure.sites):
                if ligand.element not in ANION_ELEMENTS:
                    continue
                raw_delta = np.asarray(ligand.fractional, dtype=float) - center_frac
                image = -np.rint(raw_delta).astype(int)
                delta = raw_delta + image
                distance = float(np.linalg.norm(delta @ matrix))
                cutoff = (
                    COVALENT_RADII.get(center.element, 1.0)
                    + COVALENT_RADII.get(ligand.element, 0.7)
                ) * self.bond_tolerance
                if 0.35 < distance <= cutoff:
                    vertex = tuple(float(value) for value in center_cart + delta @ matrix)
                    candidates.append((distance, PeriodicSiteRef(ligand_index, tuple(map(int, image))), vertex))
            if len(candidates) < self.min_coordination:
                continue
            candidates.sort(key=lambda item: item[0])
            lengths = np.asarray([item[0] for item in candidates])
            distortion = float(np.std(lengths) / np.mean(lengths)) if np.mean(lengths) else 0.0
            vectors = np.asarray([item[2] for item in candidates], dtype=float) - center_cart
            unit_vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1)[:, None], 1e-12)
            angles = [
                np.degrees(np.arccos(np.clip(np.dot(first, second), -1.0, 1.0)))
                for first, second in combinations(unit_vectors, 2)
            ]
            angle_dispersion = (
                float(np.std(angles) / np.mean(angles))
                if angles and np.mean(angles)
                else 0.0
            )
            polyhedra.append(
                CoordinationPolyhedron(
                    id=f"P{len(polyhedra) + 1}",
                    center_index=center_index,
                    center_element=center.element,
                    ligand_element=structure.sites[candidates[0][1].site_index].element,
                    ligands=tuple(item[1] for item in candidates),
                    bond_lengths=tuple(float(item[0]) for item in candidates),
                    vertex_coordinates=tuple(item[2] for item in candidates),
                    distortion=distortion,
                    angle_dispersion=angle_dispersion,
                )
            )
        return polyhedra

    def connect_polyhedra(
        self,
        polyhedra: list[CoordinationPolyhedron],
    ) -> list[PolyhedronConnection]:
        connections = []
        for first, second in combinations(polyhedra, 2):
            # The graph is a quotient by lattice translations. Requiring the
            # same image misses T-O-T links crossing a unit-cell boundary.
            shared_indices = sorted(
                {ligand.site_index for ligand in first.ligands}
                & {ligand.site_index for ligand in second.ligands}
            )
            first_by_index = {ligand.site_index: ligand for ligand in first.ligands}
            second_by_index = {ligand.site_index: ligand for ligand in second.ligands}
            shared_by_translation: dict[tuple[int, int, int], list[PeriodicSiteRef]] = {}
            for index in shared_indices:
                first_ligand = first_by_index[index]
                second_ligand = second_by_index[index]
                translation = tuple(
                    int(first_image - second_image)
                    for first_image, second_image in zip(
                        first_ligand.image,
                        second_ligand.image,
                        strict=True,
                    )
                )
                shared_by_translation.setdefault(translation, []).append(first_ligand)
            if not shared_by_translation:
                continue
            for translation, shared_ligands in shared_by_translation.items():
                shared = tuple(shared_ligands)
                count = len(shared)
                kind = "corner" if count == 1 else "edge" if count == 2 else "face"
                connections.append(
                    PolyhedronConnection(
                        first=first.id,
                        second=second.id,
                        shared_ligands=shared,
                        kind=kind,
                        flexible=count < self.rigid_shared_ligands,
                        translation=translation,
                    )
                )
        return connections

    def build_blocks(
        self,
        polyhedra: list[CoordinationPolyhedron],
        structural_units: list[StructuralUnit],
    ) -> list[StructuralBlock]:
        """Promote chemical motifs to the initial rigid-body DOF candidates."""
        lookup = {polyhedron.id: polyhedron for polyhedron in polyhedra}
        blocks = []
        block_members = [
            (unit, ids)
            for unit in structural_units
            for ids in (
                tuple((identifier,) for identifier in unit.polyhedron_ids)
                if unit.periodic_rank > 0 and len(unit.polyhedron_ids) > 2
                else (unit.polyhedron_ids,)
            )
        ]
        for number, (unit, ids) in enumerate(block_members, start=1):
            rigidity_indices = []
            for polyhedron_id in ids:
                polyhedron = lookup[polyhedron_id]
                rigidity_indices.append(polyhedron_rigidity_index(polyhedron))
            mean_index = float(np.mean(rigidity_indices)) if rigidity_indices else 0.0
            score = (
                float(np.mean([normalized_rigidity(value) for value in rigidity_indices]))
                if rigidity_indices
                else 0.0
            )
            blocks.append(
                StructuralBlock(
                    id=f"RB{number}",
                    polyhedron_ids=ids,
                    atom_indices=tuple(
                        sorted(
                            {
                                atom_index
                                for identifier in ids
                                for atom_index in (
                                    lookup[identifier].center_index,
                                    *(item.site_index for item in lookup[identifier].ligands),
                                )
                            }
                        )
                    ),
                    classification=unit.classification,
                    rigidity_score=score,
                    rigidity_index=mean_index,
                )
            )
        return blocks

    def build_structural_units(
        self,
        polyhedra: list[CoordinationPolyhedron],
        connections: list[PolyhedronConnection],
        *,
        role_evidence: "tuple[PolyhedronRoleEvidence, ...] | None" = None,
        structural_domains: "list[StructuralDomain] | None" = None,
    ) -> list[StructuralUnit]:
        """Extract chemical motifs without letting interstitial cations glue them."""
        from crystal_viewer.analysis.periodic_graph import PeriodicPolyhedronGraph
        from crystal_viewer.analysis.rings import RingSearchLimits, find_shortest_path_rings

        graph = nx.MultiGraph()
        lookup = {polyhedron.id: polyhedron for polyhedron in polyhedra}
        evidence_by_center = {
            item.center_index: item for item in (role_evidence or ())
        }
        role_by_center = {
            center_index: item.role for center_index, item in evidence_by_center.items()
        }
        if role_evidence is not None:
            from crystal_viewer.analysis.structural_roles import primary_motif_center_indices

            primary_centres = primary_motif_center_indices(
                role_evidence,
                {
                    item.center_index: frozenset(
                        {
                            *(f"element:{part}" for part in item.center_element.split("/")),
                            f"coordination:{item.ligand_element}:{item.coordination_number}",
                        }
                    )
                    for item in polyhedra
                },
            )
        else:
            primary_centres = frozenset()
        motif_polyhedra = [
            polyhedron
            for polyhedron in polyhedra
            if (
                polyhedron.center_index in primary_centres
                if role_evidence is not None
                else not self.is_interstitial_polyhedron(polyhedron)
            )
        ]
        graph.add_nodes_from(polyhedron.id for polyhedron in motif_polyhedra)
        for edge in connections:
            if edge.first not in graph or edge.second not in graph:
                continue
            graph.add_edge(
                edge.first,
                edge.second,
                first=edge.first,
                second=edge.second,
                translation=edge.translation,
                kind=edge.kind,
                shared_sites=tuple(item.site_index for item in edge.shared_ligands),
            )

        raw_units: list[tuple[tuple[str, ...], str, int]] = []

        components = PeriodicPolyhedronGraph(graph).components()
        for component in components:
            ids = tuple(str(value) for value in component.node_ids)
            component_graph = graph.subgraph(component.node_ids).copy()
            ring_result = find_shortest_path_rings(
                component_graph,
                RingSearchLimits(maximum_ring_size=12, maximum_states=50_000, maximum_seconds=5.0),
            )
            selected_rings = []
            claimed: set[str] = set()
            for ring in sorted(ring_result.rings, key=lambda item: (item.size, item.member_ids)):
                ring_ids = tuple(str(value) for value in ring.member_ids)
                if claimed.intersection(ring_ids):
                    continue
                claimed.update(ring_ids)
                selected_rings.append((ring, ring_ids))
            # A cycle embedded in a larger periodic net is still a useful
            # candidate, but it is not a primary chemical partition unless a
            # deterministic set of rings covers the full component.
            if selected_rings and claimed == set(ids):
                for ring, ring_ids in selected_rings:
                    composition = self.structural_unit_composition(ring_ids, lookup)
                    raw_units.append(
                        (ring_ids, f"{ring.size}-membered ring · {composition}", 0)
                    )
                continue
            all_ring_members = {
                str(identifier)
                for ring in ring_result.rings
                for identifier in ring.member_ids
            }
            if (
                component.translation_rank == 0
                and len(ring_result.rings) > 1
                and all_ring_members == set(ids)
            ):
                composition = self.structural_unit_composition(ids, lookup)
                cycle_rank = component_graph.number_of_edges() - component_graph.number_of_nodes() + 1
                cluster_kind = (
                    "double-ring cluster" if cycle_rank == 2 else "polycyclic cluster"
                )
                raw_units.append((ids, f"{cluster_kind} · {composition}", 0))
                continue
            # A periodic domain is one topological object even when its
            # quotient-cell representatives look like disconnected pieces.
            # Rigid-body candidates are split independently in build_blocks.
            if component.translation_rank and (
                role_evidence is not None or len(ids) <= 2
            ):
                raw_units.append((ids, component.classification, component.translation_rank))
                continue
            simple_graph = nx.Graph(component_graph)
            raw_units.extend(
                (unit_ids, classification, component.translation_rank)
                for unit_ids, classification in self.decompose_motif_component(
                    simple_graph,
                    lookup,
                    connections,
                )
            )

        # Keep each cavity/interlayer coordination environment inspectable.
        for polyhedron in polyhedra:
            role = role_by_center.get(polyhedron.center_index)
            if role == "interstitial" or (
                role_evidence is None and self.is_interstitial_polyhedron(polyhedron)
            ):
                raw_units.append(((polyhedron.id,), "interlayer polyhedron", 0))
            elif role == "ambiguous":
                raw_units.append(((polyhedron.id,), "ambiguous coordination environment", 0))
            elif role == "structural" and polyhedron.center_index not in primary_centres:
                raw_units.append(((polyhedron.id,), "coordination context", 0))
        raw_units.sort(key=lambda item: min(int(value[1:]) for value in item[0]))

        units = []
        for number, (ids, classification, periodic_rank) in enumerate(raw_units, start=1):
            atom_indices = set()
            for polyhedron_id in ids:
                polyhedron = lookup[polyhedron_id]
                atom_indices.add(polyhedron.center_index)
                atom_indices.update(ligand.site_index for ligand in polyhedron.ligands)
            units.append(
                StructuralUnit(
                    id=f"SU{number}",
                    polyhedron_ids=ids,
                    atom_indices=tuple(sorted(atom_indices)),
                    classification=classification,
                    periodic_rank=periodic_rank,
                )
            )
        return units

    @staticmethod
    def is_interstitial_polyhedron(polyhedron: CoordinationPolyhedron) -> bool:
        return polyhedron.center_element in INTERSTITIAL_ELEMENTS

    @staticmethod
    def structural_unit_composition(
        ids: tuple[str, ...],
        polyhedra: dict[str, CoordinationPolyhedron],
    ) -> str:
        """Compute a motif formula from unique crystallographic sites."""
        element_by_site: dict[int, str] = {}
        centre_order: list[str] = []
        ligand_order: list[str] = []
        for identifier in ids:
            polyhedron = polyhedra[identifier]
            element_by_site[polyhedron.center_index] = polyhedron.center_element
            if polyhedron.center_element not in centre_order:
                centre_order.append(polyhedron.center_element)
            for ligand in polyhedron.ligands:
                element_by_site.setdefault(ligand.site_index, polyhedron.ligand_element)
                if polyhedron.ligand_element not in ligand_order:
                    ligand_order.append(polyhedron.ligand_element)
        counts: dict[str, int] = {}
        for element in element_by_site.values():
            counts[element] = counts.get(element, 0) + 1
        order = centre_order + [element for element in ligand_order if element not in centre_order]
        return "".join(
            element + (str(counts[element]) if counts[element] != 1 else "")
            for element in order
        )

    @classmethod
    def decompose_motif_component(
        cls,
        graph: nx.Graph,
        polyhedra: dict[str, CoordinationPolyhedron],
        connections: list[PolyhedronConnection],
    ) -> list[tuple[tuple[str, ...], str]]:
        """Split a connected layer into minimal recognizable chemical motifs."""
        ids = tuple(sorted(graph.nodes, key=lambda value: int(value[1:])))
        if len(ids) <= 2:
            return [(ids, cls.classify_structural_unit(graph, polyhedra, connections))]

        degrees = dict(graph.degree())
        max_degree = max(degrees.values(), default=0)
        motifs: list[tuple[tuple[str, ...], str]] = []

        for polyhedron_id in ids:
            polyhedron = polyhedra[polyhedron_id]
            classification = (
                "linking tetrahedron"
                if polyhedron.coordination_number == 4
                and degrees[polyhedron_id] == max_degree
                and max_degree >= 4
                else "tetrahedral unit"
                if polyhedron.coordination_number == 4
                else "island"
            )
            motifs.append(((polyhedron_id,), classification))
        return motifs

    @classmethod
    def classify_structural_unit(
        cls,
        graph: nx.Graph,
        polyhedra: dict[str, CoordinationPolyhedron],
        connections: list[PolyhedronConnection],
    ) -> str:
        """Name a chemical building motif rather than a mechanical block."""
        count = graph.number_of_nodes()
        if count == 1:
            return "island"
        if count == 2:
            ids = set(graph.nodes)
            pair = next(
                (
                    connection
                    for connection in connections
                    if {connection.first, connection.second} == ids
                ),
                None,
            )
            if (
                pair is not None
                and pair.kind == "corner"
                and all(polyhedra[polyhedron_id].coordination_number == 4 for polyhedron_id in ids)
            ):
                return "pyro group"
            return "dimer"
        return cls.classify_component(graph)

    @staticmethod
    def classify_component(graph: nx.Graph) -> str:
        count = graph.number_of_nodes()
        if count == 1:
            return "isolated polyhedron"
        if count == 2:
            return "dimer"
        if count == 3 and graph.number_of_edges() <= 2:
            return "trimer"
        degrees = [degree for _, degree in graph.degree()]
        if nx.is_tree(graph) and max(degrees, default=0) <= 2:
            return "chain fragment"
        if count > 2 and all(degree == 2 for degree in degrees):
            return "ring"
        if max(degrees, default=0) >= 4:
            return "framework fragment"
        return "cluster"

    def build_connectors(
        self,
        structure: CrystalStructure,
        polyhedra: list[CoordinationPolyhedron],
        connections: list[PolyhedronConnection],
        blocks: list[StructuralBlock],
    ) -> list[FlexibleConnector]:
        block_by_polyhedron = {
            polyhedron_id: block.id
            for block in blocks
            for polyhedron_id in block.polyhedron_ids
        }
        connectors = []
        seen = set()
        polyhedron_lookup = {polyhedron.id: polyhedron for polyhedron in polyhedra}
        for connection in connections:
            first_block = block_by_polyhedron[connection.first]
            second_block = block_by_polyhedron[connection.second]
            if first_block == second_block:
                continue
            # Ca/Sr/Ba coordination environments are interlayer DOFs, not
            # literal oxygen hinges between two rigid tetrahedral bodies.
            if (
                self.is_interstitial_polyhedron(polyhedron_lookup[connection.first])
                or self.is_interstitial_polyhedron(polyhedron_lookup[connection.second])
            ):
                continue
            pair = tuple(sorted((first_block, second_block)))
            ligand_indices = tuple(sorted({item.site_index for item in connection.shared_ligands}))
            key = (*pair, ligand_indices)
            if key in seen:
                continue
            seen.add(key)
            pivots = tuple(
                tuple(
                    float(value)
                    for value in structure.cell.frac_to_cart(
                        np.asarray(structure.sites[item.site_index].fractional) + np.asarray(item.image)
                    )
                )
                for item in connection.shared_ligands
            )
            connectors.append(
                FlexibleConnector(
                    id=f"C{len(connectors) + 1}",
                    first_block=pair[0],
                    second_block=pair[1],
                    first_polyhedron=connection.first,
                    second_polyhedron=connection.second,
                    kind=(
                        "shared O vertex · pivot candidate"
                        if all(structure.sites[index].element == "O" for index in ligand_indices)
                        else "shared ligand · pivot candidate"
                    ),
                    ligand_indices=ligand_indices,
                    pivot_coordinates=pivots,
                )
            )
        return connectors
