"""Read-only library inventory for search setup; no CIF parsing or downloads."""
from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import sqlite3

from xrd_finder.services.local_phase_cache import LocalPhaseCache, DERIVED_CACHE_VERSION


@dataclass(frozen=True, slots=True)
class SearchInventory:
    total: int = 0
    ready: int = 0
    needs_preparation: int = 0
    catalogue_only: int = 0
    eligible: int = 0
    eligible_ready: int = 0
    eligible_preparation: int = 0


def search_inventory(cache: LocalPhaseCache, *, sources, required_elements=(), excluded_elements=(),
                     allow_inorganic=True, allow_organic=True, cancelled=lambda:False) -> SearchInventory:
    if cancelled():
        raise CancelledError('Library inventory cancelled')
    sources = sorted(set(str(source).upper() for source in sources))
    if not sources:
        return SearchInventory()
    params = [DERIVED_CACHE_VERSION, *sources]
    conditions = []
    for values, negative in ((sorted(set(required_elements)), False), (sorted(set(excluded_elements)), True)):
        for element in values:
            conditions.append(('not ' if negative else '') +
                'exists(select 1 from phase_elements e where e.source=p.source and e.entry_id=p.entry_id and e.element=?)')
            params.append(element)
    organic = ("exists(select 1 from phase_elements e where e.source=p.source and e.entry_id=p.entry_id and e.element='C') "
               "and exists(select 1 from phase_elements e where e.source=p.source and e.entry_id=p.entry_id and e.element='H')")
    if not allow_inorganic and not allow_organic:
        conditions.append('0')
    elif not allow_inorganic:
        conditions.append(f'({organic})')
    elif not allow_organic:
        conditions.append(f'not ({organic})')
    eligible = ' and '.join(conditions) or '1'
    sql = f'''with inventory as (
        select p.source,p.entry_id,p.cif_path,
               (p.derived_version=? and exists(select 1 from phase_peaks r
                   where r.source=p.source and r.entry_id=p.entry_id)) as ready
        from phases p where p.source in ({','.join('?' for _ in sources)})
    ), classified as (
        select i.ready,(case when i.ready then 0 else local_cif_exists(i.cif_path) end) as preparation,
               ({eligible}) as eligible
        from inventory i join phases p on p.source=i.source and p.entry_id=i.entry_id
    ) select count(*),coalesce(sum(ready),0),coalesce(sum(preparation),0),
             coalesce(sum(eligible),0),coalesce(sum(eligible and ready),0),
             coalesce(sum(eligible and preparation),0) from classified'''
    try:
        with closing(cache._connect()) as connection:
            @lru_cache(maxsize=None)
            def local_cif_exists(path):
                try:
                    return int(bool(path) and Path(path).is_file())
                except OSError:
                    return 0
            connection.create_function('local_cif_exists',1,local_cif_exists,deterministic=True)
            connection.set_progress_handler(lambda:int(cancelled()),1000)
            row = connection.execute(sql, params).fetchone()
    except sqlite3.OperationalError as exc:
        if cancelled():
            raise CancelledError('Library inventory cancelled') from exc
        raise
    if cancelled():
        raise CancelledError('Library inventory cancelled')
    total, ready, preparation, eligible, eligible_ready, eligible_preparation = map(int,row)
    return SearchInventory(total, ready, preparation, total-ready-preparation,
                           eligible, eligible_ready, eligible_preparation)
