from __future__ import annotations

import unittest

from xrd_finder.io.cif_powder_pattern import extract_cif_powder_peaks


class CifPowderPatternTests(unittest.TestCase):
    def test_reads_embedded_d_spacing_and_intensity_loop(self):
        text = """
data_test
_cell_measurement_wavelength 1.541874
loop_
_pd_peak_d_spacing
_pd_peak_intensity
5.555933 426.35
3.773646 1000.00
2.629797 0.11
"""

        peaks = extract_cif_powder_peaks(text, wavelength=1.54056, intensity_min=0.5)

        self.assertEqual(len(peaks), 2)
        self.assertAlmostEqual(peaks[0].two_theta, 15.938, delta=0.01)
        self.assertAlmostEqual(peaks[0].intensity, 42.635, delta=0.01)
        self.assertAlmostEqual(peaks[1].intensity, 100.0, delta=0.001)

    def test_converts_two_theta_loop_through_measurement_wavelength(self):
        text = """
data_test
_diffrn_radiation_wavelength 1.0000
loop_
_pd_peak_2theta
_pd_peak_intensity
20.0 50
30.0 100
"""

        peaks = extract_cif_powder_peaks(text, wavelength=1.54056, intensity_min=0.0)

        self.assertEqual(len(peaks), 2)
        self.assertGreater(peaks[0].two_theta, 20.0)
        self.assertAlmostEqual(peaks[1].intensity, 100.0)


if __name__ == "__main__":
    unittest.main()
