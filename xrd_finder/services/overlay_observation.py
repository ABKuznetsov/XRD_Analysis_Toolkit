from __future__ import annotations

import numpy as np

from xrd_finder.services.preprocessing_service import estimate_background
from xrd_finder.ui.peak_matching import observed_peak_positions
from xrd_finder.ui.pattern_plot_helpers import estimate_profile_fwhm


class OverlayObservationCancelled(RuntimeError):
    pass


def prepare_overlay_observation(
    observed, *, background_estimator=None, peak_detector=None, width_estimator=None,
    cancelled=lambda: False,
):
    """Prepare phase-independent arrays using the existing preview estimators."""
    def check_cancelled():
        if cancelled():
            raise OverlayObservationCancelled()

    def owned(values):
        values = np.asarray(values, dtype=float)
        return np.frombuffer(values.tobytes(), dtype=float).reshape(values.shape)

    check_cancelled()
    data = owned(observed)
    x, y = data[:, 0], data[:, 1]
    minimum, maximum = float(np.nanmin(y)), float(np.nanmax(y))
    background = (background_estimator or estimate_background)(x, y)
    check_cancelled()
    corrected = np.clip(y - background, 0.0, None)
    positions = (peak_detector or observed_peak_positions)(x, corrected)
    check_cancelled()
    width = (width_estimator or estimate_profile_fwhm)(x, corrected)
    check_cancelled()
    return x, minimum, maximum, owned(background), owned(positions), width
