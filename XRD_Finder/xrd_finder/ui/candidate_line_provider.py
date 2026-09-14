from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from xrd_finder.finder.reference_lines import ReferenceLineSet
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION, LocalPhaseCache


class LineSetStatus(str, Enum):
    READY = "ready"
    MISSING = "missing"
    OBSOLETE = "obsolete"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CandidateLineResolution:
    status: LineSetStatus
    line_set: ReferenceLineSet | None = None
    needs_index: bool = False


class CandidateLineProvider:
    STRUCTURAL_SOURCES = frozenset({"USER", "COD", "CCDC", "MP", "AFLOW", "OQMD"})

    def __init__(self, cache: LocalPhaseCache) -> None:
        self.cache = cache

    def resolve(self, candidate: dict[str, str]) -> CandidateLineResolution:
        source = str(candidate.get("Source", "") or "").upper()
        entry_id = str(candidate.get("Entry", "") or "").strip()
        if source not in self.STRUCTURAL_SOURCES or not entry_id:
            return CandidateLineResolution(LineSetStatus.UNSUPPORTED)
        entry = self.cache.get(source, entry_id)
        if entry is None:
            return CandidateLineResolution(LineSetStatus.MISSING, needs_index=True)
        if int(entry.derived_version) != DERIVED_CACHE_VERSION:
            return CandidateLineResolution(LineSetStatus.OBSOLETE, needs_index=True)
        records = self.cache.peak_records(source, entry_id)
        if not records:
            return CandidateLineResolution(LineSetStatus.MISSING, needs_index=True)
        line_set = ReferenceLineSet.from_records(
            source=source,
            entry_id=entry_id,
            derived_version=entry.derived_version,
            provenance=f"local-phase-cache-v{entry.derived_version}",
            records=records,
        )
        if not line_set.lines:
            return CandidateLineResolution(LineSetStatus.MISSING, needs_index=True)
        return CandidateLineResolution(LineSetStatus.READY, line_set=line_set)
