from __future__ import annotations

from contextlib import closing, contextmanager
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
import math
import heapq
from pathlib import Path
import sqlite3
from types import SimpleNamespace
from typing import Callable, Iterable, Iterator

from xrd_finder.finder.fingerprint_matching import fingerprint_match_score, MATCH_REFERENCE_LINE_LIMIT
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    radiation_lines_from_wavelength,
)
from xrd_finder.services.geometric_fingerprint import (
    peak_geometric_hashes,
    rank_fingerprint_candidates,
)


CandidateRow = list[str]
ReferencePeakLoader = Callable[[CandidateRow], Iterable[object]]
ProgressCallback = Callable[[str, int, int], None]

FINGERPRINT_PRIORITY_REFINE_LIMIT = 40
MATCH_PRIORITY_REFINE_LIMIT = 60


@dataclass(frozen=True, slots=True)
class AutoSearchRankingResult:
    rows: list[CandidateRow]
    scored_keys: set[tuple[str, str]]
    matched_count: int
    failures: dict[tuple[str, str], str] = field(default_factory=dict)
    unavailable_keys: set[tuple[str, str]] = field(default_factory=set)

    @property
    def diagnostic_summary(self):
        return (f'Match: {len(self.scored_keys)} scored, '
                f'{len(self.unavailable_keys)} unavailable, {len(self.failures)} failed')


