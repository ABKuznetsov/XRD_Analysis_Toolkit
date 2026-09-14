from __future__ import annotations

from types import SimpleNamespace
import unittest

import numpy as np

from xrd_finder.ui.pattern_plot_helpers import peak_intensity_stick_arrays


class PeakIntensityStickTests(unittest.TestCase):
    def test_confirmed_stick_reaches_observed_trace_instead_of_preview_fraction(self) -> None:
        x = np.asarray([20.0, 21.0, 22.0])
        baseline = np.asarray([10.0, 10.0, 10.0])
        observed = np.asarray([12.0, 90.0, 11.0])
        peak = SimpleNamespace(two_theta=21.0, intensity=20.0)

        stick_x, stick_y = peak_intensity_stick_arrays(
            [peak],
            x,
            baseline,
            height=20.0,
            ceiling=observed,
            reach_ceiling=True,
        )

        self.assertEqual(stick_x[:2], [21.0, 21.0])
        self.assertEqual(stick_y[:2], [10.0, 90.0])


if __name__ == "__main__":
    unittest.main()
