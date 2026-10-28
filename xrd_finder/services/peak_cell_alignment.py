"""Approximate indexed peak positions without fitting a diffraction profile."""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import math

import numpy as np
from scipy.optimize import minimize_scalar

from xrd_finder.core.structure import CellParameters
from xrd_finder.finder.cell_parameter_estimator import CellParameterEstimate, FastCellParameterEstimator
from xrd_finder.finder.models import ObservedPeak
from xrd_finder.services.calculated_pattern_service import HKLPeak


@dataclass(frozen=True, slots=True)
class PeakCellAlignment:
    peaks: tuple[object, ...]
    estimate: CellParameterEstimate | None = None


class _PeakPositionEstimator(FastCellParameterEstimator):
    @staticmethod
    def _matched_pairs(calculated_peaks,observed_peaks,*,zero_shift_deg,tolerance_deg):
        indexed=[p for p in calculated_peaks if (p.h,p.k,p.l)!=(0,0,0) and p.intensity>=4. and np.isfinite(p.two_theta)]
        indexed.sort(key=lambda p:p.intensity,reverse=True)
        if not observed_peaks:return []
        positions=np.asarray([p.two_theta for p in observed_peaks],dtype=float)
        available=np.ones(len(observed_peaks),dtype=bool);seen=set();pairs=[]
        for calculated in indexed[:48]:
            hkl=(calculated.h,calculated.k,calculated.l)
            if hkl in seen or not np.any(available):continue
            distances=np.abs(positions-(calculated.two_theta+zero_shift_deg))
            distances[~available]=np.inf
            nearest=int(np.argmin(distances));observed=observed_peaks[nearest]
            tolerance=max(tolerance_deg,min(.8,2.5*observed.fwhm))
            if distances[nearest]>tolerance:continue
            seen.add(hkl);available[nearest]=False;pairs.append((calculated,observed))
        return pairs


@lru_cache(maxsize=4096)
def _reference_cell_signature(indexed):
    if len(indexed) < 6:
        return None
    design = np.asarray([(h*h,k*k,l*l,2*h*k,2*h*l,2*k*l) for h,k,l,d in indexed],dtype=float)
    target = np.asarray([1/(d*d) for h,k,l,d in indexed],dtype=float)
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(design,target,rcond=None)
        if rank < 6:
            return None
        metric = np.asarray([[coefficients[0],coefficients[3],coefficients[4]],
                             [coefficients[3],coefficients[1],coefficients[5]],
                             [coefficients[4],coefficients[5],coefficients[2]]])
        if np.min(np.linalg.eigvalsh(metric)) <= 0:
            return None
        # The reference must describe one consistent indexed lattice.
        if np.max(np.abs(design@coefficients-target)/np.maximum(target,1e-12)) > .002:
            return None
        cell = FastCellParameterEstimator._cell_from_reciprocal_metric(metric)
    except (np.linalg.LinAlgError,ValueError):
        return None
    return None if cell is None else tuple(getattr(cell,k) for k in ('a','b','c','alpha','beta','gamma','volume'))


def _metric(cell):
    a,b,c=cell.a,cell.b,cell.c
    alpha,beta,gamma=(math.radians(v) for v in (cell.alpha,cell.beta,cell.gamma))
    return np.linalg.inv(np.asarray([[a*a,a*b*math.cos(gamma),a*c*math.cos(beta)],
                                    [a*b*math.cos(gamma),b*b,b*c*math.cos(alpha)],
                                    [a*c*math.cos(beta),b*c*math.cos(alpha),c*c]]))


