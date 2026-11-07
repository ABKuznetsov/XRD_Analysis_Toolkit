"""Source-supplied provenance, quality and status, separate from search scores."""
from contextlib import closing
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from xrd_finder.services.source_registry import is_custom_source


PDF_MARKS = {
    '*': 'High-quality reference (Star).',
    'I': 'Indexed diffraction reference.',
    'B': 'Blank quality mark; consult the source card for limitations.',
    'O': 'Low precision / doubtful reference; consult the card comments.',
    'C': 'Calculated powder pattern from a crystal structure; not necessarily a hypothetical phase.',
    'R': 'Reference based on Rietveld refinement.',
    'P': 'Prototype-derived reference.',
    'H': 'Hypothetical structure.',
    'G': 'Good supporting data for a non-crystalline or partially crystalline reference.',
    'M': 'Minimally acceptable supporting data for a non-crystalline or partially crystalline reference.',
}
LABEL_SCHEMA = '''create table if not exists phase_reference_labels (
    source text not null, entry_id text not null, labels_json text not null,
    updated_at real not null, primary key(source,entry_id))'''


@dataclass(frozen=True)
class ReferenceLabel:
    text: str
    tooltip: str
    categories: frozenset[str]


def label_info(source, data=None):
    source=str(source).upper()
    data=data if isinstance(data,dict) else {}
    categories=set();parts=[];notes=[]
    if source=='MP':
        flag=data.get('theoretical')
        if flag is False:
            parts.append('★');categories.add('mp_observed')
            notes.append('Materials Project: matched to an experimentally observed ICSD structure. The MP structure itself is DFT-relaxed; this is not a PDF quality grade.')
        elif flag is True:
            parts.append('Theo.');categories.add('mp_theoretical')
            notes.append('Materials Project: no experimental ICSD structure match reported. This does not establish that the phase has never been synthesised. Structure: DFT.')
        else:
            categories.add('unknown');notes.append('Materials Project experimental-confirmation flag has not been obtained. Missing information is not a theoretical classification.')
        if data.get('icsd_ids'):
            notes.append('ICSD matches: '+', '.join(map(str,data['icsd_ids'])))
    elif source in {'PDF2','PDF-2','PDF'} and data.get('kind')=='pdf':
        raw=str(data.get('quality','')).upper().strip()
        notes.append('Source PDF mark: '+(raw or 'blank'))
        marks=raw.replace('S','*').replace('+','*').replace('?','O')
        marks=''.join(dict.fromkeys(c for c in marks if c in PDF_MARKS))
        if not raw:
            marks='B'
        parts.extend(marks)
        for mark in marks:
            categories.add('pdf_'+mark);notes.append('PDF '+mark+': '+PDF_MARKS[mark])
        if 'D' in raw or str(data.get('status','')).casefold()=='deleted':
            parts.append('D');categories.add('deleted')
            notes.append('Deleted: withdrawn/superseded card. This is a record status, separate from quality.')
        if data.get('status') and 'deleted' not in categories:
            notes.append('PDF status: '+str(data['status']))
        if not categories:
            categories.add('unknown')
            parts.append(raw or '—')
            notes.append('Unrecognised source mark; retained without assigning a quality grade.')
    elif source=='LIB_514D4F460018':
        parts.append('Calc. DFT');categories.add('calculated')
        notes.append('QMOF: powder pattern calculated from a DFT-relaxed MOF or coordination-polymer CIF. '
                     'This is not a measured powder reference or a diffraction quality grade. '
                     'CC BY 4.0; Rosen et al. (2021, 2022). Source: https://doi.org/10.6084/m9.figshare.13147324.v18')
        if data.get('version'):notes.append('Dataset version: '+str(data['version']))
    elif source=='LIB_434F46001000':
        parts.append('Calc.');categories.add('calculated')
        notes.append('CURATED COFs v1.0.0: powder pattern calculated from a covalent organic framework CIF from published literature. '
                     'Some original geometries may have limitations; consult the source paper. '
                     'This is not a diffraction quality grade. Source: https://zenodo.org/records/3352138')
    elif source=='COREMOF':
        variant=str(data.get('variant',''))
        parts.append('Calc.');categories.add('calculated')
        notes.append('CoRE MOF SI 2024: powder pattern calculated from the processed CIF; not a measured powder reference.')
        descriptions={'ASR':'all solvent removed, including coordinated solvent',
                      'FSR':'free solvent removed; coordinated solvent retained',
                      'Ion':'ion-containing structure'}
        if variant in descriptions:
            parts.append(variant)
            notes.append(variant+': '+descriptions[variant]+'.')
        notes.append('Author computation-ready subset. This is not a diffraction quality grade. Source: https://zenodo.org/records/15055758')
    elif source=='RRUFF' and data.get('kind')=='rruff':
        parts.append('Exp.');categories.add('experimental')
        notes.append('RRUFF: measured powder-diffraction reference. No ICDD quality grade is assigned by Finder.')
    else:
        if source=='COD' or is_custom_source(source):
            parts.append('Calc.');categories.add('calculated')
            notes.append(('COD' if source=='COD' else 'CIF library')+': powder diffraction pattern calculated from the CIF crystal structure. '
                         'This does not mean that the structure is theoretical, and is not a PDF quality grade.')
        method=str(data.get('method','')).strip()
        if method:
            notes.append('CIF experimental method: '+method)
            if 'diffract' in method.casefold():
                if source!='COD' and not is_custom_source(source):parts.append('Exp.')
                categories.add('experimental')
        error=str(data.get('error','')).strip()
        if error and error.casefold() not in {'no','none','false','0','.','?'}:
            notes.append('CIF/COD error flag: '+error);categories.add('warning')
        warnings=data.get('warnings',[])
        if isinstance(warnings,list) and warnings:
            notes.extend(str(w) for w in warnings);categories.add('warning')
        if data.get('r_factor'):
            notes.append('Reported refinement R factor: '+str(data['r_factor']))
        if 'warning' in categories:parts.append('!')
        if not categories:
            categories.add('unknown');notes.append('No source quality/status label available. Finder does not infer a quality grade from the database name.')
    return ReferenceLabel(' '.join(parts) or '—','\n'.join(notes),frozenset(categories))


