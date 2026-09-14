from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from xrd_finder.core.base import new_id, utc_now
from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.core.pattern import Pattern
from xrd_finder.core.phase import Phase
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
    refinements: list[dict[str, Any]] = field(default_factory=list)
    analyses: list[AnalysisResult] = field(default_factory=list)
    series: list[SeriesAnalysis] = field(default_factory=list)
    finder_state: FinderProjectState = field(default_factory=FinderProjectState)
    analysis_summary: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = utc_now()

    def series_for_object(self, object_type: str, object_id: str) -> SeriesAnalysis | None:
        if object_type not in {"pattern", "phase"}:
            return None
        attribute = "pattern_ids" if object_type == "pattern" else "phase_ids"
        return next((series for series in self.series if object_id in getattr(series, attribute)), None)

    def assign_object_to_series(self, object_type: str, object_id: str, series_id: str | None) -> None:
        if object_type not in {"pattern", "phase"}:
            raise ValueError(f"Unsupported series object type: {object_type}")
        for series in self.series:
            series.remove_object(object_type, object_id)
        if not series_id:
            return
        target = next((series for series in self.series if series.id == series_id), None)
        if target is not None:
            target.add_object(object_type, object_id)

    def remove_object_from_series(self, object_type: str, object_id: str) -> None:
        self.assign_object_to_series(object_type, object_id, None)

    def prune_series_memberships(self) -> None:
        pattern_ids = {pattern.id for pattern in self.patterns}
        phase_ids = {phase.id for phase in self.phases}
        claimed_patterns: set[str] = set()
        claimed_phases: set[str] = set()
        for series in self.series:
            series.pattern_ids = [
                pattern_id
                for pattern_id in series.pattern_ids
                if pattern_id in pattern_ids and pattern_id not in claimed_patterns
            ]
            claimed_patterns.update(series.pattern_ids)
            series.phase_ids = [
                phase_id
                for phase_id in series.phase_ids
                if phase_id in phase_ids and phase_id not in claimed_phases
            ]
            claimed_phases.update(series.phase_ids)
