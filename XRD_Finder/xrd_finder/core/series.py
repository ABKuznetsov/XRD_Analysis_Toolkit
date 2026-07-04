from __future__ import annotations

from dataclasses import dataclass, field

from xrd_finder.core.base import ProjectObject, new_id


@dataclass(slots=True)
class SeriesPoint:
    refinement_id: str
    variable_name: str
    variable_value: float
    variable_unit: str = ""


@dataclass(slots=True)
class SeriesAnalysis(ProjectObject):
    kind: str = "temperature"
    points: list[SeriesPoint] = field(default_factory=list)
    result_paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, kind: str = "temperature") -> "SeriesAnalysis":
        return cls(name=name, id=new_id("series"), kind=kind)
