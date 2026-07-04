from __future__ import annotations

from dataclasses import dataclass, field

from xrd_finder.core.base import new_id, utc_now
from xrd_finder.core.pattern import Pattern
from xrd_finder.core.phase import Phase
from xrd_finder.core.refinement import RefinementResult
from xrd_finder.core.result import AnalysisResult
from xrd_finder.core.series import SeriesAnalysis
from xrd_finder.core.structure import Structure


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
