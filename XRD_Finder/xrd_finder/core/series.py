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
    pattern_ids: list[str] = field(default_factory=list)
    phase_ids: list[str] = field(default_factory=list)
    points: list[SeriesPoint] = field(default_factory=list)
    result_paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, kind: str = "temperature") -> "SeriesAnalysis":
        return cls(name=name, id=new_id("series"), kind=kind)

    def add_object(self, object_type: str, object_id: str) -> None:
        if object_type not in {"pattern", "phase"}:
            raise ValueError(f"Unsupported series object type: {object_type}")
        ids = self.pattern_ids if object_type == "pattern" else self.phase_ids
        if object_id not in ids:
            ids.append(object_id)

    def remove_object(self, object_type: str, object_id: str) -> None:
        if object_type not in {"pattern", "phase"}:
            raise ValueError(f"Unsupported series object type: {object_type}")
        ids = self.pattern_ids if object_type == "pattern" else self.phase_ids
        ids[:] = [item_id for item_id in ids if item_id != object_id]