def estimate_peak_cell_alignment(peaks, records, *, wavelength: float, zero_shift: float,
                                 initial_cell: CellParameters | None = None,
                                 refine_scan_zero: bool = False) -> PeakCellAlignment:
    """Estimate a small accepted-phase cell change, optionally the common zero.

    Reassociate indexed lines at each bounded zero trial for the first accepted
    phase only. Later phases (and calibrated scans) keep the supplied zero.
    Neither branch fits intensities or independently snaps indexed reflections.
    """
    original = tuple(peaks)
    measurements = tuple(records)
    baseline = _fixed_peak_cell_alignment(original, measurements, wavelength=wavelength,
        zero_shift=zero_shift, initial_cell=initial_cell)
    if not math.isfinite(wavelength) or wavelength <= 0 or not math.isfinite(zero_shift):
        return baseline
    if initial_cell is None:
        try:
            signature = _reference_cell_signature(tuple(
                (p.h, p.k, p.l, p.d) for p in original if (p.h, p.k, p.l) != (0, 0, 0)))
        except (AttributeError, TypeError, ValueError, ZeroDivisionError):
            return baseline
        if signature is None:
            return baseline
        initial_cell = CellParameters(*signature)
    if not FastCellParameterEstimator._valid_cell(initial_cell):
        return baseline
    try:
        reference_volume = math.sqrt(1./float(np.linalg.det(_metric(initial_cell))))
    except (ValueError, ZeroDivisionError, np.linalg.LinAlgError):
        return baseline
    observed = _alignment_observed_peaks(measurements)
    system = FastCellParameterEstimator._crystal_system(initial_cell)
    minimum = max(3, FastCellParameterEstimator._parameter_count(system, initial_cell) + 2)
    if len(observed) < minimum:
        return baseline
    try:
        base_score, base_count, base_rms = _alignment_support(baseline.peaks, observed)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return baseline
    if base_rms <= .005:
        return baseline
    best = (base_score, zero_shift, baseline, base_count, base_rms)
    tried = set()

    def trial(zero, scale=1.):
        nonlocal best
        zero = round(float(zero), 6) if refine_scan_zero else float(zero_shift)
        key = (zero, round(float(scale), 7))
        if key in tried:
            return
        tried.add(key)
        try:
            seed_cell = replace(initial_cell, a=initial_cell.a*scale,
                b=initial_cell.b*scale, c=initial_cell.c*scale,
                volume=reference_volume*scale**3)
            shifted = apply_peak_cell(original, seed_cell, wavelength=wavelength, zero_shift=zero)
        except (AttributeError, TypeError, ValueError, OverflowError):
            return
        if shifted is None:
            return
        fitted = _fixed_peak_cell_alignment(shifted, observed, wavelength=wavelength,
            zero_shift=zero, initial_cell=initial_cell)
        score, count, rms = _alignment_support(fitted.peaks, observed)
        if count >= minimum and score > best[0]:
            if fitted.estimate is None:
                # A seed can already be an accurate metric, but cannot stand
                # in for a rejected fit outside the reference-cell bounds.
                if rms > .025:
                    return
                fitted = PeakCellAlignment(fitted.peaks, CellParameterEstimate(
                    seed_cell, system, count, zero, base_rms, rms))
            best = (score, zero, fitted, count, rms)

    # The coarse pass changes associations; the fine pass estimates only a
    # useful starting geometry, not a calibrated instrument or refined cell.
    for zero, scale in _position_alignment_seeds(original, observed, wavelength, zero_shift,
                                                refine_scan_zero=refine_scan_zero):
        trial(zero, scale)
    polished = _polish_peak_alignment(original, observed, best[2], initial_cell,
        wavelength=wavelength, zero_shift=best[1], refine_scan_zero=refine_scan_zero)
    if polished is not None:
        score, count, rms = _alignment_support(polished.peaks, observed)
        if count >= minimum and score > best[0]:
            best = (score, polished.estimate.zero_shift_deg, polished, count, rms)
    if best[0] <= base_score or best[4] + .005 >= base_rms:
        return baseline
    selected = best[2]
    if selected.estimate is None:
        # A zero correction can improve positions without a material cell change.
        # Publish the same metric used by Gain, including CIF/cache rounding.
        aligned = apply_peak_cell(selected.peaks, initial_cell,
            wavelength=wavelength, zero_shift=best[1])
        if aligned is None:
            return baseline
        score, count, rms = _alignment_support(aligned, observed)
        if count < minimum or score <= base_score or rms + .005 >= base_rms:
            return baseline
        estimate = CellParameterEstimate(initial_cell, system, count, best[1], base_rms, rms)
        selected = PeakCellAlignment(aligned, estimate)
    return selected


