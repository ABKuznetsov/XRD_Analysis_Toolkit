"""Derived structure metadata, validated against the original embedded CIF."""
from dataclasses import asdict
from xrd_finder.core.structure import Structure,CellParameters,AtomSite
from xrd_finder.io.finder_result_cache import cif_content_signature,_digest,_engine_identity


def structure_record(structure,path):
    fingerprint=cif_content_signature(path)
    if fingerprint is None:return None
    try:
        data=asdict(structure)
        return dict(format=1,engine=_digest(_engine_identity()),cif_sha256=fingerprint,data=data,data_sha256=_digest(data))
    except (TypeError,ValueError):return None


def restore_structure(record,path):
    try:
        if (record.get('format')!=1 or not record.get('cif_sha256')
                or record.get('engine')!=_digest(_engine_identity())
                or record['cif_sha256']!=cif_content_signature(path)
                or _digest(record['data'])!=record['data_sha256']):return None
        values=dict(record['data'])
        values['cell']=CellParameters(**values['cell'])
        values['atoms']=[AtomSite(**atom) for atom in values['atoms']]
        values['source_path']=str(path)
        return Structure(**values)
    except (AttributeError,KeyError,TypeError,ValueError):return None
