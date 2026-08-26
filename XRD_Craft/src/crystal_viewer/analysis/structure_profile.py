from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import networkx as nx
import numpy as np
from pymatgen.core import Element

from crystal_viewer.analysis.periodic_bonds import PeriodicBondResult
from crystal_viewer.core.chemistry import site_elements
from crystal_viewer.core.model import CrystalStructure


class RequestedProfile(StrEnum):
    AUTO = "auto"
    INORGANIC = "inorganic"
    ORGANIC_METAL_ORGANIC = "organic-metal-organic"


class ResolvedProfile(StrEnum):
    INORGANIC = "inorganic"
    MOLECULAR = "molecular"
    RETICULAR = "reticular"


class ProfileConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class ProfileSettings:
    requested: RequestedProfile = RequestedProfile.AUTO

    def validate(self) -> None:
        if not isinstance(self.requested, RequestedProfile):
            raise ValueError("requested profile must be a RequestedProfile")


@dataclass(frozen=True, slots=True)
class ProfileDecision:
    resolved: ResolvedProfile
    score: float
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    method_version: str = "structure-profile-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if not math.isfinite(self.score) or not 0.0 <= self.score <= 1.0:
            raise ValueError("profile score must be finite and between 0 and 1")
        if not self.reasons:
            raise ValueError("profile decision requires evidence")

    @property
    def confidence(self) -> ProfileConfidence:
        if self.score >= 0.8:
            return ProfileConfidence.HIGH
        if self.score >= 0.55:
            return ProfileConfidence.MEDIUM
        return ProfileConfidence.LOW


class EdgeLike(Protocol):
    first: int
    second: int
    image: tuple[int, int, int]
    distance: float
    confidence: float
    method: str
    warnings: tuple[str, ...]


class BondLayers(Protocol):
    covalent: tuple[EdgeLike, ...]
    coordination: tuple[EdgeLike, ...]
    rejected: tuple[EdgeLike, ...]


@dataclass(frozen=True, slots=True)
class _RankEdge:
    first: int
    second: int
    image: tuple[int, int, int]


def _periodic_rank(nodes: set[int], edges: tuple[EdgeLike | _RankEdge, ...]) -> int:
    if not nodes or not edges:
        return 0
    adjacency: dict[int, list[tuple[int, tuple[int, int, int]]]] = {node: [] for node in nodes}
    for edge in edges:
        if edge.first not in nodes or edge.second not in nodes:
            continue
        adjacency[edge.first].append((edge.second, edge.image))
        adjacency[edge.second].append((edge.first, tuple(-value for value in edge.image)))
    potentials: dict[int, np.ndarray] = {}
    closures: list[np.ndarray] = []
    for root in sorted(nodes):
        if root in potentials:
            continue
        potentials[root] = np.zeros(3, dtype=int)
        stack = [root]
        while stack:
            first = stack.pop()
            for second, image in adjacency[first]:
                candidate = potentials[first] + np.asarray(image, dtype=int)
                if second not in potentials:
                    potentials[second] = candidate
                    stack.append(second)
                else:
                    closure = candidate - potentials[second]
                    if np.any(closure):
                        closures.append(closure)
    if not closures:
        return 0
    return int(np.linalg.matrix_rank(np.asarray(closures, dtype=float), tol=1e-9))


def _is_metal_site(structure: CrystalStructure, index: int) -> bool:
    for symbol in site_elements(structure.sites[index]):
        try:
            if Element(symbol).is_metal:
                return True
        except ValueError:
            continue
    return False


def _has_organic_backbone(structure: CrystalStructure, edges: tuple[EdgeLike, ...]) -> bool:
    for edge in edges:
        first = set(site_elements(structure.sites[edge.first]))
        second = set(site_elements(structure.sites[edge.second]))
        if "C" in first and "C" in second:
            return True
    return False


