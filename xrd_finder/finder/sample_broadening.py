"""Bounded phase-local effective width, with fixed instrument and line centers."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import minimize_scalar, nnls

from xrd_finder.services.calculated_pattern_service import PROFILE_WINDOW_FACTOR

MAX_WIDTH_EVALUATIONS = 16


@dataclass(frozen=True, slots=True)
class SampleBroadeningFit:
    status: str
    sample_fwhm_deg: float | None = None
    line_count: int = 0
    error_before: float | None = None
    error_after: float | None = None
    evaluations: int = 0
    message: str = ""

    @property
    def available(self):
        return self.status in {"effective_gaussian", "budget_limited", "instrument_limited"}


def broaden_profile(x, profile, sample_fwhm_deg):
    """Convolve a cached instrument profile; widths are degrees of 2theta.

    This effective Gaussian width is not a crystallite size or microstrain.
    The normalized kernel preserves integrated intensity away from boundaries.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(profile, dtype=float)
    width = float(sample_fwhm_deg)
    if (x.ndim != 1 or y.shape != x.shape or len(x) < 2
            or not np.all(np.isfinite(x)) or np.any(np.diff(x) <= 0)
            or not np.all(np.isfinite(y)) or not math.isfinite(width) or width < 0):
        raise ValueError("Broadening requires finite ordered data and a nonnegative width")
    if width == 0:
        return y.copy()
    grid = np.linspace(x[0], x[-1], len(x))
    sigma = width/(2*math.sqrt(2*math.log(2)))/(grid[1]-grid[0])
    filtered = gaussian_filter1d(np.interp(grid, x, y), sigma, mode="constant", cval=0.)
    return np.interp(x, grid, filtered)


def fit_sample_broadening(*, x, target, phase_positions, observed_peaks,
                          other_phase_positions, profile_factory) -> SampleBroadeningFit:
    """Fit one effective width on isolated matched reflection windows.

    Local nonnegative amplitude and background separate width information from
    texture/relative-intensity errors. Unmatched maxima are never new anchors.
    The instrument stays fixed; the scalar search has a strict evaluation budget.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(target, dtype=float)
    if (x.ndim != 1 or y.shape != x.shape or len(x) < 5
            or not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))
            or np.any(np.diff(x) <= 0)):
        raise ValueError("Broadening fit requires finite ordered data")
    positions = np.unique(np.asarray(phase_positions, dtype=float))
    positions = positions[np.isfinite(positions)]
    others = np.asarray(other_phase_positions, dtype=float)
    others = others[np.isfinite(others)]
    records = sorted((r for r in observed_peaks if
                      np.isfinite(r.two_theta) and np.isfinite(r.fwhm) and r.fwhm > 0),
                     key=lambda r: r.two_theta)
    windows = []
    widths = []
    step = float(np.median(np.diff(x)))
    used = set()
    for index, record in enumerate(records):
        if not len(positions):
            break
        nearest = int(np.argmin(np.abs(positions-record.two_theta)))
        center = float(positions[nearest])
        width = float(record.fwhm)
        if nearest in used or abs(center-record.two_theta) > width:
            continue
        # A neighbouring observed maximum or another phase cannot be a width
        # anchor. Five FWHM is the existing profile integration window.
        radius = PROFILE_WINDOW_FACTOR*width
        if index:
            radius = min(radius, (center-records[index-1].two_theta)/2)
        if index+1 < len(records):
            radius = min(radius, (records[index+1].two_theta-center)/2)
        if len(others):
            radius = min(radius, float(np.min(np.abs(others-center)))/2)
        if radius <= width:
            continue
        mask = np.flatnonzero((x >= center-radius) & (x <= center+radius))
        if len(mask) < 5:
            continue
        used.add(nearest)
        windows.append(mask)
        widths.append(width)
    count = len(windows)
    if not count:
        return SampleBroadeningFit("insufficient_lines", line_count=count,
                                   message="No isolated matched reflection window")
    # The added width cannot exceed the measured total width of its anchors.
    upper = float(min(widths))
    evaluations = 0

    def error(width):
        nonlocal evaluations
        evaluations += 1
        profile = np.asarray(profile_factory(width), dtype=float)
        if profile.shape != x.shape or not np.all(np.isfinite(profile)) or np.any(profile < 0):
            raise ValueError("Effective sample profile is invalid")
        total = 0.
        for mask in windows:
            local_y = y[mask]
            height = float(np.max(np.abs(local_y))) or 1.
            shape = profile[mask]
            shape = shape/(float(np.max(shape)) or 1.)
            model = np.column_stack((shape, np.ones(len(mask))))
            amplitudes, _ = nnls(model, local_y/height)
            residual = model@amplitudes-local_y/height
            total += float(np.dot(residual, residual))*step
        return total

    before = error(0.)
    fit = minimize_scalar(error, bounds=(0., upper), method="bounded",
                          options={"maxiter": MAX_WIDTH_EVALUATIONS, "xatol": step/10})
    if not math.isfinite(fit.x) or not math.isfinite(fit.fun):
        return SampleBroadeningFit("fit_failed", line_count=count, error_before=before,
                                   evaluations=evaluations, message=str(fit.message))
    after = float(fit.fun)
    if after >= before:
        return SampleBroadeningFit("instrument_limited", 0., count, before, before,
                                   evaluations, "No improvement over the fixed instrument profile")
    return SampleBroadeningFit(
        "effective_gaussian" if fit.success else "budget_limited",
        float(fit.x), count, before, after, evaluations,
        "Effective Gaussian FWHM in degrees 2theta; not a size/strain determination")
