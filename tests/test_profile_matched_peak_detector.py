from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.finder.residual_peak_refinement import pseudo_voigt_unit_height
from xrd_finder.services.profile_matched_peak_detector import (
    profile_matched_peak_hypotheses,
)


class ProfileMatchedPeakDetectorTests(unittest.TestCase):
    def test_detects_narrow_and_broad_peaks_with_their_width_scales(self):
        rng = np.random.default_rng(12)
        x = np.linspace(10.0, 60.0, 5001)
        y = rng.normal(0.0, 0.45, len(x))
        y += 7.0 * pseudo_voigt_unit_height(x, 22.0, 0.12, 0.35)
        y += 5.0 * pseudo_voigt_unit_height(x, 43.0, 0.36, 0.35)

        peaks = profile_matched_peak_hypotheses(
            x,
            y,
            fwhm_at=lambda _position: 0.12,
            broadening_scales=(1.0, 2.0, 3.0),
            sigma_threshold=3.0,
        )

        narrow = min(peaks, key=lambda peak: abs(peak.position - 22.0))
        broad = min(peaks, key=lambda peak: abs(peak.position - 43.0))
        self.assertAlmostEqual(narrow.position, 22.0, delta=0.05)
        self.assertAlmostEqual(broad.position, 43.0, delta=0.08)
        self.assertLessEqual(narrow.broadening_scale, 2.0)
        self.assertGreaterEqual(broad.broadening_scale, 2.0)
        self.assertGreater(narrow.profile_match, 0.0)
        self.assertGreater(broad.local_snr, 3.0)
        self.assertGreater(narrow.prominence, 0.0)
        self.assertGreater(narrow.area_positive, 0.0)
        self.assertGreater(narrow.area_signed, 0.0)
        self.assertGreaterEqual(narrow.area_positive, narrow.area_signed)
        self.assertGreater(narrow.area_snr, 3.0)
        self.assertGreaterEqual(narrow.width_persistence, 2)
        self.assertGreaterEqual(broad.width_persistence, 2)
        self.assertGreater(narrow.delta_chi2, 0.0)
        self.assertIn(narrow.evidence_class, {"strong", "weak"})

    def test_peak_feature_vector_is_finite_and_compact(self):
        rng = np.random.default_rng(101)
        x = np.linspace(18.0, 24.0, 2401)
        y = rng.normal(0.0, 0.25, len(x))
        y += 5.5 * pseudo_voigt_unit_height(x, 21.0, 0.20, 0.35)

        peak = min(
            profile_matched_peak_hypotheses(
                x,
                y,
                fwhm_at=lambda _position: 0.10,
                broadening_scales=(1.0, 1.5, 2.0, 2.5),
                sigma_threshold=3.0,
            ),
            key=lambda item: abs(item.position - 21.0),
        )

        feature_vector = (
            peak.position,
            peak.amplitude,
            peak.effective_fwhm,
            peak.broadening_scale,
            peak.prominence,
            peak.area_positive,
            peak.area_signed,
            peak.area_snr,
            peak.profile_match,
            float(peak.width_persistence),
        )
        self.assertTrue(all(np.isfinite(value) for value in feature_vector))
        self.assertGreater(peak.confidence, 0.0)

    def test_uses_angle_dependent_instrument_width(self):
        rng = np.random.default_rng(19)
        x = np.linspace(10.0, 90.0, 8001)

        def fwhm_at(position):
            return 0.08 + 0.0015 * (position - 10.0)

        y = rng.normal(0.0, 0.40, len(x))
        y += 6.0 * pseudo_voigt_unit_height(x, 20.0, fwhm_at(20.0), 0.35)
        y += 6.0 * pseudo_voigt_unit_height(x, 80.0, fwhm_at(80.0), 0.35)

        peaks = profile_matched_peak_hypotheses(
            x,
            y,
            fwhm_at=fwhm_at,
            broadening_scales=(1.0, 1.5, 2.0),
            sigma_threshold=3.0,
        )

        low = min(peaks, key=lambda peak: abs(peak.position - 20.0))
        high = min(peaks, key=lambda peak: abs(peak.position - 80.0))
        self.assertAlmostEqual(low.position, 20.0, delta=0.05)
        self.assertAlmostEqual(high.position, 80.0, delta=0.08)
        self.assertGreater(high.effective_fwhm, low.effective_fwhm)

    def test_recovers_close_narrow_and_broad_features(self):
        rng = np.random.default_rng(7)
        x = np.linspace(25.0, 35.0, 4001)
        y = rng.normal(0.0, 0.32, len(x))
        y += 6.0 * pseudo_voigt_unit_height(x, 30.00, 0.10, 0.35)
        y += 4.5 * pseudo_voigt_unit_height(x, 30.34, 0.34, 0.35)

        peaks = profile_matched_peak_hypotheses(
            x,
            y,
            fwhm_at=lambda _position: 0.10,
            broadening_scales=(1.0, 1.5, 2.2, 3.4),
            sigma_threshold=3.0,
        )

        positions = [peak.position for peak in peaks]
        self.assertTrue(any(abs(position - 30.00) <= 0.05 for position in positions))
        self.assertTrue(any(abs(position - 30.34) <= 0.10 for position in positions))

    def test_noise_only_signal_does_not_manufacture_hypotheses(self):
        rng = np.random.default_rng(23)
        x = np.linspace(10.0, 60.0, 5001)
        y = rng.normal(0.0, 0.50, len(x))

        peaks = profile_matched_peak_hypotheses(
            x,
            y,
            fwhm_at=lambda _position: 0.12,
            broadening_scales=(1.0, 1.5, 2.0, 3.0),
            sigma_threshold=3.0,
        )

        self.assertEqual(peaks, ())

    def test_sloped_residual_background_is_not_a_broad_peak(self):
        rng = np.random.default_rng(41)
        x = np.linspace(10.0, 60.0, 5001)
        slope = 0.18 * (x - 35.0)
        y = slope + rng.normal(0.0, 0.45, len(x))

        empty = profile_matched_peak_hypotheses(
            x,
            y,
            fwhm_at=lambda _position: 0.12,
            broadening_scales=(1.0, 1.4, 2.0, 3.0, 4.0),
            sigma_threshold=3.0,
        )
        y += 5.0 * pseudo_voigt_unit_height(x, 38.0, 0.36, 0.35)
        detected = profile_matched_peak_hypotheses(
            x,
            y,
            fwhm_at=lambda _position: 0.12,
            broadening_scales=(1.0, 1.4, 2.0, 3.0, 4.0),
            sigma_threshold=3.0,
        )

        self.assertEqual(empty, ())
        self.assertTrue(any(abs(peak.position - 38.0) <= 0.08 for peak in detected))


if __name__ == "__main__":
    unittest.main()
