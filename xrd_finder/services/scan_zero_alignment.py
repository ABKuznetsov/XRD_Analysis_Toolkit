"""Validate one scan zero against the indexed lines of all accepted phases."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from xrd_finder.core.structure import CellParameters
from xrd_finder.finder.cell_parameter_estimator import CellParameterEstimate, FastCellParameterEstimator
from xrd_finder.services.peak_cell_alignment import (
    PeakCellAlignment, _PeakPositionEstimator, _alignment_observed_peaks,
    _alignment_support, _reference_cell_signature, apply_peak_cell,
    estimate_peak_cell_alignment,
)
from xrd_finder.services.refinement_budget import RefinementBudget


@dataclass(frozen=True)
class PhasePositionInput:
    key: str
    peaks: tuple
    cell: CellParameters | None = None


@dataclass(frozen=True)
class CommonZeroAlignment:
    zero_shift_deg: float
    alignments: dict[str, PeakCellAlignment]
    diagnostics: dict


def _independent_position_lines(peaks):
    """One anchor per coincident powder line; retain all lines for the profile."""
    ordered = sorted(peaks, key=lambda peak: float(peak.two_theta))
    groups = []
    for peak in ordered:
        if (groups and math.isfinite(float(peak.two_theta))
                and abs(float(peak.two_theta)-float(groups[-1][0].two_theta))<=1.e-6):
            groups[-1].append(peak)
        else:
            groups.append([peak])
    return tuple(max(group,key=lambda peak:float(peak.intensity)) for group in groups)


def _phase_position_proposal(phase, cell, observed, wavelength, seed, budget, *, neutral_retry=True):
    """Compare all-peak and strong-anchor starts for an accepted phase.

    Every proposal is validated against the complete measured peak set. The
    extended cell range is the existing estimator's range, and shares the
    original two-second deadline. Weak phases retain the all-peak attempt.
    """
    ranked = sorted(observed,key=lambda peak:-peak.intensity)
    anchors = [observed]
    for count in (16,32,64):
        if count<len(ranked):
            anchors.append(ranked[:count])
    defaults = FastCellParameterEstimator()
    extended = (defaults.minimum_relative_length,defaults.maximum_relative_length,
                defaults.maximum_angle_change_deg)
    best = None
    best_key = None
    for limits in ((.98,1.02,1.),extended):
        for records in anchors:
            if budget.expired:
                return best
            shifted = apply_peak_cell(phase.peaks,cell,wavelength=wavelength,zero_shift=seed)
            if shifted is None:
                return best
            fitted = estimate_peak_cell_alignment(shifted,records,wavelength=wavelength,
                zero_shift=seed,initial_cell=cell,refine_scan_zero=True,budget=budget,
                cell_limits=limits)
            proposal = _validated_proposal(phase,cell,fitted,observed,wavelength,seed)
            if proposal is None:
                continue
            score = _alignment_support(fitted.peaks,observed)[0]
            key = (proposal['confirmed'],score,-proposal['rms'])
            if best_key is None or key>best_key:
                proposal['cell_limits'] = limits
                proposal['anchor_count'] = len(records)
                best,best_key = proposal,key
        # A tight cell bound can mimic contraction with a wrong scan zero.
        # Compare the extended proposal on the same full-pattern support,
        # rather than treating the first apparently precise zero as final.
    if best is None and neutral_retry and abs(seed)>.15 and not budget.expired:
        # A Match displacement is only a start, not a calibrated zero. A cell
        # change can otherwise trap the indexed refinement near a false large
        # start. Keep supported large shifts; retry zero only if none validated.
        return _phase_position_proposal(phase,cell,observed,wavelength,0.,budget,neutral_retry=False)
    return best


def align_common_zero(phases, records, *, wavelength, zero_shift=0., refine_zero=True,
                      allow_uncertain_zero=False, budget=None):
    """Use independently validated indexed phases to estimate one common zero.

    A nearest-neighbour fit alone is not a calibration. Require distinct lines
    over an angular span and estimate zero uncertainty after projecting out the
    phase's metric parameters. Duplicate cards do not get extra votes. All
    proposals and final cell fits consume the same supplied deadline.
    """
    budget = budget if budget is not None else RefinementBudget()
    phases = sorted(phases, key=lambda p: p.key)
    observed = _alignment_observed_peaks(records)
    seed = float(zero_shift) if math.isfinite(float(zero_shift)) else 0.
    zero = 0. if refine_zero else seed
    references = {}
    position_phases = {}
    proposals = []
    seen = set()
    for phase in phases:
        if budget.expired:
            references[phase.key] = phase.cell
            continue
        indexed = tuple(p for p in phase.peaks if (p.h,p.k,p.l)!=(0,0,0) and p.d>0)
        signature = _reference_cell_signature(tuple((p.h,p.k,p.l,p.d) for p in indexed))
        cell = CellParameters(*signature) if signature is not None else phase.cell
        references[phase.key] = cell
        position_phase = PhasePositionInput(phase.key,_independent_position_lines(phase.peaks),cell)
        position_phases[phase.key] = position_phase
        if not refine_zero or budget.expired or cell is None or len(indexed)<5:
            continue
        maximum = max((p.intensity for p in indexed),default=1.) or 1.
        fingerprint = tuple(sorted((p.h,p.k,p.l,round(p.d,6),round(p.intensity/maximum,6)) for p in indexed))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        # Match can independently identify a larger common displacement.
        # Keep that start; the indexed-line validator below must still confirm it.
        start = seed
        proposal = _phase_position_proposal(position_phase,cell,observed,wavelength,start,budget)
        if proposal is not None:
            proposals.append(proposal)
    trusted = []
    confirmed = [p for p in proposals if p['confirmed']]
    eligible = confirmed or (proposals if allow_uncertain_zero else [])
    rejected = bool(proposals and not confirmed and not allow_uncertain_zero)
    if eligible:
        # A narrow, independently constrained phase can correct a wrong first
        # card; many weak or duplicate cards cannot vote it away.
        def agreement(p):
            return sum(q['weight']*math.exp(-.5*((p['zero']-q['zero'])/
                max(.025,2*q['sigma']))**2) for q in eligible)
        anchor = max(eligible,key=lambda p:(agreement(p),p['weight'],p['key']))
        trusted = [p for p in eligible if abs(p['zero']-anchor['zero'])<=
                   max(.03,3*math.hypot(p['sigma'],anchor['sigma']))]
        zero = float(np.average([p['zero'] for p in trusted],weights=[p['weight'] for p in trusted]))
    if refine_zero:
        # Publish one value for profiles, stored cells and downstream Gain/SQL.
        # Keep the minimization itself at full precision.
        zero = round(zero,3) or 0.
    alignments = {}
    for phase in phases:
        cell = references[phase.key]
        position_phase = position_phases.get(phase.key,phase)
        shifted = (None if cell is None else apply_peak_cell(position_phase.peaks,cell,
            wavelength=wavelength,zero_shift=zero))
        if shifted is None:
            from dataclasses import replace
            shifted = tuple(replace(p,two_theta=p.two_theta+zero) for p in position_phase.peaks)
        fitted = PeakCellAlignment(shifted)
        prior = next((p for p in proposals if p['key']==phase.key),None)
        # Preserve an already validated result when the shared budget runs out.
        # Do not publish that cell at a different, unevaluated scan zero.
        if prior is not None and not rejected and abs(prior['zero']-zero)<=.000500001:
            validated = apply_peak_cell(position_phase.peaks,prior['cell'],wavelength=wavelength,zero_shift=zero)
            if validated is not None:
                estimate = CellParameterEstimate(prior['cell'],prior['system'],prior['matches'],
                    zero,prior['rms'],prior['rms']+abs(prior['zero']-zero))
                fitted = PeakCellAlignment(validated,estimate)
        if cell is not None and not budget.expired and not rejected:
            # Preserve the bounded cell-start search even with a fixed zero:
            # high-angle reflections may be beyond the first association
            # window. Screen from the reference metric, not an already warped
            # d-spacing seed, and retain a better validated proposal on expiry.
            refined = estimate_peak_cell_alignment(shifted,observed,wavelength=wavelength,
                zero_shift=zero,initial_cell=cell,refine_scan_zero=False,budget=budget,
                cell_limits=prior.get('cell_limits',(.98,1.02,1.)) if prior is not None else (.98,1.02,1.))
            if refined.estimate is not None and (fitted.estimate is None or
                    _alignment_support(refined.peaks,observed)[0]>
                    _alignment_support(fitted.peaks,observed)[0]):
                fitted = refined
        # Coincident HKLs are one positional observation, but their separate
        # physical strengths must all survive in the returned phase profile.
        output_cell = fitted.estimate.cell if fitted.estimate is not None else cell
        restored = (None if output_cell is None else apply_peak_cell(phase.peaks,output_cell,
                    wavelength=wavelength,zero_shift=zero))
        if restored is None:
            from dataclasses import replace
            restored = tuple(replace(p,two_theta=p.two_theta+zero) for p in phase.peaks)
        alignments[phase.key] = PeakCellAlignment(restored,fitted.estimate)
    diagnostics = dict(zero_confirmed=bool(trusted and confirmed),
        requires_confirmation=bool(trusted and not confirmed),
        position_rejected=rejected,
        zero_sigma_deg=max((p['sigma'] for p in trusted),default=0.),budget_exhausted=budget.expired,
        seconds=budget.elapsed,limit_seconds=2.,trusted_phases=[p['key'] for p in trusted],
        proposals=[{k:v for k,v in p.items() if k!='cell'} for p in proposals])
    return CommonZeroAlignment(zero,alignments,diagnostics)


def _validated_proposal(phase, cell, fitted, observed, wavelength, seed):
    estimate = fitted.estimate
    zero = seed if estimate is None else estimate.zero_shift_deg
    if abs(zero)>.5 and abs(zero-seed)>.15:
        return None
    fitted_cell = cell if estimate is None else estimate.cell
    estimator = _PeakPositionEstimator()
    system = estimator._crystal_system(cell)
    count = estimator._parameter_count(system,cell)
    # Several symmetry-equivalent hkl at one powder line are one observation.
    unique = []
    for peak in sorted(fitted.peaks,key=lambda p:-p.intensity):
        if peak.intensity>=4. and (peak.h,peak.k,peak.l)!=(0,0,0) and all(
                abs(peak.two_theta-p.two_theta)>.015 for p in unique):
            unique.append(peak)
        if len(unique)>=48:
            break
    pairs = estimator._matched_pairs(unique,observed,zero_shift_deg=0.,tolerance_deg=.12)
    pairs = [(p,q) for p,q in pairs if abs(p.two_theta-q.two_theta)<=max(.025,min(.12,.75*q.fwhm))]
    if len(pairs)<max(5,count+3):
        return None
    angles = np.asarray([q.two_theta for _,q in pairs])
    if float(np.ptp(angles))<15.:
        return None
    residual = np.asarray([p.two_theta-q.two_theta for p,q in pairs])
    weights = np.sqrt([p.intensity for p,_ in pairs])
    weights /= np.mean(weights)
    rms = float(np.sqrt(np.average(residual**2,weights=weights)))
    widths = np.asarray([q.fwhm for _,q in pairs])
    coverage = sum(math.sqrt(p.intensity) for p,_ in pairs)/max(
        sum(math.sqrt(p.intensity) for p in unique),1e-12)
    if rms>max(.02,min(.06,.30*float(np.median(widths)))) or coverage<.35:
        return None
    # d(1/d^2)/d(2theta) in degrees. Projecting the constant zero column
    # off the metric columns exposes cell/zero correlation rather than hiding
    # it behind a small residual from a flexible unit cell.
    theta = np.radians((angles-zero)/2)
    q_values = (2*np.sin(theta)/wavelength)**2
    derivative = q_values/np.tan(theta)*math.pi/180.
    design = np.asarray([estimator._design_row(p.h,p.k,p.l,system,cell) for p,_ in pairs])
    jacobian = design/derivative[:,None]
    try:
        root = np.sqrt(weights)
        parameters,_,rank,_ = np.linalg.lstsq(jacobian*root[:,None],root,rcond=None)
        if rank<count:
            return None
        information = float(np.sum(weights*(1-jacobian@parameters)**2))
        sigma = max(rms,.005)/math.sqrt(max(information,1e-12))
    except (ValueError,np.linalg.LinAlgError):
        return None
    # Compare zero precision with the resolved anchors, not the minimum
    # matching window used for sharp lines. Broad observed maxima have less
    # precise centres. A less precise, otherwise supported proposal is offered
    # for operator confirmation, never silently certified as a calibration.
    sigma_limit = min(.05, max(.025, .25*float(np.median(widths))))
    if not math.isfinite(sigma) or sigma>sigma_limit:
        return None
    return dict(key=phase.key,zero=float(zero),sigma=float(sigma),confirmed=sigma<=.025,
        sigma_limit=sigma_limit,rms=rms,coverage=coverage,
        matches=len(pairs),system=system,cell=fitted_cell,weight=coverage**2/max(sigma,.005)**2)
