from __future__ import annotations

from xrd_manager.core.pattern import Pattern
from xrd_manager.core.phase import Phase
from xrd_manager.core.project import Project
from xrd_manager.core.refinement import RefinementResult
from xrd_manager.core.result import AnalysisResult
from xrd_manager.core.series import SeriesAnalysis
from xrd_manager.core.structure import Structure
from xrd_manager.events.event_bus import EventBus
from xrd_manager.events.event_types import PROJECT_CHANGED


class ProjectService:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or EventBus()

    def add_pattern(self, project: Project, pattern: Pattern) -> None:
        project.patterns.append(pattern)
        self._changed(project)

    def add_phase(self, project: Project, phase: Phase) -> None:
        project.phases.append(phase)
        self._changed(project)

    def add_structure(self, project: Project, structure: Structure) -> None:
        project.structures.append(structure)
        self._changed(project)

    def add_refinement(self, project: Project, refinement: RefinementResult) -> None:
        project.refinements.append(refinement)
        self._changed(project)

    def add_analysis(self, project: Project, result: AnalysisResult) -> None:
        project.analyses.append(result)
        self._changed(project)

    def add_series(self, project: Project, series: SeriesAnalysis) -> None:
        project.series.append(series)
        self._changed(project)

    def _changed(self, project: Project) -> None:
        project.touch()
        self.event_bus.publish(PROJECT_CHANGED, project=project)

