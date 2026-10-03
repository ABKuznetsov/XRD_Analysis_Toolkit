from __future__ import annotations

from dataclasses import dataclass
import unittest

import numpy as np

from xrd_finder.finder.phase_width_model import (
    fit_phase_width_model,
    width_difference_corroboration,
)


@dataclass
class Record:
    two_theta: float
    fwhm_sample: float | None
    instrument_limited: bool = False
    fit_quality: float = 0.9
    asymmetry: float = 0.05


class PhaseWidthModelTests(unittest.TestCase):
    def test_uses_robust_median_when_few_lines_are_available(self):
        model = fit_phase_width_model(
            [Record(20.0, 0.18), Record(35.0, 0.20), Record(50.0, 0.19)]
        )

        self.assertIsNotNone(model)
        assert model is not None
        self.assertFalse(model.uses_angle_dependence)
        self.assertAlmostEqual(model.predict_sample_fwhm(70.0), 0.19, delta=0.02)

    def test_fits_angle_dependent_width_and_ignores_unreliable_lines(self):
        positions = np.asarray([15.0, 28.0, 42.0, 58.0, 75.0, 92.0])
        theta = np.deg2rad(positions * 0.5)
        widths = (0.11 + 0.075 * np.sin(theta)) / np.cos(theta)
        records = [Record(float(position), float(width)) for position, width in zip(positions, widths)]
        records.extend(
            [
                Record(33.0, None, instrument_limited=True),
                Record(63.0, 0.90, fit_quality=0.1),
                Record(67.0, 0.80, asymmetry=0.8),
            ]
        )

        model = fit_phase_width_model(records)

        self.assertIsNotNone(model)
        assert model is not None
        self.assertTrue(model.uses_angle_dependence)
        expected = (0.11 + 0.075 * np.sin(np.deg2rad(35.0))) / np.cos(np.deg2rad(35.0))
        self.assertAlmostEqual(model.predict_sample_fwhm(70.0), expected, delta=0.025)

    def test_width_difference_is_only_soft_corroboration(self):
        self.assertEqual(width_difference_corroboration(0.20, 0.19, 0.02), 0.0)
        self.assertGreater(width_difference_corroboration(0.42, 0.18, 0.02), 0.5)
        self.assertLessEqual(width_difference_corroboration(0.42, 0.18, 0.02), 1.0)


if __name__ == "__main__":
    unittest.main()
