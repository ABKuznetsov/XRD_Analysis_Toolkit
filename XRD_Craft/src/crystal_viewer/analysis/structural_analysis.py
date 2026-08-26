from __future__ import annotations

from dataclasses import dataclass

from crystal_viewer.analysis.periodic_bonds import BondSettings, PeriodicBondResult
from crystal_viewer.analysis.structure_profile import ProfileSettings
from crystal_viewer.analysis.structural_roles import PolyhedronRoleEvidence
from crystal_viewer.analysis.nomenclature import NomenclatureAssignment
from crystal_viewer.core.model import CrystalStructure


@dataclass(frozen=True, slots=True)
class StructuralAnalysisSettings:
    bond_settings: BondSettings = BondSettings()
    profile: ProfileSettings = ProfileSettings()
    maximum_ring_size: int = 12
    maximum_states: int = 50_000
    maximum_seconds: float = 5.0

    def validate(self) -> None:
        self.profile.validate()
        if self.maximum_ring_size < 3:
            raise ValueError("maximum_ring_size must be at least 3")
        if self.maximum_states < 1:
            raise ValueError("maximum_states must be positive")
        if self.maximum_seconds <= 0.0:
            raise ValueError("maximum_seconds must be positive")


@dataclass(frozen=True, slots=True)
class CoordinationCandidate:
    symbol: str
    name: str
    fraction: float
    csm: float
    method: str = "chemenv"


@dataclass(frozen=True, slots=True)
class CoordinationEnvironment:
    center_index: int
    neighbor_indices: tuple[int, ...]
    neighbor_images: tuple[tuple[int, int, int], ...]
    candidates: tuple[CoordinationCandidate, ...] = ()
    ambiguous: bool = False
    complete: bool = True
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RingCandidate:
    member_ids: tuple[str, ...]
    member_images: tuple[tuple[int, int, int], ...]
    atom_indices: tuple[int, ...]
    size: int
    composition: str
    confidence: float
    shortest_path: bool = True


@dataclass(frozen=True, slots=True)
class StructuralUnitCandidate:
    kind: str
    member_ids: tuple[str, ...]
    atom_indices: tuple[int, ...]
    periodic_rank: int
    composition: str
    confidence: float
    primary: bool = False
    complete: bool = True
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuralAnalysis:
    settings: StructuralAnalysisSettings
    periodic_bonds: PeriodicBondResult
    coordination_environments: tuple[CoordinationEnvironment, ...] = ()
    rings: tuple[RingCandidate, ...] = ()
    structural_units: tuple[StructuralUnitCandidate, ...] = ()
    polyhedron_roles: tuple[PolyhedronRoleEvidence, ...] = ()
    structural_domains: tuple[StructuralDomain, ...] = ()
    nomenclature: tuple[NomenclatureAssignment, ...] = ()
    complete: bool = True
    exact: bool = True
    warnings: tuple[str, ...] = ()
    method_version: str = "structural-analysis-v1"


def analyze_structure(
    structure: CrystalStructure,
    settings: StructuralAnalysisSettings | None = None,
) -> StructuralAnalysis:
    from crystal_viewer.analysis.progressive_analysis import iter_analyze_structure

    final = None
    for snapshot in iter_analyze_structure(structure, settings):
        final = snapshot.structural_analysis or final
    if final is None:  # pragma: no cover - the iterator always emits a final stage
        raise RuntimeError("structural analysis did not produce a final result")
    return final


__all__ = [
    "CoordinationCandidate",
    "CoordinationEnvironment",
    "RingCandidate",
    "StructuralAnalysis",
    "StructuralAnalysisSettings",
    "StructuralUnitCandidate",
    "analyze_structure",
]
