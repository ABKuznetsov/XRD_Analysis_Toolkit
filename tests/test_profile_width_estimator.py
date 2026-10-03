from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from xrd_finder.finder.profile_width_estimator import estimate_phase_fwhm_from_signal


def gaussian(x: np.ndarray, center: float, fwhm: float, height: float) -> np.ndarray:
    sigma = fwhm / 2.354820045
    return height * np.exp(-0.5 * ((x - center) / sigma) ** 2)


class ProfileWidthEstimatorTests(unittest.TestCase):
    def test_overlapping_reference_cluster_does_not_set_global_phase_width(self):
        x = np.linspace(18.0, 33.0, 7501)
        y = (
            gaussian(x, 20.0, 0.16, 500.0)
            + gaussian(x, 24.0, 0.18, 400.0)
            + gaussian(x, 30.0, 0.42, 1200.0)
        )
        peaks = [
            SimpleNamespace(two_theta=20.0, intensity=45.0),
            SimpleNamespace(two_theta=24.0, intensity=35.0),
            SimpleNamespace(two_theta=29.92, intensity=100.0),
            SimpleNamespace(two_theta=30.08, intensity=90.0),
        ]

        width = estimate_phase_fwhm_from_signal(peaks, x, y, base_fwhm=0.15)

        self.assertGreater(width, 0.14)
        self.assertLess(width, 0.22)


if __name__ == "__main__":
    unittest.main()
