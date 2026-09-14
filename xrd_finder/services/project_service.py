from __future__ import annotations

from xrd_finder.core.pattern import Pattern
from xrd_finder.core.phase import Phase
from xrd_finder.core.project import Project
from xrd_finder.core.result import AnalysisResult
from xrd_finder.core.structure import Structure
from xrd_finder.events.event_bus import EventBus
from xrd_finder.events.event_types import PROJECT_CHANGED


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

    def add_analysis(self, project: Project, result: AnalysisResult) -> None:
        project.analyses.append(result)
        self._changed(project)

    def _changed(self, project: Project) -> None:
        project.touch()
        self.event_bus.publish(PROJECT_CHANGED, project=project)
