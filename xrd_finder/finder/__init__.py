from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.models import (
    FinderCandidateInput,
    FinderCandidateResult,
    FinderInput,
    FinderResult,
    ObservedPeak,
    PeakAssignment,
    PeakStatus,
)
from xrd_finder.finder.reference_lines import ReferenceLine, ReferenceLineSet


def __getattr__(name: str):
    if name in {"FinderService", "FinderHeuristics"}:
        from xrd_finder.finder.service import FinderHeuristics, FinderService

        return {"FinderService": FinderService, "FinderHeuristics": FinderHeuristics}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CalculationContext",
    "FinderCandidateInput",
    "FinderCandidateResult",
    "FinderInput",
    "FinderResult",
    "ObservedPeak",
    "PeakAssignment",
    "PeakStatus",
    "ReferenceLine",
    "ReferenceLineSet",
    "FinderHeuristics",
    "FinderService",
]
