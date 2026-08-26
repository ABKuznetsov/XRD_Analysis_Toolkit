from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from crystal_viewer.core.measurement import MeasuredValue, parse_cif_number


@dataclass(frozen=True, slots=True)
class CifLoop:
    """Raw values from one CIF loop, retained in source order."""

    tags: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def column(self, tag: str) -> tuple[str, ...]:
        index = self.tags.index(tag)
        return tuple(row[index] for row in self.rows)


@dataclass(frozen=True, slots=True)
class CifSourceData:
    """Immutable source-CIF data used by publication reports."""

    scalars: Mapping[str, str] = field(default_factory=dict)
    loops: tuple[CifLoop, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "scalars", MappingProxyType(dict(self.scalars)))
        object.__setattr__(self, "loops", tuple(self.loops))

    def raw(self, tag: str) -> str | None:
        return self.scalars.get(tag)

    def numeric(self, tag: str, unit: str = "") -> MeasuredValue:
        return parse_cif_number(self.raw(tag), unit=unit, source_name=tag)

    def loop_containing(self, tag: str) -> CifLoop | None:
        return next((loop for loop in self.loops if tag in loop.tags), None)
