from __future__ import annotations

from xrd_finder.core.refinement import RefinementResult


LE_BAIL_STRATEGY = "le_bail"
CLASSICAL_RIETVELD_STRATEGY = "classical_rietveld"


class RefinementService:
    available_strategies = [
        LE_BAIL_STRATEGY,
        CLASSICAL_RIETVELD_STRATEGY,
    ]

    def create_job(self, pattern_id: str, phase_ids: list[str], method: str) -> RefinementResult:
        return self.create_strategy_job(pattern_id=pattern_id, phase_ids=phase_ids, strategy=method)

    def create_strategy_job(self, pattern_id: str, phase_ids: list[str], strategy: str) -> RefinementResult:
        name = f"{self.strategy_label(strategy)} refinement"
        return RefinementResult.create(name=name, pattern_id=pattern_id, phase_ids=phase_ids, method=strategy)

    def strategy_label(self, strategy: str) -> str:
        labels = {
            LE_BAIL_STRATEGY: "Le Bail",
            CLASSICAL_RIETVELD_STRATEGY: "Classical Rietveld",
        }
        return labels.get(strategy, strategy.replace("_", " ").title())
