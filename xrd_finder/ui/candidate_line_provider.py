from __future__ import annotations

from dataclasses import dataclass
from contextlib import closing
from enum import Enum

from xrd_finder.finder.reference_lines import ReferenceLineSet
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION, LocalPhaseCache
from xrd_finder.services.reference_batch_reader import REFERENCE_COLUMNS, read_reference_batch
from xrd_finder.services.normalized_reflections import ordered_card_query


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
        self._prefetched = {}
        self._prefetch_context = None

    def clear_prefetch(self):
        self._prefetched.clear()
        self._prefetch_context = None

    def prefetch(self, candidates, *, wavelength=None, two_theta_min=5., two_theta_max=120., cancelled=None):
        self.clear_prefetch()
        context = (wavelength,two_theta_min,two_theta_max)
        keys,unsupported = [],{}
        for candidate in candidates:
            key = (str(candidate.get('Source','') or '').upper(),str(candidate.get('Entry','') or '').strip())
            if key[0] in self.STRUCTURAL_SOURCES and key[1]:
                keys.append(key)
            else:
                unsupported[key] = CandidateLineResolution(LineSetStatus.UNSUPPORTED)
        def classify(key,row,connection):
            return self._classify(*key,row,connection,wavelength,two_theta_min,two_theta_max)
        def convert(key,row,records):
            version = int(row['derived_version'])
            lines = ReferenceLineSet.from_sql_rows(source=key[0],entry_id=key[1],derived_version=version,
                provenance=f'local-phase-cache-v{version}',records=records)
            return (CandidateLineResolution(LineSetStatus.READY,line_set=lines) if lines.lines else
                    CandidateLineResolution(LineSetStatus.MISSING,needs_index=True))
        with closing(self.cache._connect()) as connection:
            prepared = read_reference_batch(connection,keys,columns=REFERENCE_COLUMNS,
                classify=classify,convert=convert,cancelled=cancelled)
        self._prefetched = {**unsupported,**prepared}
        self._prefetch_context = context

    def _classify(self,source,entry_id,row,connection,wavelength,low,high):
        if row is None:
            return CandidateLineResolution(LineSetStatus.MISSING,needs_index=True)
        if int(row['derived_version'] or 0)!=DERIVED_CACHE_VERSION:
            return CandidateLineResolution(LineSetStatus.OBSOLETE,needs_index=True)
        if wavelength is not None:
            d_low,d_high = self.cache._requested_d_range(wavelength,low,high)
            entry = self.cache._reference_prefix_entry(source,entry_id,row,connection=connection)
            if not self.cache._entry_covers_reference_range(entry,d_low,d_high,False):
                return CandidateLineResolution(LineSetStatus.INCOMPLETE,needs_index=True)
        return None

    def resolve(self, candidate: dict[str, str], *, wavelength=None,
                two_theta_min=5., two_theta_max=120.) -> CandidateLineResolution:
        source = str(candidate.get("Source", "") or "").upper()
        entry_id = str(candidate.get("Entry", "") or "").strip()
        if self._prefetch_context==(wavelength,two_theta_min,two_theta_max) and (source,entry_id) in self._prefetched:
            result = self._prefetched[source,entry_id]
            if isinstance(result,Exception):
                raise result
            return result
        if source not in self.STRUCTURAL_SOURCES or not entry_id:
            return CandidateLineResolution(LineSetStatus.UNSUPPORTED)
        with closing(self.cache._connect()) as connection:
            # Metadata and reflections must belong to one SQLite snapshot,
            # including when another worker replaces a card concurrently.
            connection.execute('BEGIN')
            row = connection.execute(
                'select derived_version,substr(peaks_json,1,1024) as first_lines '
                'from phases where source=? and entry_id=?', (source, entry_id)).fetchone()
            status = self._classify(source,entry_id,row,connection,wavelength,two_theta_min,two_theta_max)
            if status is not None:
                return status
            version = int(row['derived_version'])
            records = connection.execute(
                ordered_card_query(connection,REFERENCE_COLUMNS), (source, entry_id))
            line_set = ReferenceLineSet.from_sql_rows(source=source, entry_id=entry_id,
                derived_version=version, provenance=f'local-phase-cache-v{version}', records=records)
        if not line_set.lines:
            return CandidateLineResolution(LineSetStatus.MISSING, needs_index=True)
        return CandidateLineResolution(LineSetStatus.READY, line_set=line_set)
