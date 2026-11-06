"""Bounded, cancellable legacy JSON library import and snapshot export."""
from concurrent.futures import CancelledError
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from xrd_finder.services.cache_json import unpack_json
from xrd_finder.services.sql_reflection_storage import unpack_sql_peaks


def export_phase_json(cache, path, *, sources, library_name, progress=None, cancelled=lambda:False):
    target = Path(path).resolve()
    if target == cache.index_path.resolve():
        raise ValueError('Choose a JSON export file, not the working SQLite database')
    normalized = [str(s or '').upper() for s in sources if str(s or '').strip()]
    if not normalized:
        raise ValueError('At least one source is required for export.')
    def check(*args):
        if cancelled():
            raise CancelledError('Phase library export cancelled; original retained')
    check()
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary = None
    try:
        with tempfile.TemporaryDirectory(prefix='xrd-json-export-') as folder:
            # Release the live database before slow JSON/CIF serialization.
            with closing(cache._connect()) as original,closing(sqlite3.connect(Path(folder)/'snapshot.sqlite')) as saved:
                if progress:
                    progress('Preparing export snapshot',0,0)
                check()
                original.backup(saved,pages=256,progress=check)
            with closing(sqlite3.connect(Path(folder)/'snapshot.sqlite')) as saved:
                saved.row_factory = sqlite3.Row
                saved.set_progress_handler(lambda:int(cancelled()),5000)
                placeholders = ','.join('?' for _ in normalized)
                total = saved.execute(f'select count(*) from phases where source in ({placeholders})',normalized).fetchone()[0]
                columns = ('source,entry_id,formula,name,spacegroup,source_text,cif_path,elements,'
                           'a,b,c,alpha,beta,gamma,volume,atoms_json,iic,iic_method,peaks_json,top_peaks_json,derived_version')
                cursor = saved.execute(f'select {columns} from phases where source in ({placeholders}) '
                                       'order by source,name,entry_id',normalized)
                header = dict(schema_version=1,application='XRD Phase Finder',library=library_name,sources=normalized)
                count = 0
                with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,suffix='.part',delete=False) as output:
                    temporary = Path(output.name)
                    output.write(json.dumps(header,ensure_ascii=False)[:-1]+',"entries":[')
                    for row in cursor:
                        check()
                        entry = dict(row)
                        entry['atoms_json'] = unpack_json(entry['atoms_json'])
                        entry['peaks_json'] = unpack_sql_peaks(entry['peaks_json'],saved,entry['source'],entry['entry_id'])
                        cif_path = Path(entry.pop('cif_path') or '')
                        try:
                            entry['cif_text'] = cif_path.read_text(encoding='utf-8',errors='replace') if cif_path.is_file() else ''
                        except OSError:
                            entry['cif_text'] = ''
                        if count:
                            output.write(',')
                        json.dump(entry,output,ensure_ascii=False)
                        count += 1
                        if progress:
                            progress('Exporting phase cards',count,total)
                    output.write(']}\n')
                    output.flush()
                    os.fsync(output.fileno())
                check()
                temporary.replace(target)
                return count
    except sqlite3.OperationalError:
        check()
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


IMPORT_BATCH_SIZE = 200


def _transfer_identity(entry,index,allowed):
    if not isinstance(entry,dict):
        return None
    source = str(entry.get('source') or '').upper()
    if source not in allowed or not str(entry.get('cif_text') or '').strip():
        return None
    entry_id = str(entry.get('entry_id') or f'user_phase_{index+1}').strip() or f'user_phase_{index+1}'
    return source,entry_id