def _position_alignment_seeds(peaks, observed, wavelength, zero_shift, *, refine_scan_zero=True):
    """Screen bounded d/zero starts using positions, never a calculated profile.

    A cell contraction moves high-angle lines further than low-angle lines.
    Searching zero alone can associate each hkl with a neighbouring shell.
    The small vectorized screen only selects starts; the existing indexed
    estimator still determines independent axes and enforces its cell bounds.
    """
    indexed = sorted((p for p in peaks if p.intensity >= 4. and p.d > 0.
        and math.isfinite(p.d) and math.isfinite(p.intensity)
        and (p.h, p.k, p.l) != (0, 0, 0)), key=lambda p: -p.intensity)[:48]
    if not indexed or not observed:
        return ((zero_shift, 1.),)
    zeros = (np.unique(np.append(np.linspace(-.5, .5, 21), zero_shift))
             if refine_scan_zero else np.asarray([zero_shift]))
    scales = np.linspace(.98, 1.02, 17)
    scale_grid, zero_grid = np.meshgrid(scales, zeros)
    strengths = np.sqrt([p.intensity for p in indexed])
    d = np.asarray([p.d for p in indexed])
    ratios = wavelength/(2.*scale_grid.ravel()[:, None]*d)
    positions = np.degrees(2.*np.arcsin(np.clip(ratios, 0., 1.))) + zero_grid.ravel()[:, None]
    measured = np.asarray([p.two_theta for p in observed])
    widths = np.clip(np.asarray([p.fwhm for p in observed])*.5, .05, .18)
    distances = np.abs(positions[:, :, None]-measured)
    quality = np.exp(-.5*(distances/widths)**2)
    scores = np.sum(np.max(quality, axis=2)*strengths, axis=1)
    seeds = [(float(zero_shift), 1.)]
    for index in np.argsort(-scores, kind='stable'):
        zero, scale = float(zero_grid.ravel()[index]), float(scale_grid.ravel()[index])
        if any(abs(zero-z) < .075 and abs(scale-s) < .004 for z,s in seeds):
            continue
        seeds.append((zero, scale))
        if len(seeds) >= 9:
            break
    return seeds


def _polish_peak_alignment(original, observed, selected, initial_cell, *, wavelength, zero_shift,
                          refine_scan_zero=True):
    """Refine only a small fixed set of hkl/maximum pairs, not a profile.

    Once the correct shells are associated, repeated coarse zero trials only
    redo that work. Each scalar trial here solves a tiny linear metric system.
    Cell bounds always refer to the original reference, never a moving seed.
    """
    estimator = _PeakPositionEstimator(minimum_relative_length=.98,
        maximum_relative_length=1.02, maximum_angle_change_deg=1.)
    pairs = estimator._matched_pairs(selected.peaks, observed,
        zero_shift_deg=0., tolerance_deg=.25)
    # The coarse tolerance can associate an unresolved/absent weak reflection
    # with a separate neighbouring maximum. Such a pair is not a local anchor
    # once the phase geometry has already converged to within a peak width.
    pairs = [(p,q) for p,q in pairs
             if abs(p.two_theta-q.two_theta) <= max(.025, min(.12, .75*q.fwhm))]
    system = estimator._crystal_system(initial_cell)
    if len(pairs) < max(3, estimator._parameter_count(system, initial_cell)+2):
        return None
    design = np.asarray([estimator._design_row(p.h,p.k,p.l,system,initial_cell) for p,_ in pairs])
    weights = np.asarray([estimator._pair_weight(pair) for pair in pairs])
    keep = np.ones(len(pairs), dtype=bool)
    best = None

    def error(zero):
        nonlocal best
        fit = estimator._metric_at_zero_shift(pairs=pairs, design=design, weights=weights,
            keep=keep, crystal_system=system, initial_cell=initial_cell,
            wavelength=wavelength, zero_shift=float(zero))
        if fit is None:
            return 1.e6
        metric, rms = fit
        cell = estimator._cell_from_reciprocal_metric(metric)
        if cell is None or not estimator._plausible_change(initial_cell, cell):
            return 1.e6
        if best is None or rms < best[0]:
            best = (rms, float(zero), cell)
        return rms

    error(zero_shift)
    if refine_scan_zero:
        minimize_scalar(error, bounds=(max(-.5,zero_shift-.15),min(.5,zero_shift+.15)),
            method='bounded', options={'maxiter':16, 'xatol':1.e-5})
    if best is None:
        return None
    rms, zero, cell = best
    aligned = apply_peak_cell(original, cell, wavelength=wavelength, zero_shift=zero)
    if aligned is None:
        return None
    initial_rms = selected.estimate.initial_rms_deg if selected.estimate is not None else rms
    return PeakCellAlignment(aligned, CellParameterEstimate(cell,system,len(pairs),zero,initial_rms,rms))


