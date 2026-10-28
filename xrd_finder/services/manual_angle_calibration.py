"""Reversible, absolute manual correction of a measured pattern's angular grid."""
import math

import numpy as np

from xrd_finder.services.preprocessing_history import capture_processing, remember_processing, reset_processing


def shifted_angle_data(data, delta):
    values = np.array(data, dtype=float, copy=True)
    if values.ndim != 2 or values.shape[1] < 2:
        raise ValueError('A measured two-column XRD pattern is required.')
    values[:, 0] -= float(delta)
    return values


def apply_manual_angle_calibration(pattern, observed_data, correction_deg: float) -> bool:
    """Apply an absolute total correction, not an additional shift on each call."""
    if getattr(pattern, 'input_kind', '') == 'peak_list':
        raise ValueError('Edit manual peak positions in the manual peak editor.')
    correction = float(correction_deg)
    old = float(getattr(pattern, 'angle_calibration_deg', 0.))
    if not math.isfinite(correction) or not math.isfinite(old):
        raise ValueError('Angle correction must be finite.')
    delta = correction-old
    shifted = shifted_angle_data(observed_data, delta)
    if np.count_nonzero(np.isfinite(shifted[:, 0]) & np.isfinite(shifted[:, 1])) < 2:
        raise ValueError('At least two measured XRD points are required.')
    if abs(delta) < 1.e-12:
        return False
    # Validate/prepare every dependent array before modifying the pattern.
    backgrounds = {name: shifted_angle_data(getattr(pattern, name), delta).tolist()
        for name in ('estimated_background_points', 'estimated_background_with_halo_points')
        if getattr(pattern, name)}
    crops = [[float(a)-delta, float(b)-delta] for a,b in pattern.crop_ranges]
    remember_processing(pattern, 'calibration', capture_processing(pattern))
    pattern.processed_points = shifted[:, :2].tolist()
    for name, values in backgrounds.items():
        setattr(pattern, name, values)
    pattern.crop_ranges = crops
    pattern.angle_calibration_deg = correction
    return True


def reset_manual_angle_calibration(pattern) -> bool:
    # The generic reset has a legacy "restore raw" fallback. A calibration
    # reset must not invoke it for an uncalibrated but smoothed old project.
    if not any(step.get('kind') == 'calibration' for step in pattern.preprocessing_history):
        return False
    return reset_processing(pattern, 'calibration')
