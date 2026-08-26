from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


Translation = tuple[int, int, int]


class ChemicalEdgeKind(StrEnum):
    COVALENT = "covalent"
    COORDINATION = "coordination"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ChemicalEdge:
    id: str
    first: int
    second: int
    image: Translation
    distance: float
    kind: ChemicalEdgeKind
    confidence: float
    method: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BondLayerReport:
    covalent: tuple[ChemicalEdge, ...]
    coordination: tuple[ChemicalEdge, ...]
    rejected: tuple[ChemicalEdge, ...]
    complete: bool
    warnings: tuple[str, ...] = ()
    method_version: str = "organic-bond-layers-v1"


__all__ = ["BondLayerReport", "ChemicalEdge", "ChemicalEdgeKind", "Translation"]
