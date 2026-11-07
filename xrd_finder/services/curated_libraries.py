"""Versioned, explicit CIF downloads for organic framework libraries."""
from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from zipfile import ZipFile

from xrd_finder.services.cod_inorganic_library import LibraryCancelled
from xrd_finder.services.database_http_session import DatabaseHttpSession
from xrd_finder.services.local_cif_preparation import prepare_local_cif_library
from xrd_finder.services.network import create_ssl_context
from xrd_finder.services.reference_labels import ReferenceLabelStore


@dataclass(frozen=True)
class LibraryPreset:
    name: str
    source: str
    version: str
    record_url: str
    archive_url: str
    maximum_bytes: int
    description: str
    md5: str = ''


PRESETS = {
    'curated_cofs': LibraryPreset('CURATED COFs', 'LIB_434F46001000', '1.0.0',
        'https://zenodo.org/records/3352138',
        'https://zenodo.org/records/3352138/files/danieleongari/CURATED-COFs-v1.0.0.zip?download=1',
        8*1024**2,
        '324 covalent organic framework CIFs from the published literature; release 1.0.0. '
        'The reference patterns are calculated from CIF, not measured powder profiles. '
        'The authors note that some original structures may have geometric limitations. '
        'Archive: less than 1 MB. Enable Organic to include these candidates.',
        '210e2c708625eab49b91ac68814288b5'),
    'qmof': LibraryPreset('QMOF', 'LIB_514D4F460018', '18',
        'https://figshare.com/articles/dataset/QMOF_Database/13147324/18',
        'https://figshare.com/ndownloader/articles/13147324/versions/18',
        768*1024**2,
        '20,000+ MOF and coordination-polymer structures; QMOF release 18. '
        'Only DFT-relaxed CIFs are prepared. These geometries may differ from experiment. '
        'Download: about 520 MB; preparation may take time. CC BY 4.0, Rosen et al. (2021, 2022). '
        'If Figshare is unavailable, download its archive in your browser and use Import CIF archive. '
        'Enable Organic to include metal-organic candidates.'),
}


def preset_connection(key):
    from xrd_finder.services.library_connections import LibraryConnection
    preset=PRESETS[key]
    return LibraryConnection(name=preset.name, source=preset.source, kind='zip_url',
                             location=preset.archive_url, preset=key)


def _check(cancelled):
    if cancelled():
        raise LibraryCancelled('Library preparation cancelled; completed cards retained')


def _digests(path, cancelled):
    sha=hashlib.sha256();md5=hashlib.md5()
    with Path(path).open('rb') as stream:
        while block:=stream.read(256*1024):
            _check(cancelled);sha.update(block);md5.update(block)
    return sha.hexdigest(),md5.hexdigest()


def download_preset(root, preset, *, progress=None, cancelled=lambda:False):
    _check(cancelled)
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    target=root/(preset.source+'-'+preset.version+'.zip')
    receipt=target.with_suffix('.receipt.json')
    if target.is_file() and 0 < target.stat().st_size <= preset.maximum_bytes:
        sha,md5=_digests(target,cancelled)
        try:saved=json.loads(receipt.read_text())
        except (OSError,ValueError):saved={}
        if (preset.md5 and md5==preset.md5) or (not preset.md5 and saved.get('sha256')==sha):
            return target
    temporary=None
    try:
        session=DatabaseHttpSession(create_ssl_context())
        with session.open(preset.archive_url,timeout=30.,headers={'User-Agent':'XRD-Phase-Finder/1.7.0'}) as response:
            with tempfile.NamedTemporaryFile(dir=root,suffix='.part',delete=False) as output:
                temporary=Path(output.name);size=0
                while True:
                    _check(cancelled);block=response.read(256*1024)
                    if not block:break
                    size+=len(block)
                    if size>preset.maximum_bytes:raise ValueError('Library archive exceeds the download limit')
                    output.write(block)
                    if progress:progress('Downloading '+preset.name+' (bytes)',size,0)
        sha,md5=_digests(temporary,cancelled)
        if preset.md5 and md5!=preset.md5:raise ValueError('Library archive checksum differs from the published release')
        with ZipFile(temporary) as archive:
            if not archive.infolist():raise ValueError('The downloaded ZIP library is empty')
        _check(cancelled);os.replace(temporary,target)
        # Atomic archive replacement is sufficient for correctness: a missing
        # receipt causes a fresh download, never use of a partial archive.
        receipt.write_text(json.dumps(dict(sha256=sha,url=preset.archive_url,version=preset.version)))
        return target
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def _qmof_cif(name):
    path=PurePosixPath(name)
    return path.suffix.lower()=='.cif' and not any('unrelaxed' in part.lower() for part in path.parts)


