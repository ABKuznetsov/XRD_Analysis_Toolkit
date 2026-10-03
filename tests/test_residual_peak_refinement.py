from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.finder.residual_peak_refinement import (
    pseudo_voigt_unit_height,
    pseudo_voigt_radiation_profile,
    refine_residual_peak,
)


class ResidualPeakRefinementTests(unittest.TestCase):
    def test_refines_peak_on_unsmoothed_signed_residual_with_sloped_baseline(self):
        rng = np.random.default_rng(5036)
        x = np.arange(24.0, 27.0, 0.01)
        center = 25.317
        fwhm = 0.28
        amplitude = 140.0
        eta = 0.35
        baseline = -8.0 + 2.5 * (x - center)
        y = baseline + amplitude * pseudo_voigt_unit_height(x, center, fwhm, eta)
        y += rng.normal(0.0, 2.0, size=len(x))

        result = refine_residual_peak(
            x,
            y,
            25.29,
            expected_fwhm=0.22,
            instrument_fwhm=0.10,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result.two_theta, center, delta=0.025)
        self.assertAlmostEqual(result.fwhm_observed, fwhm, delta=0.05)
        self.assertAlmostEqual(result.fwhm_sample, np.sqrt(fwhm**2 - 0.10**2), delta=0.06)
        self.assertGreater(result.area, 35.0)
        self.assertGreater(result.fit_quality, 0.85)
        self.assertLess(result.asymmetry, 0.20)

    def test_instrument_limited_peak_has_no_inferred_sample_width(self):
        x = np.arange(30.0, 32.0, 0.005)
        y = 90.0 * pseudo_voigt_unit_height(x, 31.0, 0.105, 0.25)

        result = refine_residual_peak(
            x,
            y,
            31.01,
            expected_fwhm=0.11,
            instrument_fwhm=0.10,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.instrument_limited)
        self.assertIsNone(result.fwhm_sample)

    def test_broad_peak_retains_positive_sample_width(self):
        x = np.arange(40.0, 43.0, 0.01)
        y = 75.0 * pseudo_voigt_unit_height(x, 41.4, 0.42, 0.65)

        result = refine_residual_peak(
            x,
            y,
            41.4,
            expected_fwhm=0.25,
            instrument_fwhm=0.12,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result.instrument_limited)
        self.assertIsNotNone(result.fwhm_sample)
        self.assertGreater(float(result.fwhm_sample), 0.30)

    def test_resolves_component_width_in_an_unresolved_kalpha_doublet(self):
        x = np.arange(48.0, 52.0, 0.005)
        y = 100.0 * pseudo_voigt_radiation_profile(
            x,
            50.0,
            0.12,
            0.30,
            ((0.16, 0.50),),
        )

        result = refine_residual_peak(
            x,
            y,
            50.02,
            expected_fwhm=0.16,
            instrument_fwhm=0.08,
            satellite_offsets_weights=((0.16, 0.50),),
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertAlmostEqual(result.two_theta, 50.0, delta=0.02)
        self.assertAlmostEqual(result.fwhm_observed, 0.12, delta=0.025)


if __name__ == "__main__":
    unittest.main()
