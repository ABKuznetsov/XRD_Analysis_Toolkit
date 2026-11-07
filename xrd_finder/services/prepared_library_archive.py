"""Portable, byte-preserving snapshots of prepared local phase libraries."""
from concurrent.futures import CancelledError
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import tempfile
from itertools import zip_longest
from zipfile import ZipFile, ZIP_DEFLATED

from xrd_finder import __version__
from xrd_finder.services.cod_cif_store import atomic_save_cif, lock_cifs
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION
from xrd_finder.services.cache_storage import COMPACT_STORAGE_VERSION, SUPPORTED_STORAGE_VERSIONS, rewrite_payloads, optimize_database_copy
from xrd_finder.services.normalized_reflections import normalized_reflections, denormalize_reflections, validate_normalized_schema
from xrd_finder.services.reference_labels import ensure_label_schema
from xrd_finder.services.cif_import_identity import ensure_origin_schema, validate_origins, bind_origins

PHASE_TABLES = ('phases','phase_elements','phase_peaks','phase_fingerprints',
                'phase_fingerprint_state','phase_chemistry','reference_preparation_failures','phase_reference_labels',
                'local_cif_origins')
TABLES = PHASE_TABLES+('search_cache',)
MAX_UNPACKED_BYTES = 64*1024**3


@dataclass(frozen=True)
class PreparedLibraryResult:
    phases: int
    files: int
    ready: int
    missing_cifs: int
    sources: tuple[str, ...]


def _check(cancelled):
    if cancelled():
        raise CancelledError('Library transfer cancelled; completed original data are retained')


def _hash(path, cancelled):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while block := handle.read(1024*1024):
            _check(cancelled)
            digest.update(block)
    return digest.hexdigest()


