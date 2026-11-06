"""Recover only explicitly owned CIF files from inactive import batches."""
from concurrent.futures import CancelledError
from dataclasses import dataclass
import errno
from itertools import islice
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
from time import monotonic,sleep
from uuid import uuid4

MAX_BATCHES = 16
MAX_FILES = 256
MAX_MANIFEST_BYTES = 16*1024
OWNER_NAME = '.import-owner'
_TOKEN = re.compile(r'[a-f0-9]{32}')
_OWNED_FILE = re.compile(r'(?:[0-9]+-[a-f0-9]{16}\.cif|tmp[A-Za-z0-9_-]+\.part)')


def _check(cancelled):
    if cancelled():raise CancelledError('Interrupted import cleanup cancelled; remaining journal retained')


def _try_lock(handle):
    handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return True
    except OSError as error:
        if error.errno in (errno.EACCES,errno.EAGAIN,errno.EDEADLK):return False
        raise


def _same_file(handle,path):
    try:
        opened,current=os.fstat(handle.fileno()),path.lstat()
        return stat.S_ISREG(current.st_mode) and (opened.st_dev,opened.st_ino)==(current.st_dev,current.st_ino)
    except OSError:return False


class ImportBatchJournal:
    def __init__(self,cache):
        self.cache=cache;self.root=cache.root.resolve()
        self.registry=self.root/'import_pending'
        if self.registry.is_symlink():raise ValueError('Import journal directory must not be a symlink')
        self.registry.mkdir(parents=True,exist_ok=True)
        self.directories={};self._handle=None;self._committed=False
        # Another cleaner may win the short create/lock race. Never publish a
        # manifest while holding a lease whose directory entry was unlinked.
        for _ in range(4):
            self.token=uuid4().hex
            self.lease_path=self.registry/(self.token+'.lock')
            self.marker=self.registry/(self.token+'.json')
            self._handle=self.lease_path.open('x+b')
            self._handle.write(b'1');self._handle.flush()
            if _try_lock(self._handle) and _same_file(self._handle,self.lease_path):return
            self.close()
        raise OSError('Could not reserve an import journal')

    def close(self):
        if self._handle is not None:self._handle.close();self._handle=None

    def _expected(self,source):
        directory=self.cache._transfer_import_dir(source).resolve()/('json-import-'+self.token)
        if not directory.is_relative_to(self.root):raise ValueError('Import directory is outside the library')
        return directory

    def _save(self):
        payload=dict(schema=1,token=self.token,root=str(self.root),
                     directories=[dict(source=source,path=str(path.relative_to(self.root)))
                                  for source,path in self.directories.items()])
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=self.registry,prefix=self.token+'.',suffix='.part',delete=False) as output:
                temporary=Path(output.name)
                output.write(json.dumps(payload).encode('utf-8'));output.flush();os.fsync(output.fileno())
            temporary.replace(self.marker)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)

    def directory(self,source):
        if self._handle is None:raise RuntimeError('Import journal is not active')
        if source not in self.directories:
            directory=self._expected(source)
            if directory.exists():raise FileExistsError(directory)
            self.directories[source]=directory
            self._save()  # Ownership intent must precede every new CIF directory.
            directory.mkdir(parents=True)
            (directory/OWNER_NAME).write_text(self.token,encoding='ascii')
        return self.directories[source]

    def _files(self,cancelled):
        files=[]
        for source,directory in self.directories.items():
            _check(cancelled)
            if directory!=self._expected(source) or directory.is_symlink() or directory.resolve()!=directory:
                raise ValueError('Unsafe import directory')
            if not directory.exists():continue
            owner=directory/OWNER_NAME
            if (owner.is_symlink() or not owner.is_file() or owner.stat().st_size!=32
                    or owner.read_bytes()!=self.token.encode('ascii')):
                raise ValueError('Import directory ownership is unknown')
            for path in directory.iterdir():
                _check(cancelled)
                if path.name==OWNER_NAME:continue
                info=path.lstat()
                if not _OWNED_FILE.fullmatch(path.name) or not stat.S_ISREG(info.st_mode):
                    raise ValueError('Unexpected file in interrupted import directory')
                files.append((path,(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)))
                if len(files)>MAX_FILES:raise ValueError('Interrupted import batch is too large')
        return files

    def _empty_directories(self):
        for directory in self.directories.values():
            if directory.is_symlink() or directory.resolve()!=directory:
                raise OSError('Import directory changed during cleanup')
            owner=directory/OWNER_NAME
            if directory.exists() and list(islice(directory.iterdir(),2))==[owner]:
                owner.unlink()
                try:directory.rmdir()
                except OSError:
                    # Keep ownership provable if an empty-directory removal
                    # fails after its files were successfully cleaned.
                    try:
                        with owner.open('x',encoding='ascii') as saved:saved.write(self.token)
                    except OSError:pass
                    raise

    def _forget(self):
        removed=False
        try:
            self.marker.unlink(missing_ok=True)
            for path in self.registry.glob(self.token+'.*.part'):
                if path.is_file() and not path.is_symlink():path.unlink()
            removed=True
        except OSError:pass
        finally:self.close()
        if removed:
            try:self.lease_path.unlink(missing_ok=True)
            except OSError:return False
        return removed

    def finish(self):
        # Once the main SQL commit succeeded, this object must never abort CIFs,
        # even if removal of the small journal itself fails.
        self._committed=True
        return self._forget()

    def abort(self):
        if self._committed:return self.finish()
        if self._handle is None:return False
        # The caller has rolled back its SQL transaction. Release the lease,
        # then use the same coherent reference check as crash recovery: another
        # writer may have committed a reference, and ownership alone cannot
        # authorize deleting a now-shared file.
        self.close()
        try:
            cleanup_interrupted_imports(self.cache)
            return not self.marker.exists()
        except (OSError,ValueError,sqlite3.Error):
            return False  # Leave a recoverable journal for retry.

    @classmethod
    def _open(cls,cache,path):
        journal=cls.__new__(cls)
        journal.cache=cache;journal.root=cache.root.resolve();journal.registry=path.parent
        journal.token=path.stem;journal.lease_path=path;journal.marker=path.with_suffix('.json')
        journal.directories={};journal._handle=None;journal._committed=False
        if path.is_symlink():raise ValueError('Unsafe import lease')
        flags=os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)
        journal._handle=os.fdopen(os.open(path,flags),'r+b')
        try:
            if not _try_lock(journal._handle):journal.close();return None
            if not _same_file(journal._handle,path):raise ValueError('Import lease changed')
            if not journal.marker.exists():return journal
            if journal.marker.is_symlink():raise ValueError('Unsafe import manifest')
            with journal.marker.open('rb') as source:raw=source.read(MAX_MANIFEST_BYTES+1)
            if len(raw)>MAX_MANIFEST_BYTES:raise ValueError('Import manifest is too large')
            value=json.loads(raw)
            if (not isinstance(value,dict) or value.get('schema')!=1 or value.get('token')!=journal.token
                    or value.get('root')!=str(journal.root)):
                raise ValueError('Unrecognized import manifest')
            directories=value.get('directories')
            if not isinstance(directories,list) or len(directories)>8:raise ValueError('Invalid import directories')
            from xrd_finder.services.local_phase_cache import TRANSFERABLE_LIBRARY_SOURCES
            for item in directories:
                source,relative=item['source'],Path(item['path'])
                if (source not in TRANSFERABLE_LIBRARY_SOURCES or source in journal.directories
                        or relative.is_absolute() or '..' in relative.parts):raise ValueError('Unsafe import path')
                directory=journal.root/relative
                if directory!=journal._expected(source):raise ValueError('Unexpected import path')
                journal.directories[source]=directory
            return journal
        except Exception:journal.close();raise


