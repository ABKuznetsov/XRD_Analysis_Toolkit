"""Joint structural phase model for quantities and accepted-phase curves."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import hashlib
import math
from pathlib import Path

import numpy as np
from scipy.optimize import nnls
import cristma

from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter
from xrd_finder.services.calculated_pattern_service import HKLPeak
from xrd_finder.finder.sample_broadening import broaden_profile, fit_sample_broadening
from xrd_finder.finder.composition_validation import CifCompositionError, validate_composition, occupied_cell as _occupied_cell


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
    return _occupied_cell(structure)[0]


@lru_cache(maxsize=256)
def _cif_metadata(path: str, modified_ns: int, size: int) -> tuple[float,float]:
    # Resolve exactly the native setting used for diffraction; a CIF can omit
    # the explicit symmetry-operation loop and still have a nontrivial group.
    read_result=cristma.read(path)
    # Collapsing explicitly repeated symmetry mates preserves the occupied
    # structure; it is not parser recovery or a loss of physical metadata.
    if any(
        getattr(diagnostic.severity, 'value', '') == 'error'
        or getattr(diagnostic, 'recovery', None) is not None
        or (getattr(diagnostic.severity, 'value', '') == 'warning'
            and diagnostic.code != 'cif.map.symmetry_expanded_sites_collapsed')
        for diagnostic in read_result.diagnostics
    ):
        raise ValueError('CIF physical metadata required parser recovery')
    native,_setting=CristmaPowderAdapter._structure_and_setting(path,read_result=read_result)
    mass,composition=_occupied_cell(native)
    try:
        validate_composition(native.formula,composition)
    except CifCompositionError as exc:
        raise CifCompositionError(f'{Path(path).name}: {exc}') from exc
    return mass,unit_cell_volume(native.cell)


@dataclass(frozen=True)
class AcceptedPhaseFit:
    fractions: np.ndarray
    # Columns are unnormalised integrated-intensity structural profiles.
    profiles: np.ndarray
    scales: np.ndarray
    peaks: tuple[tuple[HKLPeak, ...], ...]
    sample_broadening: tuple[dict, ...] = ()
    mass_factors: tuple[float, ...] = ()


@lru_cache(maxsize=256)
def _cif_source_hash(path: str, modified_ns: int, size: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit_accepted_phases(items, x, target, context, instrument, calculator, *,
                        refine_sample_broadening=False, observed_peaks=(), diagnostics=None) -> AcceptedPhaseFit | None:
    """Fit accepted structural phases once in physical units.

    Keep the fitted columns and coefficients alongside Hill--Howard fractions
    so plotted phase contributions cannot describe a different mixture.
    Cached reference cards require their local CIF for this physical model.
    """
    def unavailable(reason):
        if diagnostics is not None:
            diagnostics.append(reason)
        return None

    if not items:
        return unavailable('No selected phases for quantitative analysis')
    if instrument is None:
        return unavailable('An instrument profile is required for quantitative analysis')
    profiles=[];masses=[];volumes=[];peak_sets=[];broadening_fits=[]
    phase_label='selected phases'
    seen_sources=set()
    try:
        target=np.asarray(target,dtype=float)
        if not np.all(np.isfinite(target)):
            return unavailable('Observed signal contains non-finite intensities')
        if not np.any(target>0):
            return unavailable('No positive diffraction signal (zero or nonpositive intensity) for quantitative analysis')
        for phase_index,item in enumerate(items):
            candidate,_structure,_reference,_adjusted,_display,cell_scale,width,eta,estimate=item
            phase_label=candidate.name or candidate.entry_id or candidate.cif_path or 'selected phase'
            cif_path=candidate.cif_path or candidate.quantification_cif_path
            if not cif_path:
                return unavailable(f'{phase_label}: no local CIF structure for quantitative analysis')
            path=Path(cif_path).resolve()
            phase_label=path.name
            stat=path.stat()
            mass,volume=_cif_metadata(str(path),stat.st_mtime_ns,stat.st_size)
            source_hash=_cif_source_hash(str(path),stat.st_mtime_ns,stat.st_size)
            input_cell=candidate.initial_cell or getattr(candidate.structure,'cell',None)
            input_metric=(None if input_cell is None else tuple(getattr(input_cell,name)
                for name in ('a','b','c','alpha','beta','gamma')))
            # Identical inputs cannot become distinct phases merely through
            # separate heuristic refinements. Explicitly different cell models
            # still reach the independent profile-rank check below.
            source_identity=(source_hash,input_metric)
            if source_identity in seen_sources:
                return unavailable(f'{path.name}: identical CIF structures cannot be separated into individual phase fractions')
            seen_sources.add(source_identity)
            override=estimate.cell if estimate is not None else None
            if candidate.structure is not None and not candidate.cif_path:
                # Preserve the sample-linked display model. A CIF supplies
                # absolute intensities only while its sites/symmetry agree.
                _phase,source=create_phase_from_cif(path)
                active=candidate.structure
                if any(getattr(active,name)!=getattr(source,name) for name in
                       ('atoms','symops','space_group','space_group_number')):
                    return unavailable(f'{path.name}: selected atomic sites or symmetry differ from the physical CIF model')
                if override is None:
                    override=active.cell
            phase_context=context.with_alignment(context.global_zero_shift,cell_scale)
            phase_context=replace(phase_context,fwhm=width,profile_eta=float(eta or 0.0))
            _structure,lines=calculator.line_calculator.candidate_structure_and_lines(
                str(path),phase_context,use_lp=True,instrument_profile=instrument,cell_override=override)
            profile=None
            broadening={}
            if refine_sample_broadening:
                adapter=calculator.line_calculator.cristma_adapter
                base=adapter.profile_from_lines(
                    lines.cristma_lines,x_grid=x,instrument_profile=instrument,
                    zero_shift_deg=context.global_zero_shift,d_spacing_scale=cell_scale,
                    normalize=False,include_boundary_wings=True).profile_y
                def native_profile(sample_fwhm):
                    return broaden_profile(x,base,sample_fwhm)
                phase_positions=[]
                for peak in lines.peaks:
                    if float(peak.intensity)<3.:
                        continue
                    angle=2*math.degrees(math.asin(context.primary_wavelength/(2*peak.d*cell_scale)))
                    phase_positions.append(angle+context.global_zero_shift)
                other_positions=[peak.two_theta for index,other in enumerate(items)
                                 if index!=phase_index for peak in other[3] if peak.intensity>=3.]
                fitted=fit_sample_broadening(
                    x=x,target=target,phase_positions=phase_positions,observed_peaks=observed_peaks,
                    other_phase_positions=other_positions,profile_factory=native_profile)
                broadening=asdict(fitted)
                broadening['profile_model']='effective_gaussian_convolution' if fitted.available else 'legacy_width_floor'
                if fitted.available:
                    profile=native_profile(fitted.sample_fwhm_deg)
            if profile is None:
                profile=calculator.profile_from_lines(lines,x,phase_context,
                    instrument_profile=instrument,normalize=False)
            broadening_fits.append(broadening)
            profiles.append(np.asarray(profile,dtype=float))
            peak_sets.append(tuple(lines.peaks))
            masses.append(mass)
            volumes.append(unit_cell_volume(override) if override is not None else volume*float(cell_scale)**3)
        matrix=np.column_stack(profiles)
        if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(target)):
            return unavailable('Calculated profiles or observed signal contain non-finite intensities')
        weights=1./np.sqrt(np.maximum(np.abs(target),1.))
        weighted=matrix*weights[:,None]
        norms=np.linalg.norm(weighted,axis=0)
        if not np.all(norms>0):
            return unavailable('A selected phase has no usable calculated intensity within the scan range')
        normalized=weighted/norms
        if np.linalg.matrix_rank(normalized)<len(items):
            return unavailable('Selected phase profiles are linearly dependent; individual mass fractions cannot be separated')
        scales,_=nnls(normalized,target*weights)
        scales=scales/norms
        fractions=mass_fractions(scales,masses,volumes)
        if not np.all(np.isfinite(fractions)):
            return unavailable('No identifiable positive phase contribution; mass fractions cannot be normalized')
        return AcceptedPhaseFit(fractions,matrix,scales,tuple(peak_sets),tuple(broadening_fits),
                                tuple(float(m*v) for m,v in zip(masses,volumes)))
    except CifCompositionError as exc:
        return unavailable(str(exc))
    except (OSError,ValueError,TypeError,AttributeError,RuntimeError,np.linalg.LinAlgError) as exc:
        return unavailable(f'Quant calculation failed for {phase_label}: {type(exc).__name__}: {exc}')


def accepted_phase_quantities(items, x, target, context, instrument, calculator) -> np.ndarray:
    """Compatibility accessor for callers needing only mass fractions."""
    fit=fit_accepted_phases(items,x,target,context,instrument,calculator)
    return fit.fractions if fit is not None else np.full(len(items),np.nan)