def _qmof_archive(path, temporary_root, cancelled):
    """Unwrap the known QMOF containers; never execute conversion scripts."""
    for depth in range(3):
        _check(cancelled)
        with ZipFile(path) as archive:
            members=archive.infolist()
            if any(_qmof_cif(m.filename) for m in members):return path
            nested=[m for m in members if PurePosixPath(m.filename).name=='relaxed_structures.zip']
            if not nested:
                nested=[m for m in members if PurePosixPath(m.filename).name=='qmof_database.zip']
            if len(nested)!=1:raise ValueError('QMOF archive has no unambiguous relaxed CIF collection')
            member=nested[0]
            if member.flag_bits & 1 or not 0 < member.file_size <= 640*1024**2:
                raise ValueError('QMOF nested CIF archive is encrypted or too large')
            target=Path(temporary_root)/('nested-'+str(depth)+'.zip')
            with archive.open(member) as source,target.open('wb') as output:
                size=0
                while block:=source.read(256*1024):
                    _check(cancelled);size+=len(block)
                    if size>640*1024**2:raise ValueError('QMOF nested CIF archive exceeds the size limit')
                    output.write(block)
        path=target
    raise ValueError('QMOF CIF collection is nested too deeply')


def prepare_curated_library(cache, connection, *, archive_path=None, progress=None, status=None, cancelled=lambda:False):
    preset=PRESETS[connection.preset]
    path=Path(archive_path) if archive_path is not None else (
        Path(connection.location).expanduser() if connection.kind=='zip' else
        download_preset(cache.root/'downloads',preset,progress=progress,cancelled=cancelled))
    if archive_path is None and connection.kind=='zip' and preset.md5:
        if _digests(path,cancelled)[1]!=preset.md5:
            raise ValueError('Choose the original CURATED COFs v1.0.0 archive; its checksum differs from the published release')
    with tempfile.TemporaryDirectory(prefix='xrd-framework-cifs-') as temporary:
        include=None
        if connection.preset=='qmof':
            path=_qmof_archive(path,temporary,cancelled);include=_qmof_cif
        else:
            include=lambda name:len(PurePosixPath(name).parts)==3 and PurePosixPath(name).parts[1]=='cifs'
            with ZipFile(path) as archive:
                if not any(include(n) and n.lower().endswith('.cif') for n in archive.namelist()):
                    raise ValueError('The CURATED COFs archive contains no CIF structures in cifs/')
        result=prepare_local_cif_library(cache,path,archive=True,source=connection.source,
            include_member=include,progress=progress,status=status,cancelled=cancelled)
    with closing(cache._connect()) as database:
        entries=[row[0] for row in database.execute('select entry_id from phases where source=?',(connection.source,))]
    store=ReferenceLabelStore(cache.index_path)
    for start in range(0,len(entries),100):
        version=preset.version if connection.preset!='qmof' or (archive_path is None and connection.kind=='zip_url') else 'unverified local archive'
        store.save_many({(connection.source,entry):dict(kind=connection.preset,version=version,
            record=preset.record_url) for entry in entries[start:start+100]})
    return result
