from __future__ import annotations

from dataclasses import dataclass, field

from xrd_finder.core.base import ProjectObject, new_id


@dataclass(slots=True)
class Pattern(ProjectObject):
    source_path: str = ""
    x_unit: str = "2theta"
    y_unit: str = "intensity"
    wavelength: float | None = None
    linked_phase_ids: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, name: str, source_path: str = "") -> "Pattern":
        return cls(name=name, id=new_id("pattern"), source_path=source_path)