def rank_candidate_rows(
    rows: list[CandidateRow],
    observed_records,
    *,
    wavelength: float,
    reference_peak_loader: ReferencePeakLoader,
    two_theta_range: tuple[float, float] | None = None,
    rank_limit: int | None = None,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> AutoSearchRankingResult:
    """Rank the initial local auto-search pool without touching Qt objects."""

    normalized_rows = [_normalized_row(row) for row in rows]
    limit = (
        len(normalized_rows)
        if rank_limit is None
        else min(len(normalized_rows), max(0, int(rank_limit)))
    )
    scored_rows: list[tuple[float, int, CandidateRow, list[object]]] = []
    scored_keys: set[tuple[str, str]] = set()
    failures = {}
    unavailable_keys = set()

    for index, original in enumerate(normalized_rows[:limit]):
        if cancelled is not None and cancelled():
            raise CancelledError('Candidate ranking cancelled')
        row = list(original)
        row[5] = ""
        row[6] = ""
        source = row[0].strip().upper()
        entry_id = row[1].strip()
        key = (source, entry_id)
        reference_peaks = []
        probability = 0.0
        try:
            reference_peaks = reference_peaks_in_range(reference_peak_loader(row), two_theta_range)
            if reference_peaks:
                probability = fingerprint_match_score(
                    reference_peaks, observed_records, wavelength=float(wavelength),
                    refine_alignment=False).score
                if source and entry_id:
                    scored_keys.add(key)
            elif source and entry_id:
                unavailable_keys.add(key)
        except (sqlite3.DatabaseError, CancelledError):
            raise  # A job-wide database failure or cancellation is not partial success.
        except Exception as exc:
            failures[key] = f'{type(exc).__name__}: {exc}'
            reference_peaks = []
        if probability > 0.0:
            row[5] = f"{probability:.0f}%"
        scored_rows.append((float(probability), index, row, reference_peaks))
        if progress is not None:
            progress("Ranking local candidates", index + 1, limit)

    if progress is not None:
        progress("Ranking local candidates", limit, limit)

    # Protect the quick Match priority; share the geometric priority between
    # height and area so differing widths do not hide a shifted phase.
    height_priority_limit = FINGERPRINT_PRIORITY_REFINE_LIMIT // 2
    refine_indices = set(range(min(height_priority_limit, len(scored_rows))))
    quick_order = sorted(scored_rows, key=lambda item: (-item[0], item[1]))
    refine_indices.update(
        item[1]
        for item in quick_order[: min(MATCH_PRIORITY_REFINE_LIMIT, len(quick_order))]
    )
    refinement_budget = FINGERPRINT_PRIORITY_REFINE_LIMIT + MATCH_PRIORITY_REFINE_LIMIT
    refine_indices.update(_area_geometry_refinements(
        scored_rows, observed_records, excluded=refine_indices,
        limit=FINGERPRINT_PRIORITY_REFINE_LIMIT-height_priority_limit,
    ))
    # Missing area evidence and overlapping priorities give their slots back
    # to the original geometric order, including legacy height-only callers.
    for index in range(min(FINGERPRINT_PRIORITY_REFINE_LIMIT, len(scored_rows))):
        if len(refine_indices) >= refinement_budget:
            break
        refine_indices.add(index)
    refined_rows: list[tuple[float, int, CandidateRow, list[object]]] = []
    for probability, index, row, reference_peaks in scored_rows:
        if cancelled is not None and cancelled():
            raise CancelledError('Candidate ranking cancelled')
        if index in refine_indices and len(reference_peaks) >= 3:
            try:
                probability = fingerprint_match_score(
                    reference_peaks, observed_records, wavelength=float(wavelength),
                    refine_alignment=True).score
            except (sqlite3.DatabaseError, CancelledError):
                raise
            except Exception as exc:
                key = (row[0].strip().upper(), row[1].strip())
                failures[key] = f'{type(exc).__name__}: {exc}'
                scored_keys.discard(key)
                probability = 0.0
            row[5] = f"{probability:.0f}%" if probability > 0.0 else ""
        refined_rows.append((float(probability), index, row, reference_peaks))
    scored_rows = refined_rows

    if any(probability > 0.0 for probability, _index, _row, _peaks in scored_rows):
        scored_rows.sort(key=lambda item: (-item[0], item[1]))
    ranked = [row for _probability, _index, row, _peaks in scored_rows]
    ranked.extend(normalized_rows[limit:])
    return AutoSearchRankingResult(
        rows=ranked,
        scored_keys=scored_keys,
        matched_count=sum(probability > 0.0 for probability, *_rest in scored_rows),
        failures=failures,
        unavailable_keys=unavailable_keys,
    )


def _area_geometry_refinements(scored_rows, observed_records, *, excluded, limit):
    if limit <= 0:
        return ()
    measured = []
    for record in observed_records:
        try:
            position = float(record.two_theta)
            area = float(record.area)
        except (AttributeError, TypeError, ValueError):
            continue
        if math.isfinite(position) and math.isfinite(area) and area > 0.0:
            measured.append((position, area))
    query = peak_geometric_hashes(measured, expanded=True)
    if not query:
        return ()
    hashes = {
        ('ROW', str(index)): peak_geometric_hashes(peaks)
        for _score, index, _row, peaks in scored_rows
        if index not in excluded and len(peaks) >= 3
    }
    return tuple(int(item.key[1]) for item in rank_fingerprint_candidates(query, hashes, limit=limit))


class LocalReferencePeakLoader:
    """Callable reference reader with explicit worker-scope connection ownership."""

    def __init__(self, load, connection, *, snapshot=False):
        self._load = load
        self._connection = connection
        self._snapshot = snapshot

    def __call__(self, row):
        if self._connection is None:
            raise RuntimeError("Reference reader is closed")
        if not self._snapshot:
            return self._load(row)
        self._connection.execute('BEGIN')
        try:
            return self._load(row)
        finally:
            # A card is coherent, but its read lock must not span the expensive
            # ranking of every other card or delay preparation writers.
            self._connection.rollback()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __del__(self):
        self.close()


def reference_peaks_in_range(peaks, two_theta_range=None):
    """Limit evidence to measured angles before strongest-line selection."""
    if two_theta_range is None:
        return list(peaks)
    low, high = two_theta_range
    return [peak for peak in peaks if low <= float(peak.two_theta) <= high]


def create_local_reference_peak_loader(
    cache_root: str | Path,
    pdf2_root: str | Path | None,
    wavelength: float,
    *, instrument_profile=None, prepared_only=False, match_only=False, two_theta_range=None,
) -> ReferencePeakLoader:
    """Own a read-only structural-index connection for one ranking task."""

    # Imports are intentionally local. The pure ranking function remains usable
    # in lightweight test environments, while each worker owns its DB services.
    from xrd_finder.services.local_phase_cache import (
        DERIVED_CACHE_VERSION, REINDEXABLE_CACHE_VERSIONS, LocalPhaseCache,
    )
    from xrd_finder.services.match_pdf2_service import MatchPdf2Service

    cache = LocalPhaseCache.read_only(cache_root) if prepared_only else LocalPhaseCache(cache_root)
    pdf2 = MatchPdf2Service(pdf2_root, initialize_index=not prepared_only) if pdf2_root else None
    active_wavelength = float(wavelength)
    primary_wavelength = radiation_lines_from_wavelength(
        active_wavelength,
        include_kalpha2=False,
    )[0][0]

    def load(row: CandidateRow) -> list[object]:
        source = row[0].strip().upper() if row else ""
        entry_id = row[1].strip() if len(row) > 1 else ""
        if not source or not entry_id:
            return []
        if source == "PDF2":
            if pdf2 is None:
                return []
            return reference_peaks_in_range(_pdf2_reference_peaks(
                pdf2.diffraction_peaks(entry_id),
                active_wavelength,
            ), two_theta_range)
        if source not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"}:
            return []
        columns = ('derived_version,substr(peaks_json,1,1024) as first_lines'
                   if prepared_only else 'derived_version')
        entry = connection.execute(f'select {columns} from phases where source=? and entry_id=?',
                                   (source, entry_id)).fetchone()
        if entry is None or int(entry['derived_version'] or 0) not in (*REINDEXABLE_CACHE_VERSIONS, DERIVED_CACHE_VERSION):
            return []
        requested_wavelength = (float(instrument_profile.radiation.components[0].wavelength_angstrom)
                               if instrument_profile is not None else primary_wavelength)
        # The worker expands the d range before scoring, including old local
        # cards. Returning an incomplete but READY Cu line set is not safe.
        if prepared_only:
            low, high = cache._requested_d_range(requested_wavelength)
            support = cache._reference_prefix_entry(source, entry_id, entry, connection=connection)
            if not cache._entry_covers_reference_range(support, low, high, False):
                return []
        elif not cache.ensure_reference_range(source, entry_id, wavelength=requested_wavelength):
            return []
        columns = ("d,two_theta,intensity,norm_intensity,raw_intensity,h,k,l,intrinsic_intensity,intensity_origin"
                   if match_only else "*")
        records = connection.execute(
            f"""
            select {', '.join('peaks.'+name for name in columns.split(','))}
            from phase_peaks as peaks
            join phases as phase
              on phase.source = peaks.source and phase.entry_id = peaks.entry_id
            where phase.source = ? and phase.entry_id = ? and phase.derived_version = ?
            order by peaks.peak_index
            """,
            (source, entry_id, DERIVED_CACHE_VERSION),
        ).fetchall()
        if match_only:
            return _cached_match_peaks(records, primary_wavelength,
                instrument_profile=instrument_profile, sql_records=True, two_theta_range=two_theta_range)
        return _cached_reference_peaks((dict(record) for record in records), primary_wavelength,
                                       instrument_profile=instrument_profile, two_theta_range=two_theta_range)

    uri = cache.index_path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return LocalReferencePeakLoader(load, connection, snapshot=prepared_only)


def _normalized_row(row: CandidateRow) -> CandidateRow:
    result = [str(value or "") for value in row[:8]]
    result.extend([""] * (8 - len(result)))
    return result


def _cached_reference_peaks(records, wavelength: float, *, instrument_profile=None, two_theta_range=None) -> list[object]:
    from xrd_finder.finder.reference_lines import ReferenceLineSet, reference_peaks_for_context
    from xrd_finder.finder.context import CalculationContext
    lines = ReferenceLineSet.from_records(source="CACHE",entry_id="",derived_version=0,
        provenance="SQL intensity metadata",records=records)
    low, high = two_theta_range if two_theta_range is not None else (5., 120.)
    context = CalculationContext(wavelength,wavelength,.18,low,high,(0,0.,0.,0),include_kalpha2=False)
    return reference_peaks_for_context(lines, context, instrument_profile)


@dataclass(frozen=True, slots=True)
class _MatchPeak:
    two_theta: float
    intensity: float


def _cached_match_peaks(records, wavelength, *, instrument_profile=None, sql_records=False, two_theta_range=None):
    """The same physical strengths as the complete reader, projected for Match.

    Match uses at most 64 strong lines, geometric priority at most 14. Select
    after converting *all* validated reflections and selecting the scan range;
    a cached-Cu top-N preselection would be wrong for another radiation/geometry.
    Full reflection cards, native completeness and Quant remain unchanged.
    """
    from xrd_finder.finder.reference_lines import _float_value, _int_value
    from xrd_finder.instrument.models import InstrumentProfile, RadiationProfile
    from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
    instrument = instrument_profile or InstrumentProfile(
        radiation=RadiationProfile.custom_monochromatic(wavelength))
    usable = []
    for index, record in enumerate(records):
        try:
            if sql_records:
                d, angle, intensity, normalized, raw, h, k, l, intrinsic, origin = record
                d, angle = d or 0., angle or 0.
                intensity, normalized, raw = intensity or 0., normalized or 0., raw or 0.
                h, k, l = int(h or 0), int(k or 0), int(l or 0)
                intrinsic = None if intrinsic is None else float(intrinsic)
                origin = origin or ''
            else:
                d, angle = _float_value(record, 'd'), _float_value(record, 'two_theta')
                intensity = _float_value(record, 'intensity')
                normalized = _float_value(record, 'norm_intensity')
                raw = _float_value(record, 'raw_intensity')
                intrinsic = (_float_value(record, 'intrinsic_intensity')
                             if record.get('intrinsic_intensity') is not None else None)
                origin = str(record.get('intensity_origin') or '')
                h, k, l = _int_value(record, 'h'), _int_value(record, 'k'), _int_value(record, 'l')
            if not (math.isfinite(d) and d > 0. and math.isfinite(angle)):
                continue
            usable.append((d, angle, max(intensity, 0.), max(normalized, 0.), max(raw, 0.),
                           intrinsic, origin, h, k, l, index))
        except (TypeError, ValueError):
            # SQLite rows written by the cache are typed. Retain tolerant
            # mapping conversion for unusually edited/legacy numeric values.
            if sql_records:
                columns = ('d','two_theta','intensity','norm_intensity','raw_intensity',
                           'h','k','l','intrinsic_intensity','intensity_origin')
                fallback = dict(zip(columns, record))
                # Run the same decoder used by the full-card reader.
                d, angle = _float_value(fallback,'d'), _float_value(fallback,'two_theta')
                if math.isfinite(d) and d > 0. and math.isfinite(angle):
                    usable.append((d,angle,max(_float_value(fallback,'intensity'),0.),
                        max(_float_value(fallback,'norm_intensity'),0.),max(_float_value(fallback,'raw_intensity'),0.),
                        None if fallback.get('intrinsic_intensity') is None else _float_value(fallback,'intrinsic_intensity'),
                        str(fallback.get('intensity_origin') or ''),_int_value(fallback,'h'),
                        _int_value(fallback,'k'),_int_value(fallback,'l'),index))
    structural = any(line[6] == 'cristma-structure' and line[5] is not None for line in usable)
    geometry = CristmaPowderAdapter._geometry_from_profile(instrument, use_lp=True) if structural else None
    radiation = CristmaPowderAdapter.radiation_from_profile(instrument)
    primary_weight = radiation.components[0].relative_weight / sum(c.relative_weight for c in radiation.components)
    active_wavelength = float(instrument.radiation.components[0].wavelength_angstrom)
    cached_angles = math.isclose(wavelength, CU_KA1_WAVELENGTH, abs_tol=1.e-4, rel_tol=0.)
    values = []
    maximum = 0.
    low, high = two_theta_range if two_theta_range is not None else (5., 120.)
    for d, angle, intensity, normalized, raw, intrinsic, origin, h, k, l, index in usable:
        center = angle
        native = origin == 'cristma-structure' and intrinsic is not None
        if native or origin or not cached_angles:
            argument = active_wavelength / (2.*d)
            if not 0. < argument <= 1.:
                continue
            center = math.degrees(2.*math.asin(argument))
        if not low <= center <= high:
            continue
        if native:
            lp = CristmaPowderAdapter._lorentz_polarization_factor(center, geometry)
            raw = float(intrinsic) * lp * primary_weight
            intensity = raw
        else:
            raw = float(raw or intensity)
            intensity = float(normalized or intensity)
        if not math.isfinite(intensity) or intensity <= 0. or not math.isfinite(raw):
            continue
        maximum = max(maximum, intensity)
        values.append((center, intensity, angle, h, k, l, index))
    if maximum <= 0.:
        return []
    scale = 100./maximum
    values = [(center, value*scale, angle, h, k, l, index)
              for center, value, angle, h, k, l, index in values]
    # Tie order is the complete ReferenceLineSet's (cached angle, h,k,l),
    # followed by the original row order. This also preserves dense multiplets.
    strongest = heapq.nsmallest(MATCH_REFERENCE_LINE_LIMIT, values,
        key=lambda item: (-item[1], *item[2:]))
    return [_MatchPeak(item[0], item[1]) for item in strongest]


def _pdf2_reference_peaks(records, wavelength: float) -> list[object]:
    peaks = []
    for record in records:
        try:
            two_theta = _two_theta_from_d(float(record.d_spacing), wavelength)
            intensity = max(float(record.intensity), 0.0)
            if 5.0 <= two_theta <= 120.0 and intensity > 0.0:
                peaks.append(SimpleNamespace(two_theta=two_theta, intensity=intensity))
        except (TypeError, ValueError):
            continue
    return peaks


def _two_theta_from_d(d_spacing: float, wavelength: float) -> float:
    if d_spacing <= 0.0:
        return 0.0
    argument = float(wavelength) / (2.0 * float(d_spacing))
    if not 0.0 < argument <= 1.0:
        return 0.0
    return math.degrees(2.0 * math.asin(argument))


__all__ = [
    "AutoSearchRankingResult",
    "create_local_reference_peak_loader",
    "rank_candidate_rows",
]