def _relative(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe library archive path')
    return path


def export_prepared_library(cache, path, *, progress=None, cancelled=lambda: False, compact=True):
    _check(cancelled)
    target = Path(path)
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='xrd-library-export-') as folder:
        snapshot = Path(folder)/'index.sqlite'
        if compact:
            optimize_database_copy(cache.index_path,snapshot,progress=progress,cancelled=cancelled)
        else:
            with closing(cache._connect()) as original,closing(sqlite3.connect(snapshot)) as saved:
                original.backup(saved,pages=256,progress=lambda *_:_check(cancelled))
            with closing(sqlite3.connect(snapshot)) as saved,saved:
                saved.execute('pragma journal_mode=delete')
                rewrite_payloads(saved,compact=False,progress=progress,cancelled=cancelled)
                denormalize_reflections(saved,cancelled=cancelled)
                saved.execute('pragma user_version=0')
        with closing(sqlite3.connect(snapshot)) as saved:
            with saved:
                ensure_label_schema(saved)
                ensure_origin_schema(saved)
                saved.execute('delete from local_cif_origins where not exists (select 1 from phases p where p.source=local_cif_origins.source and p.entry_id=local_cif_origins.entry_id)')
                saved.execute('delete from phase_reference_labels where not exists (select 1 from phases p where p.source=phase_reference_labels.source and p.entry_id=phase_reference_labels.entry_id)')
            rows = saved.execute('select source,entry_id,cif_path from phases').fetchall()
            paths = {Path(row[2]).resolve() for row in rows if row[2] and Path(row[2]).is_file()}
            paths.update(item.resolve() for item in cache.root.rglob('*.cif') if item.is_file())
            blobs = {};path_blobs = {};aliases = []
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent,suffix='.part',delete=False) as handle:
                    temporary = Path(handle.name)
                with ZipFile(temporary,'w',compression=ZIP_DEFLATED,compresslevel=3,allowZip64=True) as archive:
                    for index,original in enumerate(sorted(paths),1):
                        _check(cancelled)
                        with lock_cifs([original],check_cancelled=lambda:_check(cancelled)):
                            before = original.stat()
                            digest = _hash(original,cancelled)
                            name = 'blobs/'+digest+'.cif'
                            if name not in blobs:
                                archive.write(original,name)
                                blobs[name] = digest
                            after = original.stat()
                            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                                raise ValueError('CIF changed during library export; retry: '+str(original))
                            path_blobs[str(original)] = name
                            if original.is_relative_to(cache.root.resolve()):
                                aliases.append(dict(path=original.relative_to(cache.root.resolve()).as_posix(),blob=name))
                        if progress and (index%100==0 or index==len(paths)):
                            progress('Saving original CIFs',index,len(paths))
                    updates = [(path_blobs.get(str(Path(row[2]).resolve()),'') if row[2] else '',row[0],row[1]) for row in rows]
                    missing = sum(bool(row[2]) and not new[0] for row,new in zip(rows,updates))
                    with saved:
                        saved.executemany('update phases set cif_path=? where source=? and entry_id=?',updates)
                    ready = saved.execute("select count(*) from phases where derived_version=? and peaks_json not in ('','[]')",(DERIVED_CACHE_VERSION,)).fetchone()[0]
                    sources = tuple(row[0] for row in saved.execute('select distinct source from phases order by source'))
                    auxiliary = {}
                    for reference in (cache.root/'references').glob('corundum-*.json'):
                        if re.fullmatch(r'corundum-[a-f0-9]{64}\.json',reference.name):
                            _check(cancelled)
                            name = 'references/'+reference.name
                            auxiliary[name] = _hash(reference,cancelled)
                            archive.write(reference,name)
                    storage_version = saved.execute('pragma user_version').fetchone()[0]
                    manifest = dict(schema=2 if storage_version else 1,
                        storage_version=storage_version,application='XRD Phase Finder prepared library',
                        app_version=__version__,derived_version=DERIVED_CACHE_VERSION,
                        calculation_signature=cache.calculated_iic.signature,auxiliary=auxiliary,
                        phases=len(rows),ready=ready,missing_cifs=missing,sources=sources,
                        files=blobs,local_files=aliases,database_sha256=_hash(snapshot,cancelled))
                    if progress:
                        progress('Saving prepared SQLite and search indexes',0,0)
                    archive.write(snapshot,'index.sqlite')
                    archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
                _check(cancelled)
                temporary.replace(target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return PreparedLibraryResult(len(rows),len(blobs),ready,missing,sources)


def _validate_database(saved, destination):
    objects = saved.execute("select type,name,sql from sqlite_master where type in ('table','view','trigger')").fetchall()
    expected_triggers = dict(destination.execute("select name,sql from sqlite_master where type='trigger'"))
    normalized_objects = validate_normalized_schema(saved) if normalized_reflections(saved) else frozenset()
    for kind,name,sql in objects:
        if name in normalized_objects:
            continue  # Exact known schema, not arbitrary archive views/triggers.
        if kind=='view' or (kind=='table' and (name not in (*TABLES,'sqlite_stat1','sqlite_stat4') or 'virtual table' in (sql or '').lower())):
            raise ValueError('Unsupported database object in prepared library')
        if kind=='trigger' and expected_triggers.get(name)!=sql:
            raise ValueError('Unsupported database trigger in prepared library')
    for table in TABLES:
        columns = saved.execute('pragma table_xinfo('+table+')').fetchall()
        expected = destination.execute('pragma table_xinfo('+table+')').fetchall()
        # A compatibility view has no declared PK; logical peak keys are fixed.
        def schema(rows):
            return {(r[1],r[2],0 if table=='phase_peaks' else r[5]) for r in rows}
        if not columns or any(row[6] for row in columns) or schema(columns)!=schema(expected):
            raise ValueError('Library SQL schema differs; use the same Finder version on both computers')
    if saved.execute('pragma quick_check').fetchone()[0]!='ok':
        raise ValueError('The prepared SQLite library is damaged')


def _incoming_matches(destination, *, progress, cancelled, tables=TABLES):
    """Compare affected rows in the write snapshot, without materializing a library.

    Count auxiliary rows as well as their values: a matching card header alone
    cannot certify a complete reflection/fingerprint index. Unrelated cards and
    unrelated cached queries are outside this archive's replacement scope.
    """
    missing = object()
    for index,table in enumerate(tables,1):
        if progress:
            progress('Checking existing prepared records',index,len(tables))
        _check(cancelled)
        columns = destination.execute('pragma main.table_info('+table+')').fetchall()
        keys = [row[1] for row in sorted(columns,key=lambda row:row[5]) if row[5]]
        if table=='phase_peaks':
            keys = ['source','entry_id','peak_index']
        fields = ','.join('t.'+row[1] for row in columns)
        order = ','.join('t.'+key for key in keys)
        scope = 'search_cache' if table=='search_cache' else 'phases'
        scope_keys = keys if table=='search_cache' else ('source','entry_id')
        join = ' and '.join('t.'+key+'=p.'+key for key in scope_keys)
        query = f'select {fields} from main.{table} t join incoming.{scope} p on {join} order by {order}'
        with closing(destination.execute(query)) as existing,closing(destination.execute(
                f'select {fields} from incoming.{table} t order by {order}')) as incoming:
            for number,(left,right) in enumerate(zip_longest(existing,incoming,fillvalue=missing)):
                if number%256==0:
                    _check(cancelled)
                if left is missing or right is missing or tuple(left)!=tuple(right):
                    return False
    _check(cancelled)
    return True


def import_prepared_library(cache, path, *, progress=None, cancelled=lambda: False):
    _check(cancelled)
    with tempfile.TemporaryDirectory(prefix='xrd-library-import-') as folder:
        folder = Path(folder)
        with ZipFile(path) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names)!=len(set(names)) or sum(member.file_size for member in members)>MAX_UNPACKED_BYTES:
                raise ValueError('Invalid or excessively large library archive')
            for name in names:
                _relative(name)
            if archive.getinfo('manifest.json').file_size>64*1024**2:
                raise ValueError('Library manifest is too large')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('schema') not in (1,2) or manifest.get('application')!='XRD Phase Finder prepared library':
                raise ValueError('Unsupported prepared library archive')
            if manifest.get('schema')==2 and manifest.get('storage_version') not in SUPPORTED_STORAGE_VERSIONS[1:]:
                raise ValueError('Unsupported prepared library storage format')
            if manifest.get('derived_version')!=DERIVED_CACHE_VERSION:
                raise ValueError('Library calculation version differs; use the same Finder version on both computers')
            if not cache.calculated_iic.compatible_library_signature(manifest.get('calculation_signature')):
                raise ValueError('Library CrIStMa/reference settings differ; install the same Finder runtime on both computers')
            files = manifest['files']
            auxiliary = manifest.get('auxiliary',{})
            if not isinstance(auxiliary,dict) or any(not re.fullmatch(r'references/corundum-[a-f0-9]{64}\.json',name) for name in auxiliary):
                raise ValueError('Unsupported library reference file')
            if not isinstance(files,dict) or set(names)!=set(files)|set(auxiliary)|{'manifest.json','index.sqlite'}:
                raise ValueError('Incomplete prepared library archive')
            for name,digest in files.items():
                if name!='blobs/'+digest+'.cif' or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('Invalid original CIF identity')
            checksums = {**files,**auxiliary,'index.sqlite':manifest['database_sha256']}
            for index,name in enumerate(checksums,1):
                _check(cancelled)
                target = folder/name
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as original,target.open('wb') as output:
                    while block := original.read(1024*1024):
                        _check(cancelled);output.write(block)
                expected = checksums[name]
                if _hash(target,cancelled)!=expected:
                    raise ValueError('Library checksum mismatch: '+name)
                if progress and (index%100==0 or index==len(checksums)):
                    progress('Checking prepared library archive',index,len(checksums))
        snapshot = folder/'index.sqlite'
        with closing(sqlite3.connect(snapshot)) as saved,closing(cache._connect()) as destination:
            saved.execute('pragma trusted_schema=off')
            if saved.execute('pragma user_version').fetchone()[0] != manifest.get('storage_version',0):
                raise ValueError('Prepared library storage version does not match its manifest')
            # Older libraries have no optional provenance labels. Adding an
            # empty, fixed-schema table requires no recalculation of reflections.
            has_labels = saved.execute("select 1 from sqlite_master where type='table' and name='phase_reference_labels'").fetchone() is not None
            # Origins are additive identity metadata. An older archive must not
            # erase a destination's established path-to-public-ID bindings.
            comparison_tables = tuple(t for t in TABLES if t!='local_cif_origins'
                                      and (has_labels or t!='phase_reference_labels'))
            with saved:
                ensure_label_schema(saved)
                ensure_origin_schema(saved)
            _validate_database(saved,destination)
            validate_origins(saved)
            # Dictionary IDs belong to one database. Merge by public card keys,
            # never copy foreign numeric IDs into another laboratory's library.
            with saved:
                denormalize_reflections(saved,cancelled=cancelled)
            rows = saved.execute('select source,entry_id,cif_path from phases').fetchall()
            referenced = {row[2] for row in rows if row[2]}
            if referenced-set(files):
                raise ValueError('A prepared card refers to a missing CIF')
            blob_root = cache.root/'library_cif'
            blob_root.mkdir(parents=True,exist_ok=True)
            for index,name in enumerate(files,1):
                _check(cancelled)
                target = blob_root/Path(name).name
                with lock_cifs([target],check_cancelled=lambda:_check(cancelled)):
                    if not target.is_file() or _hash(target,cancelled)!=files[name]:
                        atomic_save_cif(target,(folder/name).read_bytes())
                if progress and (index%100==0 or index==len(files)):
                    progress('Restoring original CIFs',index,len(files))
            for alias in manifest.get('local_files',[]):
                relative = _relative(alias['path']);name = alias['blob']
                if name not in files:
                    raise ValueError('Invalid downloaded CIF reference')
                # Indexed cards use the portable content-addressed originals.
                # Restore unindexed downloads to their canonical cache location.
                if name in referenced or relative.parts[0] not in {'cif','cod_bulk_cif','user_cif','materials_project_cif'}:
                    continue
                target = (cache.root/str(relative)).resolve()
                if not target.is_relative_to(cache.root.resolve()):
                    raise ValueError('Unsafe downloaded CIF location')
                with lock_cifs([target],check_cancelled=lambda:_check(cancelled)):
                    if not target.exists():
                        atomic_save_cif(target,(folder/name).read_bytes())
            for name in auxiliary:
                _check(cancelled)
                atomic_save_cif(cache.root/name,(folder/name).read_bytes())
            updates = [(str((blob_root/Path(row[2]).name).resolve()) if row[2] else '',row[0],row[1]) for row in rows]
            with saved:
                saved.executemany('update phases set cif_path=? where source=? and entry_id=?',updates)
                rewrite_payloads(saved,compact=cache.compact_storage,
                    sql_reflections=cache.storage_version>=COMPACT_STORAGE_VERSION,progress=progress,cancelled=cancelled)
            destination.execute('attach database ? as incoming',(str(snapshot),))
            try:
                destination.set_progress_handler(lambda:1 if cancelled() else 0,10000)
                with destination:
                    destination.execute('begin immediate')
                    for source, in destination.execute('select distinct source from incoming.local_cif_origins'):
                        _check(cancelled)
                        bind_origins(destination,source,dict(destination.execute(
                            'select relative_path,entry_id from incoming.local_cif_origins where source=?',(source,))),
                            check=lambda:_check(cancelled))
                    if not _incoming_matches(destination,progress=progress,cancelled=cancelled,tables=comparison_tables):
                        for index,table in enumerate(TABLES,1):
                            _check(cancelled)
                            if table=='local_cif_origins':
                                continue  # Merged above, with no public-ID reassignment.
                            if table!='phases' and table!='search_cache':
                                destination.execute(f'delete from {table} where exists (select 1 from incoming.phases p where p.source={table}.source and p.entry_id={table}.entry_id)')
                            columns = [row[1] for row in destination.execute('pragma table_info('+table+')')]
                            fields = ','.join(columns)
                            destination.execute(f'insert or replace into main.{table} ({fields}) select {fields} from incoming.{table}')
                            if progress:
                                progress('Restoring prepared index: '+table,index,len(TABLES))
                    _check(cancelled)
            except sqlite3.OperationalError:
                _check(cancelled)
                raise
            finally:
                destination.set_progress_handler(None,0)
                destination.execute('detach database incoming')
    return PreparedLibraryResult(len(rows),len(files),int(manifest['ready']),int(manifest['missing_cifs']),tuple(manifest['sources']))
