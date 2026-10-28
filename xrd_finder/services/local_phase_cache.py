from __future__ import annotations

from collections.abc import Iterable
from contextlib import closing
from concurrent.futures import CancelledError
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
import math
from numbers import Real
import re
from pathlib import Path
import shutil
import sqlite3
import time
from types import SimpleNamespace

from xrd_finder.core.structure import Structure
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.io.native_cif_session import native_cif_session
from xrd_finder.io.cif_powder_pattern import extract_cif_powder_peaks
from xrd_finder.services.calculated_pattern_service import CU_KA1_WAVELENGTH, CalculatedPatternService
from xrd_finder.services.cache_paths import default_phase_cache_root
from xrd_finder.services.calculated_iic import CalculatedIic
from xrd_finder.services.cod_online_service import CodEntry, CodOnlineService, formula_elements
from xrd_finder.services.geometric_fingerprint import peak_geometric_hashes


DEFAULT_CACHE_ROOT = default_phase_cache_root()
DERIVED_CACHE_VERSION = 11
# Old geometry may propose cards, but scoring must rebuild their intensity and
# completeness contract from the local CIF before consuming the cached lines.
REINDEXABLE_CACHE_VERSIONS = (9, 10)
INCOMPLETE_SEARCH_MAX_AGE_SECONDS = 30 * 60
TRANSFERABLE_LIBRARY_SOURCES = frozenset({"USER", "COD", "MP"})
GEOMETRIC_FINGERPRINT_VERSION = 1
GEOMETRIC_FINGERPRINT_PEAK_LIMIT = 10


def _embedded_source_dir_name(source: str) -> str:
    return f"source-{source.encode('utf-8', errors='surrogatepass').hex()}"


class LocalPhaseSearchError(sqlite3.OperationalError, RuntimeError):
    """The local query failed; an empty result must not imply completeness."""

    def __init__(self, error: sqlite3.OperationalError) -> None:
        code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        if code == sqlite3.SQLITE_INTERRUPT:
            detail = "timed out"
        elif code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            detail = "failed because the database is locked"
        else:
            detail = f"failed: {error}"
        super().__init__(
            f"Local phase search {detail}. Results are incomplete. "
            "Refine the search or try again."
        )


@dataclass(slots=True)
class CachedPhaseEntry:
    source: str
    entry_id: str
    formula: str = ""
    name: str = ""
    spacegroup: str = ""
    source_text: str = ""
    cif_path: str = ""
    a: float | None = None
    b: float | None = None
    c: float | None = None
    alpha: float | None = None
    beta: float | None = None
    gamma: float | None = None
    volume: float | None = None
    atoms_json: str = ""
    iic: float | None = None
    iic_method: str = ""
    peaks_json: str = ""
    top_peaks_json: str = ""
    derived_version: int = 0

    @property
    def cached(self) -> bool:
        return bool(self.cif_path)


@dataclass(frozen=True, slots=True)
class CachedPhaseSummary:
    """Shortlist metadata, not a hydrated structure or reflection card."""

    source: str
    entry_id: str
    formula: str
    name: str
    spacegroup: str
    iic: float | None
    iic_method: str
    derived_version: int


@dataclass(frozen=True, slots=True)
class CachedCompositionCheck:
    source: str
    entry_id: str
    cif_path: str
    stored_formula: str
    reported_formula: str
    search_formula: str
    warning: str
    needs_reindex: bool
    status: str = 'checked'


@dataclass(frozen=True, slots=True)
class CachedPreparationState:
    cif_path: str
    source_text: str
    derived_version: int
    has_peaks: bool

    @property
    def ready(self) -> bool:
        return self.derived_version == DERIVED_CACHE_VERSION and self.has_peaks


