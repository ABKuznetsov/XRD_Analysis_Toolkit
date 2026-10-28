from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from enum import Enum

from xrd_finder.finder.reference_lines import ReferenceLineSet
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION, LocalPhaseCache


class LineSetStatus(str, Enum):
    READY = "ready"
    MISSING = "missing"
    OBSOLETE = "obsolete"
    UNSUPPORTED = "unsupported"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class CandidateLineResolution:
    status: LineSetStatus
    line_set: ReferenceLineSet | None = None
    needs_index: bool = False


class CandidateLineProvider:
    STRUCTURAL_SOURCES = frozenset({"USER", "COD", "CCDC", "MP", "AFLOW", "OQMD"})

    def __init__(self, cache: LocalPhaseCache) -> None:
        self.cache = cache

    def resolve(self, candidate: dict[str, str], *, wavelength=None,
                two_theta_min=5., two_theta_max=120.) -> CandidateLineResolution:
        source = str(candidate.get("Source", "") or "").upper()
        entry_id = str(candidate.get("Entry", "") or "").strip()
        if source not in self.STRUCTURAL_SOURCES or not entry_id:
            return CandidateLineResolution(LineSetStatus.UNSUPPORTED)
        with closing(self.cache._connect()) as connection:
            # Metadata and reflections must belong to one SQLite snapshot,
            # including when another worker replaces a card concurrently.
            connection.execute('BEGIN')
            row = connection.execute(
                'select derived_version,substr(peaks_json,1,1024) as first_lines '
                'from phases where source=? and entry_id=?', (source, entry_id)).fetchone()
            if row is None:
                return CandidateLineResolution(LineSetStatus.MISSING, needs_index=True)
            version = int(row['derived_version'] or 0)
            if version != DERIVED_CACHE_VERSION:
                return CandidateLineResolution(LineSetStatus.OBSOLETE, needs_index=True)
            if wavelength is not None:
                low, high = self.cache._requested_d_range(wavelength, two_theta_min, two_theta_max)
                entry = self.cache._reference_prefix_entry(source, entry_id, row, connection=connection)
                if not self.cache._entry_covers_reference_range(entry, low, high, False):
                    return CandidateLineResolution(LineSetStatus.INCOMPLETE, needs_index=True)
            records = connection.execute(
                'select d,two_theta,intensity,norm_intensity,raw_intensity,h,k,l,multiplicity,'
                'intrinsic_intensity,intensity_origin from phase_peaks '
                'where source=? and entry_id=? order by peak_index', (source, entry_id))
            line_set = ReferenceLineSet.from_sql_rows(source=source, entry_id=entry_id,
                derived_version=version, provenance=f'local-phase-cache-v{version}', records=records)
        if not line_set.lines:
            return CandidateLineResolution(LineSetStatus.MISSING, needs_index=True)
        return CandidateLineResolution(LineSetStatus.READY, line_set=line_set)
