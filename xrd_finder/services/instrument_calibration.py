"""Instrument-only whole-pattern TCH calibration against a fixed CIF standard.

No smoothing, cell refinement, sample broadening or Le Bail extraction is used.
The linear scale/background are nuisance terms; the common zero is not exported
as broadening. Radiation components and geometry come from the supplied profile.
"""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
import time
from uuid import uuid4

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import correlate, correlation_lags, find_peaks
from cristma.diffraction import PowderProfileCalculator, UniformTwoThetaGrid

from xrd_finder.instrument.models import InstrumentProfile, ResolutionProfile
from xrd_finder.instrument.resolution import cristma_tch_profile
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter


@dataclass(frozen=True)
class CalibrationResult:
    profile: InstrumentProfile
    x: np.ndarray
    observed: np.ndarray
    calculated: np.ndarray
    background: np.ndarray
    residual: np.ndarray
    rwp: float
    rp: float
    zero_shift_deg: float
    evaluations: int
    elapsed_seconds: float
    transferable: bool
    diagnostics: tuple[str, ...]
    cif_path: str


def validate_standard_data(data):
    values = np.array(data, dtype=float, copy=True)
    if values.ndim != 2 or values.shape[1] < 2 or len(values) < 2:
        raise ValueError('Load a measured two-column XRD pattern.')
    values = values[:, :2]
    if not np.isfinite(values).all():
        raise ValueError('Standard data must contain finite angles and intensities.')
    x, y = values.T
    if x[0] < 0. or x[-1] > 125.:
        raise ValueError('The standard must be within 0–125° 2θ. Crop the source data explicitly.')
    steps = np.diff(x)
    if np.any(steps <= 0.):
        raise ValueError('Standard angles must be strictly increasing without duplicate points.')
    if len(x) < 100 or np.ptp(x) < 30.:
        raise ValueError('Calibration needs at least 100 points and a range of at least 30° 2θ.')
    if not np.allclose(steps, np.median(steps), rtol=.002, atol=1e-7):
        raise ValueError('Calibration requires a uniform measured grid without missing intervals.')
    if np.max(y) <= 0. or np.ptp(y) <= max(1e-12, abs(float(np.max(y)))*1e-8):
        raise ValueError('No usable diffraction signal in the standard.')
    return values


def find_standard_peaks(data):
    values = validate_standard_data(data)
    x, y = values.T
    differences = np.diff(y)
    noise = 1.4826*np.median(abs(differences-np.median(differences)))/np.sqrt(2.)
    indices = find_peaks(y, prominence=max(5.*noise, np.ptp(y)*.015),
                        distance=max(1, int(.12/np.median(np.diff(x)))))[0]
    return values[indices].copy()


def _resolution(parameters, tangent_limit, sine_limit):
    # Bernstein quadratic: q0,q2>0 and q1 > -sqrt(q0*q2) make the
    # Gaussian variance positive throughout the full supported interval.
    # Parameterizing Lorentzian*cos(theta) by positive endpoint values
    # similarly allows negative Y without allowing negative physical widths.
    a, b, rho, left, right = parameters[:5]
    q0, q1, q2 = a*a, rho*a*b, b*b
    return ResolutionProfile.tch(u=(q0-2.*q1+q2)/tangent_limit**2,
        v=2.*(q1-q0)/tangent_limit, w=q0, x=left, y=(right-left)/sine_limit)


def _initial_parameters(profile, tangent_limit, sine_limit):
    r = profile.resolution
    if r.model == 'constant_fwhm':
        a = b = float(r.constant_fwhm_deg)
        return np.array([a, b, 1., .01, .01, 0.])
    native = cristma_tch_profile(r)
    gaussian_factor = (2.*np.sqrt(2.*np.log(2.))/100.)**2
    u, v, w = np.array([native.u, native.v, native.w])*gaussian_factor
    q0, q1 = w, w+v*tangent_limit/2.
    q2 = u*tangent_limit**2+v*tangent_limit+w
    if min(q0, q2) <= 0. or q1 <= -np.sqrt(q0*q2):
        return np.array([.12, .12, 1., .01, .01, 0.])
    left = native.x/100.
    right = (native.x+native.y*sine_limit)/100.
    return np.array([np.sqrt(q0), np.sqrt(q2), q1/np.sqrt(q0*q2),
                     max(left, .001), max(right, .001), 0.])


