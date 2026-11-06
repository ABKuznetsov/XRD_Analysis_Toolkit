"""Build a refreshed legacy-library snapshot before the main GUI owns any services."""
from concurrent.futures import CancelledError
from contextlib import closing
from dataclasses import dataclass,field
from pathlib import Path
import re,shutil,sqlite3,tempfile
from uuid import uuid4

from xrd_finder.services.cache_storage import COMPACT_STORAGE_VERSION,CURRENT_STORAGE_VERSION,storage_version,compact_indexes
from xrd_finder.services.normalized_reflections import normalize_reflections
from xrd_finder.services.library_storage_migration import migrate_library_storage,_verify,_retry
from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.services.prepared_library_archive import TABLES


@dataclass(frozen=True)
class LegacyLibraryInfo:
    version: int
    cards: int


@dataclass
class LibraryRefreshResult:
    activated: bool
    compacted: bool
    cards: int
    downloaded: int=0
    prepared: int=0
    failures: dict=field(default_factory=dict)
    before_bytes: int=0
    after_bytes: int=0
    notice: str=''


def inspect_legacy_library(root):
    path=Path(root)/'index.sqlite'
    if not path.is_file() or not path.stat().st_size:return None
    version=storage_version(path,recover=True)
    if version>=COMPACT_STORAGE_VERSION:return None  # Storage-only upgrades never redownload/recalculate ready cards.
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
        return LegacyLibraryInfo(version,c.execute('select count(*) from phases').fetchone()[0])


def _check(cancelled):
    if cancelled():raise CancelledError('Library update cancelled; original library retained')


def _file_id(path):
    s=path.stat();return s.st_dev,s.st_ino


def _compact_active(connection):
    connection.execute('vacuum');_verify(connection)


