"""Read-only local peak measurements and existing accepted assignments."""
from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import find_peaks, peak_widths

from xrd_finder.finder.residual_peak_refinement import RefinedResidualPeak, refine_residual_peak


@dataclass(frozen=True, slots=True)
class PeakCharacterization:
    seed: float
    maximum_position: float
    maximum_intensity: float
    wavelength: float
    d_spacing: float | None
    fit: RefinedResidualPeak | None
    x: np.ndarray
    y: np.ndarray
    model: np.ndarray
    background: np.ndarray
    status: str
    warnings: tuple[str, ...] = ()


def _noise_sigma(y):
    differences = np.diff(y)
    if not len(differences):
        return 0.
    return float(1.4826 * np.median(abs(differences-np.median(differences))) / np.sqrt(2.))


def characterize_peak(x, y, seed, *, wavelength, instrument_fwhm=0., satellite_offsets_weights=()):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 1 or x.shape != y.shape:
        raise ValueError('Peak data must be equal one-dimensional arrays.')
    valid = np.isfinite(x) & np.isfinite(y)
    xx, inverse = np.unique(x[valid], return_inverse=True)
    yy = np.bincount(inverse, weights=y[valid]) / np.maximum(np.bincount(inverse), 1)
    if len(xx) < 3 or not math.isfinite(seed) or not xx[0] <= seed <= xx[-1]:
        raise ValueError('Not enough measured data around the selected peak.')
    step = float(np.median(np.diff(xx)))
    index = int(np.argmin(abs(xx-seed)))
    # Cropped intervals and missing observations must not become an invented
    # continuous profile. Keep the connected segment containing the pick.
    gaps = np.flatnonzero(np.diff(xx) > 4.*step)
    left = max((int(g)+1 for g in gaps if g < index), default=0)
    right = min((int(g)+1 for g in gaps if g >= index), default=len(xx))
    xx, yy = xx[left:right], yy[left:right]
    index = int(np.argmin(abs(xx-seed)))
    maxima = find_peaks(yy)[0]
    expected = max(float(instrument_fwhm), .12, step*3.)
    can_fit = bool(len(maxima))
    if can_fit:
        maximum = int(maxima[np.argmin(abs(xx[maxima]-seed))])
        can_fit = abs(xx[maximum]-seed) <= max(step*2., .06)
        if can_fit:
            _width, _level, lpos, rpos = peak_widths(yy, [maximum], rel_height=.5)
            measured = float(np.interp(rpos[0], np.arange(len(xx)), xx)-np.interp(lpos[0], np.arange(len(xx)), xx))
            if measured > 0.:
                expected = measured
            index = maximum
    expected = float(np.clip(expected, max(step*2., .025), 1.2))
    radius = float(np.clip(expected*4., .32, 1.6))
    local = abs(xx-seed) <= radius
    local_x, local_y = xx[local].copy(), yy[local].copy()
    warnings = []
    if not len(local_x):
        raise ValueError('No measured points in the selected peak window.')
    if local_x[0] > seed-radius+step or local_x[-1] < seed+radius-step:
        warnings.append('Peak window is truncated by the data range or a gap; width and area may be unreliable.')
    fitted = None
    if can_fit:
        fitted = refine_residual_peak(xx, yy, seed, expected_fwhm=expected,
            instrument_fwhm=instrument_fwhm, satellite_offsets_weights=satellite_offsets_weights,
            constrain_center=True, enforce_instrument_floor=False, peak_only_quality=True, return_curve=True)
    fit = None
    model = background = np.asarray([], dtype=float)
    status = 'No reliable local peak measurement'
    if fitted is not None:
        trial, fit_x, fit_y, base = fitted
        sigma = _noise_sigma(local_y)
        if trial.height > max(5.*sigma, 1e-10) and trial.fit_quality >= .05:
            fit, local_x = trial, fit_x
            local_y = np.interp(local_x, xx, yy)
            model, background = fit_y, base
            residual = local_y-model
            structure = find_peaks(abs(residual), prominence=max(5.*sigma, trial.height*.1))[0]
            status = ('Single-component model adequately describes this local profile'
                if trial.fit_quality >= .9 and not len(structure)
                else 'Single-component model does not fully describe this local profile')
    position = float(fit.two_theta) if fit is not None else float(xx[index])
    angle = math.radians(position/2.)
    d = float(wavelength)/(2.*math.sin(angle)) if 0. < position < 180. and wavelength > 0. else None
    return PeakCharacterization(float(seed), float(xx[index]), float(yy[index]), float(wavelength),
        d, fit, local_x, local_y, model, background, status, tuple(warnings))


def assignments_near_peak(observed_peaks, seed, grid_step):
    peaks = [p for p in observed_peaks if math.isfinite(float(p.two_theta))]
    if not peaks:
        return []
    peak = min(peaks, key=lambda p: abs(p.two_theta-seed))
    tolerance = max(2.*float(grid_step), min(.15, max(.03, float(peak.fwhm)*.5)))
    if abs(peak.two_theta-seed) > tolerance:
        return []
    return list(peak.assignments)
