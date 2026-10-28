"""Find search marks on measured maxima using the existing peak detector."""
from concurrent.futures import CancelledError

import numpy as np
from scipy.signal import find_peaks

from xrd_finder.services.observed_search_preparation import (
    ObservedSearchCancelled, ObservedSearchInput, prepare_observed_search,
)


def detect_search_peak_positions(inputs: ObservedSearchInput, *, cancelled=lambda: False) -> np.ndarray:
    def check():
        if cancelled():
            raise CancelledError('Peak detection cancelled')

    check()
    data = inputs.observed
    if data.ndim != 2 or data.shape[1] != 2:
        raise ValueError('Peak detection needs a two-column XRD pattern.')
    x, y = data[:, 0], data[:, 1]
    valid = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    if len(valid) < 5:
        return np.asarray([], dtype=float)
    differences = np.diff(x[valid])
    if np.any(differences <= 0.):
        raise ValueError('Measured 2theta values must increase within the displayed pattern.')
    step = float(np.median(differences))
    # NaNs and large gaps separate crop intervals. Never fit a baseline or
    # create peak evidence across missing measured data.
    cuts = np.flatnonzero((np.diff(valid) > 1) | (differences > 4.*step))+1
    segments = np.split(valid, cuts)
    scale = float(np.max(np.abs(y[valid])))
    if scale <= 0.:
        return np.asarray([], dtype=float)
    strengths = {}
    for indices in segments:
        check()
        if len(indices) < 5:
            continue
        xx, yy = x[indices], y[indices]
        segment = ObservedSearchInput(
            np.column_stack([xx, yy*(100./scale)]), inputs.preprocess_auto,
            inputs.background_removed, inputs.instrument_profile,
            global_zero_shift=inputs.global_zero_shift,
        )
        try:
            detected = prepare_observed_search(segment, cancelled=cancelled, refine_peaks=False)
        except ObservedSearchCancelled as exc:
            raise CancelledError('Peak detection cancelled') from exc
        check()
        maxima = find_peaks(yy)[0]
        if not len(maxima):
            continue
        snap_radius = max(2.*float(np.median(np.diff(xx))), .06)
        for record in detected.records:
            check()
            index = int(maxima[np.argmin(np.abs(xx[maxima]-record.two_theta))])
            if abs(float(xx[index])-record.two_theta) > snap_radius:
                continue
            position = float(xx[index])
            strengths[position] = max(strengths.get(position, 0.), float(record.height))
    # Use the detector's existing 80-peak budget for the complete pattern,
    # including multiple crop intervals. Repeated calls produce the same set.
    strongest = sorted(strengths, key=lambda position: (-strengths[position], position))[:80]
    return np.asarray(sorted(strongest), dtype=float)
