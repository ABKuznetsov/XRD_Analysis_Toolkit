"""Portable Match/Gain results guarded by scientific inputs and library revision."""
from dataclasses import asdict,is_dataclass
from enum import Enum
import logging
import math
import sqlite3
import numpy as np
from xrd_finder.io.finder_result_cache import _digest,_engine_identity,cif_content_signature
from xrd_finder.finder.profile_calculator import array_fingerprint
from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY
from xrd_finder.services.candidate_rows import normalize_candidate_row
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION


def _json(value):
    if is_dataclass(value):return _json(asdict(value))
    if isinstance(value,Enum):return value.value
    if isinstance(value,np.ndarray):return _json(value.tolist())
    if isinstance(value,np.generic):return _json(value.item())
    if isinstance(value,float) and not math.isfinite(value):return None
    if isinstance(value,dict):return {str(k):_json(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,set)):return [_json(v) for v in value]
    return value


def _array(data):
    if data is None:return None
    values=np.asarray(data,dtype=float)
    return (values.shape,array_fingerprint(values.ravel()))


def _rows(rows):
    fields=('Source','Entry','Formula','Phase','Space group','Match (%)','Gain (%)','I/Ic*')
    return [[row.get(field,'') for field in fields] if isinstance(row,dict)
            else normalize_candidate_row(row) for row in rows]


def _project_references(window,pattern):
    linked=set(getattr(pattern,'linked_phase_ids',[]) or [])
    phases=getattr(window.project,'phases',[])
    structure_ids={phase.structure_id for phase in phases if phase.id in linked}
    records=[]
    for item in [*phases,*[structure for structure in getattr(window.project,'structures',[])
                         if structure.id in structure_ids or structure.phase_id in linked]]:
        data=asdict(item)
        data['source_path']=cif_content_signature(data.get('source_path'))
        records.append(data)
    return dict(linked=sorted(linked),records=records)


def score_signature(window,kind,rows):
    w=window;pattern=w._active_pattern()
    if pattern is None or getattr(pattern,'input_kind','')=='peak_list' or getattr(w,'_search_mode','')=='peaks':return None
    # External pattern providers need their own portable content revisions.
    if w._reference_patterns_enabled():return None
    state=w.profile_states.get(pattern.id,{})
    if kind=='gain' and not state.get('calculated_result',{}).get('result_sha256'):return None
    normalized=_rows(rows)
    row_keys=sorted((r[0],r[1],r[2]) for r in normalized if r[0] and r[1])
    candidates=getattr(w,'match_candidates',[]) if kind=='gain' else []
    accepted=[{k:v for k,v in candidate.items() if k in
        ('Source','Entry','Formula','_EstimatedCell','_ReferenceCell')} for candidate in candidates]
    paths=getattr(w.project.finder_state,'candidate_cif_paths',{})
    accepted_keys={str(c.get('Source',''))+':'+str(c.get('Entry','')) for c in candidates}
    row_keys_set={r[0]+':'+r[1] for r in normalized}
    relevant=accepted_keys | (row_keys_set & paths.keys())
    # Only embedded overrides and accepted CIFs require content reads here.
    # The SQLite revision guards ordinary references without opening thousands
    # of files on the UI thread to validate a saved score table.
    states=w.local_phase_cache.preparation_states([key.split(':',1) for key in relevant if ':' in key])
    cifs={}
    for key in sorted(relevant):
        stored=states.get(tuple(key.split(':',1)))
        path=paths.get(key) or (stored.cif_path if stored is not None else None)
        fingerprint=cif_content_signature(path)
        if key in accepted_keys:
            cifs[key]=fingerprint
        elif fingerprint!=cif_content_signature(stored.cif_path if stored is not None else None):
            cifs[key]=fingerprint
    observed=(w._active_observed_data() if getattr(w,'_scoring_source','Auto')=='Auto'
              else w._active_scoring_observed_data())
    def checked(name):
        widget=getattr(w,name,None)
        return None if widget is None else widget.isChecked()
    context=dict(format=1,engine=_engine_identity(),kind=kind,rows=row_keys,
        signal=_array(observed),background=_array(w._pattern_finder_background_data(pattern)),
        removed=w._pattern_scoring_background_removed(pattern),scoring=getattr(w,'_scoring_source','Auto'),
        normalized=bool(getattr(w,'normalize_observed_patterns',False)),
        instrument=w._instrument_profile_for_pattern(pattern).calculation_key(),
        sources=sorted(w._local_cache_sources()),library=w.local_phase_cache.reference_revision(w._local_cache_sources()),
        derived=DERIVED_CACHE_VERSION,required=list(w.selected_element_order),
        optional=sorted(w._optional_elements()),excluded=sorted(w._excluded_elements()),
        element_states=getattr(w,'element_states',{}),
        inorganic=checked('inorganics_checkbox'),organic=checked('organics_checkbox'),
        structures=w._structural_data_enabled(),cifs=cifs,accepted=accepted,
        project_references=_project_references(w,pattern) if kind=='gain' else None,
        accepted_fit=state.get('calculated_result',{}).get('result_sha256') if kind=='gain' else None,
        gain_policy=asdict(DEFAULT_GAIN_POLICY) if kind=='gain' else None,
        overlap_locked=bool(getattr(w,'_gain_overlap_locked',False)) if kind=='gain' else None,
        zero_shifts=getattr(w,'match_zero_shifts',{}) if kind=='gain' else None,
        cell_scales=getattr(w,'match_cell_scales',{}) if kind=='gain' else None,
        fwhm=getattr(w,'_last_match_profile_fwhm',0.) if kind=='gain' else None,
        eta=getattr(w,'_last_match_profile_eta',0.) if kind=='gain' else None)
    return _digest(_json(context))


