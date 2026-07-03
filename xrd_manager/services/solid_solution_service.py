from __future__ import annotations

from xrd_manager.core.series import SeriesAnalysis


class SolidSolutionService:
    def create_composition_series(self, name: str = "Composition series") -> SeriesAnalysis:
        return SeriesAnalysis.create(name=name, kind="composition")

