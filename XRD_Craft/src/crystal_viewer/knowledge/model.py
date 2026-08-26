from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_ROLES = frozenset({"structural", "interstitial", "ambiguous"})


@dataclass(frozen=True, slots=True)
class PeriodicBondChange:
    first: int
    second: int
    image: tuple[int, int, int]
    distance: float

    def __post_init__(self) -> None:
        if self.first < 0 or self.second < 0 or self.first == self.second:
            raise ValueError("bond site indices must be distinct and non-negative")
        if len(self.image) != 3 or any(isinstance(value, bool) or not isinstance(value, int) for value in self.image):
            raise ValueError("bond image must contain exactly three integers")
        if not math.isfinite(self.distance) or self.distance <= 0.0:
            raise ValueError("bond distance must be finite and positive")


@dataclass(frozen=True, slots=True)
class MotifFingerprint:
    algorithm: str
    periodic_rank: int
    nodes: tuple[tuple[object, ...], ...]
    edges: tuple[tuple[object, ...], ...]
    topology_digest: str = ""

    def __post_init__(self) -> None:
        if not self.algorithm:
            raise ValueError("fingerprint algorithm is required")
        if self.periodic_rank not in {0, 1, 2, 3}:
            raise ValueError("periodic rank must be between zero and three")
        if not self.nodes:
            raise ValueError("fingerprint must contain at least one node")


@dataclass(frozen=True, slots=True)
class InterpretationChanges:
    name: str | None = None
    vocabulary: str | None = None
    member_polyhedron_ids: tuple[str, ...] = ()
    role_overrides: tuple[tuple[int, str], ...] = ()
    bond_additions: tuple[PeriodicBondChange, ...] = ()
    bond_removals: tuple[PeriodicBondChange, ...] = ()

    def __post_init__(self) -> None:
        if self.name is not None and not self.name.strip():
            raise ValueError("interpretation name cannot be blank")
        if self.vocabulary is not None and not self.vocabulary.strip():
            raise ValueError("interpretation vocabulary cannot be blank")
        if len(set(self.member_polyhedron_ids)) != len(self.member_polyhedron_ids):
            raise ValueError("member polyhedron identifiers must be unique")
        centers = [center for center, _role in self.role_overrides]
        if any(center < 0 for center in centers) or len(set(centers)) != len(centers):
            raise ValueError("role override centers must be unique and non-negative")
        if any(role not in _ROLES for _center, role in self.role_overrides):
            raise ValueError("unsupported polyhedron role")


@dataclass(frozen=True, slots=True)
class KnowledgePreset:
    schema_version: int
    id: str
    scope: Literal["local", "reusable"]
    source_identity: str
    analysis_method: str
    fingerprint: MotifFingerprint | None
    changes: InterpretationChanges
    created_at: str
    modified_at: str
    note: str = ""
    accepted_count: int = 0
    dismissed_count: int = 0

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported preset schema")
        if _IDENTIFIER.fullmatch(self.id) is None:
            raise ValueError("preset id contains unsafe characters")
        if self.scope not in {"local", "reusable"}:
            raise ValueError("preset scope must be local or reusable")
        if not self.source_identity or not self.analysis_method:
            raise ValueError("source identity and analysis method are required")
        if self.scope == "reusable" and self.fingerprint is None:
            raise ValueError("reusable presets require a motif fingerprint")
        if not self.created_at or not self.modified_at:
            raise ValueError("preset timestamps are required")
        if self.accepted_count < 0 or self.dismissed_count < 0:
            raise ValueError("preset counters cannot be negative")


__all__ = [
    "InterpretationChanges",
    "KnowledgePreset",
    "MotifFingerprint",
    "PeriodicBondChange",
]
