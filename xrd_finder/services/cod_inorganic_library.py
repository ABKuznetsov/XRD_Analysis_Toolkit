"""Original COD CIF downloads for a versioned, identifier-only selection."""
from concurrent.futures import CancelledError
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from queue import Queue, Full
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request
from zipfile import BadZipFile, ZipFile

from xrd_finder.services.network import open_url
from xrd_finder.services.cod_cif_store import atomic_save_cif, lock_cifs

SELECTION_DATE = '2026-06-02'
SELECTION_SOURCE = 'https://www.crystalimpact.com/match/download.htm'
COD_BASES = ('https://www.crystallography.net/cod', 'https://cod.ibt.lt/cod')
BATCH_SIZE = 250
MAX_CIF_BYTES = 8 * 1024 * 1024
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_BATCH_BYTES = 256 * 1024 * 1024
SELECTION_PATH = Path(__file__).resolve().parents[1]/'core/cod_inorganic_20260602.ids'


class LibraryCancelled(CancelledError):
    pass


@dataclass
class DownloadResult:
    paths: dict[str, Path] = field(default_factory=dict)
    downloaded: int = 0
    reused: int = 0
    missing: set[str] = field(default_factory=set)
    errors: dict[str, str] = field(default_factory=dict)


@dataclass
class LibraryResult:
    total: int
    downloaded: int = 0
    reused: int = 0
    prepared: int = 0
    skipped: int = 0
    download_failed: dict[str, str] = field(default_factory=dict)
    preparation_failed: dict[str, str] = field(default_factory=dict)
    cancelled: bool = False

    @property
    def failed(self):
        return {**self.download_failed, **self.preparation_failed}


def _check_cancelled(cancelled):
    if cancelled():
        raise LibraryCancelled('COD library preparation cancelled')


def load_selection(path=None):
    bundled = path is None
    path = SELECTION_PATH if bundled else Path(path)
    ids = tuple(line.strip() for line in path.read_text(encoding='ascii').splitlines()
                if line.strip() and not line.lstrip().startswith('#'))
    if not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r'[1-9]\d{6}', value) for value in ids):
        raise ValueError('Invalid COD identifier selection')
    if bundled and len(ids) != 77812:
        raise ValueError('The bundled COD selection is incomplete')
    return ids


def _valid_cif(data, identifier):
    if not data or len(data) > MAX_CIF_BYTES or b'\x00' in data:
        return False
    if not re.search(rb'(?mi)^\s*data_\S+', data) or b'_atom_site_' not in data:
        return False
    reported = re.findall(rb'(?mi)^\s*_cod_database_code\s+[\'\"]?(\d+)', data)
    return not reported or set(reported) == {identifier.encode('ascii')}


def extract_cif_batch(payload, identifiers, target_dir, *, cancelled=lambda: False):
    allowed = set(identifiers)
    files = {}
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if sum(member.file_size for member in members) > MAX_BATCH_BYTES:
                raise ValueError('COD ZIP has an excessive uncompressed size')
            for member in members:
                _check_cancelled(cancelled)
                name = PurePosixPath(member.filename.replace('\\', '/'))
                if name.is_absolute() or '..' in name.parts or ':' in member.filename:
                    raise ValueError('Unsafe path in COD ZIP')
                if member.is_dir() or name.suffix.lower() != '.cif':
                    continue
                identifier = name.stem
                if identifier not in allowed or identifier in files:
                    raise ValueError('COD ZIP contains an unexpected or duplicate identifier')
                if member.file_size > MAX_CIF_BYTES:
                    raise ValueError('COD CIF exceeds the supported size')
                data = archive.read(member)
                if not _valid_cif(data, identifier):
                    raise ValueError('Invalid CIF or mismatched COD number: '+identifier)
                files[identifier] = data
    except BadZipFile as error:
        raise ValueError('COD did not return a valid CIF ZIP archive') from error
    if not files:
        raise ValueError('COD ZIP contains no requested CIF structures')
    root = Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {}
    with lock_cifs([root/(value+'.cif') for value in files],check_cancelled=lambda:_check_cancelled(cancelled)):
        for identifier, data in files.items():
            _check_cancelled(cancelled)
            target = root/(identifier+'.cif')
            if not _existing_cif(target,identifier):
                atomic_save_cif(target,data)
            paths[identifier] = target
    return paths


