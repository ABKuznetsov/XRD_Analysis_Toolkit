from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.finder.gain_evidence import phase_signal_to_noise


class PhaseSignalToNoiseTests(unittest.TestCase):
    def test_three_supported_phase_lines_are_stronger_than_one_accidental_line(self):
        rng = np.random.default_rng(17)
        x = np.linspace(10.0, 50.0, 4001)
        residual_after = rng.normal(0.0, 1.0, size=len(x))

        def peak(position: float, height: float) -> np.ndarray:
            return height * np.exp(-0.5 * ((x - position) / 0.08) ** 2)

        three_line_curve = peak(20.0, 12.0) + peak(30.0, 11.0) + peak(40.0, 10.0)
        one_line_curve = peak(20.0, 12.0)

        three_line_snr = phase_signal_to_noise(
            x=x,
            residual_after=residual_after,
            candidate_curve=three_line_curve,
            peak_positions=np.asarray([20.0, 30.0, 40.0]),
            peak_amplitudes=np.asarray([100.0, 80.0, 60.0]),
            fwhm=0.19,
        )
        one_line_snr = phase_signal_to_noise(
            x=x,
            residual_after=residual_after,
            candidate_curve=one_line_curve,
            peak_positions=np.asarray([20.0]),
            peak_amplitudes=np.asarray([100.0]),
            fwhm=0.19,
        )

        self.assertGreater(three_line_snr, 7.0)
        self.assertGreater(three_line_snr, one_line_snr)

    def test_weak_candidate_profile_stays_below_detection_level(self):
        rng = np.random.default_rng(23)
        x = np.linspace(10.0, 50.0, 4001)
        residual_after = rng.normal(0.0, 1.0, size=len(x))
        curve = 1.2 * np.exp(-0.5 * ((x - 25.0) / 0.08) ** 2)

        value = phase_signal_to_noise(
            x=x,
            residual_after=residual_after,
            candidate_curve=curve,
            peak_positions=np.asarray([25.0]),
            peak_amplitudes=np.asarray([100.0]),
            fwhm=0.19,
        )

        self.assertLess(value, 3.0)


if __name__ == "__main__":
    unittest.main()
