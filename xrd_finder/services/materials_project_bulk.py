"""Bounded MP summary downloads; existing CIF conversion and rare single-ID fallback."""
from concurrent.futures import CancelledError
from email.utils import parsedate_to_datetime
from pathlib import Path
import re,tempfile,time
from urllib.error import HTTPError

from xrd_finder.services.cod_cif_store import atomic_save_cif
from xrd_finder.services.candidate_cif_batches import (
    CandidateCifDownloads as MpCandidateDownloads, CifBatchDownloadResult as MpBulkDownloadResult,
)

MAX_BATCH=100
MAX_CIF_BYTES=8*1024*1024
STOP_CODES=(401,403,429,500,502,503,504)


def _check(cancelled):
    if cancelled():raise CancelledError('Materials Project download cancelled')


def _wait(seconds,cancelled):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        _check(cancelled);time.sleep(min(.05,max(0.,deadline-time.monotonic())))
    _check(cancelled)


def _http_error(error):
    seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error,HTTPError):return error
        error=error.__cause__
    return None


def _local_text(service,path):
    try:
        if not 0<path.stat().st_size<=MAX_CIF_BYTES:return None
        text=path.read_text(encoding='utf-8')
        obsolete=('XRD Phase Finder Materials Project REST adapter' in text[:2000]
                  and 'REST adapter v2' not in text[:2000])
        return text if not obsolete and service._looks_like_cif(text) else None
    except (OSError,UnicodeError):return None


def download_mp_cifs(service,material_ids,target_dir,*,progress=None,cancelled=lambda:False,batch_size=100):
    result=MpBulkDownloadResult();ids=[];seen=set()
    for value in material_ids:
        _check(cancelled);key=str(value).strip()
        if not re.fullmatch(r'(?:mp|mvc)-\d{1,16}',key):
            result.errors[key]='Invalid Materials Project identifier';continue
        if key not in seen:ids.append(key);seen.add(key)
    size=max(1,min(MAX_BATCH,int(batch_size)))
    root=Path(target_dir);root.mkdir(parents=True,exist_ok=True)
    pending=[]
    for key in ids:
        _check(cancelled)
        if _local_text(service,root/(key+'.cif')) is not None:
            result.paths[key]=root/(key+'.cif');result.reused+=1
        else:pending.append(key)
    done=result.reused;total=len(ids);last_request=None;bad_batches=0
    def report(label='Downloading Materials Project structures'):
        _check(cancelled)
        if progress:progress(label,done,total)
    def pause():
        nonlocal last_request
        _check(cancelled)
        # A fallback can issue two HTTP calls. Ten logical calls/second keeps
        # this bulk client below MP's documented starting limit of 25 HTTP/s.
        if last_request is not None:_wait(max(0.,last_request+.1-time.monotonic()),cancelled)
        last_request=time.monotonic()
    def query(batch):
        for attempt in range(3):
            pause()
            try:
                docs=service._summary_search({'material_ids':','.join(batch)},
                    fields=['material_id','formula_pretty','structure','symmetry'],limit=len(batch))
                _check(cancelled);return docs
            except CancelledError:raise
            except Exception as error:
                http=_http_error(error);code=http.code if http is not None else None
                transient=code in (429,500,502,503,504) or isinstance(error.__cause__,TimeoutError) or isinstance(error,TimeoutError)
                if not transient or attempt==2:raise
                delay=.5*2**attempt
                header=(http.headers or {}).get('Retry-After','') if http is not None else ''
                if header:
                    try:delay=max(delay,float(header))
                    except (ValueError,TypeError):
                        try:delay=max(delay,parsedate_to_datetime(header).timestamp()-time.time())
                        except (ValueError,TypeError,OverflowError):pass
                # Do not retry earlier than a longer server-directed delay.
                if delay>30:raise
                report('Materials Project is busy; retrying')
                _wait(delay,cancelled)
    report()
    if not service.api_key and pending:
        result.errors.update({key:'Materials Project API key is not configured' for key in pending})
        return result
    for offset in range(0,len(pending),size):
        batch=pending[offset:offset+size];report()
        try:
            docs=query(batch);bad_batches=0
        except CancelledError:raise
        except Exception as error:
            bad_batches+=1
            result.errors.update({key:str(error) for key in batch});done+=len(batch);report()
            http=_http_error(error)
            if bad_batches>=2 or http is not None and http.code in STOP_CODES:
                result.errors.update({key:'Bulk download stopped after server errors; saved card retained' for key in pending[offset+size:]})
                break
            continue
        wanted=set(batch);documents={};duplicates=set()
        for doc in docs:
            key=str(doc.get('material_id') or '')
            if key not in wanted:continue
            if key in documents:duplicates.add(key)
            documents[key]=doc
        missing=[]
        for key in batch:
            _check(cancelled)
            if key not in documents:missing.append(key);continue
            try:
                if key in duplicates:raise ValueError('MP returned duplicate material identities')
                doc=documents[key];structure=doc.get('structure')
                if not isinstance(structure,dict):raise ValueError('MP response has no structure')
                text=service._structure_to_cif_text(structure,material_id=key,
                    formula=str(doc.get('formula_pretty') or ''),symmetry=doc.get('symmetry'))
                data=text.encode('utf-8')
                if len(data)>MAX_CIF_BYTES or not service._looks_like_cif(text):raise ValueError('Invalid or excessive MP CIF')
                _check(cancelled);path=root/(key+'.cif');atomic_save_cif(path,data)
                result.paths[key]=path;result.downloaded+=1
            except CancelledError:raise
            except Exception as error:result.errors[key]=str(error)
            done+=1;report()
        failures=0;halt=False
        for key in missing:
            _check(cancelled)
            try:
                if failures>=2:raise ValueError('Single-card retries stopped after repeated failures; saved card retained')
                report('Downloading legacy Materials Project CIFs');pause()
                with tempfile.TemporaryDirectory(prefix='mp-single-',dir=root) as folder:
                    path=service.download_cif(key,folder);_check(cancelled)
                    text=_local_text(service,Path(path))
                    if text is None:raise ValueError('No usable CIF for requested MP identity')
                    output=root/(key+'.cif');_check(cancelled);atomic_save_cif(output,text.encode('utf-8'))
                result.paths[key]=output;result.downloaded+=1;failures=0
            except CancelledError:raise
            except Exception as error:
                failures+=1;result.errors[key]=str(error)
                http=_http_error(error)
                if http is not None and http.code in STOP_CODES:failures=2;halt=True
            done+=1;report()
        if halt:
            result.errors.update({key:'Bulk download stopped after server errors; saved card retained' for key in pending[offset+size:]})
            break
    return result
