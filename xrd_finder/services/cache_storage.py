"""Storage policy and cancellable conversion of isolated SQLite copies."""
from __future__ import annotations

from concurrent.futures import CancelledError
from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import sqlite3
import tempfile

from xrd_finder.services.cache_json import MAGIC, pack_json, unpack_json
from xrd_finder.services.sql_reflection_storage import is_sql_peaks, pack_sql_peaks, unpack_sql_peaks
from xrd_finder.services.normalized_reflections import normalized_reflections, normalize_reflections, create_indexes

PACKED_STORAGE_VERSION = 1700
COMPACT_STORAGE_VERSION = 1701
CURRENT_STORAGE_VERSION = 1702
SUPPORTED_STORAGE_VERSIONS = (0, PACKED_STORAGE_VERSION, COMPACT_STORAGE_VERSION, CURRENT_STORAGE_VERSION)


def storage_version(path: Path, *, recover=False) -> int:
    if not path.is_file() or not path.stat().st_size:
        return CURRENT_STORAGE_VERSION
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            version = c.execute('pragma user_version').fetchone()[0]
    except sqlite3.OperationalError as error:
        if not recover or getattr(error,'sqlite_errorcode',0)!=sqlite3.SQLITE_READONLY_ROLLBACK:
            raise
        # A killed write leaves a hot rollback journal. Only the normal
        # writable owner may let SQLite recover it; read-only workers stay RO.
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True)) as c:
            version = c.execute('pragma user_version').fetchone()[0]
    if version not in SUPPORTED_STORAGE_VERSIONS:
        raise ValueError('Unsupported local library storage version')
    return version


def check_cancelled(cancelled):
    if cancelled():
        raise CancelledError('Library storage optimization cancelled; original retained')


def storage_policy(path: Path, requested: bool | None = None, *, recover=False) -> bool:
    if not path.is_file() or not path.stat().st_size:
        return True if requested is None else requested
    compact = storage_version(path,recover=recover) != 0
    if requested is not None and requested!=compact:
        raise ValueError('Use a converted database copy to change an existing library storage format')
    return compact


def compact_indexes(c):
    if normalized_reflections(c):
        create_indexes(c)
        return
    c.execute('drop index if exists idx_phase_peaks_phase')
    # Range retrieval uses the covering d index; per-card reads use the PK.
    # Keep two_theta values, but avoid a second unused full-range index.
    c.execute('drop index if exists idx_phase_peaks_twotheta')
    row = c.execute("select sql from sqlite_master where name='idx_phase_peaks_top_rank'").fetchone()
    if row and 'where top_rank is not null' not in row[0].lower():
        c.execute('drop index idx_phase_peaks_top_rank')
    c.execute('create index if not exists idx_phase_peaks_top_rank '
              'on phase_peaks(top_rank,two_theta,source,entry_id) where top_rank is not null')


def rewrite_payloads(c, *, compact: bool, sql_reflections=False, progress=None, cancelled=lambda:False) -> tuple[int,int]:
    """Convert field representation only; never calculate reflections or change scores."""
    count = c.execute('select count(*) from phases').fetchone()[0]
    cursor = c.execute('select source,entry_id,atoms_json,peaks_json from phases order by rowid')
    completed = packed = 0
    while rows := cursor.fetchmany(16):
        for source,entry_id,atoms,peaks in rows:
            check_cancelled(cancelled)
            original = (unpack_json(atoms),unpack_sql_peaks(peaks,c,source,entry_id))
            values = original
            if compact:
                packed_atoms = atoms if isinstance(atoms,bytes) and atoms.startswith(MAGIC) else pack_json(original[0])
                packed_peaks = peaks if isinstance(peaks,bytes) and peaks.startswith(MAGIC) else None
                if sql_reflections:
                    packed_peaks = peaks if is_sql_peaks(peaks) else pack_sql_peaks(
                        original[1],c,source,entry_id,fallback=packed_peaks)
                elif packed_peaks is None:
                    packed_peaks = pack_json(original[1],peaks=True)
                values = (packed_atoms,packed_peaks)
            # Verify restored bytes, including formatting used in persisted signatures.
            if values!=(atoms,peaks) and (unpack_json(values[0]),unpack_sql_peaks(values[1],c,source,entry_id))!=original:
                raise ValueError('Cached data changed during storage conversion')
            if values!=(atoms,peaks):
                c.execute('update phases set atoms_json=?,peaks_json=? where source=? and entry_id=?',
                          (*values,source,entry_id))
            packed += sum(isinstance(v,bytes) for v in values)
            completed += 1
        if progress:
            progress('Optimizing prepared library storage',completed,count)
    check_cancelled(cancelled)
    return completed,packed


@dataclass(frozen=True)
class StorageOptimizationResult:
    cards: int
    packed_fields: int
    before_bytes: int
    after_bytes: int


def optimize_database_copy(source, destination, *, progress=None, cancelled=lambda:False):
    """Publish a new SQL snapshot; preserve source and CIF paths, no library relocation."""
    source,destination = Path(source).resolve(),Path(destination).resolve()
    check_cancelled(cancelled)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent,suffix='.sqlite.part',delete=False) as f:
        temporary = Path(f.name)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as original,closing(sqlite3.connect(temporary)) as saved:
            original.backup(saved,pages=256,progress=lambda *_:check_cancelled(cancelled))
            before = temporary.stat().st_size
            # Backups inherit the source's WAL flag. Publish a single complete
            # SQLite file, without depending on transient -wal/-shm siblings.
            saved.execute('pragma journal_mode=delete')
            saved.set_progress_handler(lambda:int(cancelled()),10000)
            try:
                with saved:
                    cards,packed = rewrite_payloads(saved,compact=True,sql_reflections=True,progress=progress,cancelled=cancelled)
                    normalize_reflections(saved,progress=progress,cancelled=cancelled)
                    compact_indexes(saved)
                    saved.execute(f'pragma user_version={CURRENT_STORAGE_VERSION}')
                check_cancelled(cancelled)
                if progress:
                    progress('Compacting SQLite pages',0,0)
                saved.execute('vacuum')
                if saved.execute('pragma quick_check').fetchone()[0]!='ok':
                    raise ValueError('Optimized library failed SQLite verification')
                check_cancelled(cancelled)
            except sqlite3.OperationalError:
                check_cancelled(cancelled)
                raise
            finally:
                saved.set_progress_handler(None,0)
        result = StorageOptimizationResult(cards,packed,before,temporary.stat().st_size)
        check_cancelled(cancelled)
        # Atomic create-if-absent, including another conversion racing for this path.
        os.link(temporary,destination)
        return result
    finally:
        temporary.unlink(missing_ok=True)
