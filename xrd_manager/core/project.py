from __future__ import annotations

from dataclasses import dataclass, field

from xrd_manager.core.base import new_id, utc_now
from xrd_manager.core.pattern import Pattern
from xrd_manager.core.phase import Phase
from xrd_manager.core.refinement import RefinementResult
from xrd_manager.core.result import AnalysisResult
from xrd_manager.core.series import SeriesAnalysis
from xrd_manager.core.structure import Structure


@dataclass(slots=True)
class Project:
    name: str
    id: str = field(default_factory=lambda: new_id("project"))
    root_path: str = ""
    notes: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    patterns: list[Pattern] = field(default_factory=list)
    phases: list[Phase] = field(default_factory=list)
    structures: list[Structure] = field(default_factory=list)
    refinements: list[RefinementResult] = field(default_factory=list)
    analyses: list[AnalysisResult] = field(default_factory=list)
    series: list[SeriesAnalysis] = field(default_factory=list)

    def touch(self) -> None:
        self.updated_at = utc_now()