def _alignment_observed_peaks(records):
    observed = []
    for record in records:
        try:
            position = float(record.two_theta)
            width = float(getattr(record, 'fwhm', .18) or .18)
            strength = float(getattr(record, 'area', 0.) or getattr(record, 'height', 0.)
                             or getattr(record, 'intensity', 0.))
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if all(math.isfinite(v) for v in (position, width, strength)) and width > 0 and strength > 0:
            observed.append(ObservedPeak(position, strength, width))
    return observed


def _alignment_support(peaks, observed):
    """Whole-pattern positional support, without optimizing intensity ratios."""
    calculated = sorted((p for p in peaks if p.intensity >= 4.
        and math.isfinite(p.intensity) and math.isfinite(p.two_theta)
        and (p.h, p.k, p.l) != (0, 0, 0)), key=lambda p: -p.intensity)[:48]
    pairs = _PeakPositionEstimator._matched_pairs(calculated, observed,
        zero_shift_deg=0., tolerance_deg=.25)
    candidate_total = sum(math.sqrt(p.intensity) for p in calculated)
    observed_total = sum(math.sqrt(p.intensity) for p in observed)
    candidate_support = observed_support = 0.
    errors = []; weights = []
    for calculated_peak, observed_peak in pairs:
        delta = calculated_peak.two_theta - observed_peak.two_theta
        scale = max(.05, min(.18, .5 * observed_peak.fwhm))
        quality = math.exp(-.5 * (delta / scale)**2)
        weight = math.sqrt(calculated_peak.intensity)
        candidate_support += quality * weight
        observed_support += quality * math.sqrt(observed_peak.intensity)
        errors.append(delta); weights.append(weight)
    candidate_support /= max(candidate_total, 1e-12)
    observed_support /= max(observed_total, 1e-12)
    score = 2 * candidate_support * observed_support / max(candidate_support + observed_support, 1e-12)
    rms = float(np.sqrt(np.average(np.asarray(errors)**2, weights=weights))) if errors else math.inf
    return score, len(pairs), rms


def improve_peak_cell_estimate(peaks, records, *, baseline_estimate,
                               initial_cell: CellParameters, wavelength: float,
                               zero_shift: float, refine_scan_zero: bool):
    """Rescue a bad CIF association with the bounded cached-line search.

    Preserve a successful existing estimate unless whole-pattern positional
    support improves. Intensities are only fixed weights; no profile is fitted
    and no individual reflection is snapped to an experimental maximum.
    Input reflections do not yet include the common scan zero.
    """
    original = tuple(peaks)
    observed = _alignment_observed_peaks(records)
    shifted = apply_peak_cell(original, initial_cell, wavelength=wavelength, zero_shift=zero_shift)
    if shifted is None or len(observed) < 3:
        return baseline_estimate
    alternative = estimate_peak_cell_alignment(shifted, observed, wavelength=wavelength,
        zero_shift=zero_shift, initial_cell=initial_cell, refine_scan_zero=refine_scan_zero).estimate
    if alternative is None:
        return baseline_estimate

    def support(estimate):
        aligned = shifted if estimate is None else apply_peak_cell(original, estimate.cell,
            wavelength=wavelength, zero_shift=estimate.zero_shift_deg)
        return _alignment_support(aligned, observed)[0] if aligned is not None else -math.inf

    return alternative if support(alternative) > support(baseline_estimate) + .005 else baseline_estimate


