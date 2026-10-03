from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.instrument.models import InstrumentProfile, ResolutionProfile
from xrd_finder.ui.peak_matching import observed_peak_records


class ObservedLineMeasurementTests(unittest.TestCase):
    def test_detects_on_light_smoothing_but_measures_the_raw_corrected_peak(self):
        rng = np.random.default_rng(5036)
        x = np.arange(20.0, 30.0, 0.01)
        true_center = 25.137
        true_fwhm = 0.24
        sigma = true_fwhm / 2.354820045
        y = 180.0 * np.exp(-0.5 * ((x - true_center) / sigma) ** 2)
        y += rng.normal(0.0, 2.0, size=len(x))
        profile = InstrumentProfile(
            resolution=ResolutionProfile(constant_fwhm_deg=0.10),
        )

        records = observed_peak_records(x, y, limit=10, instrument_profile=profile)
        peak = min(records, key=lambda item: abs(item.two_theta - true_center))

        self.assertAlmostEqual(peak.two_theta, true_center, delta=0.025)
        self.assertAlmostEqual(peak.fwhm_observed, true_fwhm, delta=0.06)
        self.assertGreater(peak.area, 20.0)
        self.assertGreater(peak.prominence, 100.0)
        self.assertGreater(peak.area_positive, 0.0)
        self.assertGreater(peak.area_signed, 0.0)
        self.assertGreater(peak.area_snr, 3.0)
        self.assertGreater(peak.broadening_scale, 1.0)
        self.assertGreater(peak.profile_match, 0.45)
        self.assertGreater(peak.local_snr, 3.0)
        self.assertGreater(peak.confidence, 0.0)
        self.assertAlmostEqual(
            peak.fwhm_sample,
            np.sqrt(true_fwhm**2 - 0.10**2),
            delta=0.07,
        )

    def test_three_sigma_gate_uses_local_background_noise(self):
        rng = np.random.default_rng(1203)
        x = np.arange(10.0, 40.0, 0.01)
        y = np.empty_like(x)
        low_noise = x < 25.0
        y[low_noise] = rng.normal(0.0, 1.0, size=np.count_nonzero(low_noise))
        y[~low_noise] = rng.normal(0.0, 5.0, size=np.count_nonzero(~low_noise))
        y += 8.0 * np.exp(-0.5 * ((x - 20.0) / 0.06) ** 2)
        y += 8.0 * np.exp(-0.5 * ((x - 30.0) / 0.06) ** 2)

        records = observed_peak_records(x, y, limit=160, sigma_threshold=3.0)
        overlap_seeds = observed_peak_records(x, y, limit=160, sigma_threshold=2.0)

        self.assertTrue(any(abs(record.two_theta - 20.0) < 0.10 for record in records))
        self.assertFalse(any(abs(record.two_theta - 30.0) < 0.10 for record in records))
        self.assertTrue(any(abs(record.two_theta - 30.0) < 0.10 for record in overlap_seeds))
        detected = min(records, key=lambda record: abs(record.two_theta - 20.0))
        self.assertGreaterEqual(detected.local_snr, 3.0)
        self.assertGreater(detected.area_snr, 0.0)


if __name__ == "__main__":
    unittest.main()