@dataclass
class ImportCleanupResult:
    files_removed:int=0
    bytes_removed:int=0
    protected_files:int=0
    completed_batches:int=0
    active_batches:int=0
    invalid_batches:int=0
    deferred_batches:int=0
    more_pending:bool=False


def cleanup_interrupted_imports(cache, *, progress=None,cancelled=lambda:False):
    """One coherent reference scan for a bounded set of inactive owned batches."""
    _check(cancelled)
    if getattr(cache,'_read_only',False):raise ValueError('Import cleanup requires a writable library owner')
    result=ImportCleanupResult();registry=cache.root.resolve()/'import_pending'
    if not registry.exists():return result
    if registry.is_symlink():raise ValueError('Unsafe import journal directory')
    batches=[]
    try:
        seen=0
        with os.scandir(registry) as entries:
            for item in entries:
                _check(cancelled)
                if not item.name.endswith('.lock') or not _TOKEN.fullmatch(item.name[:-5]):continue
                if seen>=MAX_BATCHES:result.more_pending=True;break
                seen+=1;journal=None
                try:
                    journal=ImportBatchJournal._open(cache,Path(item.path))
                    if journal is None:result.active_batches+=1;continue
                    files=journal._files(cancelled)
                    batches.append((journal,files))
                except (OSError,ValueError,KeyError,TypeError):
                    result.invalid_batches+=1
                    if journal is not None:journal.close()
                except BaseException:
                    if journal is not None:journal.close()
                    raise
        if not batches:return result
        candidates={os.path.normcase(str(path)):False for _journal,files in batches for path,_info in files}
        connection=None
        try:
            if candidates:
                connection=sqlite3.connect(cache.index_path.resolve().as_uri()+'?mode=rw',uri=True,timeout=.1)
                deadline=monotonic()+1.
                while True:
                    _check(cancelled)
                    try:connection.execute('begin immediate');break
                    except sqlite3.OperationalError as error:
                        if (getattr(error,'sqlite_errorcode',0)&255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):raise
                        if monotonic()>=deadline:
                            result.deferred_batches+=len(batches);return result
                        sleep(.01)
                connection.set_progress_handler(lambda:int(cancelled()),5000)
                if progress:progress('Checking interrupted import references',0,0)
                _check(cancelled)
                # Resolve aliases conservatively, once per live reference. A
                # failed/cancelled scan is never interpreted as zero references.
                last=monotonic()
                for index,(path,) in enumerate(connection.execute("select cif_path from phases where cif_path!=''"),1):
                    _check(cancelled)
                    try:
                        normalized=os.path.normcase(os.path.realpath(path,strict=True))
                    except FileNotFoundError:
                        # A missing path cannot reference an existing candidate.
                        # Permission/alias errors must still stop the scan;
                        # non-strict realpath would silently hide those errors.
                        continue
                    if normalized in candidates:candidates[normalized]=True
                    if progress and monotonic()-last>=.1:
                        progress('Checking interrupted import references',index,0);last=monotonic()
                _check(cancelled)
            total=sum(len(files) for _journal,files in batches);done=0
            for journal,files in batches:
                try:
                    for path,expected in files:
                        _check(cancelled)
                        if candidates[os.path.normcase(str(path))]:result.protected_files+=1
                        else:
                            if path.parent.is_symlink() or path.parent.resolve()!=path.parent:
                                raise OSError('Import directory changed during cleanup')
                            current=path.lstat()
                            if (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns)!=expected:
                                raise OSError('Interrupted import file changed during cleanup')
                            path.unlink();result.files_removed+=1;result.bytes_removed+=current.st_size
                        done+=1
                        if progress:progress('Cleaning interrupted imports',done,total)
                    journal._empty_directories()
                    if journal.finish():result.completed_batches+=1
                    else:result.deferred_batches+=1
                except OSError:result.deferred_batches+=1
            return result
        except sqlite3.OperationalError:
            _check(cancelled);raise
        finally:
            if connection is not None:
                connection.set_progress_handler(None,0);connection.rollback();connection.close()
    finally:
        for journal,_files in batches:journal.close()
