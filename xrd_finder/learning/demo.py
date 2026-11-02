"""Synthetic practice data built by Finder's real native profile pipeline."""
from dataclasses import dataclass,replace
from itertools import permutations,product
from pathlib import Path
import shutil

import numpy as np
from xrd_finder.core.pattern import Pattern
from xrd_finder.core.project import Project
from xrd_finder.core.series import SeriesAnalysis
from xrd_finder.core.reference_structures import corundum_reference_path
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.local_phase_cache import LocalPhaseCache
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter


@dataclass
class DemoWorkspace:
    root: Path
    project: Project
    references: dict
    profile: InstrumentProfile
    cache: LocalPhaseCache


def _halite_cif():
    # Full Fm-3m group: 48 signed permutations times four F translations.
    operations=[]
    for axes in permutations('xyz'):
        for signs in product((1,-1),repeat=3):
            for translation in ((0,0,0),(0,1,1),(1,0,1),(1,1,0)):
                terms=[('' if sign==1 else '-')+axis+('+1/2' if shift else '')
                       for axis,sign,shift in zip(axes,signs,translation)]
                operations.append("'"+','.join(terms)+"'")
    return """data_training_halite
_chemical_name_mineral 'Halite'
_chemical_formula_sum 'Na Cl'
_space_group_IT_number 225
_space_group_name_H-M_alt 'F m -3 m'
_cell_length_a 5.6402
_cell_length_b 5.6402
_cell_length_c 5.6402
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_cell_formula_units_Z 4
loop_
_space_group_symop_operation_xyz
"""+'\n'.join(operations)+"""
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Na1 Na 0 0 0 1 0
Cl1 Cl 0.5 0.5 0.5 1 0
"""


def build_demo_workspace(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'.learning-sandbox').write_text('Synthetic Finder practice data; not personal experimental data.\n')
    refs=root/'references';refs.mkdir(exist_ok=True)
    references={'training-nacl':refs/'training-nacl.cif','training-corundum':refs/'training-corundum.cif'}
    references['training-nacl'].write_text(_halite_cif())
    shutil.copyfile(corundum_reference_path(),references['training-corundum'])
    base=InstrumentProfile.default_cu_kalpha()
    profile=replace(base,profile_id='learning-synthetic-cu',
        identity=replace(base.identity,name='Synthetic training Cu profile'),
        resolution=replace(base.resolution,model='constant_fwhm',constant_fwhm_deg=.16))
    cache=LocalPhaseCache(root/'cod_cache')
    for key,path in references.items():
        if not cache.index_cif(path,'USER',key):
            raise RuntimeError('Could not prepare training reference '+key+': '+getattr(cache,'_last_reference_preparation_error',''))
    x=np.linspace(15.,90.,3751)
    adapter=CristmaPowderAdapter()
    profiles={key:adapter.calculate_from_cif(path,x_grid=x,instrument_profile=profile,use_lp=True).profile_y
              for key,path in references.items()}
    profiles={key:values/float(np.max(values)) for key,values in profiles.items()}
    background=16.+40.*np.exp(-(x-15.)/30.)
    rng=np.random.default_rng(169)
    signals=(background+1700.*profiles['training-nacl']+rng.normal(0,.7,len(x)),
             background+1400.*profiles['training-nacl']+550.*profiles['training-corundum']+rng.normal(0,.7,len(x)))
    patterns=[]
    folder=root/'measurements';folder.mkdir(exist_ok=True)
    for name,label,values in zip(('pure-nacl','nacl-corundum'),('Training · NaCl','Training · NaCl + corundum'),signals):
        path=folder/(name+'.xy');np.savetxt(path,np.column_stack((x,values)),fmt='%.8f')
        pattern=Pattern.create(label,str(path))
        pattern.instrument_profile=profile.to_dict()
        pattern.wavelength=profile.radiation.components[0].wavelength_angstrom
        pattern.metadata.update(synthetic=True,training_components=['NaCl'] if name=='pure-nacl' else ['NaCl','Al2O3'])
        pattern.notes=('Deterministic synthetic training signal from native CIF profiles. '
                       'Known component identities; intensity coefficients are not certified mass fractions. '
                       'This is not an experimental instrument standard.')
        patterns.append(pattern)
    series=SeriesAnalysis.create('Synthetic training measurements')
    series.pattern_ids=[pattern.id for pattern in patterns]
    project=Project('Finder training sandbox',patterns=patterns,series=[series],
        notes='Synthetic practice data in an isolated offline workspace. Personal measurements, settings and reference libraries are not copied.')
    return DemoWorkspace(root,project,references,profile,cache)