def refresh_legacy_library(root,*,api_key='',progress=None,cancelled=lambda:False,
                           download_cod=None,download_mp=None,download_mp_batch=None,prepare=None):
    """Refresh by stable identities; atomically replace rows, never exchange an open SQL file.

    Online failures retain the original prepared card; they do not erase it or
    claim that it was refreshed. Fresh files belong to this run until commit.
    """
    from xrd_finder.services.cod_inorganic_library import collect_cifs
    from xrd_finder.services.cod_inorganic_worker import prepare_paths
    from xrd_finder.services.materials_project_service import MaterialsProjectService
    root=Path(root).resolve();source=root/'index.sqlite'
    info=inspect_legacy_library(root)
    if info is None:return LibraryRefreshResult(False,True,0)
    collect=download_cod or collect_cifs
    mp_service=MaterialsProjectService(api_key)
    mp=download_mp or mp_service.download_cif
    mp_bulk=download_mp_batch or (mp_service.download_cifs if download_mp is None else None)
    prepare=prepare or prepare_paths
    fresh=root/'library_refresh'/uuid4().hex
    committed=False
    result=LibraryRefreshResult(False,False,info.cards,before_bytes=source.stat().st_size)
    def report(label,value=0,maximum=0):
        _check(cancelled)
        if progress:progress(label,int(value),int(maximum))
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as guard, \
                tempfile.TemporaryDirectory(prefix='.xrd-library-update-',dir=root.parent) as folder:
            identity=_file_id(source);generation=guard.execute('pragma data_version').fetchone()[0]
            workspace=Path(folder);stage_root=workspace/'library';stage_root.mkdir()
            stage=stage_root/'index.sqlite'
            report('Reading existing library',0,info.cards)
            with closing(sqlite3.connect(stage)) as saved:
                guard.backup(saved,pages=256,progress=lambda *_:_check(cancelled))
            # Schema work and lossless conversion affect the disposable snapshot only.
            cache=LocalPhaseCache(stage_root)
            migrate_library_storage(stage,workspace/'original.sqlite',progress=progress,cancelled=cancelled)
            cache=LocalPhaseCache(stage_root)
            with closing(cache._connect()) as c:
                records=[tuple(r) for r in c.execute('select source,entry_id,cif_path from phases order by source,entry_id')]
            jobs={};fresh.mkdir(parents=True)
            cod=[key for origin,key,_ in records if origin=='COD' and re.fullmatch(r'[1-9]\d{6}',key)]
            if cod:
                report('Downloading COD CIFs',0,len(cod))
                try:
                    downloaded=collect(cod,fresh/'COD',progress=progress,cancelled=cancelled)
                    jobs['COD']=list(downloaded.paths.items());result.downloaded+=len(jobs['COD'])
                    for key in set(cod)-set(downloaded.paths):
                        result.failures['COD:'+key]=downloaded.errors.get(key,'CIF unavailable; saved card retained')
                except CancelledError:raise
                except Exception as error:
                    for key in cod:result.failures['COD:'+key]=str(error)
            mp_ids=[key for origin,key,_ in records if origin=='MP' and re.fullmatch(r'mp-\d+',key)]
            valid={'COD':set(cod),'MP':set(mp_ids)}
            for origin,key,_ in records:
                if origin in valid and key not in valid[origin]:
                    result.failures[origin+':'+key]='Unrecognized online identifier; saved card retained'
            if mp_ids and mp_bulk is not None:
                report('Downloading Materials Project structures',0,len(mp_ids))
                try:
                    downloaded=mp_bulk(mp_ids,fresh/'MP',progress=progress,cancelled=cancelled)
                    jobs['MP']=list(downloaded.paths.items());result.downloaded+=len(jobs['MP'])
                    for key in set(mp_ids)-set(downloaded.paths):
                        result.failures['MP:'+key]=downloaded.errors.get(key,'CIF unavailable; saved card retained')
                except CancelledError:raise
                except Exception as error:
                    for key in mp_ids:result.failures['MP:'+key]=str(error)
            elif mp_ids:
                # Preserve the single-card injection seam and existing clients.
                failed=0
                for number,key in enumerate(mp_ids,1):
                    report('Downloading Materials Project CIFs',number-1,len(mp_ids))
                    try:
                        if failed>=2:raise RuntimeError('Download stopped after repeated server failures; saved card retained')
                        path=Path(mp(key,fresh/'MP'))
                        _check(cancelled)
                        if not path.is_file():raise ValueError('Downloaded CIF is missing')
                        jobs.setdefault('MP',[]).append((key,path));result.downloaded+=1;failed=0
                    except CancelledError:raise
                    except Exception as error:
                        failed+=1;result.failures['MP:'+key]=str(error)
            for origin,key,path in records:
                _check(cancelled)
                if origin in ('COD','MP'):continue
                if path and Path(path).is_file():jobs.setdefault(origin,[]).append((key,Path(path)))
            total=sum(len(paths) for paths in jobs.values());completed=0
            for origin,paths in jobs.items():
                report('Calculating reference profiles',completed,total)
                def ready(key,success,error):
                    nonlocal completed
                    completed+=1
                    if success:result.prepared+=1
                    else:result.failures[origin+':'+key]=error or 'Calculation failed; saved card retained'
                    report('Calculating reference profiles',completed,total)
                prepare(stage_root,paths,source=origin,ready=ready,cancelled=cancelled)
            report('Checking refreshed library',0,info.cards)
            with closing(cache._connect()) as c:
                _verify(c)
                used={Path(r[0]).resolve() for r in c.execute('select cif_path from phases where cif_path!=""')}
            # Failed refreshed CIFs are unused; never remove original/local files.
            for path in fresh.rglob('*.cif'):
                _check(cancelled)
                if path.resolve() not in used:path.unlink()
            report('Activating refreshed library',info.cards,info.cards)
            with closing(sqlite3.connect(source.as_uri()+'?mode=rw',uri=True,timeout=.1)) as writer:
                writer.execute('attach database ? as refreshed',(stage.as_uri()+'?mode=ro',))
                try:
                    _retry(lambda:writer.execute('begin immediate'),cancelled)
                    writer.set_progress_handler(lambda:int(cancelled()),10000)
                    if (_file_id(source)!=identity or guard.execute('pragma data_version').fetchone()[0]!=generation):
                        raise RuntimeError('The working library changed in another window; restart the update')
                    for left,right in (('main','refreshed'),('refreshed','main')):
                        if writer.execute(f'select source,entry_id from {left}.phases except select source,entry_id from {right}.phases limit 1').fetchone():
                            raise ValueError('The refreshed library has different card identities')
                    for table in TABLES:
                        old=writer.execute('pragma main.table_info('+table+')').fetchall()
                        new=writer.execute('pragma refreshed.table_info('+table+')').fetchall()
                        if table=='phase_peaks':
                            old={(r[1],r[2]) for r in old};new={(r[1],r[2]) for r in new}
                        if old!=new:raise ValueError('Library schema changed; original retained')
                    for number,table in enumerate(TABLES,1):
                        report('Updating working SQL: '+table,number,len(TABLES))
                        fields=','.join(r[1] for r in writer.execute('pragma main.table_info('+table+')'))
                        writer.execute('delete from main.'+table)
                        writer.execute(f'insert into main.{table} ({fields}) select {fields} from refreshed.{table}')
                    compact_indexes(writer)
                    normalize_reflections(writer,progress=progress,cancelled=cancelled)
                    writer.execute(f'pragma user_version={CURRENT_STORAGE_VERSION}')
                    _verify(writer);_check(cancelled)
                    writer.set_progress_handler(None,0)
                    _retry(writer.commit,cancelled)
                    committed=result.activated=True
                except sqlite3.OperationalError:
                    writer.set_progress_handler(None,0);writer.rollback();_check(cancelled);raise
                except Exception:
                    writer.set_progress_handler(None,0);writer.rollback();raise
                finally:
                    writer.set_progress_handler(None,0)
                    try:writer.execute('detach database refreshed')
                    except Exception as error:
                        if not committed:raise
                        result.notice='New storage is active; temporary snapshot close failed: '+str(error)
                try:
                    if progress:progress('Releasing old database space',0,0)
                    writer.set_progress_handler(lambda:int(cancelled()),10000)
                    _check(cancelled);_compact_active(writer);result.compacted=True
                except Exception as error:
                    result.notice+='\nNew storage is active; space compaction did not finish: '+str(error)
                finally:writer.set_progress_handler(None,0)
                try:
                    result.after_bytes=writer.execute('pragma page_count').fetchone()[0]*writer.execute('pragma page_size').fetchone()[0]
                except Exception as error:
                    result.notice+='\nNew storage is active; size could not be read: '+str(error)
        return result
    except Exception as error:
        if not committed:raise
        # Cleanup/connection-finalization errors cannot turn a durable new
        # library into a reported rollback or delete its now-referenced CIFs.
        result.notice+='\nNew storage is active; final cleanup did not finish: '+str(error)
        return result
    finally:
        if not committed and fresh.exists():shutil.rmtree(fresh)
