"""Share a native read only within one preparation transaction/thread.

The CrIStMa result is consumed without mutation. Nothing survives the scope:
changed files and subsequent requests always get a fresh parse.
"""
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from dataclasses import replace
import cristma

_reads = ContextVar('xrd_native_cif_reads', default=None)

_MP_METHOD='XRD Phase Finder Materials Project REST adapter v2'
_GROUP_TAGS=frozenset(('_symmetry_space_group_name_h-m','_space_group_name_h-m_alt',
    '_space_group_it_number','_symmetry_int_tables_number','_space_group_name_hall',
    '_symmetry_space_group_name_hall','_space_group_it_coordinate_system_code','_symmetry_cell_setting'))


def _read_calculation_model(path):
    result=cristma.read(path,format='cif')
    blocks=getattr(result.document,'blocks',())
    method=blocks[0].scalar('_audit_creation_method') if len(blocks)==1 else None
    if method is None or str(method.value).strip("'\"")!=_MP_METHOD or len(result.structures)!=1:
        return result
    if any(blocks[0].scalar(tag) is not None or blocks[0].loops_with_tag(tag)
           for tag in ('_space_group_symop_operation_xyz','_symmetry_equiv_pos_as_xyz')):
        return result
    text=Path(path).read_text(encoding='utf-8',errors='replace')
    # REST v2 exports structure.sites in its original lattice basis. The
    # reported conventional group need not describe that basis. Preserve each
    # full-cell coordinate once instead of deriving another asymmetric unit.
    retained=[line for line in text.splitlines() if not line.strip() or line.split()[0].casefold() not in _GROUP_TAGS]
    normalized='\n'.join(retained)+"\n_space_group_name_H-M_alt 'P 1'\n_space_group_IT_number 1\nloop_\n_space_group_symop_operation_xyz\n'x,y,z'\n"
    from cristma.io.cif.handler import CifFormatHandler
    calculation=CifFormatHandler().read_text(normalized,source_name=str(path))
    structures=tuple(replace(s,metadata={**s.metadata,'source_representation':'explicit_full_cell_P1'})
                     for s in calculation.structures)
    # The original document remains authoritative for displayed identifiers,
    # reported group, formula and provenance. No source file is rewritten.
    return replace(calculation,document=result.document,source_info=result.source_info,structures=structures)


def read_native_cif(path):
    cache = _reads.get()
    if cache is None:
        return _read_calculation_model(path)
    key = str(Path(path).resolve())
    if key not in cache:
        cache[key] = _read_calculation_model(path)
    return cache[key]


def native_cif_session(function):
    @wraps(function)
    def run(*args, **kwargs):
        if _reads.get() is not None:
            return function(*args, **kwargs)
        token = _reads.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _reads.reset(token)
    return run
