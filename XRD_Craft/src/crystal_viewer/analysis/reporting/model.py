from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from crystal_viewer.core.measurement import MeasuredValue


class Provenance(StrEnum):
    REPORTED = "reported"
    CALCULATED = "calculated"
    MODEL_DEPENDENT = "model-dependent"
    INFERRED = "inferred"
    CURATED = "curated"
    UNAVAILABLE = "unavailable"


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ReportCell:
    value: MeasuredValue | float | int | str | None
    display: str
    provenance: Provenance
    source_name: str = ""
    method_id: str = ""
    warning: str = ""


@dataclass(frozen=True, slots=True)
class ReportColumn:
    id: str
    title: str
    unit: str = ""
    visible: bool = True


@dataclass(frozen=True, slots=True)
class ReportRow:
    id: str
    cells: Mapping[str, ReportCell]
    include_in_publication: bool = True
    object_refs: tuple[str, ...] = ()
    expanded_records: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", MappingProxyType(dict(self.cells)))
        object.__setattr__(self, "object_refs", tuple(self.object_refs))
        object.__setattr__(self, "expanded_records", tuple(self.expanded_records))


@dataclass(frozen=True, slots=True)
class ReportWarning:
    code: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True, slots=True)
class ReportSettings:
    bond_tolerance: float = 1.18
    distance_group_tolerance: float = 0.001
    angle_group_tolerance: float = 0.01


@dataclass(frozen=True, slots=True)
class ReportTable:
    id: str
    title: str
    columns: tuple[ReportColumn, ...]
    rows: tuple[ReportRow, ...]
    availability: Availability = Availability.AVAILABLE
    unavailable_reason: str = ""
    warnings: tuple[ReportWarning, ...] = ()
    method: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "rows", tuple(self.rows))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True, slots=True)
class StructureReport:
    structure_name: str
    source_path: str
    settings: ReportSettings
    tables: Mapping[str, ReportTable] = field(default_factory=dict)
    generator_version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "tables", MappingProxyType(dict(self.tables)))

    def table(self, table_id: str) -> ReportTable:
        return self.tables[table_id]
