"""Public CCDC query URLs and explicit import of user-downloaded CIF data."""
from concurrent.futures import CancelledError
from contextlib import closing
from dataclasses import dataclass,field
import hashlib
from pathlib import Path
import re
from urllib.parse import urlencode
from zipfile import ZipFile,is_zipfile

from xrd_finder.services.ccdc_service import extract_doi
from xrd_finder.services.cod_cif_store import atomic_save_cif
from xrd_finder.services.cod_inorganic_library import current_preparation

CCDC_HOME = 'https://www.ccdc.cam.ac.uk/structures/'
CCDC_LOGIN = CCDC_HOME+'login'
MAX_DOWNLOAD_BYTES = 128*1024*1024


def ccdc_query(text):
    text = text.strip()
    doi = extract_doi(text)
    if doi:
        return 'Doi',doi
    identifier = re.sub(r'^(?:CCDC|CSD)[ :#-]*','',text,flags=re.I).strip()
    if re.fullmatch(r'[1-9][0-9]{0,8}',identifier):
        return 'Ccdcid',identifier
    if re.fullmatch(r'[a-z]{6}[0-9]{0,2}',identifier,re.I):
        return 'Ccdcid',identifier.upper()
    raise ValueError('Enter a CCDC deposition number, CSD refcode, or DOI.')


def ccdc_search_url(text):
    key,value = ccdc_query(text)
    return CCDC_HOME+'Search?'+urlencode({key:value,'DatabaseToSearch':'Published'})


def _marker(query):
    return '\nCCDC lookup: '+ccdc_query(query)[1]+'\n'


def find_cached_ccdc(cache,query):
    _kind,value = ccdc_query(query)
    with closing(cache._connect()) as connection:
        ids = connection.execute("select entry_id from phases where source='CCDC' and "
            "(lower(entry_id)=lower(?) or instr(lower(source_text),lower(?))>0) order by entry_id",
            (value,_marker(query))).fetchall()
    return [entry for row in ids if (entry:=cache.get('CCDC',row[0])) is not None
            and entry.cif_path and Path(entry.cif_path).is_file()]


@dataclass
class CcdcImportResult:
    entries: list = field(default_factory=list)
    errors: dict[str,str] = field(default_factory=dict)


def import_ccdc_download(cache,path,query='',*,progress=None,cancelled=lambda:False):
    from cristma.io.cif.parser import parse_cif

    def check():
        if cancelled():
            raise CancelledError('CCDC CIF import cancelled')

    check()
    path = Path(path)
    if path.stat().st_size>MAX_DOWNLOAD_BYTES:
        raise ValueError('CCDC download is too large for a single import')
    payloads = []
    if is_zipfile(path):
        with ZipFile(path) as archive:
            members = [item for item in archive.infolist() if Path(item.filename).suffix.lower()=='.cif']
            if sum(item.file_size for item in members)>MAX_DOWNLOAD_BYTES:
                raise ValueError('CCDC CIF archive is too large')
            for member in members:
                check();payloads.append((Path(member.filename).name,archive.read(member)))
    else:
        payloads.append((path.name,path.read_bytes()))
    result = CcdcImportResult()
    root = cache.root/'ccdc_cif'
    originals = root/'originals'
    entries_seen = set()
    for filename,data in payloads:
        check()
        digest = hashlib.sha256(data).hexdigest()
        # Preserve the complete original, including comments and original bytes.
        atomic_save_cif(originals/(digest+'.cif'),data)
        try:
            source = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            source = data.decode('latin-1')
        parsed = parse_cif(source,source_name=filename)
        document = parsed.document
        blocks = document.blocks
        structural = [block for block in blocks if block.scalar('_cell_length_a') and block.loops_with_tag('_atom_site_fract_x')]
        if not structural:
            result.errors[filename] = 'CIF contains no unit cell with fractional atomic sites'
            continue
        prefix = source[:blocks[0].data_token.span.start.offset]
        for index,block in enumerate(structural,1):
            check()
            start = block.data_token.span.start.offset
            following = [item.data_token.span.start.offset for item in blocks if item.data_token.span.start.offset>start]
            text = prefix+source[start:min(following) if following else len(source)]
            code = block.scalar('_database_code_depnum_ccdc_archive') or block.scalar('_database_code_csd')
            identity = str(code.value).strip("\"'") if code else block.name
            identity = re.sub(r'^CCDC[ :#-]*','',identity,flags=re.I)
            identity = re.sub(r'[^A-Za-z0-9_.-]+','_',identity).strip('._') or digest[:16]
            if len(structural)>1:
                identity += '--'+hashlib.sha256(text.encode()).hexdigest()[:12]
            target = root/(identity+'.cif')
            atomic_save_cif(target,text.encode('utf-8'))
            key = ('CCDC',identity)
            existing = cache.get(*key)
            covered = cache.reference_range_coverage([key]).get(key,False)
            if progress:progress('Preparing CCDC structure '+identity,index,len(structural))
            if not current_preparation(target,existing,covered=covered,calculated_iic=cache.calculated_iic):
                if not cache.index_cif(target,source='CCDC',entry_id=identity):
                    result.errors[filename+':'+block.name] = str(getattr(cache,'_last_reference_preparation_error','Could not prepare the structure'))
                    continue
            if query:
                marker = _marker(query)
                with closing(cache._connect()) as connection,connection:
                    connection.execute("update phases set source_text=source_text||? where source='CCDC' and entry_id=? and instr(source_text,?)=0",(marker,identity,marker))
            if identity not in entries_seen:
                entries_seen.add(identity);result.entries.append(cache.get(*key))
    if not payloads:
        raise ValueError('CCDC download contains no CIF files')
    return result
