from __future__ import annotations

from dataclasses import dataclass

from xrd_manager.core.base import ProjectObject, new_id


@dataclass(slots=True)
class Phase(ProjectObject):
    source_path: str = ""
    formula: str = ""
    space_group: str = ""
    structure_id: str | None = None

    @classmethod
    def create(cls, name: str, source_path: str = "") -> "Phase":
        return cls(name=name, id=new_id("phase"), source_path=source_path)