def save_scores(window,kind,rows,payload):
    try:
        signature=score_signature(window,kind,rows)
        if signature is None:return False
        data=_json(dict(rows=_rows(rows),**payload))
        record=dict(format=1,signature=signature,payload=data,payload_sha256=_digest(data))
        window.profile_states.setdefault(window._active_pattern().id,{}).setdefault('score_results',{})[kind]=record
        return True
    except (AttributeError,ValueError,TypeError,OSError,sqlite3.Error):
        logging.getLogger(__name__).debug('Could not persist optional %s score cache',kind,exc_info=True)
        return False


def restore_scores(window,kind,rows):
    try:
        pattern=window._active_pattern()
        record=window.profile_states.get(pattern.id,{}).get('score_results',{}).get(kind,{})
        signature=score_signature(window,kind,rows)
        if (not signature or record.get('format')!=1 or record.get('signature')!=signature
                or _digest(record['payload'])!=record['payload_sha256']):return None
        payload=_json(record['payload'])
        # I/Ic is independently prepared in idle; do not replace a newer value
        # by the old cosmetic column stored with the scientific scores.
        keys=[tuple(normalize_candidate_row(row)[:2]) for row in payload['rows']]
        entries=window.local_phase_cache.iic_entries(keys)
        from xrd_finder.services.candidate_rows import CandidateRowFormatter
        formatter=CandidateRowFormatter(window.local_phase_cache)
        for row in payload['rows']:
            entry=entries.get(tuple(row[:2]))
            if entry is not None:
                row[7]=formatter.display_iic(entry.iic,entry.derived_version,entry.iic_method)
        return payload
    except (KeyError,AttributeError,ValueError,TypeError,OSError,sqlite3.Error):return None


def save_match_scores(window,result):
    save_scores(window,'match',result.rows,dict(
        failures=[[list(key),value] for key,value in result.failures.items()],
        unavailable=[list(key) for key in result.unavailable_keys],
        scored=[list(key) for key in result.scored_keys]))
