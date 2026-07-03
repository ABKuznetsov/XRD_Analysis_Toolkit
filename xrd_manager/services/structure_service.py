from __future__ import annotations

from xrd_manager.core.result import AnalysisResult


class StructureService:
    def create_structure_analysis(self, structure_id: str) -> AnalysisResult:
        return AnalysisResult.create(
            name="Structure analysis",
            result_type="structure_analysis",
            source_ids=[structure_id],
        )