def download_cif_batch(identifiers, target_dir, *, cancelled=lambda: False, opener=None):
    if not identifiers or len(identifiers) > BATCH_SIZE:
        raise ValueError('Invalid COD download batch size')
    root = Path(target_dir)
    with lock_cifs([root/(value+'.cif') for value in identifiers],check_cancelled=lambda:_check_cancelled(cancelled)):
        saved = {value: root/(value+'.cif') for value in identifiers if _existing_cif(root/(value+'.cif'),value)}
        pending = [value for value in identifiers if value not in saved]
        if pending:
            saved.update(_fetch_cif_batch(pending,root,cancelled=cancelled,opener=opener))
        return saved


def _existing_cif(path, identifier):
    try:
        return path.stat().st_size <= MAX_CIF_BYTES and _valid_cif(path.read_bytes(),identifier)
    except OSError:
        return False


def _fetch_cif_batch(identifiers, target_dir, *, cancelled, opener):
    opener = open_url if opener is None else opener
    query = urlencode(dict(id=','.join(identifiers), format='zip', include_duplicates='1',
                           include_errors='1', include_theoretical='1'), safe=',')
    errors = []
    for base in COD_BASES:
        _check_cancelled(cancelled)
        try:
            request = Request(base+'/result?'+query, headers={'User-Agent':'XRD-Phase-Finder/COD-library'})
            with opener(request, timeout=30) as response:
                output = io.BytesIO()
                while True:
                    _check_cancelled(cancelled)
                    chunk = response.read(256*1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    if output.tell() > MAX_ZIP_BYTES:
                        raise ValueError('COD ZIP download exceeds the supported size')
            return extract_cif_batch(output.getvalue(), identifiers, target_dir, cancelled=cancelled)
        except LibraryCancelled:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            errors.append(str(error))
    raise RuntimeError('COD batch download failed: '+'; '.join(errors))


def collect_cifs(identifiers, target_dir, *, existing_paths=None, cancelled=lambda: False,
                 progress=None, fetcher=None, request_interval=10., result=None, available=None):
    identifiers = list(identifiers)
    fetcher = download_cif_batch if fetcher is None else fetcher
    root = Path(target_dir)
    result = DownloadResult() if result is None else result
    pending = []
    for identifier in identifiers:
        _check_cancelled(cancelled)
        candidates = ((existing_paths or {}).get(identifier), root/(identifier+'.cif'))
        for candidate in candidates:
            if candidate is None:
                continue
            path = Path(candidate)
            try:
                if path.stat().st_size <= MAX_CIF_BYTES and _valid_cif(path.read_bytes(), identifier):
                    result.paths[identifier] = path
                    result.reused += 1
                    if available:
                        available(identifier,path,True)
                    break
            except OSError:
                pass
        else:
            pending.append(identifier)
        if progress and (len(result.paths)+len(pending)) % 200 == 0:
            progress('Checking local COD CIFs', len(result.paths)+len(pending), len(identifiers))
    if progress:
        progress('Checking downloaded COD CIFs', len(result.paths), len(identifiers))
    if pending and fetcher is download_cif_batch:
        from xrd_finder.services.network import ensure_online_allowed
        ensure_online_allowed('COD library download')
    previous = None
    consecutive_failures = 0
    for offset in range(0, len(pending), BATCH_SIZE):
        batch = pending[offset:offset+BATCH_SIZE]
        if previous is not None:
            deadline = previous+request_interval
            while time.monotonic() < deadline:
                _check_cancelled(cancelled)
                time.sleep(min(.1, max(0., deadline-time.monotonic())))
        _check_cancelled(cancelled)
        if progress:
            progress('Downloading original COD CIFs', len(result.paths), len(identifiers))
        previous = time.monotonic()
        try:
            downloaded = fetcher(batch, root, cancelled=cancelled)
            consecutive_failures = 0
            result.paths.update(downloaded)
            result.downloaded += len(downloaded)
            for identifier in set(batch)-set(downloaded):
                result.errors[identifier] = 'COD did not return this identifier'
        except LibraryCancelled:
            raise
        except Exception as error:
            consecutive_failures += 1
            for identifier in batch:
                result.errors[identifier] = str(error)
            if consecutive_failures >= 2:
                # A disconnected server must not trigger hundreds of timed-out
                # requests. Leave the remainder explicit and resume on demand.
                for identifier in pending[offset+BATCH_SIZE:]:
                    result.errors[identifier] = 'Download stopped after repeated server failures; continue to retry'
                break
        if available:
            for identifier in batch:
                if identifier in result.paths:
                    available(identifier,result.paths[identifier],False)
        if progress:
            progress('Downloaded COD CIFs', len(result.paths), len(identifiers))
    result.missing = set(identifiers)-set(result.paths)
    return result


def current_preparation(path, entry, *, covered, calculated_iic):
    from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION
    if entry is None or entry.derived_version != DERIVED_CACHE_VERSION or not covered:
        return False
    try:
        method = json.loads(entry.iic_method)
        return (method.get('structure') == hashlib.sha256(Path(path).read_bytes()).hexdigest()
                and calculated_iic.value_current(entry.iic, entry.iic_method))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def prepare_inorganic_library(cache, *, identifiers=None, progress=None, status=None,
                              cancelled=lambda: False):
    from xrd_finder.services.cod_inorganic_worker import prepare_paths
    from xrd_finder.services.cod_library_progress import LibraryProgress
    identifiers = load_selection() if identifiers is None else tuple(identifiers)
    result = LibraryResult(total=len(identifiers))
    downloads = DownloadResult()
    state = LibraryProgress(len(identifiers),batch_size=BATCH_SIZE)
    stop = threading.Event()
    source_done = threading.Event()
    jobs = Queue(maxsize=2*BATCH_SIZE)
    publish_lock = threading.Lock()
    last_publish = [0.]

    def is_cancelled():
        return stop.is_set() or cancelled()

    def publish(force=False):
        if status is not None:
            with publish_lock:
                now = time.monotonic()
                if force or now-last_publish[0] >= .2:
                    last_publish[0] = now
                    status(state.snapshot())

    def report(text,value,maximum):
        if text == 'Downloading original COD CIFs':
            state.start_download()
        if text == 'Checking downloaded COD CIFs':
            state.scan_complete()
        if progress:
            progress(text,value,maximum)
        publish(True)

    producer = None
    try:
        _check_cancelled(cancelled)
        if progress:
            progress('Checking prepared COD records',0,result.total)
        publish(True)
        keys = [('COD',value) for value in identifiers]
        states = cache.preparation_states(keys)
        existing = {value:entry.cif_path for (_,value),entry in states.items() if entry.cif_path}
        covered = cache.reference_range_coverage(keys,cancelled=cancelled)
        entries = cache.iic_entries(keys)

        def available(identifier,path,reused):
            _check_cancelled(is_cancelled)
            state.file_available(reused)
            key = ('COD',identifier)
            if current_preparation(path,entries.get(key),covered=covered.get(key,False),
                                   calculated_iic=cache.calculated_iic):
                result.skipped += 1
                state.card_ready(skipped=True)
            else:
                state.start_processing()
                while True:
                    _check_cancelled(is_cancelled)
                    try:
                        jobs.put((identifier,str(path)),timeout=.1)
                        break
                    except Full:
                        continue
            publish()

        def download():
            try:
                collect_cifs(identifiers,cache.cif_dir,existing_paths=existing,
                             progress=report,cancelled=is_cancelled,result=downloads,available=available)
            except LibraryCancelled:
                pass
            except Exception as error:
                for identifier in identifiers:
                    if identifier not in downloads.paths:
                        downloads.errors.setdefault(identifier,str(error))
            finally:
                result.downloaded,result.reused = downloads.downloaded,downloads.reused
                result.download_failed.update(downloads.errors)
                state.finish_download(len(result.download_failed))
                source_done.set()
                publish(True)

        def ready(identifier,success,error):
            if success:
                result.prepared += 1
            else:
                result.preparation_failed[identifier] = error or 'CrIStMa could not prepare this CIF'
            state.card_ready(failed=not success)
            publish()

        producer = threading.Thread(target=download,name='cod-library-download')
        producer.start()
        try:
            prepare_paths(cache.root,jobs,source_done=source_done.is_set,
                          ready=ready,cancelled=is_cancelled)
        finally:
            stop.set()
            producer.join()
        _check_cancelled(cancelled)
        state.finish()
    except LibraryCancelled:
        result.cancelled = True
    finally:
        stop.set()
        if producer is not None and producer.is_alive():
            producer.join()
        publish(True)
    return result
