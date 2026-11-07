"""COD's documented ID-list ZIP endpoint, with bounded, atomic publication.

https://wiki.crystallography.net/RESTful_API/
Archive paths are never extracted; each requested CIF is read by exact ID.
"""
from concurrent.futures import CancelledError
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlencode
from zipfile import BadZipFile, ZipFile

from xrd_finder.services.candidate_cif_batches import CifBatchDownloadResult
from xrd_finder.services.cod_cif_store import atomic_save_cif, lock_cifs

MAX_BATCH = 100
MAX_CIF_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_UNPACKED_BYTES = 64 * 1024 * 1024


def _check(cancelled):
    if cancelled():
        raise CancelledError('COD download cancelled')


def _validate_cif(data, key):
    if not 0 < len(data) <= MAX_CIF_BYTES:
        raise ValueError('COD CIF is empty or exceeds the size limit')
    text = data.decode('utf-8-sig')
    blocks = re.findall(r'^\s*data_(\S+)\s*$', text, re.MULTILINE | re.IGNORECASE)
    codes = re.findall(r'^\s*_cod_database_code\s+[\'\"]?(\d+)', text, re.MULTILINE | re.IGNORECASE)
    if not blocks or (codes and set(codes) != {key}) or key not in blocks and not codes:
        raise ValueError('COD CIF identity does not match the requested card')


def _local_cif(path, key):
    try:
        if not 0 < path.stat().st_size <= MAX_CIF_BYTES:
            return False
        _validate_cif(path.read_bytes(), key)
        return True
    except (OSError, ValueError):
        return False


def download_cod_cifs(service, entry_ids, target_dir, *, progress=None,
                      cancelled=lambda: False, batch_size=100):
    result = CifBatchDownloadResult()
    root = Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    ids = list(dict.fromkeys(str(value).strip() for value in entry_ids))
    pending = []
    for key in ids:
        _check(cancelled)
        if not re.fullmatch(r'\d{7}', key):
            result.errors[key] = 'Invalid COD identifier'
        elif _local_cif(root / f'{key}.cif', key):
            result.paths[key] = root / f'{key}.cif'
            result.reused += 1
        else:
            pending.append(key)
    size = max(1, min(MAX_BATCH, int(batch_size)))
    for offset in range(0, len(pending), size):
        _check(cancelled)
        batch = pending[offset:offset + size]
        if progress:
            progress('Downloading COD structures', len(result.paths) + len(result.errors), len(ids))
        params = dict(id=','.join(batch), format='zip', include_duplicates=1,
                      include_errors=1, include_theoretical=1)
        try:
            data = service._request_bytes('/result?' + urlencode(params), timeout=20.,
                                          max_bytes=MAX_ARCHIVE_BYTES, cancelled=cancelled)
            _check(cancelled)
            if len(data) > MAX_ARCHIVE_BYTES:
                raise ValueError('COD archive exceeds the download limit')
            with ZipFile(BytesIO(data)) as archive:
                infos = archive.infolist()
                if len(infos) > 2 * MAX_BATCH or sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES:
                    raise ValueError('COD archive exceeds the unpacked size limit')
                members = {}
                for info in infos:
                    path = PurePosixPath(info.filename)
                    if path.is_absolute() or '..' in path.parts or '\\' in info.filename:
                        raise ValueError('COD archive contains an unsafe path')
                    if info.is_dir():
                        continue
                    match = re.fullmatch(r'(\d{7})\.cif', path.name, re.IGNORECASE)
                    if match and match[1] in batch:
                        members.setdefault(match[1], []).append(info)
                for key in batch:
                    _check(cancelled)
                    try:
                        matches = members.get(key, [])
                        if len(matches) != 1:
                            raise ValueError('COD archive has a missing or duplicate CIF for this card')
                        info = matches[0]
                        if info.flag_bits & 1 or not 0 < info.file_size <= MAX_CIF_BYTES:
                            raise ValueError('COD archive has an encrypted or excessive CIF')
                        body = archive.read(info)
                        _validate_cif(body, key)
                        _check(cancelled)
                        output = root / f'{key}.cif'
                        with lock_cifs([output], check_cancelled=lambda: _check(cancelled)):
                            if _local_cif(output, key):
                                result.reused += 1
                            else:
                                atomic_save_cif(output, body)
                                result.downloaded += 1
                        result.paths[key] = output
                    except CancelledError:
                        raise
                    except (OSError, ValueError, BadZipFile, RuntimeError) as error:
                        result.errors[key] = str(error)
        except CancelledError:
            raise
        except Exception as error:
            result.errors.update({key: str(error) for key in batch if key not in result.paths})
    _check(cancelled)
    if progress:
        progress('Downloaded COD structures', len(result.paths) + len(result.errors), len(ids))
    return result
