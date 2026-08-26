"""Typed values shared by comparison tables and 3D focus actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Iterable, Mapping, TypeAlias

import numpy as np

from crystal_viewer.analysis.hierarchy import HierarchyLevel


class DescriptorKind(StrEnum):
    SCALAR = "scalar"
    INTERVAL = "interval"
    DISTRIBUTION = "distribution"
    CATEGORICAL = "categorical"
    GRAPH = "graph"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    minimum: float | None
    mean: float | None
    maximum: float | None
    std: float | None
    count: int
    values: tuple[float, ...] = ()

    @classmethod
    def from_values(cls, values: Iterable[float]) -> "DistributionSummary":
        stored = tuple(float(value) for value in values)
        data = np.asarray(stored, dtype=float)
        if not data.size:
            return cls(None, None, None, None, 0, ())
        return cls(
            minimum=float(data.min()),
            mean=float(data.mean()),
            maximum=float(data.max()),
            std=float(data.std()),
            count=len(stored),
            values=stored,
        )


DescriptorPayload: TypeAlias = (
    float | str | DistributionSummary | Mapping[str, object] | None
)


@dataclass(frozen=True, slots=True)
class DescriptorValue:
    id: str
    title: str
    section: str
    kind: DescriptorKind
    value: DescriptorPayload
    unit: str = ""
    method_id: str = ""
    warning: str = ""
    object_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FocusCommand:
    action: str
    level: HierarchyLevel
    selector: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
