from __future__ import annotations

from dataclasses import dataclass, field

from xrd_manager.core.base import ProjectObject, new_id
from xrd_manager.core.structure import CellParameters


@dataclass(slots=True)
class RefinementMetrics:
    rwp: float | None = None
    rp: float | None = None
    chi2: float | None = None


@dataclass(slots=True)
class RefinementResult(ProjectObject):
    pattern_id: str = ""
    phase_ids: list[str] = field(default_factory=list)
    method: str = "unknown"
    metrics: RefinementMetrics = field(default_factory=RefinementMetrics)
    refined_cell: CellParameters = field(default_factory=CellParameters)
    output_paths: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(cls, name: str, pattern_id: str, phase_ids: list[str], method: str) -> "RefinementResult":
        return cls(
            name=name,
            id=new_id("refinement"),
            pattern_id=pattern_id,
            phase_ids=list(phase_ids),
            method=method,
        )

