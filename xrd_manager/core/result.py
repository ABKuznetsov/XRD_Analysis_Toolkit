from __future__ import annotations

from dataclasses import dataclass, field

from xrd_manager.core.base import ProjectObject, new_id


@dataclass(slots=True)
class AnalysisResult(ProjectObject):
    result_type: str = "generic"
    source_ids: list[str] = field(default_factory=list)
    output_paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, result_type: str, source_ids: list[str] | None = None) -> "AnalysisResult":
        return cls(
            name=name,
            id=new_id("result"),
            result_type=result_type,
            source_ids=list(source_ids or []),
        )