def mp_reference_labels(doc):
    def value(key, default=None):
        return doc.get(key,default) if isinstance(doc,dict) else getattr(doc,key,default)
    flag=value('theoretical')
    databases=value('database_IDs',{}) or {}
    ids=databases.get('icsd',[]) if isinstance(databases,dict) else []
    return {'kind':'mp','theoretical':flag if isinstance(flag,bool) else None,
            'icsd_ids':list(map(str,ids))[:100] if isinstance(ids,(list,tuple)) else []}


def cif_reference_labels(path, *, warning=''):
    from xrd_finder.io.native_cif_session import read_native_cif
    from xrd_finder.io.cif_loader import _cif_value
    result=read_native_cif(path)
    blocks=getattr(result.document,'blocks',())
    if len(blocks)!=1:return {}
    block=blocks[0]
    data={'kind':'cif','method':_cif_value(block,'_exptl_method'),
          'error':_cif_value(block,'_cod_error_flag'),
          'r_factor':_cif_value(block,'_refine_ls_R_factor_gt','_refine_ls_R_factor_all')}
    if warning:data['warnings']=[str(warning)]
    return data


def ensure_label_schema(connection):
    connection.execute(LABEL_SCHEMA)


class ReferenceLabelStore:
    def __init__(self, path):self.path=Path(path)

    def get_many(self, keys):
        keys=list(dict.fromkeys((str(s).upper(),str(e)) for s,e in keys if s and e))
        if not keys or not self.path.is_file():return {}
        result={}
        with closing(sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1.)) as connection:
            if not connection.execute("select 1 from sqlite_master where type='table' and name='phase_reference_labels'").fetchone():return {}
            for start in range(0,len(keys),300):
                batch=keys[start:start+300];parameters=[v for key in batch for v in key]
                for source,entry,payload in connection.execute(
                    'with wanted(s,e) as (values '+','.join('(?,?)' for _ in batch)+') '
                    'select l.source,l.entry_id,l.labels_json from wanted w join phase_reference_labels l '
                    'on l.source=w.s and l.entry_id=w.e',parameters):
                    try:
                        value=json.loads(payload)
                        if isinstance(value,dict):result[(source,entry)]=value
                    except (ValueError,TypeError):pass
        return result

    def save_many(self, records):
        if not records:return
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path,timeout=2.)) as connection,connection:
            ensure_label_schema(connection)
            self.save_on_connection(connection,records)

    @staticmethod
    def save_on_connection(connection, records):
        for (source,entry),data in records.items():
            if not isinstance(data,dict) or not data:continue
            source=str(source).upper();entry=str(entry)
            if source=='MP' and data.get('theoretical') is None:
                old=connection.execute('select labels_json from phase_reference_labels where source=? and entry_id=?',(source,entry)).fetchone()
                if old:
                    try:
                        if isinstance(json.loads(old[0]).get('theoretical'),bool):continue
                    except (ValueError,TypeError):pass
            connection.execute('insert or replace into phase_reference_labels values(?,?,?,?)',
                (source,entry,json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False),time.time()))
