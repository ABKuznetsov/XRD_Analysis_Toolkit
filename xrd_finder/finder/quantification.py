"""Joint structural phase model for quantities and accepted-phase curves."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import math
from pathlib import Path

import numpy as np
from scipy.optimize import nnls
import cristma
from cristma.symmetry.orbit import expand_structure

from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.services.element_masses import atomic_weight
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
from xrd_finder.services.calculated_pattern_service import HKLPeak


def quantification_source_signature(path, structure) -> tuple:
    """Invalidate Quant when a local physical model changes, without fetching it."""
    file_signature = None
    if path is not None:
        local = Path(path)
        try:
            stat = local.stat()
            file_signature = (str(local.resolve()), stat.st_mtime_ns, stat.st_size)
        except OSError:
            file_signature = (str(local), None, None)
    structure_signature = None
    if structure is not None:
        structure_signature = (
            getattr(structure, 'space_group', ''),
            getattr(structure, 'space_group_number', ''),
            tuple(getattr(structure, 'symops', ())),
            tuple(tuple(getattr(atom, name, None) for name in
                        ('label', 'element', 'x', 'y', 'z', 'occupancy', 'biso', 'uiso',
                         'wyckoff', 'multiplicity')) for atom in getattr(structure, 'atoms', ())),
        )
    return file_signature, structure_signature


def mass_fractions(scales, cell_masses, cell_volumes) -> np.ndarray:
    """Hill & Howard (1987): W = S * (Z M) * V / sum(S * (Z M) * V).

    S refers to an unnormalised, integrated-intensity structural profile, never
    the coefficient of a curve independently normalized to its tallest peak.
    """
    s,m,v=(np.asarray(values,dtype=float) for values in (scales,cell_masses,cell_volumes))
    if s.shape != m.shape or s.shape != v.shape:
        raise ValueError('Quantification arrays must have matching shapes')
    if not (np.all(np.isfinite(s)) and np.all(s>=0) and
            np.all(np.isfinite(m)) and np.all(m>0) and
            np.all(np.isfinite(v)) and np.all(v>0)):
        return np.full_like(s,np.nan)
    contributions=s*m*v
    total=float(np.sum(contributions))
    return contributions/total if math.isfinite(total) and total>0 else np.full_like(s,np.nan)


def unit_cell_volume(cell) -> float:
    def value(name):
        measured=getattr(cell,name)
        return float(getattr(measured,'value',measured))
    a,b,c=(value(name) for name in ('a','b','c'))
    angles=np.asarray([value(name) for name in ('alpha','beta','gamma')])
    if not all(math.isfinite(x) and x>0 for x in (a,b,c)) or not np.all((angles>0)&(angles<180)):
        raise ValueError('Invalid unit cell')
    ca,cb,cg=np.cos(np.radians(angles))
    volume=a*b*c*math.sqrt(max(0.,float(1+2*ca*cb*cg-ca*ca-cb*cb-cg*cg)))
    if not math.isfinite(volume) or volume<=0:
        raise ValueError('Invalid cell volume')
    return volume


def unit_cell_mass(structure) -> float:
    """Use exactly the native diffraction engine's occupied symmetry orbits."""
    atoms=expand_structure(structure).atoms
    if not atoms:
        raise ValueError('No occupied structural model')
    total=0.
    for atom in atoms:
        for component in atom.components:
            weight=atomic_weight(component.species.symbol)
            occupancy=float(component.occupancy.value)
            if not math.isfinite(weight) or weight<=0 or not math.isfinite(occupancy) or not 0<=occupancy<=1:
                raise ValueError('Invalid atom or occupancy')
            total+=weight*occupancy
    if not math.isfinite(total) or total<=0:
        raise ValueError('Unknown cell mass')
    return total