def calibrate_instrument(data, cif_path, profile, *, cancelled=lambda: False,
                         progress=lambda *_: None, timeout_seconds=60.) -> CalibrationResult:
    started = time.monotonic()

    def check():
        if cancelled():
            raise CancelledError('Calibration cancelled.')
        if time.monotonic()-started >= timeout_seconds:
            raise TimeoutError('Calibration time limit reached. No parameters were transferred.')

    check()
    values = validate_standard_data(data)
    x, y = values.T
    path = Path(cif_path)
    if not path.is_file():
        raise ValueError('Select an existing CIF of the calibration standard.')
    progress('Preparing CIF reflections…', 0, 0)
    check()
    adapter = CristmaPowderAdapter()
    lines = adapter.lines_from_cif(path, two_theta_min=.001,
        two_theta_max=min(135., float(x[-1])+5.), instrument_profile=profile,
        use_lp=profile.geometry.apply_lorentz_polarization)
    check()
    visible = [p for p in lines.peaks if x[0]+.5 <= p.two_theta <= x[-1]-.5]
    strongest = max((p.intensity for p in visible), default=0.)
    angles = sorted(p.two_theta for p in visible if p.intensity >= strongest*.02)
    separate = []
    for angle in angles:
        if not separate or angle-separate[-1] > .25:
            separate.append(angle)
    observed_peaks = find_standard_peaks(values)
    if len(separate) < 6 or np.ptp(separate) < 30. or len(observed_peaks) < 6:
        raise ValueError('Too few distinct standard peaks or too narrow angular coverage to determine five profile coefficients.')
    support = max(125., max(line.two_theta_deg for family in lines.intrinsic_lines.families for line in family.lines))
    tangent_limit = float(np.tan(np.radians(support/2.)))
    sine_limit = float(np.sin(np.radians(support/2.)))
    grid = UniformTwoThetaGrid(float(x[0]), float(x[-1]), float(np.median(np.diff(x))))
    calculator = PowderProfileCalculator()
    intensity_scale = float(np.max(abs(y)))
    target = y/intensity_scale
    t = (x-x[0])/np.ptp(x)
    background_basis = np.column_stack([(1.-t)**3, 3.*t*(1.-t)**2, 3.*t*t*(1.-t), t**3])
    weights = 1./np.sqrt(np.maximum(abs(target), .005))
    weighted_background = background_basis*weights[:, None]
    evaluations = 0

    def evaluate(parameters):
        nonlocal evaluations
        check()
        resolution = _resolution(parameters, tangent_limit, sine_limit)
        calculated = calculator.calculate(lines.profile_lines, grid,
            cristma_tch_profile(resolution), zero_shift_deg=float(parameters[5]))
        shape = np.asarray(calculated.intensity, dtype=float)
        native_x = np.asarray(calculated.two_theta_deg)
        if len(shape) != len(x) or not np.allclose(native_x, x, rtol=0., atol=1e-7):
            shape = np.interp(x, native_x, shape)
        peak_max = float(np.max(shape))
        if peak_max <= 0. or not np.isfinite(shape).all():
            raise ValueError('The CIF has no usable calculated profile in the measured range.')
        shape = shape/peak_max
        matrix = np.column_stack([shape, background_basis])
        coefficients = np.linalg.lstsq(matrix*weights[:, None], target*weights, rcond=None)[0]
        if coefficients[0] < 0.:
            coefficients[0] = 0.
            coefficients[1:] = np.linalg.lstsq(weighted_background, target*weights, rcond=None)[0]
        model = matrix@coefficients
        baseline = background_basis@coefficients[1:]
        evaluations += 1
        if evaluations == 1 or evaluations % 12 == 0:
            progress(f'Fitting instrument profile · {evaluations} evaluations', evaluations, 0)
        check()
        return (model-target)*weights, model, baseline

    initial = _initial_parameters(profile, tangent_limit, sine_limit)
    lower = np.array([.002, .002, -.999, 0., 0., -.5])
    upper = np.array([1.5, 3., 20., 1., 2., .5])
    initial = np.clip(initial, lower+1e-7, upper-1e-7)
    # Find a zero seed by cross-correlation, without moving the CIF cell.
    base_residual, initial_model, baseline = evaluate(initial)
    signal = target-np.percentile(target, 20.)
    reference = initial_model-baseline
    cc = correlate(signal, reference, mode='full', method='fft')
    lags = correlation_lags(len(signal), len(reference), mode='full')
    step = float(np.median(np.diff(x)))
    permitted = abs(lags*step) <= .5
    zero_seed = float(lags[permitted][np.argmax(cc[permitted])]*step)
    seeded = initial.copy(); seeded[5] = np.clip(zero_seed, -.4999, .4999)
    if np.linalg.norm(evaluate(seeded)[0]) < np.linalg.norm(base_residual):
        initial = seeded
    progress('Refining whole-pattern TCH profile…', evaluations, 0)
    # Extend only when the refined instrument model actually requires more
    # reflection wings. Reuse the native Finder coverage contract, not an
    # arbitrary angle margin or a second profile kernel.
    for expansion in range(4):
        upper[1] = max(3., float(initial[1])*2.)
        initial = np.clip(initial, lower+1e-7, upper-1e-7)
        scales = np.array([.1, max(.2, float(initial[1])), 1., .1, .1, .1])
        fit = least_squares(lambda parameters: evaluate(parameters)[0], initial,
            bounds=(lower, upper), x_scale=scales,
            max_nfev=220, ftol=1e-8, xtol=1e-8, gtol=1e-8)
        check()
        refined_profile = replace(profile, resolution=_resolution(fit.x, tangent_limit, sine_limit))
        extended = adapter._lines_with_profile_support(lines, x, refined_profile, float(fit.x[5]), 1., None)
        check()
        if extended.reflection_limit_deg <= lines.reflection_limit_deg+1e-8:
            break
        progress('Including boundary reflection wings…', evaluations, 0)
        lines = extended
        support = max(125., max(line.two_theta_deg for family in lines.intrinsic_lines.families for line in family.lines))
        tangent_limit = float(np.tan(np.radians(support/2.)))
        sine_limit = float(np.sin(np.radians(support/2.)))
        initial = _initial_parameters(refined_profile, tangent_limit, sine_limit)
        initial[5] = fit.x[5]
    else:
        raise ValueError('Reflection coverage did not stabilize. No calibration can be transferred.')
    residual, model, baseline = evaluate(fit.x)
    rwp = float(np.linalg.norm(residual)/max(np.linalg.norm(target*weights), 1e-15))
    rp = float(np.sum(abs(model-target))/max(np.sum(abs(target)), 1e-15))
    diagnostics = []
    if not fit.success:
        diagnostics.append('The optimizer did not converge.')
    if rwp > .20:
        diagnostics.append('Poor whole-pattern agreement. Check the standard CIF, radiation and unmodelled peaks.')
    peak_signal = target-baseline
    explained = 1.-float(np.sum((model-target)**2)/max(np.sum(peak_signal**2), 1e-15))
    if explained < .85:
        diagnostics.append('The calculated standard does not explain enough measured peak intensity.')
    singular = np.linalg.svd(fit.jac*scales, compute_uv=False)
    if singular[-1] <= singular[0]*1e-7:
        diagnostics.append('Profile coefficients are not independently determined by this standard.')
    if abs(float(fit.x[5])) > .495 or np.any(fit.active_mask[:5]):
        diagnostics.append('The fit reached a parameter limit; a reliable calibration was not established.')
    resolution = _resolution(fit.x, tangent_limit, sine_limit)
    check()
    arrays = [np.array(item, copy=True) for item in
              (x, y, model*intensity_scale, baseline*intensity_scale, (y-model*intensity_scale))]
    for array in arrays:
        array.setflags(write=False)
    return CalibrationResult(replace(profile, resolution=resolution), *arrays,
        rwp, rp, float(fit.x[5]), evaluations, time.monotonic()-started,
        not diagnostics, tuple(diagnostics), str(path.resolve()))


def calibrated_draft(profile, result, *, standard_name=''):
    if not result.transferable:
        raise ValueError('This calibration is not reliable enough to transfer. '+ ' '.join(result.diagnostics))
    standard = standard_name or Path(result.cif_path).stem
    metadata = (f'Instrumental-only whole-pattern calibration: {standard}; CIF: {Path(result.cif_path).name}; '
        f'range {result.x[0]:.3f}–{result.x[-1]:.3f}° 2θ; Rwp {100.*result.rwp:.2f}%; '
        f'Rp {100.*result.rp:.2f}%; fitted zero {result.zero_shift_deg:.3f}° (not included in widths). '
        'Coarse-grained standard; intrinsic size/strain broadening assumed negligible. Fixed CIF cell and relative intensities; no Le Bail.')
    return replace(profile, profile_id=f'instrument-{uuid4()}', resolution=result.profile.resolution,
        identity=replace(profile.identity, name=profile.identity.name+' (calibrated)',
            calibration_date=date.today().isoformat(),
            comment='\n'.join(part for part in (profile.identity.comment, metadata) if part)))