def import_phase_json(cache,path, *, allowed_sources=None,progress=None,cancelled=lambda:False):
    """Validate first, then import bounded transactions; committed batches persist."""
    from hashlib import sha256
    from time import monotonic,sleep
    from xrd_finder.services.cod_cif_store import atomic_save_cif
    from xrd_finder.services.import_recovery import ImportBatchJournal,cleanup_interrupted_imports
    from xrd_finder.services.local_phase_cache import TRANSFERABLE_LIBRARY_SOURCES
    from xrd_finder.services.phase_json_reader import iter_phase_entries

    source_path = Path(path).resolve()
    allowed = {str(s or '').upper() for s in (allowed_sources or TRANSFERABLE_LIBRARY_SOURCES)}
    allowed &= set(TRANSFERABLE_LIBRARY_SOURCES)
    def check():
        if cancelled():
            raise CancelledError('Phase library import cancelled; committed batches retained')
    def signature(stat):
        return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns
    last_progress = 0.
    def report(label,value,total, *, force=False):
        nonlocal last_progress
        now = monotonic()
        if progress and (force or now-last_progress>=.1):
            progress(label,value,total)
            last_progress = now
    def retry(action):
        deadline = monotonic()+30.
        while True:
            check()
            try:
                return action()
            except sqlite3.OperationalError as error:
                if (getattr(error,'sqlite_errorcode',0)&255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) or monotonic()>=deadline:
                    raise
                sleep(.02)
    check()
    with source_path.open('r',encoding='utf-8-sig',newline='\n') as stream, ExitStack() as resources:
        cleanup_interrupted_imports(cache,progress=progress,cancelled=cancelled)
        original = signature(os.fstat(stream.fileno()))
        size = original[2]
        def unchanged():
            if signature(os.fstat(stream.fileno()))!=original or signature(source_path.stat())!=original:
                raise ValueError('The phase library JSON changed during import; committed batches retained')
        report('Validating phase library',0,1000,force=True)
        # Keep only small key/position metadata, on disk with a bounded cache.
        # Full card/CIF payloads are still consumed one at a time. The unnamed
        # SQLite file is removed when this owned connection closes or exits.
        positions = resources.enter_context(closing(sqlite3.connect('')))
        positions.execute('pragma cache_size=-2048')
        positions.execute('create table last_entry(source text,entry_id text,position integer,'
                          'primary key(source,entry_id)) without rowid')
        pending = []
        save_positions = ('insert into last_entry values(?,?,?) on conflict(source,entry_id) '
                          'do update set position=excluded.position')
        total = 0
        for index,entry in enumerate(iter_phase_entries(stream,cancelled=cancelled,
                progress=lambda value:report('Validating phase library',min(1000,value*1000//max(1,size)),1000))):
            total = index+1
            identity = _transfer_identity(entry,index,allowed)
            if identity is not None:pending.append((*identity,index))
            if len(pending)>=IMPORT_BATCH_SIZE:
                positions.executemany(save_positions,pending);pending.clear()
        if pending:positions.executemany(save_positions,pending)
        positions.commit()
        report('Validating phase library',1000,1000,force=True)
        check();unchanged();stream.seek(0)
        imported = 0
        directories = {}
        journal = None
        batch_new = 0
        def remove_uncommitted():
            nonlocal journal
            if journal is not None:journal.abort();journal=None
        with closing(cache._connect()) as connection:
            connection.execute('pragma busy_timeout=100')
            def commit(done):
                nonlocal imported,batch_new,journal
                check();unchanged()
                # Native cancellation must not interrupt the internal commit
                # after SQLite has made the batch durable.
                connection.set_progress_handler(None,0)
                retry(connection.commit)
                imported += batch_new
                batch_new = 0
                saved_journal,journal = journal,None
                directories.clear()
                if saved_journal is not None:saved_journal.finish()
                report('Importing phase cards',done,total,force=True)
            try:
                report('Importing phase cards',0,total,force=True)
                done = 0
                for index,entry in enumerate(iter_phase_entries(stream,cancelled=cancelled)):
                    check()
                    if index%IMPORT_BATCH_SIZE==0:
                        unchanged()
                        retry(lambda:connection.execute('begin immediate'))
                        connection.set_progress_handler(lambda:int(cancelled()),5000)
                    identity = _transfer_identity(entry,index,allowed)
                    chosen = (positions.execute('select position from last_entry where source=? and entry_id=?',identity).fetchone()
                              if identity is not None else None)
                    if chosen is not None and chosen[0]==index:
                        source,entry_id = identity
                        cif_text = str(entry['cif_text'])
                        previous = connection.execute('select cif_path from phases where source=? and entry_id=?',
                            (source,entry_id)).fetchone()
                        data = cif_text.encode('utf-8')
                        target = Path(previous[0]) if previous is not None and previous[0] else None
                        try:
                            same = target is not None and target.is_file() and target.read_bytes()==data
                        except OSError:
                            same = False
                        if not same:
                            if source not in directories:
                                if journal is None:journal=ImportBatchJournal(cache)
                                registered=journal.directory(source)
                                # Preserve the existing persisted path spelling
                                # (including a caller's relative library root).
                                directories[source]=cache._transfer_import_dir(source)/registered.name
                            # Unique per card, including repeated keys with
                            # changed content; never overwrite an older CIF.
                            target = directories[source]/f'{index}-{sha256(data).hexdigest()[:16]}.cif'
                            atomic_save_cif(target,data)
                        cached = cache._entry_from_transfer_payload(entry,source,entry_id,target)
                        cache._upsert(connection,cached,keep_cif=False,skip_unchanged=True)
                        batch_new += previous is None
                    done = index+1
                    if done%IMPORT_BATCH_SIZE==0:
                        commit(done)
                check();unchanged()
                if connection.in_transaction:
                    commit(done)
                else:
                    report('Importing phase cards',done,total,force=True)
                check()
                return imported
            except Exception:
                connection.set_progress_handler(None,0)
                connection.rollback()
                remove_uncommitted()
                check()
                raise
            finally:
                connection.set_progress_handler(None,0)