@lru_cache(maxsize=256)
def _cif_metadata(path: str, modified_ns: int, size: int) -> tuple[float,float]:
    # Resolve exactly the native setting used for diffraction; a CIF can omit
    # the explicit symmetry-operation loop and still have a nontrivial group.
    read_result=cristma.read(path)
    if any(getattr(diagnostic.severity,'value','') in ('warning','error') for diagnostic in read_result.diagnostics):
        raise ValueError('CIF physical metadata required parser recovery')
    native,_setting=CristmaPowderAdapter._structure_and_setting(path)
    return unit_cell_mass(native),unit_cell_volume(native.cell)


@dataclass(frozen=True)
class AcceptedPhaseFit:
    fractions: np.ndarray
    # Columns are unnormalised integrated-intensity structural profiles.
    profiles: np.ndarray
    scales: np.ndarray
    peaks: tuple[tuple[HKLPeak, ...], ...]


def fit_accepted_phases(items, x, target, context, instrument, calculator) -> AcceptedPhaseFit | None:
    """Fit accepted structural phases once in physical units.

    Keep the fitted columns and coefficients alongside Hill--Howard fractions
    so plotted phase contributions cannot describe a different mixture.
    Cached reference cards require their local CIF for this physical model.
    """
    if not items or instrument is None:
        return None
    profiles=[];masses=[];volumes=[];peak_sets=[]
    try:
        for item in items:
            candidate,_structure,_reference,_adjusted,_display,cell_scale,width,eta,estimate=item
            cif_path=candidate.cif_path or candidate.quantification_cif_path
            if not cif_path:
                return None
            path=Path(cif_path).resolve()
            stat=path.stat()
            mass,volume=_cif_metadata(str(path),stat.st_mtime_ns,stat.st_size)
            override=estimate.cell if estimate is not None else None
            if candidate.structure is not None and not candidate.cif_path:
                # Preserve the sample-linked display model. A CIF supplies
                # absolute intensities only while its sites/symmetry agree.
                _phase,source=create_phase_from_cif(path)
                active=candidate.structure
                if any(getattr(active,name)!=getattr(source,name) for name in
                       ('atoms','symops','space_group','space_group_number')):
                    return None
                if override is None:
                    override=active.cell
            phase_context=context.with_alignment(context.global_zero_shift,cell_scale)
            phase_context=replace(phase_context,fwhm=width,profile_eta=eta)
            _structure,lines=calculator.line_calculator.candidate_structure_and_lines(
                str(path),phase_context,use_lp=True,instrument_profile=instrument,cell_override=override)
            profile=calculator.profile_from_lines(lines,x,phase_context,
                instrument_profile=instrument,normalize=False)
            profiles.append(np.asarray(profile,dtype=float))
            peak_sets.append(tuple(lines.peaks))
            masses.append(mass)
            volumes.append(unit_cell_volume(override) if override is not None else volume*float(cell_scale)**3)
        matrix=np.column_stack(profiles)
        target=np.asarray(target,dtype=float)
        if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(target)):
            return None
        weights=1./np.sqrt(np.maximum(np.abs(target),1.))
        weighted=matrix*weights[:,None]
        norms=np.linalg.norm(weighted,axis=0)
        if not np.all(norms>0):
            return None
        normalized=weighted/norms
        if np.linalg.matrix_rank(normalized)<len(items):
            return None
        scales,_=nnls(normalized,target*weights)
        scales=scales/norms
        fractions=mass_fractions(scales,masses,volumes)
        if not np.all(np.isfinite(fractions)):
            return None
        return AcceptedPhaseFit(fractions,matrix,scales,tuple(peak_sets))
    except (OSError,ValueError,TypeError,AttributeError,RuntimeError,np.linalg.LinAlgError):
        return None


def accepted_phase_quantities(items, x, target, context, instrument, calculator) -> np.ndarray:
    """Compatibility accessor for callers needing only mass fractions."""
    fit=fit_accepted_phases(items,x,target,context,instrument,calculator)
    return fit.fractions if fit is not None else np.full(len(items),np.nan)
