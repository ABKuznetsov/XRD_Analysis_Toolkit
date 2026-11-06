"""Activate compact storage through SQLite, never by exchanging an open file."""
from concurrent.futures import CancelledError
from contextlib import closing
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from time import monotonic, sleep

from xrd_finder.services.cache_storage import (
    CURRENT_STORAGE_VERSION, SUPPORTED_STORAGE_VERSIONS, compact_indexes, rewrite_payloads,
)
from xrd_finder.services.normalized_reflections import normalize_reflections


@dataclass(frozen=True)
class LibraryMigrationResult:
    activated: bool
    already_current: bool
    compacted: bool
    backup_path: Path | None
    cards: int
    before_bytes: int
    after_bytes: int | None
    notice: str = ''


def _check(cancelled):
    if cancelled():
        raise CancelledError('Storage operation cancelled')


def _busy(error):
    return (getattr(error,'sqlite_errorcode',0) & 255) in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)


def _retry(action, cancelled, *, timeout=30.):
    deadline = monotonic()+timeout
    while True:
        _check(cancelled)
        try:
            return action()
        except sqlite3.OperationalError as error:
            if not _busy(error) or monotonic()>=deadline:
                raise
            sleep(.02)  # SQLITE_LOCKED may bypass SQLite's busy timeout.


def _size(connection):
    return (connection.execute('pragma page_count').fetchone()[0]
            * connection.execute('pragma page_size').fetchone()[0])


def _counts(connection):
    names = [r[0] for r in connection.execute(
        "select name from sqlite_master where type in ('table','view') and name not like 'sqlite_%' "
        "and name not in ('reflection_cards','reflection_origins','reflection_lines')")]
    return {name: connection.execute('select count(*) from "'+name.replace('"','""')+'"').fetchone()[0]
            for name in names}


def _verify(connection):
    if connection.execute('pragma quick_check').fetchone()[0]!='ok':
        raise ValueError('The library failed SQLite integrity verification')


def _check_space(source, backup, size):
    margin = 1024*1024
    same_device = source.stat().st_dev == backup.parent.stat().st_dev
    required = (3 if same_device else 2)*size + margin
    if shutil.disk_usage(source.parent).free < required:
        raise OSError('Not enough temporary disk space for the backup, transaction and SQLite compaction')
    if not same_device and shutil.disk_usage(backup.parent).free < size+margin:
        raise OSError('Not enough disk space for the original-library backup')


def _backup_original(source, backup, counts, version, *, progress, cancelled):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=backup.parent,suffix='.sqlite.part',delete=False) as handle:
            temporary = Path(handle.name)
        # BEGIN IMMEDIATE on the other connection excludes concurrent writers,
        # while this separate read-only connection can safely use the backup API.
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as reader, \
                closing(sqlite3.connect(temporary)) as saved:
            def copied(status,remaining,total):
                _check(cancelled)
                if progress:
                    progress('Saving original library backup',total-remaining,total)
            reader.backup(saved,pages=256,progress=copied)
            saved.set_progress_handler(lambda:int(cancelled()),10000)
            saved.execute('pragma journal_mode=delete')
            _verify(saved)
            if saved.execute('pragma user_version').fetchone()[0]!=version or _counts(saved)!=counts:
                raise ValueError('Original library backup verification failed')
        _check(cancelled)
        os.link(temporary,backup)  # Atomic create-if-absent; never overwrite.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _compact(connection, cancelled):
    _check(cancelled)
    connection.execute('vacuum')
    _verify(connection)


def _finish_compaction(writer,source,backup,cards,before, *, progress,cancelled,activated,already_current):
    notice = ''
    compacted = False
    try:
        writer.set_progress_handler(lambda:int(cancelled()),10000)
        if progress:
            progress('Compacting working SQLite',0,0)
        if shutil.disk_usage(source.parent).free < 2*before+1024*1024:
            raise OSError('Not enough temporary disk space for SQLite compaction')
        _compact(writer,cancelled)
        compacted = True
    except Exception as error:
        notice = 'Optimized storage is active. Space compaction did not finish: '+str(error)
        if writer.in_transaction:
            writer.rollback()
    finally:
        writer.set_progress_handler(None,0)
    try:
        after = _size(writer)
    except Exception as error:
        after = None
        notice += '\nOptimized storage is active, but its size could not be read: '+str(error)
    return LibraryMigrationResult(activated,already_current,compacted,backup,cards,before,after,notice)


def migrate_library_storage(source, backup_path, *, progress=None, cancelled=lambda:False):
    """Back up, transactionally activate, then separately compact the live file.

    Precommit exceptions mean rollback. After commit, interrupted compaction
    returns an active-format result with a notice, never a false rollback.
    """
    source,backup = Path(source).resolve(),Path(backup_path).resolve()
    _check(cancelled)
    if not source.is_file():
        raise FileNotFoundError(source)
    committed = owned_backup = False
    with closing(sqlite3.connect(source.as_uri()+'?mode=rw',uri=True,timeout=.1)) as writer:
        try:
            if progress:
                progress('Waiting for database access',0,0)
            _retry(lambda:writer.execute('begin immediate'),cancelled)
            writer.set_progress_handler(lambda:int(cancelled()),10000)
            version = writer.execute('pragma user_version').fetchone()[0]
            if version not in SUPPORTED_STORAGE_VERSIONS:
                raise ValueError('Unsupported local library storage version')
            before = _size(writer)
            counts = _counts(writer)
            cards = counts.get('phases',0)
            if version==CURRENT_STORAGE_VERSION:
                unused = writer.execute('pragma freelist_count').fetchone()[0]
                writer.rollback()
                if unused:
                    committed = True  # The format was already active on entry.
                    return _finish_compaction(writer,source,None,cards,before,progress=progress,
                        cancelled=cancelled,activated=False,already_current=True)
                return LibraryMigrationResult(False,True,False,None,cards,before,before)
            if backup.exists():
                raise FileExistsError(backup)
            backup.parent.mkdir(parents=True,exist_ok=True)
            _check_space(source,backup,before)
            _verify(writer)
            _backup_original(source,backup,counts,version,progress=progress,cancelled=cancelled)
            owned_backup = True
            writer.set_progress_handler(lambda:int(cancelled()),10000)
            rewrite_payloads(writer,compact=True,sql_reflections=True,progress=progress,cancelled=cancelled)
            normalize_reflections(writer,progress=progress,cancelled=cancelled)
            compact_indexes(writer)
            writer.execute(f'pragma user_version={CURRENT_STORAGE_VERSION}')
            if _counts(writer)!=counts:
                raise ValueError('Library record counts changed during migration')
            _verify(writer)
            if progress:
                progress('Activating optimized storage',cards,cards)
            # Commit itself must not be interrupted after its internal commit
            # point. Cooperative cancellation still applies between busy retries.
            writer.set_progress_handler(None,0)
            _retry(writer.commit,cancelled)
            committed = True
        except Exception:
            writer.set_progress_handler(None,0)
            writer.rollback()
            if owned_backup:
                backup.unlink(missing_ok=True)
            _check(cancelled)
            raise
        finally:
            if not committed:
                writer.set_progress_handler(None,0)

        return _finish_compaction(writer,source,backup,cards,before,progress=progress,
            cancelled=cancelled,activated=True,already_current=False)