def _fixed_peak_cell_alignment(peaks, records, *, wavelength: float, zero_shift: float,
                               initial_cell: CellParameters | None = None) -> PeakCellAlignment:
    """Estimate only small cell changes, with the scan zero held fixed.

    Input positions already include the common zero. Use the already loaded CIF
    cell when available; otherwise infer a complete metric from cached indexed d
    spacings. No phase amplitude or profile parameters are optimized.
    """
    original=tuple(peaks)
    fallback=PeakCellAlignment(original)
    if not math.isfinite(wavelength) or wavelength<=0 or not math.isfinite(zero_shift):
        return fallback
    indexed=[];calculated=[]
    for p in original:
        try:
            h,k,l=(int(getattr(p,name) or 0) for name in ('h','k','l'))
            d=float(getattr(p,'d',0.) or 0.);position=float(p.two_theta);intensity=float(p.intensity)
        except (AttributeError,TypeError,ValueError,OverflowError):
            continue
        if (h,k,l)==(0,0,0) or d<=0 or not all(math.isfinite(v) for v in (d,position,intensity)):
            continue
        indexed.append((h,k,l,d))
        calculated.append(HKLPeak(h,k,l,d,position-zero_shift,intensity))
    if initial_cell is None:
        signature=_reference_cell_signature(tuple(indexed))
        if signature is None:
            return fallback
        initial_cell = CellParameters(*signature)
    if not FastCellParameterEstimator._valid_cell(initial_cell):
        return fallback
    observed = _alignment_observed_peaks(records)
    if len(observed)<3:
        return fallback
    estimator=_PeakPositionEstimator(minimum_relative_length=.98,maximum_relative_length=1.02,maximum_angle_change_deg=1.)
    best = fallback
    best_score = -math.inf
    initial_rms = None
    # One nearest-neighbour assignment can retain the wrong hkl in a dense
    # pattern. Reassociate after a cell update, always bounding the total change
    # against the original cell and keeping the common scan zero fixed.
    for _iteration in range(4):
        estimate=estimator.estimate(initial_cell=initial_cell,calculated_peaks=calculated,
            observed_peaks=observed,wavelength=wavelength,zero_shift_deg=zero_shift,tolerance_deg=.65,refine_zero_shift=False)
        if estimate is None:
            break
        aligned = apply_peak_cell(original, estimate.cell, wavelength=wavelength, zero_shift=zero_shift)
        if aligned is None:
            break
        score, _count, _rms = _alignment_support(aligned, observed)
        if score <= best_score:
            break
        if initial_rms is None:
            initial_rms = estimate.initial_rms_deg
        best = PeakCellAlignment(aligned, replace(estimate, initial_rms_deg=initial_rms))
        best_score = score
        calculated = [replace(p, two_theta=p.two_theta-zero_shift) for p in aligned
                      if (p.h,p.k,p.l)!=(0,0,0)]
    return best


def apply_peak_cell(peaks, cell: CellParameters, *, wavelength: float, zero_shift: float):
    """Reposition indexed lines from a saved metric, preserving their intensities.

    Non-indexed lines are retained as supplied. Return None for an invalid metric
    so callers can keep the original alignment instead of partially applying it.
    """
    original = tuple(peaks)
    if not math.isfinite(wavelength) or wavelength <= 0 or not math.isfinite(zero_shift):
        return None
    try:
        if not FastCellParameterEstimator._valid_cell(cell):
            return None
        metric = _metric(cell)
        if not np.all(np.isfinite(metric)) or np.min(np.linalg.eigvalsh(metric)) <= 0:
            return None
    except (np.linalg.LinAlgError, ValueError, TypeError):
        return None
    try:
        vectors=np.asarray([(int(getattr(p,'h') or 0),int(getattr(p,'k') or 0),int(getattr(p,'l') or 0)) for p in original],dtype=float)
        squares=np.einsum('ij,jk,ik->i',vectors,metric,vectors)
    except (AttributeError,TypeError,ValueError,OverflowError):
        return None
    aligned=[]
    for p,vector,square in zip(original,vectors,squares):
        try:
            h,k,l=(int(v) for v in vector)
            if (h,k,l)==(0,0,0) or square<=0:
                aligned.append(p);continue
            d=1/math.sqrt(square);argument=wavelength/(2*d)
            if not 0<argument<1:
                return None
            aligned.append(HKLPeak(h,k,l,d,math.degrees(2*math.asin(argument))+zero_shift,float(p.intensity),
                multiplicity=int(getattr(p,'multiplicity',1) or 1),f2=float(getattr(p,'f2',0.) or 0.),
                lp=float(getattr(p,'lp',1.) or 1.),raw_intensity=float(getattr(p,'raw_intensity',0.) or 0.)))
        except (AttributeError,TypeError,ValueError,OverflowError):
            return None
    return tuple(aligned)