def resolve_structure_profile(
    structure: CrystalStructure,
    periodic_bonds: PeriodicBondResult,
    layers: BondLayers,
    *,
    requested: RequestedProfile = RequestedProfile.AUTO,
) -> ProfileDecision:
    if not isinstance(requested, RequestedProfile):
        raise ValueError("requested profile must be a RequestedProfile")

    graph = nx.Graph()
    graph.add_nodes_from(range(len(structure.sites)))
    graph.add_edges_from((edge.first, edge.second) for edge in layers.covalent)
    organic_components: list[set[int]] = []
    periodic_nonorganic_weight = 0.0
    organic_weight = 0.0
    heavy_weight = math.fsum(
        site.effective_occupancy
        for site in structure.sites
        if "H" not in site_elements(site)
    )
    for members in nx.connected_components(graph):
        members = set(members)
        component_edges = tuple(
            edge for edge in layers.covalent if edge.first in members and edge.second in members
        )
        weight = math.fsum(
            structure.sites[index].effective_occupancy
            for index in members
            if "H" not in site_elements(structure.sites[index])
        )
        organic = _has_organic_backbone(structure, component_edges)
        rank = _periodic_rank(members, component_edges)
        if organic:
            organic_components.append(members)
            if rank == 0:
                organic_weight += weight
        elif rank > 0:
            periodic_nonorganic_weight += weight

    reticular = False
    reticular_rank = 0
    for component_index, members in enumerate(organic_components):
        incident: list[tuple[int, EdgeLike | _RankEdge]] = []
        for edge in layers.coordination:
            first_metal = _is_metal_site(structure, edge.first)
            second_metal = _is_metal_site(structure, edge.second)
            if first_metal and edge.second in members:
                incident.append((edge.first, edge))
            elif second_metal and edge.first in members:
                inverted = _RankEdge(
                    edge.second,
                    edge.first,
                    tuple(-value for value in edge.image),
                )
                incident.append((edge.second, inverted))
        metal_indices = {metal for metal, _edge in incident}
        if len(metal_indices) < 2:
            continue
        linker_node = len(structure.sites) + component_index
        network_edges = tuple(
            _RankEdge(
                metal,
                linker_node,
                edge.image,
            )
            for metal, edge in incident
        )
        rank = _periodic_rank(metal_indices | {linker_node}, network_edges)
        reticular_rank = max(reticular_rank, rank)
        reticular = reticular or rank > 0

    unresolved_fraction = len(layers.rejected) / max(
        1,
        len(layers.covalent) + len(layers.coordination) + len(layers.rejected),
    )
    organic_fraction = organic_weight / max(heavy_weight, 1e-12)
    inorganic_fraction = periodic_nonorganic_weight / max(heavy_weight, 1e-12)
    reasons = [
        f"finite organic occupied-heavy-atom fraction {organic_fraction:.3f}",
        f"periodic inorganic occupied-heavy-atom fraction {inorganic_fraction:.3f}",
        f"metal-linker periodic rank {reticular_rank}",
    ]
    if unresolved_fraction:
        reasons.append(f"unresolved edges fraction {unresolved_fraction:.3f}")
    if not periodic_bonds.complete:
        reasons.append("periodic bond search incomplete")

    if reticular:
        automatic = ResolvedProfile.RETICULAR
        score = 0.9
    elif organic_fraction >= 0.5 and inorganic_fraction < organic_fraction:
        automatic = ResolvedProfile.MOLECULAR
        score = 0.9 if organic_fraction >= 0.8 and unresolved_fraction == 0.0 else 0.45
    else:
        automatic = ResolvedProfile.INORGANIC
        score = 0.9 if organic_fraction < 0.2 and unresolved_fraction == 0.0 else 0.45

    resolved = automatic
    if requested is RequestedProfile.INORGANIC:
        resolved = ResolvedProfile.INORGANIC
    elif requested is RequestedProfile.ORGANIC_METAL_ORGANIC:
        resolved = automatic if automatic is ResolvedProfile.RETICULAR else ResolvedProfile.MOLECULAR
    warnings: list[str] = []
    if requested is not RequestedProfile.AUTO and resolved is not automatic and score >= 0.8:
        warnings.append(
            f"Manual profile override conflicts with high-confidence automatic {automatic.value} evidence."
        )
    return ProfileDecision(resolved, score, tuple(reasons), tuple(warnings))


__all__ = [
    "ProfileConfidence",
    "ProfileDecision",
    "ProfileSettings",
    "RequestedProfile",
    "ResolvedProfile",
    "resolve_structure_profile",
]
