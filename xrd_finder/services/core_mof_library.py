"""Explicit download and native preparation of the public CoRE MOF SI subset."""
import hashlib
import os
from pathlib import Path, PurePosixPath
import tempfile
from urllib.request import Request
from zipfile import ZipFile

from xrd_finder.services.cod_inorganic_library import LibraryCancelled
from xrd_finder.services.local_cif_preparation import prepare_local_cif_library
from xrd_finder.services.network import open_url
from xrd_finder.services.reference_labels import ReferenceLabelStore

RECORD_URL = 'https://zenodo.org/records/15055758'
ARCHIVE_NAME = 'CoREMOF2024DB_SI_20250204.zip'
ARCHIVE_URL = RECORD_URL + '/files/' + ARCHIVE_NAME + '?download=1'
ARCHIVE_SHA256 = 'd07a0c1f0161a12ae998ea9531cc3bc333ad0e8cacd8c5c097fcc7e88006fa8a'
READY_COUNT = 2664
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024


def _digest(path, cancelled):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(256 * 1024):
            if cancelled():
                raise LibraryCancelled('CoRE MOF preparation cancelled')
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(root, *, progress=None, cancelled=lambda:False):
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    target = root / ARCHIVE_NAME
    if target.is_file() and _digest(target, cancelled) == ARCHIVE_SHA256:
        return target
    temporary = None
    try:
        if cancelled():
            raise LibraryCancelled('CoRE MOF download cancelled')
        with open_url(Request(ARCHIVE_URL, headers={'User-Agent':'XRD-Phase-Finder/1.7.0'}), timeout=20.) as response:
            with tempfile.NamedTemporaryFile(dir=root, suffix='.part', delete=False) as output:
                temporary = Path(output.name); total = 0; digest = hashlib.sha256()
                while True:
                    if cancelled():
                        raise LibraryCancelled('CoRE MOF download cancelled')
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise ValueError('CoRE MOF archive exceeds the download limit')
                    output.write(chunk); digest.update(chunk)
                    if progress:
                        progress('Downloading CoRE MOF archive (bytes)', total, 44022768)
        if digest.hexdigest() != ARCHIVE_SHA256:
            raise ValueError('CoRE MOF archive checksum differs from the verified release')
        os.replace(temporary, target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _ready_member(name):
    path = PurePosixPath(name)
    return len(path.parts) == 4 and path.parts[:2] == ('SI','CR') and path.parts[2] in {'ASR','FSR','Ion'}


def prepare_core_mof_library(cache, *, archive_path=None, progress=None, status=None, cancelled=lambda:False):
    path = Path(archive_path) if archive_path is not None else download_archive(
        cache.root/'downloads', progress=progress, cancelled=cancelled)
    # The generic archive importer validates paths, file sizes, cancellation
    # and atomic SQL records. NCR structures are deliberately not imported.
    result = prepare_local_cif_library(cache, path, archive=True, source='COREMOF',
        include_member=_ready_member, progress=progress, status=status, cancelled=cancelled)
    # Preserve processing provenance even when a user cancelled after some
    # successful cards; no full reflection JSON is loaded for these checks.
    with ZipFile(path) as archive:
        variants = {PurePosixPath(name).stem:PurePosixPath(name).parts[2]
                    for name in archive.namelist() if _ready_member(name) and name.lower().endswith('.cif')}
    store = ReferenceLabelStore(cache.index_path)
    items = list(variants)
    for start in range(0, len(items), 100):
        keys = [('COREMOF', key) for key in items[start:start+100]]
        states = cache.preparation_states(keys)
        store.save_many({key:dict(kind='core_mof', variant=variants[key[1]], record=RECORD_URL)
                         for key in keys if key in states and states[key].ready})
    return result