class _ReadOnlyConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class LocalPhaseCache:
    @classmethod
    def read_only(cls, root: str | Path) -> LocalPhaseCache:
        cache = cls.__new__(cls)
        cache.root = Path(root)
        cache.cif_dir = cache.root / "cif"
        cache.index_path = cache.root / "index.sqlite"
        cache._read_only = True
        cache.calculated_iic = CalculatedIic(cache.root / "references")
        return cache

    def __init__(self, root: str | Path = DEFAULT_CACHE_ROOT) -> None:
        self.root = Path(root)
        self.cif_dir = self.root / "cif"
        self.index_path = self.root / "index.sqlite"
        self.cif_dir.mkdir(parents=True, exist_ok=True)
        self._calculated_pattern_service = CalculatedPatternService()
        self.calculated_iic = CalculatedIic(self.root / "references")
        self._cristma_powder_adapter = self.calculated_iic.adapter
        self._ensure_schema()

    def status_row(self) -> list[str]:
        cached = self.cached_count()
        peak_indexed = self.peak_indexed_count()
        size = sum(path.stat().st_size for path in self.cif_dir.glob("*.cif") if path.is_file())
        return [
            "Local phase cache",
            "Ready",
            f"{cached} cached CIF files, {peak_indexed} peak-indexed phases",
            str(cached),
            f"{size / (1024 * 1024):.1f}",
            "sqlite+cif",
            str(self.root),
        ]

    def cached_count(self) -> int:
        with closing(self._connect()) as connection, connection:
            return int(connection.execute("select count(*) from phases where cif_path != ''").fetchone()[0])

    def source_count(self, source: str) -> int:
        with closing(self._connect()) as connection, connection:
            return int(
                connection.execute(
                    "select count(*) from phases where source = ?",
                    (str(source or "").upper(),),
                ).fetchone()[0]
            )

    def peak_indexed_count(self) -> int:
        with closing(self._connect()) as connection, connection:
            return int(connection.execute("select count(distinct source || ':' || entry_id) from phase_peaks").fetchone()[0])

    def search_is_fresh(self, source: str, query_key: str, max_age_seconds: float = 7 * 24 * 60 * 60) -> bool:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "select updated_at, complete from search_cache where source = ? and query_key = ?",
                (source, query_key),
            ).fetchone()
        if not row:
            return False
        freshness = (
            float(max_age_seconds)
            if bool(row["complete"])
            else float(INCOMPLETE_SEARCH_MAX_AGE_SECONDS)
        )
        return (time.time() - float(row["updated_at"])) < freshness

    def mark_search(self, source: str, query_key: str) -> None:
        self.record_search_attempt(source, query_key, result_limit=0, complete=True)

    def record_search_attempt(
        self,
        source: str,
        query_key: str,
        *,
        result_limit: int,
        complete: bool,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                insert into search_cache(source, query_key, updated_at, result_limit, complete)
                values(?, ?, ?, ?, ?)
                on conflict(source, query_key) do update set
                    updated_at = excluded.updated_at,
                    result_limit = excluded.result_limit,
                    complete = excluded.complete
                """,
                (
                    str(source),
                    str(query_key),
                    time.time(),
                    max(0, int(result_limit)),
                    int(bool(complete)),
                ),
            )

    def next_search_limit(
        self,
        source: str,
        query_key: str,
        *,
        base_limit: int,
        maximum_limit: int,
    ) -> int:
        base = max(1, int(base_limit))
        maximum = max(base, int(maximum_limit))
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "select result_limit, complete from search_cache where source = ? and query_key = ?",
                (source, query_key),
            ).fetchone()
        if not row or bool(row["complete"]):
            return base
        previous = max(0, int(row["result_limit"] or 0))
        return min(maximum, max(base, previous + base))

    def upsert_cod_entries(self, entries: list[CodEntry]) -> None:
        with closing(self._connect()) as connection, connection:
            for entry in entries:
                self._upsert(
                    connection,
                    CachedPhaseEntry(
                        source="COD",
                        entry_id=entry.cod_id,
                        formula=entry.formula,
                        name=entry.name or entry.mineral,
                        spacegroup=entry.spacegroup,
                        source_text=entry.source,
                    ),
                    keep_cif=True,
                )

    def upsert_materials_project_entries(self, entries) -> None:
        with closing(self._connect()) as connection, connection:
            for entry in entries:
                self._upsert(
                    connection,
                    CachedPhaseEntry(
                        source="MP",
                        entry_id=entry.material_id,
                        formula=entry.formula,
                        name=entry.name or entry.formula,
                        spacegroup=entry.spacegroup,
                        source_text=entry.energy_above_hull,
                    ),
                    keep_cif=True,
                )

    def upsert_computational_entries(self, entries) -> None:
        with closing(self._connect()) as connection, connection:
            for entry in entries:
                self._upsert(
                    connection,
                    CachedPhaseEntry(
                        source=entry.source,
                        entry_id=entry.entry_id,
                        formula=entry.formula,
                        name=entry.name or entry.formula,
                        spacegroup=entry.spacegroup,
                        source_text=entry.note,
                    ),
                    keep_cif=True,
                )

    def search(
        self,
        text: str = "",
        elements: list[str] | None = None,
        excluded_elements: list[str] | None = None,
        sources: list[str] | None = None,
        limit: int = 100,
        *,
        strict: bool = False,
        deduplicate: bool = True,
        summary_only: bool = False,
        cancelled=None,
    ) -> list[CachedPhaseEntry | CachedPhaseSummary]:
        if cancelled is not None and cancelled():
            raise CancelledError('Local phase search cancelled')
        required = {element.strip() for element in elements or [] if element.strip()}
        excluded = {element.strip() for element in excluded_elements or [] if element.strip()}
        allowed_sources = {source.strip() for source in sources or [] if source.strip()}
        text = text.strip()
        where = ["1 = 1"]
        params: list[object] = []
        if allowed_sources:
            placeholders = ", ".join("?" for _ in allowed_sources)
            where.append(f"source in ({placeholders})")
            params.extend(sorted(allowed_sources))
        for element in sorted(required):
            where.append(
                "exists ("
                "select 1 from phase_elements pe "
                "where pe.source = phases.source and pe.entry_id = phases.entry_id and pe.element = ?"
                ")"
            )
            params.append(element)
        for element in sorted(excluded):
            where.append(
                "not exists ("
                "select 1 from phase_elements pe "
                "where pe.source = phases.source and pe.entry_id = phases.entry_id and pe.element = ?"
                ")"
            )
            params.append(element)
        with closing(self._connect()) as connection, connection:
            if text:
                clause,text_params=self._chemical_text_filter(connection,text)
                where.append(clause)
                params.extend(text_params)
            # Worker population validation must finish or report an error.
            # A timed-out empty result cannot certify complete d support.
            deadline = math.inf if strict else time.monotonic() + 2.0

            was_cancelled = False

            def abort_slow_query() -> int:
                nonlocal was_cancelled
                was_cancelled = bool(cancelled is not None and cancelled())
                return int(was_cancelled or time.monotonic() > deadline)

            connection.set_progress_handler(abort_slow_query, 5000)
            try:
                rows = connection.execute(
                    f"""
                    select {self._search_columns(summary_only, connection=connection)}
                    from phases
                    where {" and ".join(where)}
                    order by updated_at desc
                    limit ?
                    """,
                    (*params, max(limit * 3, limit)),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if was_cancelled:
                    raise CancelledError('Local phase search cancelled') from exc
                raise LocalPhaseSearchError(exc) from exc
            finally:
                connection.set_progress_handler(None, 0)
        results = []
        seen = set()
        for row in rows:
            if cancelled is not None and cancelled():
                raise CancelledError('Local phase search cancelled')
            dedupe_key = self._dedupe_key(row)
            if deduplicate and dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(self._row_to_summary(row) if summary_only else self._row_to_entry(row))
            if len(results) >= limit:
                break
        return results

    def search_by_peaks(
        self,
        positions: list[float],
        *,
        text: str = "",
        elements: list[str] | None = None,
        excluded_elements: list[str] | None = None,
        sources: list[str] | None = None,
        wavelength: float = CU_KA1_WAVELENGTH,
        tolerance_two_theta: float = 0.35,
        limit: int = 100,
        summary_only: bool = False,
        strict: bool = False,
        cancelled=None,
    ) -> list[CachedPhaseEntry | CachedPhaseSummary]:
        from concurrent.futures import CancelledError
        if cancelled is not None and cancelled():
            raise CancelledError('Peak search cancelled')
        wavelength = float(wavelength or CU_KA1_WAVELENGTH)
        peak_positions = []
        for position in positions:
            if not isinstance(position, Real) or not math.isfinite(float(position)):
                continue
            two_theta = float(position)
            d_spacing = self._d_from_two_theta(two_theta, wavelength)
            if d_spacing is None:
                continue
            peak_positions.append((two_theta, d_spacing))
        if not peak_positions:
            return self.search(
                text=text,
                elements=elements,
                excluded_elements=excluded_elements,
                sources=sources,
                limit=limit,
                summary_only=summary_only,
                strict=strict,
            )
        anchor_positions = [item for item in peak_positions if 5.0 <= item[0] <= 60.0][:10]
        anchor_keys = {round(item[0], 5) for item in anchor_positions}
        remaining_positions = [
            item
            for item in peak_positions
            if round(item[0], 5) not in anchor_keys
        ]
        selected_positions = (anchor_positions + remaining_positions)[:80]
        anchor_count = len(anchor_positions)
        required = {element.strip() for element in elements or [] if element.strip()}
        excluded = {element.strip() for element in excluded_elements or [] if element.strip()}
        allowed_sources = {source.strip() for source in sources or [] if source.strip()}
        text = text.strip()
        where = ["1 = 1"]
        params: list[object] = []
        if allowed_sources:
            placeholders = ", ".join("?" for _ in allowed_sources)
            where.append(f"p.source in ({placeholders})")
            params.extend(sorted(allowed_sources))
        for element in sorted(required):
            where.append(
                "exists ("
                "select 1 from phase_elements pe "
                "where pe.source = p.source and pe.entry_id = p.entry_id and pe.element = ?"
                ")"
            )
            params.append(element)
        for element in sorted(excluded):
            where.append(
                "not exists ("
                "select 1 from phase_elements pe "
                "where pe.source = p.source and pe.entry_id = p.entry_id and pe.element = ?"
                ")"
            )
            params.append(element)
        query_peak_sql = " union all ".join(
            "select ? as query_index, ? as query_position, ? as query_d, ? as query_tolerance_d, ? as query_weight, ? as anchor_weight"
            for _ in selected_positions
        )
        query_params: list[object] = []
        tolerance = max(float(tolerance_two_theta), 0.02)
        for index, (position, d_spacing) in enumerate(selected_positions):
            query_weight = 1.0 / math.sqrt(index + 1.0)
            anchor_weight = 1.0 if index < anchor_count else 0.0
            query_params.extend([
                index,
                position,
                d_spacing,
                self._d_tolerance_from_two_theta_window(position, tolerance, wavelength),
                query_weight,
                anchor_weight,
            ])
        with closing(self._connect()) as connection, connection:
            if text:
                clause,text_params=self._chemical_text_filter(connection,text,'p.')
                where.append(clause)
                params.extend(text_params)
            deadline = math.inf if strict else time.monotonic() + 2.0
            was_cancelled=False

            def abort_slow_query() -> int:
                nonlocal was_cancelled
                if cancelled is not None and cancelled():
                    was_cancelled=True
                    return 1
                return int(time.monotonic() > deadline)

            connection.set_progress_handler(abort_slow_query, 5000)
            try:
                rows = connection.execute(
                    f"""
                    with query_peaks as ({query_peak_sql}),
                    matched_lines as (
                        select p.rowid as phase_id, q.query_index, q.query_weight, q.anchor_weight,
                               pp.peak_index, pp.top_rank, max(pp.norm_intensity, 0.0) as norm_intensity,
                               max(pp.intensity, 0.0) as intensity, abs(pp.d - q.query_d) as delta
                        from query_peaks q
                        cross join phase_peaks pp indexed by idx_phase_peaks_d
                        join phases p on p.source = pp.source and p.entry_id = pp.entry_id
                        where pp.d is not null
                          and pp.d between q.query_d - q.query_tolerance_d and q.query_d + q.query_tolerance_d
                          and {" and ".join(where)}
                    ),
                    observed_matches as (
                        select phase_id, query_index, max(query_weight) as query_weight,
                               max(anchor_weight) as anchor_weight,
                               max(case when anchor_weight > 0 and top_rank between 1 and 10 then 1 else 0 end) as strong_anchor_hit,
                               max(norm_intensity) as intensity_support, min(delta) as best_delta
                        from matched_lines
                        group by phase_id, query_index
                    ),
                    observed_evidence as (
                        select phase_id, count(*) as observed_hits,
                               sum(anchor_weight) as anchor_hits, sum(strong_anchor_hit) as strong_anchor_hits,
                               sum(anchor_weight * intensity_support) as anchor_intensity_support,
                               sum(query_weight) as weighted_observed_hits,
                               sum(query_weight * intensity_support) as weighted_intensity_support,
                               min(best_delta) as best_delta
                        from observed_matches
                        group by phase_id
                    ),
                    reflection_matches as (
                        select phase_id, peak_index, max(intensity) as intensity
                        from matched_lines
                        group by phase_id, peak_index
                    ),
                    reflection_evidence as (
                        select phase_id, count(*) as peak_hits, sum(intensity) as matched_intensity
                        from reflection_matches
                        group by phase_id
                    )
                    select {self._search_columns(summary_only, 'p.', connection=connection)}
                    from observed_evidence o
                    join reflection_evidence r on r.phase_id = o.phase_id
                    join phases p on p.rowid = o.phase_id
                    order by strong_anchor_hits desc,
                             anchor_intensity_support desc,
                             anchor_hits desc,
                             weighted_intensity_support desc,
                             weighted_observed_hits desc,
                             observed_hits desc,
                             peak_hits desc,
                             matched_intensity desc,
                             best_delta asc,
                             p.updated_at desc,p.source,p.entry_id
                    limit ?
                    """,
                    (*query_params, *params, max(limit * 3, limit)),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if was_cancelled:
                    raise CancelledError('Peak search cancelled') from exc
                raise LocalPhaseSearchError(exc) from exc
            finally:
                connection.set_progress_handler(None, 0)
        results = []
        seen = set()
        for row in rows:
            dedupe_key = self._dedupe_key(row)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(self._row_to_summary(row) if summary_only else self._row_to_entry(row))
            if len(results) >= limit:
                break
        return results

    def search_by_geometric_fingerprint(
        self,
        positions: list[float],
        *,
        elements: list[str] | None = None,
        excluded_elements: list[str] | None = None,
        sources: list[str] | None = None,
        limit: int = 500,
        summary_only: bool = False,
        cancelled=None,
        progress=None,
    ) -> list[CachedPhaseEntry | CachedPhaseSummary]:
        """Retrieve a bounded shortlist from the complete local peak index."""

        from concurrent.futures import CancelledError
        if cancelled is not None and cancelled():
            raise CancelledError('Geometric search cancelled')
        query_peaks = [
            SimpleNamespace(two_theta=float(position), intensity=float(len(positions) - index))
            for index, position in enumerate(positions)
            if isinstance(position, Real) and math.isfinite(float(position))
        ]
        query_hashes = peak_geometric_hashes(
            query_peaks,
            max_peaks=10,
            expanded=False,
        )
        if not query_hashes:
            return []
        required = {element.strip() for element in elements or [] if element.strip()}
        excluded = {element.strip() for element in excluded_elements or [] if element.strip()}
        allowed_sources = {source.strip() for source in sources or [] if source.strip()}
        versions = (*REINDEXABLE_CACHE_VERSIONS, DERIVED_CACHE_VERSION)
        where = [f"p.derived_version in ({', '.join('?' for _ in versions)})"]
        params: list[object] = list(versions)
        if allowed_sources:
            placeholders = ", ".join("?" for _ in allowed_sources)
            where.append(f"p.source in ({placeholders})")
            params.extend(sorted(allowed_sources))
        for element in sorted(required):
            where.append(
                "exists (select 1 from phase_elements pe "
                "where pe.source=p.source and pe.entry_id=p.entry_id and pe.element=?)"
            )
            params.append(element)
        for element in sorted(excluded):
            where.append(
                "not exists (select 1 from phase_elements pe "
                "where pe.source=p.source and pe.entry_id=p.entry_id and pe.element=?)"
            )
            params.append(element)
        self.ensure_geometric_fingerprint_index(cancelled=cancelled, progress=progress)
        was_cancelled = False

        def abort():
            nonlocal was_cancelled
            if cancelled is not None and cancelled():
                was_cancelled = True
            return int(was_cancelled)

        try:
            with closing(self._connect()) as connection, connection:
                connection.set_progress_handler(abort, 5000)
                try:
                    if abort():
                        raise CancelledError('Geometric search cancelled')
                    # A legacy read-only Gain may have no fingerprint tables.
                    # Existing ready fingerprints remain usable; line retrieval
                    # supplies the independent fallback for unprepared cards.
                    if getattr(self, '_read_only', False):
                        tables = {row[0] for row in connection.execute(
                            "select name from sqlite_master where type='table' "
                            "and name in ('phase_fingerprints','phase_fingerprint_state')")}
                        if len(tables) != 2:
                            return []
                    connection.execute(
                        "create temp table if not exists query_geometric_hashes "
                        "(hash integer primary key) without rowid"
                    )
                    connection.execute("delete from query_geometric_hashes")
                    connection.executemany(
                        "insert or ignore into query_geometric_hashes(hash) values(?)",
                        [(int(value),) for value in query_hashes],
                    )
                    rows = connection.execute(
                        f"""
                        select {self._search_columns(summary_only, 'p.')},
                               count(distinct pf.hash) as fingerprint_votes
                        from query_geometric_hashes q
                        join phase_fingerprints pf on pf.hash=q.hash
                        join phase_fingerprint_state fs on fs.source=pf.source and fs.entry_id=pf.entry_id and fs.version=?
                        join phases p on p.source=pf.source and p.entry_id=pf.entry_id
                        where {" and ".join(where)}
                        group by p.source,p.entry_id
                        order by fingerprint_votes desc,p.updated_at desc
                        limit ?
                        """,
                        (GEOMETRIC_FINGERPRINT_VERSION, *params, max(1, int(limit))),
                    ).fetchall()
                    if abort():
                        raise CancelledError('Geometric search cancelled')
                finally:
                    connection.set_progress_handler(None, 0)
        except sqlite3.Error as error:
            if was_cancelled:
                raise CancelledError('Geometric search cancelled') from error
            raise LocalPhaseSearchError(error) from error
        return [(self._row_to_summary(row) if summary_only else self._row_to_entry(row)) for row in rows]

    def ensure_geometric_fingerprint_index(self, *, progress=None, cancelled=None) -> int:
        """Build legacy fingerprints atomically and cooperatively in a writer.

        Read-only ranking never attempts a migration. It uses the ready subset
        of this optional index and continues through independent line search.
        """
        from concurrent.futures import CancelledError
        was_cancelled = False

        def abort():
            nonlocal was_cancelled
            if cancelled is not None and cancelled():
                was_cancelled = True
            return int(was_cancelled)

        def check_cancelled():
            if abort():
                raise CancelledError('Geometric index preparation cancelled')

        check_cancelled()
        if getattr(self, '_read_only', False):
            return 0

        versions = (*REINDEXABLE_CACHE_VERSIONS, DERIVED_CACHE_VERSION)
        try:
            with closing(self._connect()) as connection, connection:
                connection.set_progress_handler(abort, 5000)
                try:
                    missing = connection.execute(
                        f"""
                        select p.source,p.entry_id
                        from phases p
                        where p.derived_version in ({', '.join('?' for _ in versions)})
                          and exists (
                              select 1 from phase_peaks pp
                              where pp.source=p.source and pp.entry_id=p.entry_id
                          )
                          and not exists (
                              select 1 from phase_fingerprint_state fs
                              where fs.source=p.source and fs.entry_id=p.entry_id and fs.version=?
                          )
                        """,
                        (*versions, GEOMETRIC_FINGERPRINT_VERSION),
                    ).fetchall()
                    if progress is not None and missing:
                        progress('Preparing geometric peak index...', 0, len(missing))
                    progress_step = max(1, len(missing) // 100)
                    for index, row in enumerate(missing):
                        check_cancelled()
                        peaks = connection.execute(
                            """
                            select two_theta,norm_intensity,intensity
                            from phase_peaks
                            where source=? and entry_id=? and top_rank is not null
                            order by top_rank
                            limit ?
                            """,
                            (row['source'], row['entry_id'], GEOMETRIC_FINGERPRINT_PEAK_LIMIT),
                        ).fetchall()
                        self._replace_phase_fingerprints(connection, row['source'], row['entry_id'], peaks)
                        if progress is not None and ((index + 1) % progress_step == 0 or index + 1 == len(missing)):
                            progress('Preparing geometric peak index...', index + 1, len(missing))
                    check_cancelled()
                finally:
                    # Disable before the connection context commits/rolls back.
                    connection.set_progress_handler(None, 0)
        except sqlite3.Error as error:
            if was_cancelled:
                raise CancelledError('Geometric index preparation cancelled') from error
            raise LocalPhaseSearchError(error) from error
        return len(missing)

    @staticmethod
    def _d_from_two_theta(two_theta: float, wavelength: float) -> float | None:
        theta = math.radians(float(two_theta) / 2.0)
        sine = math.sin(theta)
        if sine <= 0.0:
            return None
        d_spacing = float(wavelength) / (2.0 * sine)
        return d_spacing if math.isfinite(d_spacing) and d_spacing > 0.0 else None

    def _d_tolerance_from_two_theta_window(self, two_theta: float, tolerance: float, wavelength: float) -> float:
        low = self._d_from_two_theta(max(float(two_theta) - float(tolerance), 0.001), wavelength)
        high = self._d_from_two_theta(float(two_theta) + float(tolerance), wavelength)
        center = self._d_from_two_theta(float(two_theta), wavelength)
        values = [value for value in (low, high, center) if value is not None]
        if len(values) < 2:
            return 0.02
        return max(abs(value - float(center or values[0])) for value in values) + 1.0e-6

    def download_cod_entry(self, entry: CodEntry, cod_online: CodOnlineService) -> Path:
        self.upsert_cod_entries([entry])
        cif_path = cod_online.download_cif(entry.cod_id, self.cif_dir)
        self.index_cif(cif_path, source="COD", entry_id=entry.cod_id, fallback=entry)
        return cif_path

    def add_user_cif(self, cif_path: str | Path) -> CachedPhaseEntry:
        source_path = Path(cif_path)
        user_dir = self.root / "user_cif"
        user_dir.mkdir(parents=True, exist_ok=True)
        existing_user_path = self._matching_user_cif_path(user_dir, source_path)
        if existing_user_path is not None:
            entry_id = existing_user_path.stem
            if not self.index_cif(existing_user_path, source="USER", entry_id=entry_id):
                raise ValueError(f"Cannot import CIF '{source_path}': {self._last_reference_preparation_error}")
            entry = self.get("USER", entry_id)
            if entry is not None:
                return entry
            raise ValueError(f"CIF was not indexed: {source_path}")
        target_path = user_dir / source_path.name
        if (
            target_path.exists()
            and target_path.resolve() != source_path.resolve()
            and not self._same_file_content(target_path, source_path)
        ):
            target_path = user_dir / f"{source_path.stem}_{time.time_ns()}{source_path.suffix}"
            while target_path.exists():
                target_path = user_dir / f"{source_path.stem}_{time.time_ns()}{source_path.suffix}"
        created_copy = False
        if target_path.resolve() != source_path.resolve():
            if not target_path.exists() or not self._same_file_content(target_path, source_path):
                shutil.copy2(source_path, target_path)
                created_copy = True
        entry_id = target_path.stem
        if not self.index_cif(target_path, source="USER", entry_id=entry_id):
            if created_copy:
                target_path.unlink(missing_ok=True)
            raise ValueError(f"Cannot import CIF '{source_path}': {self._last_reference_preparation_error}")
        entry = self.get("USER", entry_id)
        if entry is None:
            raise ValueError(f"CIF was not indexed: {source_path}")
        return entry

    def _matching_user_cif_path(self, user_dir: Path, source_path: Path) -> Path | None:
        try:
            if not source_path.is_file():
                return None
            source_digest = self._file_sha256(source_path)
            source_size = source_path.stat().st_size
        except OSError:
            return None
        for candidate in user_dir.glob("*.cif"):
            try:
                if candidate.resolve() == source_path.resolve():
                    return candidate
                if candidate.stat().st_size == source_size and self._file_sha256(candidate) == source_digest:
                    return candidate
            except OSError:
                continue
        return None

    def _same_file_content(self, left: Path, right: Path) -> bool:
        try:
            left_stat = left.stat()
            right_stat = right.stat()
            if left_stat.st_size != right_stat.st_size:
                return False
            if left.resolve() == right.resolve():
                return True
            return self._file_sha256(left) == self._file_sha256(right)
        except OSError:
            return False

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def install_embedded_cif(self, cif_path: str | Path, source: str, entry_id: str) -> Path | None:
        existing_entry = self.get(source, entry_id)
        if existing_entry is not None:
            return Path(existing_entry.cif_path) if existing_entry.cif_path else None

        source_path = Path(cif_path)
        if not source_path.is_file():
            raise FileNotFoundError(f"Embedded CIF does not exist: {source_path}")
        if not source or not entry_id:
            raise ValueError("Embedded CIF source and entry id are required.")

        source_dir = _embedded_source_dir_name(source)
        cache_key = hashlib.sha256(f"{source}\0{entry_id}".encode("utf-8")).hexdigest()[:24]
        target_dir = self.root / "embedded_cif" / source_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{cache_key}.cif"
        if target_path.resolve() != source_path.resolve():
            shutil.copy2(source_path, target_path)
        if self.index_cif(target_path, source=source, entry_id=entry_id, if_absent=True):
            return target_path

        concurrent_entry = self.get(source, entry_id)
        concurrent_path = (
            Path(concurrent_entry.cif_path)
            if concurrent_entry is not None and concurrent_entry.cif_path
            else None
        )
        if (
            target_path.resolve() != source_path.resolve()
            and (concurrent_path is None or target_path.resolve() != concurrent_path.resolve())
        ):
            target_path.unlink(missing_ok=True)
        return concurrent_path

    def cif_path(self, source: str, entry_id: str) -> Path | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "select cif_path from phases where source = ? and entry_id = ?",
                (source, entry_id),
            ).fetchone()
        if not row or not row["cif_path"]:
            return None
        path = Path(row["cif_path"])
        return path if path.exists() else None

    def cif_path_for_cache_id(self, cache_id: str) -> Path | None:
        if ":" in cache_id:
            source, entry_id = cache_id.split(":", 1)
            return self.cif_path(source, entry_id)
        return self.cif_path("COD", cache_id)

    def get(self, source: str, entry_id: str) -> CachedPhaseEntry | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                select source, entry_id, formula, name, spacegroup, source_text, cif_path, elements,
                       a, b, c, alpha, beta, gamma, volume, atoms_json, iic, iic_method, peaks_json, top_peaks_json, derived_version
                from phases
                where source = ? and entry_id = ?
                """,
                (source, entry_id),
            ).fetchone()
        return self._row_to_entry(row) if row else None

    def iic_entries(
        self, keys: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], CachedPhaseEntry]:
        requested = list(dict.fromkeys(keys))
        if not requested:
            return {}
        entries = {}
        with closing(self._connect()) as connection:
            # Two parameters per key; support older SQLite's 999-variable limit.
            for offset in range(0, len(requested), 450):
                batch = requested[offset:offset + 450]
                values = ",".join("(?,?)" for _ in batch)
                rows = connection.execute(
                    f"""
                    with requested(source, entry_id) as (values {values})
                    select p.source, p.entry_id, p.iic, p.iic_method, p.derived_version
                    from requested r
                    join phases p on p.source=r.source and p.entry_id=r.entry_id
                    """,
                    [value for key in batch for value in key],
                ).fetchall()
                for row in rows:
                    entry = CachedPhaseEntry(**dict(row))
                    entries[(entry.source, entry.entry_id)] = entry
        return entries

    def preparation_states(
        self, keys: Iterable[tuple[str, str]],
    ) -> dict[tuple[str, str], CachedPreparationState]:
        requested = list(dict.fromkeys(
            (str(source).strip().upper(), str(entry_id).strip())
            for source, entry_id in keys
            if str(source).strip() and str(entry_id).strip()
        ))
        if not requested:
            return {}
        states = {}
        with closing(self._connect()) as connection:
            # Stay below the 999-variable limit of older SQLite runtimes.
            for offset in range(0, len(requested), 450):
                batch = requested[offset:offset + 450]
                values = ",".join("(?,?)" for _ in batch)
                try:
                    rows = connection.execute(
                        f"""
                        with requested(source, entry_id) as (values {values})
                        select p.source, p.entry_id, p.cif_path, p.source_text, p.derived_version,
                               exists(select 1 from phase_peaks pp
                                      where pp.source=p.source and pp.entry_id=p.entry_id) as has_peaks
                        from requested r
                        join phases p on p.source=r.source and p.entry_id=r.entry_id
                        """,
                        [value for key in batch for value in key],
                    ).fetchall()
                except sqlite3.OperationalError as exc:
                    raise LocalPhaseSearchError(exc) from exc
                for row in rows:
                    states[(row["source"], row["entry_id"])] = CachedPreparationState(
                        cif_path=str(row["cif_path"] or ""),
                        source_text=str(row["source_text"] or ""),
                        derived_version=int(row["derived_version"] or 0),
                        has_peaks=bool(row["has_peaks"]),
                    )
        return states

    def peak_records(self, source: str, entry_id: str) -> list[dict[str, object]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                select peak_index, two_theta, d, intensity, norm_intensity, top_rank,
                       raw_intensity, h, k, l, multiplicity, intrinsic_intensity, intensity_origin
                from phase_peaks
                where source = ? and entry_id = ?
                order by peak_index
                """,
                (str(source or "").upper(), str(entry_id or "")),
            ).fetchall()
        return [dict(row) for row in rows]

    def reference_revision(self, sources=None):
        """Small metadata token; never loads CIF atoms or peak JSON on the GUI thread."""
        allowed = sorted({str(source).upper() for source in sources or []})
        where = f"where source in ({', '.join('?' for _ in allowed)})" if allowed else ''
        with closing(self._connect()) as connection, connection:
            row = connection.execute(f'select count(*), max(updated_at) from phases {where}', allowed).fetchone()
        return int(row[0]), float(row[1] or 0.)

    def entries_with_peaks(self, sources: list[str] | None = None, limit: int | None = None) -> list[CachedPhaseEntry]:
        where = ["peaks_json != ''"]
        params: list[object] = []
        allowed_sources = [source.strip() for source in sources or [] if source.strip()]
        if allowed_sources:
            placeholders = ", ".join("?" for _ in allowed_sources)
            where.append(f"source in ({placeholders})")
            params.extend(sorted(allowed_sources))
        sql = f"""
            select source, entry_id, formula, name, spacegroup, source_text, cif_path, elements,
                   a, b, c, alpha, beta, gamma, volume, atoms_json, iic, iic_method, peaks_json, top_peaks_json, derived_version
            from phases
            where {" and ".join(where)}
            order by updated_at desc
        """
        if limit is not None:
            sql += " limit ?"
            params.append(max(0, int(limit)))
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def diffraction_rows(self, source: str, entry_id: str, limit: int = 60, *,
                         wavelength=None, instrument_profile=None) -> list[list[str]]:
        entry = self.get(source, entry_id)
        if entry is None or not entry.peaks_json:
            return []
        try:
            peaks = json.loads(entry.peaks_json)
        except json.JSONDecodeError:
            return []
        if wavelength is not None:
            from xrd_finder.services.auto_search_ranker import _cached_reference_peaks
            peaks = [{
                name: getattr(peak, name) for name in ('d', 'two_theta', 'intensity', 'h', 'k', 'l', 'multiplicity')}
                for peak in _cached_reference_peaks(peaks, wavelength, instrument_profile=instrument_profile)]
        rows = []
        for peak in peaks[:limit]:
            rows.append([
                f"{float(peak.get('d', 0.0)):.4f}",
                f"{float(peak.get('two_theta', 0.0)):.3f}",
                f"{float(peak.get('intensity', 0.0)):.1f}",
                str(peak.get("h", "")),
                str(peak.get("k", "")),
                str(peak.get("l", "")),
                str(peak.get("multiplicity", "")),
            ])
        return rows

    def build_index(self, progress=None) -> int:
        indexed_keys: set[tuple[str, str]] = set()
        successful = 0
        with closing(self._connect()) as connection, connection:
            cached_rows = connection.execute(
                "select source, entry_id, cif_path from phases where cif_path != '' order by source, entry_id"
            ).fetchall()
        existing_rows = [
            row
            for row in cached_rows
            if Path(str(row["cif_path"] or "")).is_file()
        ]
        total = len(existing_rows)
        for position, row in enumerate(existing_rows, start=1):
            cif_path = Path(str(row["cif_path"] or ""))
            source = str(row["source"] or "").upper()
            entry_id = str(row["entry_id"] or "")
            if progress is not None:
                progress(f"Recalculating {source} {entry_id} with CrIStMa", position, total)
            successful += bool(self.index_cif(cif_path, source=source, entry_id=entry_id))
            indexed_keys.add((source, entry_id))

        for cif_path in self.cif_dir.glob("*.cif"):
            key = ("COD", cif_path.stem)
            if key in indexed_keys:
                continue
            successful += bool(self.index_cif(cif_path, source=key[0], entry_id=key[1]))
            indexed_keys.add(key)
        user_dir = self.root / "user_cif"
        for cif_path in user_dir.glob("*.cif") if user_dir.exists() else []:
            key = ("USER", cif_path.stem)
            if key in indexed_keys:
                continue
            successful += bool(self.index_cif(cif_path, source=key[0], entry_id=key[1]))
            indexed_keys.add(key)
        return successful

    def clear_user_library(self) -> None:
        self._clear_sources(["USER"])
        self._remove_cache_dirs(["user_cif"])

    def export_user_library(self, path: str | Path) -> int:
        return self.export_phase_library(path, sources=["USER"], library_name="user_phase_library")

    def import_user_library(self, path: str | Path) -> int:
        return self.import_phase_library(path, allowed_sources=["USER"])

    def export_phase_library(
        self,
        path: str | Path,
        *,
        sources: list[str] | tuple[str, ...],
        library_name: str = "phase_library",
    ) -> int:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        normalized_sources = [str(source or "").upper() for source in sources if str(source or "").strip()]
        if not normalized_sources:
            raise ValueError("At least one source is required for export.")
        placeholders = ", ".join("?" for _ in normalized_sources)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                select source, entry_id, formula, name, spacegroup, source_text, cif_path, elements,
                       a, b, c, alpha, beta, gamma, volume, atoms_json, iic, iic_method, peaks_json, top_peaks_json, derived_version
                from phases
                where source in ({placeholders})
                order by source, name, entry_id
                """,
                normalized_sources,
            ).fetchall()
        entries = []
        for row in rows:
            entry = dict(row)
            cif_text = ""
            cif_path = Path(str(entry.get("cif_path") or ""))
            if cif_path.is_file():
                try:
                    cif_text = cif_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    cif_text = ""
            entry["cif_text"] = cif_text
            entry.pop("cif_path", None)
            entries.append(entry)
        payload = {
            "schema_version": 1,
            "application": "XRD Phase Finder",
            "library": library_name,
            "sources": normalized_sources,
            "entries": entries,
        }
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return len(entries)

    def import_phase_library(
        self,
        path: str | Path,
        *,
        allowed_sources: list[str] | tuple[str, ...] | None = None,
    ) -> int:
        source_path = Path(path)
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("library") not in {"user_phase_library", "phase_library"}:
            raise ValueError("Unsupported phase library file")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise ValueError("Phase library file does not contain entries")
        allowed = {
            str(source or "").upper()
            for source in (allowed_sources or TRANSFERABLE_LIBRARY_SOURCES)
            if str(source or "").strip()
        }
        imported = 0
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            source = str(entry.get("source") or "").upper()
            if source not in allowed or source not in TRANSFERABLE_LIBRARY_SOURCES:
                continue
            cif_text = str(entry.get("cif_text") or "")
            if not cif_text.strip():
                continue
            entry_id = str(entry.get("entry_id") or f"user_phase_{index + 1}").strip() or f"user_phase_{index + 1}"
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", entry_id).strip("._") or f"user_phase_{index + 1}"
            import_dir = self._transfer_import_dir(source)
            import_dir.mkdir(parents=True, exist_ok=True)
            temporary_path = import_dir / f"{safe_id}.cif"
            counter = 1
            while temporary_path.exists() and temporary_path.read_text(encoding="utf-8", errors="replace") != cif_text:
                temporary_path = import_dir / f"{safe_id}_{counter}.cif"
                counter += 1
            temporary_path.write_text(cif_text, encoding="utf-8")
            before = self.get(source, entry_id)
            cached_entry = self._entry_from_transfer_payload(entry, source, entry_id, temporary_path)
            with closing(self._connect()) as connection, connection:
                self._upsert(connection, cached_entry, keep_cif=False)
            if before is None:
                imported += 1
        return imported

    def _entry_from_transfer_payload(
        self,
        payload: dict[str, object],
        source: str,
        entry_id: str,
        cif_path: Path,
    ) -> CachedPhaseEntry:
        return CachedPhaseEntry(
            source=source,
            entry_id=entry_id,
            formula=str(payload.get("formula") or ""),
            name=str(payload.get("name") or entry_id),
            spacegroup=str(payload.get("spacegroup") or ""),
            source_text=str(payload.get("source_text") or ""),
            cif_path=str(cif_path),
            a=self._optional_float(payload.get("a")),
            b=self._optional_float(payload.get("b")),
            c=self._optional_float(payload.get("c")),
            alpha=self._optional_float(payload.get("alpha")),
            beta=self._optional_float(payload.get("beta")),
            gamma=self._optional_float(payload.get("gamma")),
            volume=self._optional_float(payload.get("volume")),
            atoms_json=str(payload.get("atoms_json") or ""),
            iic=self._optional_float(payload.get("iic")),
            iic_method=str(payload.get("iic_method") or ""),
            peaks_json=str(payload.get("peaks_json") or ""),
            top_peaks_json=str(payload.get("top_peaks_json") or ""),
            derived_version=int(payload.get("derived_version") or 0),
        )

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _transfer_import_dir(self, source: str) -> Path:
        source = str(source or "").upper()
        if source == "USER":
            return self.root / "user_cif_imports"
        if source == "COD":
            return self.root / "cod_bulk_cif" / "imported"
        if source == "MP":
            return self.root / "materials_project_cif" / "imported"
        return self.root / "imported_cif" / _embedded_source_dir_name(source)

    def clear_cod_cache(self) -> None:
        self._clear_sources(["COD"])
        self._remove_cache_dirs(["cif", "cod_bulk_cif", "downloads"])
        self.cif_dir.mkdir(parents=True, exist_ok=True)

    def clear_materials_project_cache(self) -> None:
        self._clear_sources(["MP"])
        self._remove_cache_dirs(["materials_project_cif"])

    def clear_aflow_cache(self) -> None:
        self._clear_sources(["AFLOW"])
        self._remove_cache_dirs(["aflow_cif"])

    def clear_oqmd_cache(self) -> None:
        self._clear_sources(["OQMD"])
        self._remove_cache_dirs(["oqmd_cif"])

    def index_cif_folder(self, folder: str | Path, source: str = "COD") -> int:
        root = Path(folder)
        if not root.exists():
            raise FileNotFoundError(f"Folder does not exist: {root}")
        count = 0
        for cif_path in root.rglob("*.cif"):
            if self.index_cif(cif_path, source=source, entry_id=cif_path.stem):
                count += 1
        return count

    @native_cif_session
    def _validated_search_formula(self, cif_path):
        from xrd_finder.finder.composition_validation import (
            occupied_composition,empirical_search_formula,validate_composition,CifCompositionError)
        if not hasattr(self,'_cristma_powder_adapter'):
            from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
            self._cristma_powder_adapter = CristmaPowderAdapter()
        native,_setting = self._cristma_powder_adapter._structure_and_setting(cif_path)
        composition = occupied_composition(native)
        occupied_formula = empirical_search_formula(composition)
        reported = native.formula or ''
        warning = ''
        try:
            validate_composition(reported,composition)
        except CifCompositionError as exc:
            warning = str(exc)
        if not warning and formula_elements(reported) != set(composition) and reported:
            warning = 'Reported element labels include elements absent from occupied positions'
        # A contradictory/uninterpretable header must never control element
        # filtering. Keep the source CIF intact and Quant's independent guard.
        formula = occupied_formula if warning or not reported else re.sub(r'\s+','',reported)
        return formula,reported,composition,warning

    def audit_compositions(self, sources=None, progress=None, cancelled=None):
        """Read-only audit; explicit Build index reindexes affected structures."""
        from concurrent.futures import CancelledError
        from xrd_finder.finder.composition_validation import validate_composition, CifCompositionError
        where = "p.cif_path != ''"
        params = []
        if sources:
            where += ' and p.source in (' + ','.join('?' for _ in sources) + ')'
            params.extend(sources)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "select p.source,p.entry_id,p.formula,p.cif_path,p.elements,"
                "coalesce((select group_concat(e.element,' ') from phase_elements e "
                "where e.source=p.source and e.entry_id=p.entry_id),'') as indexed_elements "
                f"from phases p where {where} order by p.source,p.entry_id",params).fetchall()
        reports=[]
        for index,row in enumerate(rows):
            if cancelled is not None and cancelled():
                raise CancelledError('Composition audit cancelled')
            if progress is not None:
                progress('Checking cached CIF composition',index+1,len(rows))
            try:
                expected,reported,composition,warning = self._validated_search_formula(row['cif_path'])
                needs_reindex=False
                try:
                    if not row['formula'].strip():
                        raise CifCompositionError('Cached formula is empty')
                    validate_composition(row['formula'],composition)
                except CifCompositionError as exc:
                    warning = '; '.join(filter(None,(warning,str(exc))))
                    needs_reindex=True
                if warning and self._normalize_formula(row['formula']) != self._normalize_formula(expected):
                    warning = '; '.join(filter(None,(warning,'Cached search formula differs from the current occupied formula')))
                    needs_reindex=True
                if (set(row['elements'].split()) != set(composition)
                        or set(row['indexed_elements'].split()) != set(composition)):
                    warning = '; '.join(filter(None,(warning,'Element index differs from occupied composition')))
                    needs_reindex=True
                reports.append(CachedCompositionCheck(row['source'],row['entry_id'],row['cif_path'],
                    row['formula'],reported,expected,warning,needs_reindex))
            except Exception as exc:
                reports.append(CachedCompositionCheck(row['source'],row['entry_id'],row['cif_path'],
                    row['formula'],'','',f'{type(exc).__name__}: {exc}',False,'unavailable'))
        return reports

    @native_cif_session
    def index_cif(
        self,
        cif_path: str | Path,
        source: str,
        entry_id: str,
        fallback: CodEntry | None = None,
        *,
        if_absent: bool = False,
        reference_range: tuple[float, float, float] | None = None,
        preserve_existing_on_failure: bool = False,
    ) -> bool:
        cif_path = Path(cif_path)
        try:
            source_hash = hashlib.sha256(cif_path.read_bytes()).hexdigest()
            _phase, structure = create_phase_from_cif(cif_path)
            search_formula,_reported,_composition,composition_warning = self._validated_search_formula(cif_path)
            formula = self._best_formula(search_formula, fallback.formula if fallback else "")
            if composition_warning:
                logging.getLogger(__name__).warning(
                    '%s %s: %s; search uses occupied composition %s; source CIF is unchanged',
                    source,entry_id,composition_warning,formula)
            name = self._best_name(structure.name, fallback.name if fallback else "", formula, entry_id)
            spacegroup = structure.space_group or (fallback.spacegroup if fallback else "")
            source_text = (fallback.source if fallback else "") or str(structure.metadata.get("publication", "") or "")
            cell = structure.cell
            atoms_json = self._atoms_to_json(structure)
            support = self._calculation_support(source, entry_id, reference_range)
            calculated_peaks = self._calculate_cached_peaks(
                structure, cif_path, wavelength=support['wavelength'],
                two_theta_min=self._angle_from_d(support['d_max'], support['wavelength']),
                two_theta_max=self._angle_from_d(support['d_min'], support['wavelength']),
            )
            native_peaks = calculated_peaks
            reference_peaks = extract_cif_powder_peaks(
                cif_path,
                wavelength=float(getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH),
                intensity_min=0.5,
            )
            peaks = reference_peaks or calculated_peaks
            if not peaks:
                raise ValueError('CIF has no usable diffraction reflections')
            peaks_json = self._peaks_to_json(peaks, origin="reference-pattern" if reference_peaks else None,
                                           support=None if reference_peaks else support)
            top_peaks_json = self._top_peaks_to_json(peaks)
            # A legacy fallback can still supply search peaks, but never RIR.
            # Both sides of the intensity ratio must use the native engine.
            existing = self.get(source, entry_id)
            try:
                previous_iic = json.loads(existing.iic_method) if existing is not None else {}
            except (ValueError, TypeError):
                previous_iic = {}
            if (existing is not None and previous_iic.get('structure') == source_hash
                    and self.calculated_iic.value_current(existing.iic, existing.iic_method)):
                iic, iic_method = existing.iic, existing.iic_method
            else:
                # RIR is always Cu K-alpha1, even if the requested support is Mo.
                cu_peaks = ([peak for peak in native_peaks if 5. <= peak.two_theta <= 120.]
                            if support['wavelength'] == CU_KA1_WAVELENGTH else None)
                iic, iic_method = self._calculated_iic_record(cif_path, cu_peaks)
            if hashlib.sha256(cif_path.read_bytes()).hexdigest() != source_hash:
                raise ValueError('CIF changed during reference preparation')
            derived_version = DERIVED_CACHE_VERSION
        except Exception as exc:
            self._last_reference_preparation_error = f'{type(exc).__name__}: {exc}'
            if exc.__cause__ is not None:
                self._last_reference_preparation_error += f' ({exc.__cause__})'
            # Catalog registration is separate from successful CIF preparation.
            # A failed attempt must never replace an already usable structure.
            return False
        entry = CachedPhaseEntry(
            source=source,
            entry_id=entry_id,
            formula=formula,
            name=name,
            spacegroup=spacegroup,
            source_text=source_text,
            cif_path=str(cif_path),
            a=getattr(cell, "a", None),
            b=getattr(cell, "b", None),
            c=getattr(cell, "c", None),
            alpha=getattr(cell, "alpha", None),
            beta=getattr(cell, "beta", None),
            gamma=getattr(cell, "gamma", None),
            volume=getattr(cell, "volume", None),
            atoms_json=atoms_json,
            iic=iic,
            iic_method=iic_method,
            peaks_json=peaks_json,
            top_peaks_json=top_peaks_json,
            derived_version=derived_version,
        )
        with closing(self._connect()) as connection, connection:
            return self._upsert(connection, entry, keep_cif=False, insert_only=if_absent)

    @staticmethod
    def _requested_d_range(wavelength, two_theta_min=5., two_theta_max=120.):
        wavelength, low, high = float(wavelength), float(two_theta_min), float(two_theta_max)
        if not all(math.isfinite(v) for v in (wavelength, low, high)) or wavelength <= 0. or not 0. < low < high < 180.:
            raise ValueError('Invalid reference wavelength or angular range')
        return (wavelength / (2. * math.sin(math.radians(high / 2.))),
                wavelength / (2. * math.sin(math.radians(low / 2.))))

    @staticmethod
    def _angle_from_d(d, wavelength):
        return round(math.degrees(2. * math.asin(float(wavelength) / (2. * float(d)))), 12)

    @staticmethod
    def _stored_reference_support(entry):
        try:
            text = entry.peaks_json.lstrip()
            if not text.startswith('['):
                return None
            offset = 1
            while offset < len(text) and text[offset].isspace():
                offset += 1
            first, _end = json.JSONDecoder().raw_decode(text, offset)
            if not isinstance(first, dict):
                return None
            if first.get('intensity_origin') == 'reference-pattern':
                return {'kind': 'measured'}
            support = first.get('reference_support')
            if support is None and entry.derived_version == DERIVED_CACHE_VERSION and first.get(
                    'intensity_origin') == 'cristma-structure':
                # Version11's original, known generation contract was Cu5–120.
                low, high = LocalPhaseCache._requested_d_range(CU_KA1_WAVELENGTH)
                return {'d_min': low, 'd_max': high, 'wavelength': CU_KA1_WAVELENGTH}
            if not isinstance(support, dict):
                return None
            low, high, wavelength = (float(support[key]) for key in ('d_min', 'd_max', 'wavelength'))
            if all(math.isfinite(v) for v in (low, high, wavelength)) and 0. < low < high and 0. < wavelength < 2.*low:
                return {'d_min': low, 'd_max': high, 'wavelength': wavelength}
        except (AttributeError, TypeError, ValueError, KeyError):
            pass
        return None

    def _calculation_support(self, source, entry_id, requested):
        low, high = self._requested_d_range(CU_KA1_WAVELENGTH)
        wavelength = CU_KA1_WAVELENGTH
        old = self._stored_reference_support(self.get(source, entry_id))
        if old and old.get('kind') != 'measured':
            low, high = min(low, old['d_min']), max(high, old['d_max'])
            wavelength = min(wavelength, old['wavelength'])
        if requested is not None:
            requested_low, requested_high = self._requested_d_range(*requested)
            low, high = min(low, requested_low), max(high, requested_high)
            wavelength = min(wavelength, float(requested[0]))
        return {'d_min': low, 'd_max': high, 'wavelength': wavelength}

    def _reference_support_entry(self, source, entry_id):
        # The support contract is in the first reflection. Avoid transferring
        # atoms and the complete reflection JSON just to check its range.
        with closing(self._connect()) as connection:
            row = connection.execute(
                "select derived_version, substr(peaks_json,1,1024) as first_lines "
                "from phases where source=? and entry_id=?", (source, entry_id)).fetchone()
        if row is None:
            return None
        return self._reference_prefix_entry(source, entry_id, row)

    def _reference_prefix_entry(self, source, entry_id, row, *, connection=None):
        text = row['first_lines'] or ''
        stripped = text.lstrip()
        if stripped.startswith('['):
            offset = len(text)-len(stripped)+1
            while offset < len(text) and text[offset].isspace():
                offset += 1
            try:
                json.JSONDecoder().raw_decode(text, offset)
            except ValueError:
                # Unusually long/custom first records keep the exact old
                # contract; a truncated prefix never certifies readiness.
                if len(text) == 1024:
                    if connection is None:
                        return self.get(source, entry_id)
                    full = connection.execute(
                        'select derived_version,peaks_json from phases where source=? and entry_id=?',
                        (source, entry_id)).fetchone()
                    return (CachedPhaseEntry(source, entry_id, derived_version=full['derived_version'],
                                             peaks_json=full['peaks_json']) if full is not None else None)
        return CachedPhaseEntry(source, entry_id, derived_version=row['derived_version'], peaks_json=text)

    def reference_range_coverage(self, keys, *, wavelength=CU_KA1_WAVELENGTH,
                                 two_theta_min=5., two_theta_max=120., for_search=False,
                                 cancelled=None):
        """Check a worker's population with one connection and bounded reads."""
        from concurrent.futures import CancelledError
        low, high = self._requested_d_range(wavelength, two_theta_min, two_theta_max)
        requested = list(dict.fromkeys((source, entry_id) for source, entry_id in keys))
        covered = dict.fromkeys(requested, False)
        if not requested:
            return covered
        with closing(self._connect()) as connection:
            for offset in range(0, len(requested), 450):
                if cancelled is not None and cancelled():
                    raise CancelledError('Reference readiness check cancelled')
                batch = requested[offset:offset+450]
                marks = ','.join('(?,?)' for _ in batch)
                rows = connection.execute(
                    f'with requested(source,entry_id) as (values {marks}) '
                    'select p.source,p.entry_id,p.derived_version,substr(p.peaks_json,1,1024) as first_lines '
                    'from requested r join phases p on p.source=r.source and p.entry_id=r.entry_id',
                    [value for key in batch for value in key])
                for row in rows:
                    key = (row['source'], row['entry_id'])
                    entry = self._reference_prefix_entry(*key, row, connection=connection)
                    covered[key] = self._entry_covers_reference_range(entry, low, high, for_search)
        return covered

    def reference_range_covered(self, source, entry_id, *, wavelength=CU_KA1_WAVELENGTH,
                               two_theta_min=5., two_theta_max=120., for_search=False):
        low, high = self._requested_d_range(wavelength, two_theta_min, two_theta_max)
        entry = self._reference_support_entry(source, entry_id)
        return self._entry_covers_reference_range(entry, low, high, for_search)

    def _entry_covers_reference_range(self, entry, low, high, for_search):
        if entry is None:
            return False
        legacy_geometry = for_search and entry.derived_version in REINDEXABLE_CACHE_VERSIONS
        if entry.derived_version != DERIVED_CACHE_VERSION and not legacy_geometry:
            return False
        support = self._stored_reference_support(entry)
        if support is None and legacy_geometry and entry.peaks_json:
            # Versions 9/10 stored Cu 5–120° geometry. It can retrieve cards
            # without re-reading every CIF. Scoring still requires version 11
            # and validated native intensities, through the default contract.
            old_low, old_high = self._requested_d_range(CU_KA1_WAVELENGTH)
            support = {'d_min': old_low, 'd_max': old_high}
        # Measured patterns are finite empirical data, not extensible structures.
        return bool(support and (support.get('kind') == 'measured' or (
            support['d_min'] <= low * (1. + 1.e-10) and support['d_max'] >= high * (1. - 1.e-10))))

    def ensure_reference_range(self, source, entry_id, *, wavelength=CU_KA1_WAVELENGTH,
                               two_theta_min=5., two_theta_max=120., for_search=False):
        """Expand structural d support in a worker; keep an existing valid cache on failure."""
        if self.reference_range_covered(source, entry_id, wavelength=wavelength,
                two_theta_min=two_theta_min, two_theta_max=two_theta_max, for_search=for_search):
            return True
        if getattr(self, "_read_only", False):
            return False
        path = self.cif_path(source, entry_id)
        if path is None:
            return False
        signature = hashlib.sha256(json.dumps((
            hashlib.sha256(path.read_bytes()).hexdigest(), DERIVED_CACHE_VERSION,
            float(wavelength), float(two_theta_min), float(two_theta_max),
            self.calculated_iic.signature,
        )).encode()).hexdigest()
        with closing(self._connect()) as connection:
            failed = connection.execute(
                'select signature from reference_preparation_failures where source=? and entry_id=?',
                (source, entry_id)).fetchone()
        if failed is not None and failed['signature'] == signature:
            return False
        if not self.index_cif(path, source, entry_id,
                reference_range=(wavelength, two_theta_min, two_theta_max), preserve_existing_on_failure=True):
            with closing(self._connect()) as connection, connection:
                connection.execute('insert or replace into reference_preparation_failures values (?,?,?,?,?)',
                    (source, entry_id, signature,
                     getattr(self, '_last_reference_preparation_error', 'Native preparation failed'), time.time()))
            return False
        with closing(self._connect()) as connection, connection:
            connection.execute('delete from reference_preparation_failures where source=? and entry_id=?',
                               (source, entry_id))
        return self.reference_range_covered(source, entry_id, wavelength=wavelength,
                two_theta_min=two_theta_min, two_theta_max=two_theta_max)

    def _calculate_cached_peaks(self, structure, cif_path: str | Path | None = None, *,
                                wavelength=CU_KA1_WAVELENGTH, two_theta_min=5., two_theta_max=120.) -> list:
        if cif_path is not None:
            try:
                from xrd_finder.instrument.models import InstrumentProfile, RadiationProfile
                from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter

                if self._cristma_powder_adapter is None:
                    self._cristma_powder_adapter = CristmaPowderAdapter()
                return list(
                    self._cristma_powder_adapter.reference_sticks_from_cif(
                        cif_path,
                        two_theta_min=two_theta_min,
                        two_theta_max=two_theta_max,
                        instrument_profile=(InstrumentProfile.default_cu_kalpha() if wavelength == CU_KA1_WAVELENGTH
                            else InstrumentProfile(radiation=RadiationProfile.custom_monochromatic(wavelength))),
                        use_lp=True,
                    )
                )
            except Exception as exc:
                raise ValueError("Cannot index validated CrIStMa structural intensities") from exc
        try:
            return self._calculated_pattern_service.calculate_sticks(
                structure,
                two_theta_min=5.0,
                two_theta_max=120.0,
                wavelength=float(getattr(structure, "wavelength", None) or CU_KA1_WAVELENGTH),
                use_lp=True,
                intensity_min=0.5,
            )
        except Exception:
            return []

    def _calculate_native_cached_peaks(self, path) -> list:
        return list(self._cristma_powder_adapter.reference_sticks_from_cif(
            path, two_theta_min=5., two_theta_max=120.,
            instrument_profile=self.calculated_iic.instrument, use_lp=True,
        ))

    def _peaks_to_json(self, peaks, *, origin=None, support=None) -> str:
        rows = []
        # Keep the complete generated range. An angle-ordered count limit can
        # discard strong high-angle families, especially in supercell CIFs.
        for peak in peaks:
            rows.append({
                "d": float(getattr(peak, "d", 0.0)),
                "two_theta": round(float(getattr(peak, "two_theta", 0.0)), 5),
                "intensity": round(float(getattr(peak, "intensity", 0.0)), 4),
                "raw_intensity": round(float(getattr(peak, "raw_intensity", 0.0)), 6),
                "h": int(getattr(peak, "h", 0)),
                "k": int(getattr(peak, "k", 0)),
                "l": int(getattr(peak, "l", 0)),
                "multiplicity": int(getattr(peak, "multiplicity", 1) or 1),
                "intrinsic_intensity": getattr(peak, "intrinsic_intensity", None),
                "intensity_origin": origin or getattr(peak, "intensity_origin", "") or "unknown",
            })
        if rows and support is not None:
            rows[0]['reference_support'] = support
        return json.dumps(rows, ensure_ascii=True, separators=(",", ":"))

    def _top_peaks_to_json(self, peaks, limit: int = 10) -> str:
        rows = []
        strongest = sorted(
            [
                peak
                for peak in peaks
                if 5.0 <= float(getattr(peak, "two_theta", 0.0) or 0.0) <= 60.0
                and float(getattr(peak, "intensity", 0.0) or 0.0) > 0.0
            ],
            key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0),
            reverse=True,
        )[: max(1, int(limit))]
        max_intensity = max((float(getattr(peak, "intensity", 0.0) or 0.0) for peak in strongest), default=0.0)
        if max_intensity <= 0.0:
            return ""
        for peak in strongest:
            rows.append([
                round(float(getattr(peak, "two_theta", 0.0) or 0.0), 5),
                round(max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0) / max_intensity, 4),
            ])
        return json.dumps(rows, ensure_ascii=True, separators=(",", ":"))

    def _top_peaks_json_from_peaks_json(self, peaks_json: str, limit: int = 10) -> str:
        if not peaks_json:
            return ""
        try:
            peaks = json.loads(peaks_json)
        except json.JSONDecodeError:
            return ""
        usable = []
        for peak in peaks if isinstance(peaks, list) else []:
            try:
                two_theta = float(peak.get("two_theta", 0.0) or 0.0)
                intensity = max(float(peak.get("intensity", 0.0) or 0.0), 0.0)
            except (TypeError, ValueError):
                continue
            if 5.0 <= two_theta <= 60.0 and intensity > 0.0:
                usable.append((two_theta, intensity))
        strongest = sorted(usable, key=lambda item: item[1], reverse=True)[: max(1, int(limit))]
        max_intensity = max((item[1] for item in strongest), default=0.0)
        if max_intensity <= 0.0:
            return ""
        return json.dumps(
            [[round(two_theta, 5), round(intensity / max_intensity, 4)] for two_theta, intensity in strongest],
            ensure_ascii=True,
            separators=(",", ":"),
        )

    def _calculated_iic_record(self, path: Path, peaks=None) -> tuple[float | None, str]:
        try:
            return self.calculated_iic.calculate(path, peaks)
        except (OSError, ValueError, RuntimeError) as exc:
            # Preserve why a value is unavailable; never substitute a legacy
            # estimate or invalidate otherwise usable search/structural data.
            return None, json.dumps({"signature": self.calculated_iic.signature,
                                     "status": "unavailable", "reason": str(exc)}, sort_keys=True)

    def update_calculated_iic(self, source: str, entry_id: str, path: str | Path) -> CachedPhaseEntry | None:
        value, method = self._calculated_iic_record(Path(path))
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "update phases set iic=?, iic_method=? where source=? and entry_id=? and cif_path=?",
                (value, method, source, entry_id, str(path)),
            )
        return self.get(source, entry_id)

    def outdated_iic_entries(self) -> list[CachedPhaseEntry]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "select source,entry_id,cif_path,iic,iic_method from phases p "
                "where cif_path != '' and derived_version=? and exists("
                "select 1 from phase_peaks pp where pp.source=p.source and pp.entry_id=p.entry_id)",
                (DERIVED_CACHE_VERSION,),
            ).fetchall()
        return [CachedPhaseEntry(source=row['source'], entry_id=row['entry_id'],
                                 cif_path=row['cif_path'], iic_method=row['iic_method']) for row in rows
                if not self.calculated_iic.value_current(row["iic"], row["iic_method"])]

    def ensure_peak_search_index(self,*,progress=None,cancelled=None):
        """Upgrade old range indexes in the search worker, with atomic rollback.

        No CIF or scientific data is recalculated. New databases already have
        this covering index; read-only legacy workers retain a usable old one.
        """
        from concurrent.futures import CancelledError
        if cancelled is not None and cancelled():
            raise CancelledError('Peak index preparation cancelled')
        columns=['d','source','entry_id','peak_index','top_rank','norm_intensity','intensity']
        with closing(self._connect()) as connection:
            stored=[row['name'] for row in connection.execute('pragma index_info(idx_phase_peaks_d)')]
            if stored==columns or getattr(self,'_read_only',False):
                return False
            if progress is not None:
                progress('Preparing local peak-search index (once)...',0,0)
            was_cancelled=False
            def abort():
                nonlocal was_cancelled
                was_cancelled=bool(cancelled is not None and cancelled())
                return int(was_cancelled)
            connection.set_progress_handler(abort,5000)
            try:
                connection.execute('begin immediate')
                connection.execute('drop index if exists idx_phase_peaks_d')
                connection.execute('create index idx_phase_peaks_d on phase_peaks('+','.join(columns)+')')
                connection.commit()
            except sqlite3.OperationalError as exc:
                connection.set_progress_handler(None,0)
                connection.rollback()
                if was_cancelled:
                    raise CancelledError('Peak index preparation cancelled') from exc
                raise LocalPhaseSearchError(exc) from exc
            finally:
                connection.set_progress_handler(None,0)
            if progress is not None:
                progress('Local peak-search index ready',1,1)
            return True

    def _chemical_text_filter(self,connection,text,prefix=''):
        from xrd_finder.finder.composition_validation import chemical_search_key
        like=f'%{text.lower()}%'
        clauses=[f'lower({prefix}{name}) like ?' for name in ('entry_id','formula','name','spacegroup')]
        params=[like]*4
        clauses.append(f"lower(replace({prefix}formula,' ','')) like ?")
        params.append('%'+re.sub(r'\s+','',text.lower())+'%')
        key=chemical_search_key(text)
        if key:
            connection.create_function('chemical_search_key',1,chemical_search_key,deterministic=True)
            present=connection.execute("select 1 from sqlite_master where type='table' and name='phase_chemistry'").fetchone()
            if present:
                owner=prefix or 'phases.'
                valid=(f'c.source={owner}source and c.entry_id={owner}entry_id '
                       f'and c.formula={owner}formula and c.version=1')
                clauses.append(f'exists(select 1 from phase_chemistry c where {valid} and c.chemical_key=?)')
                params.append(key)
                # Legacy/read-only/external writers may not yet have a saved
                # key. Only those rows use the parser until explicit migration.
                clauses.append(f'(not exists(select 1 from phase_chemistry c where {valid}) '
                               f'and chemical_search_key({prefix}formula)=?)')
                params.append(key)
            else:
                clauses.append(f'chemical_search_key({prefix}formula)=?')
                params.append(key)
        else:
            clauses.append(f'{prefix}formula_key like ?')
            params.append('%'+self._formula_key(text)+'%')
        return '('+' or '.join(clauses)+')',params

    def _save_chemical_key(self,connection,source,entry_id,formula):
        from xrd_finder.finder.composition_validation import chemical_search_key
        connection.execute('insert or replace into phase_chemistry(source,entry_id,formula,chemical_key,version) '
                           'values(?,?,?,?,1)',(source,entry_id,formula,chemical_search_key(formula)))

    def _ensure_chemical_index(self,connection):
        connection.execute('create table if not exists phase_chemistry('
                           'source text not null,entry_id text not null,formula text not null,'
                           'chemical_key text not null,version integer not null,primary key(source,entry_id))')
        connection.execute('create index if not exists idx_phase_chemistry_key on phase_chemistry(chemical_key,source,entry_id)')
        # Ordinary sqlite writers need no Python UDF. Invalidate on change,
        # then either our atomic upsert or the next cache open repairs the key.
        connection.execute('create trigger if not exists invalidate_phase_chemistry '
                           'after update of formula on phases when new.formula is not old.formula '
                           'begin delete from phase_chemistry where source=old.source and entry_id=old.entry_id; end')
        connection.execute('create trigger if not exists delete_phase_chemistry '
                           'after delete on phases begin delete from phase_chemistry '
                           'where source=old.source and entry_id=old.entry_id; end')
        rows=connection.execute('select p.source,p.entry_id,p.formula from phases p '
             'left join phase_chemistry c on c.source=p.source and c.entry_id=p.entry_id '
             'where c.entry_id is null or c.version!=1 or c.formula is not p.formula').fetchall()
        for row in rows:
            self._save_chemical_key(connection,row['source'],row['entry_id'],row['formula'])

    def _ensure_schema(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("""create table if not exists reference_preparation_failures (
                source text not null, entry_id text not null, signature text not null,
                reason text not null, updated_at real not null,
                primary key(source, entry_id))""")
            connection.execute(
                """
                create table if not exists phases (
                    source text not null,
                    entry_id text not null,
                    formula text not null default '',
                    name text not null default '',
                    spacegroup text not null default '',
                    source_text text not null default '',
                    elements text not null default '',
                    formula_key text not null default '',
                    cif_path text not null default '',
                    a real,
                    b real,
                    c real,
                    alpha real,
                    beta real,
                    gamma real,
                    volume real,
                    atoms_json text not null default '',
                    iic real,
                    peaks_json text not null default '',
                    top_peaks_json text not null default '',
                    derived_version integer not null default 0,
                    updated_at real not null,
                    primary key (source, entry_id)
                )
                """
            )
            connection.execute(
                """
                create table if not exists search_cache (
                    source text not null,
                    query_key text not null,
                    updated_at real not null,
                    result_limit integer not null default 0,
                    complete integer not null default 1,
                    primary key (source, query_key)
                )
                """
            )
            connection.execute(
                """
                create table if not exists phase_elements (
                    source text not null,
                    entry_id text not null,
                    element text not null,
                    primary key (source, entry_id, element)
                )
                """
            )
            connection.execute(
                """
                create table if not exists phase_peaks (
                    source text not null,
                    entry_id text not null,
                    peak_index integer not null,
                    two_theta real not null,
                    d real,
                    intensity real not null default 0,
                    norm_intensity real not null default 0,
                    top_rank integer,
                    raw_intensity real not null default 0,
                    h integer,
                    k integer,
                    l integer,
                    multiplicity integer,
                    primary key (source, entry_id, peak_index)
                )
                """
            )
            connection.execute(
                """
                create table if not exists phase_fingerprints (
                    source text not null,
                    entry_id text not null,
                    hash integer not null,
                    primary key (source, entry_id, hash)
                )
                """
            )
            connection.execute(
                """
                create table if not exists phase_fingerprint_state (
                    source text not null,
                    entry_id text not null,
                    version integer not null,
                    primary key (source, entry_id)
                )
                """
            )
            existing = {row[1] for row in connection.execute("pragma table_info(phases)").fetchall()}
            for column in ["a", "b", "c", "alpha", "beta", "gamma", "volume"]:
                if column not in existing:
                    connection.execute(f"alter table phases add column {column} real")
            if "atoms_json" not in existing:
                connection.execute("alter table phases add column atoms_json text not null default ''")
            if "iic" not in existing:
                connection.execute("alter table phases add column iic real")
            if "iic_method" not in existing:
                connection.execute("alter table phases add column iic_method text not null default ''")
            if "peaks_json" not in existing:
                connection.execute("alter table phases add column peaks_json text not null default ''")
            if "top_peaks_json" not in existing:
                connection.execute("alter table phases add column top_peaks_json text not null default ''")
                connection.execute("update phases set top_peaks_json = ''")
            if "derived_version" not in existing:
                connection.execute("alter table phases add column derived_version integer not null default 0")
            if "formula_key" not in existing:
                connection.execute("alter table phases add column formula_key text not null default ''")
                connection.execute("update phases set formula_key = lower(replace(formula, ' ', '')) where formula_key = ''")
            search_existing = {
                row[1] for row in connection.execute("pragma table_info(search_cache)").fetchall()
            }
            if "result_limit" not in search_existing:
                connection.execute(
                    "alter table search_cache add column result_limit integer not null default 0"
                )
            if "complete" not in search_existing:
                connection.execute(
                    "alter table search_cache add column complete integer not null default 1"
                )
            peak_existing = {row[1] for row in connection.execute("pragma table_info(phase_peaks)").fetchall()}
            if "intrinsic_intensity" not in peak_existing:
                connection.execute("alter table phase_peaks add column intrinsic_intensity real")
            if "intensity_origin" not in peak_existing:
                connection.execute("alter table phase_peaks add column intensity_origin text not null default ''")
            rebuild_peak_index = False
            if "norm_intensity" not in peak_existing:
                connection.execute("alter table phase_peaks add column norm_intensity real not null default 0")
                rebuild_peak_index = True
            if "top_rank" not in peak_existing:
                connection.execute("alter table phase_peaks add column top_rank integer")
                rebuild_peak_index = True
            connection.execute("create index if not exists idx_phases_source_updated on phases(source, updated_at desc)")
            connection.execute("create index if not exists idx_phases_formula_key on phases(formula_key)")
            connection.execute("create index if not exists idx_phases_elements on phases(elements)")
            connection.execute("create index if not exists idx_phase_elements_element on phase_elements(element, source, entry_id)")
            connection.execute("create index if not exists idx_phase_peaks_twotheta on phase_peaks(two_theta, source, entry_id)")
            connection.execute("create index if not exists idx_phase_peaks_d on phase_peaks(d, source, entry_id, peak_index, top_rank, norm_intensity, intensity)")
            connection.execute("create index if not exists idx_phase_peaks_phase on phase_peaks(source, entry_id)")
            connection.execute("create index if not exists idx_phase_peaks_top_rank on phase_peaks(top_rank, two_theta, source, entry_id)")
            connection.execute("create index if not exists idx_phase_fingerprints_hash on phase_fingerprints(hash, source, entry_id)")
            element_count = connection.execute("select count(*) from phase_elements").fetchone()[0]
            if not element_count:
                for row in connection.execute("select source, entry_id, elements from phases").fetchall():
                    self._replace_phase_elements(connection, row["source"], row["entry_id"], row["elements"])
            peak_count = connection.execute("select count(*) from phase_peaks").fetchone()[0]
            if rebuild_peak_index or not peak_count:
                connection.execute("delete from phase_peaks")
                for row in connection.execute("select source, entry_id, peaks_json from phases where peaks_json != ''").fetchall():
                    self._replace_phase_peaks(connection, row["source"], row["entry_id"], row["peaks_json"])
                    connection.execute(
                        "update phases set top_peaks_json = ? where source = ? and entry_id = ?",
                        (self._top_peaks_json_from_peaks_json(row["peaks_json"]), row["source"], row["entry_id"]),
                    )
            self._ensure_chemical_index(connection)

    def _connect(self) -> sqlite3.Connection:
        if getattr(self, "_read_only", False):
            connection = sqlite3.connect(
                self.index_path.resolve().as_uri() + "?mode=ro", uri=True,
                factory=_ReadOnlyConnection,
            )
            connection.row_factory = sqlite3.Row
            return connection
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.index_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _clear_sources(self, sources: list[str]) -> None:
        if not sources:
            return
        placeholders = ", ".join("?" for _ in sources)
        with closing(self._connect()) as connection, connection:
            connection.execute(f"delete from phases where source in ({placeholders})", sources)
            connection.execute(f"delete from phase_elements where source in ({placeholders})", sources)
            connection.execute(f"delete from phase_peaks where source in ({placeholders})", sources)
            connection.execute(f"delete from phase_fingerprints where source in ({placeholders})", sources)
            connection.execute(f"delete from phase_fingerprint_state where source in ({placeholders})", sources)
            connection.execute(f"delete from search_cache where source in ({placeholders})", sources)
        self._remove_cache_dirs([f"embedded_cif/{_embedded_source_dir_name(source)}" for source in sources])

    def _remove_cache_dirs(self, names: list[str]) -> None:
        root = self.root.resolve()
        for name in names:
            path = (self.root / name).resolve()
            if path == root or root not in path.parents:
                continue
            if path.exists():
                shutil.rmtree(path)

    def _upsert(
        self,
        connection: sqlite3.Connection,
        entry: CachedPhaseEntry,
        keep_cif: bool,
        *,
        insert_only: bool = False,
    ) -> bool:
        old_cif = ""
        if keep_cif:
            row = connection.execute(
                """
                select formula, spacegroup, cif_path, a, b, c, alpha, beta, gamma, volume, atoms_json, iic, iic_method, peaks_json, top_peaks_json, derived_version
                from phases
                where source = ? and entry_id = ?
                """,
                (entry.source, entry.entry_id),
            ).fetchone()
            old_cif = row["cif_path"] if row else ""
            if row and old_cif and not entry.cif_path:
                if row['derived_version'] > 0:
                    # A catalog refresh cannot edit one part of a calculated
                    # structure. Only reindexing its CIF replaces this set.
                    if entry.formula and self._normalize_formula(entry.formula) != self._normalize_formula(row['formula']):
                        logging.getLogger(__name__).warning(
                            'Catalog formula %s differs from local CIF %s for %s %s; keeping CIF metadata',
                            entry.formula, row['formula'], entry.source, entry.entry_id)
                    for field in ('formula', 'spacegroup', 'a', 'b', 'c', 'alpha', 'beta', 'gamma',
                                  'volume', 'atoms_json', 'iic', 'iic_method', 'peaks_json',
                                  'top_peaks_json', 'derived_version'):
                        setattr(entry, field, row[field])
                copy_iic = entry.iic is None
                for field in ("a", "b", "c", "alpha", "beta", "gamma", "volume", "iic"):
                    if getattr(entry, field) is None:
                        setattr(entry, field, row[field])
                if copy_iic:
                    entry.iic_method = row["iic_method"]
                for field in ("atoms_json", "peaks_json", "top_peaks_json"):
                    if not getattr(entry, field):
                        setattr(entry, field, row[field])
                if getattr(entry, "derived_version", 0) == 0:
                    setattr(entry, "derived_version", row["derived_version"])
        cif_path = old_cif or entry.cif_path
        conflict_clause = (
            "on conflict(source, entry_id) do nothing"
            if insert_only
            else """
            on conflict(source, entry_id) do update set
                formula = excluded.formula,
                name = excluded.name,
                spacegroup = excluded.spacegroup,
                source_text = excluded.source_text,
                elements = excluded.elements,
                formula_key = excluded.formula_key,
                cif_path = excluded.cif_path,
                a = excluded.a,
                b = excluded.b,
                c = excluded.c,
                alpha = excluded.alpha,
                beta = excluded.beta,
                gamma = excluded.gamma,
                volume = excluded.volume,
                atoms_json = excluded.atoms_json,
                iic = excluded.iic,
                iic_method = excluded.iic_method,
                peaks_json = excluded.peaks_json,
                top_peaks_json = excluded.top_peaks_json,
                derived_version = excluded.derived_version,
                updated_at = excluded.updated_at
            """
        )
        cursor = connection.execute(
            f"""
            insert into phases(
                source, entry_id, formula, name, spacegroup, source_text, elements, formula_key, cif_path,
                a, b, c, alpha, beta, gamma, volume, atoms_json, iic, iic_method, peaks_json, top_peaks_json, derived_version, updated_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            {conflict_clause}
            """,
            (
                entry.source,
                entry.entry_id,
                entry.formula,
                entry.name,
                entry.spacegroup,
                entry.source_text,
                " ".join(sorted(formula_elements(entry.formula))),
                self._formula_key(entry.formula),
                cif_path,
                entry.a,
                entry.b,
                entry.c,
                entry.alpha,
                entry.beta,
                entry.gamma,
                entry.volume,
                entry.atoms_json,
                entry.iic,
                entry.iic_method,
                entry.peaks_json,
                entry.top_peaks_json or self._top_peaks_json_from_peaks_json(entry.peaks_json),
                entry.derived_version,
                time.time(),
            ),
        )
        if cursor.rowcount == 0:
            return False
        self._save_chemical_key(connection,entry.source,entry.entry_id,entry.formula)
        self._replace_phase_elements(connection, entry.source, entry.entry_id, " ".join(sorted(formula_elements(entry.formula))))
        self._replace_phase_peaks(connection, entry.source, entry.entry_id, entry.peaks_json)
        return True

    def _replace_phase_elements(
        self,
        connection: sqlite3.Connection,
        source: str,
        entry_id: str,
        elements_text: str,
    ) -> None:
        connection.execute("delete from phase_elements where source = ? and entry_id = ?", (source, entry_id))
        rows = [
            (source, entry_id, element)
            for element in sorted({item.strip() for item in elements_text.split() if item.strip()})
        ]
        if rows:
            connection.executemany(
                "insert or ignore into phase_elements(source, entry_id, element) values(?, ?, ?)",
                rows,
            )

    def _replace_phase_peaks(
        self,
        connection: sqlite3.Connection,
        source: str,
        entry_id: str,
        peaks_json: str,
    ) -> None:
        connection.execute("delete from phase_peaks where source = ? and entry_id = ?", (source, entry_id))
        connection.execute("delete from phase_fingerprints where source = ? and entry_id = ?", (source, entry_id))
        connection.execute("delete from phase_fingerprint_state where source = ? and entry_id = ?", (source, entry_id))
        if not peaks_json:
            return
        try:
            peaks = json.loads(peaks_json)
        except json.JSONDecodeError:
            return
        normalized_peaks = peaks if isinstance(peaks, list) else []
        intensities = []
        for peak in normalized_peaks:
            try:
                intensity = max(float(peak.get("intensity", 0.0) or 0.0), 0.0)
            except (TypeError, ValueError):
                intensity = 0.0
            intensities.append(intensity)
        max_intensity = max(intensities, default=0.0)
        top_rank_by_index = {}
        top_candidates = []
        for index, peak in enumerate(normalized_peaks):
            try:
                two_theta = float(peak.get("two_theta", 0.0) or 0.0)
                intensity = intensities[index]
            except (TypeError, ValueError, IndexError):
                continue
            if 5.0 <= two_theta <= 60.0 and intensity > 0.0:
                top_candidates.append((intensity, index))
        for rank, (_intensity, index) in enumerate(sorted(top_candidates, reverse=True)[:10], start=1):
            top_rank_by_index[index] = rank
        rows = []
        for index, peak in enumerate(normalized_peaks):
            try:
                two_theta = float(peak.get("two_theta", 0.0))
                if not math.isfinite(two_theta):
                    continue
                intensity = max(float(peak.get("intensity", 0.0) or 0.0), 0.0)
                rows.append(
                    (
                        source,
                        entry_id,
                        int(index),
                        two_theta,
                        self._optional_float(peak.get("d")),
                        intensity,
                        intensity / max_intensity if max_intensity > 0.0 else 0.0,
                        top_rank_by_index.get(index),
                        max(float(peak.get("raw_intensity", 0.0) or 0.0), 0.0),
                        self._optional_int(peak.get("h")),
                        self._optional_int(peak.get("k")),
                        self._optional_int(peak.get("l")),
                        self._optional_int(peak.get("multiplicity")),
                        self._optional_float(peak.get("intrinsic_intensity")),
                        str(peak.get("intensity_origin") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue
        if rows:
            connection.executemany(
                """
                insert or replace into phase_peaks(
                    source, entry_id, peak_index, two_theta, d, intensity, norm_intensity, top_rank, raw_intensity,
                    h, k, l, multiplicity, intrinsic_intensity, intensity_origin
                ) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        self._replace_phase_fingerprints(connection, source, entry_id, rows)

    def _replace_phase_fingerprints(
        self,
        connection: sqlite3.Connection,
        source: str,
        entry_id: str,
        peak_rows,
    ) -> None:
        connection.execute("delete from phase_fingerprints where source=? and entry_id=?", (source, entry_id))
        connection.execute("delete from phase_fingerprint_state where source=? and entry_id=?", (source, entry_id))
        peaks = []
        for row in peak_rows:
            try:
                if isinstance(row, sqlite3.Row):
                    two_theta = float(row["two_theta"])
                    normalized = float(row["norm_intensity"] or 0.0)
                    intensity = 100.0 * normalized if normalized > 0.0 else float(row["intensity"] or 0.0)
                else:
                    two_theta = float(row[3])
                    normalized = float(row[6] or 0.0)
                    intensity = 100.0 * normalized if normalized > 0.0 else float(row[5] or 0.0)
                peaks.append(SimpleNamespace(two_theta=two_theta, intensity=intensity))
            except (IndexError, KeyError, TypeError, ValueError):
                continue
        hashes = peak_geometric_hashes(
            peaks,
            max_peaks=GEOMETRIC_FINGERPRINT_PEAK_LIMIT,
        )
        if hashes:
            connection.executemany(
                "insert or ignore into phase_fingerprints(source,entry_id,hash) values(?,?,?)",
                [(source, entry_id, int(value)) for value in hashes],
            )
        connection.execute(
            "insert or replace into phase_fingerprint_state(source,entry_id,version) values(?,?,?)",
            (source, entry_id, GEOMETRIC_FINGERPRINT_VERSION),
        )

    def rebuild_peak_index(self) -> int:
        with closing(self._connect()) as connection, connection:
            connection.execute("delete from phase_peaks")
            connection.execute("delete from phase_fingerprints")
            connection.execute("delete from phase_fingerprint_state")
            rows = connection.execute("select source, entry_id, peaks_json from phases where peaks_json != ''").fetchall()
            for row in rows:
                self._replace_phase_peaks(connection, row["source"], row["entry_id"], row["peaks_json"])
                connection.execute(
                    "update phases set top_peaks_json = ? where source = ? and entry_id = ?",
                    (self._top_peaks_json_from_peaks_json(row["peaks_json"]), row["source"], row["entry_id"]),
                )
        return self.peak_indexed_count()

    @staticmethod
    def _search_columns(summary_only: bool, prefix: str = "", *, connection=None) -> str:
        # Cell metadata remains in the SQL rows for the existing dedupe policy.
        columns = (*CachedPhaseSummary.__dataclass_fields__,
                   "a", "b", "c", "alpha", "beta", "gamma", "volume")
        if not summary_only:
            columns += ("source_text", "cif_path", "elements", "atoms_json", "peaks_json", "top_peaks_json")
        projection = ", ".join(prefix + column for column in columns)
        if connection is not None:
            present = connection.execute(
                "select 1 from sqlite_master where type='table' and name='phase_chemistry'").fetchone()
            owner = prefix or 'phases.'
            key = (f'(select c.chemical_key from phase_chemistry c '
                   f'where c.source={owner}source and c.entry_id={owner}entry_id '
                   f'and c.formula={owner}formula and c.version=1)') if present else 'null'
            projection += f', {key} as _chemical_key'
        return projection

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> CachedPhaseSummary:
        return CachedPhaseSummary(**{name: row[name] for name in CachedPhaseSummary.__dataclass_fields__})

    def _row_to_entry(self, row: sqlite3.Row) -> CachedPhaseEntry:
        return CachedPhaseEntry(
            source=row["source"],
            entry_id=row["entry_id"],
            formula=row["formula"],
            name=row["name"],
            spacegroup=row["spacegroup"],
            source_text=row["source_text"],
            cif_path=row["cif_path"],
            a=row["a"],
            b=row["b"],
            c=row["c"],
            alpha=row["alpha"],
            beta=row["beta"],
            gamma=row["gamma"],
            volume=row["volume"],
            atoms_json=row["atoms_json"],
            iic=row["iic"],
            iic_method=row["iic_method"],
            peaks_json=row["peaks_json"],
            top_peaks_json=row["top_peaks_json"] if "top_peaks_json" in row.keys() else "",
            derived_version=row["derived_version"],
        )

    def _dedupe_key(self, row: sqlite3.Row) -> tuple:
        cell_key = self._cell_key(row)
        if cell_key is None:
            return ("unique", row["source"], row["entry_id"])
        key = row['_chemical_key'] if '_chemical_key' in row.keys() else None
        if key is None:
            # Only unmigrated/stale read-only rows need a composition parse.
            from xrd_finder.finder.composition_validation import chemical_search_key
            key = chemical_search_key(row['formula'])
        if not key:
            # Unknown/variable compositions cannot establish equivalence.
            return ('unique', row['source'], row['entry_id'])
        return (
            key,
            self._normalize_text(row["spacegroup"]),
            cell_key,
        )

    def _cell_key(self, row: sqlite3.Row) -> tuple | None:
        values = [row["a"], row["b"], row["c"], row["alpha"], row["beta"], row["gamma"]]
        if any(value is None for value in values):
            return None
        lengths = tuple(round(float(value), 2) for value in values[:3])
        angles = tuple(round(float(value), 1) for value in values[3:])
        volume = row["volume"]
        volume_key = round(float(volume), 1) if volume is not None else None
        return lengths + angles + (volume_key,)

    def _normalize_formula(self, formula: str) -> str:
        tokens = re.findall(r"([A-Z][a-z]?)([0-9.]+)?", formula or "")
        if not tokens:
            return self._normalize_text(formula)
        parts = []
        for element, amount in sorted(tokens):
            try:
                amount_text = format(Decimal(amount or '1'), 'f')
                if '.' in amount_text:
                    amount_text = amount_text.rstrip('0').rstrip('.')
            except InvalidOperation:
                amount_text = amount
            parts.append(f"{element}{amount_text}")
        return " ".join(parts)

    def _formula_key(self, formula: str) -> str:
        tokens = re.findall(r"([A-Z][a-z]?)([0-9.]+)?", formula or "")
        if not tokens:
            return re.sub(r"\s+", "", (formula or "").lower())
        return "".join(f"{element.lower()}{amount}" for element, amount in tokens)

    def _sorted_formula_key(self, formula: str) -> str:
        tokens = re.findall(r"([A-Z][a-z]?)([0-9.]+)?", formula or "")
        if not tokens:
            return re.sub(r"\s+", "", (formula or "").lower())
        return "".join(f"{element.lower()}{amount}" for element, amount in sorted(tokens))

    def _optional_float(self, value) -> float | None:
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _optional_int(self, value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

    def _best_formula(self, structure_formula: str, fallback_formula: str) -> str:
        structure_formula = (structure_formula or '').strip()
        fallback_formula = (fallback_formula or '').strip()
        if (structure_formula and fallback_formula
                and self._normalize_formula(structure_formula) != self._normalize_formula(fallback_formula)):
            logging.getLogger(__name__).warning(
                'Catalog formula %s differs from CIF %s during indexing; using CIF composition',
                fallback_formula, structure_formula)
        return structure_formula or fallback_formula

    def _best_name(self, structure_name: str, fallback_name: str, formula: str, entry_id: str) -> str:
        fallback_name = (fallback_name or "").strip()
        if fallback_name:
            return fallback_name
        structure_name = (structure_name or "").strip()
        if structure_name and self._normalize_formula(structure_name) != self._normalize_formula(formula):
            return structure_name
        return formula.strip() or entry_id

    def _atoms_to_json(self, structure) -> str:
        atoms = []
        for atom in getattr(structure, "atoms", []) or []:
            atoms.append(
                {
                    "label": atom.label,
                    "element": atom.element,
                    "x": atom.x,
                    "y": atom.y,
                    "z": atom.z,
                    "occupancy": atom.occupancy,
                    "biso": atom.biso,
                    "uiso": atom.uiso,
                    "wyckoff": atom.wyckoff,
                    "multiplicity": atom.multiplicity,
                }
            )
        return json.dumps(atoms, ensure_ascii=True, separators=(",", ":"))
