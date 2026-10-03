from __future__ import annotations

import unittest

from benchmarks.match.parameter_sensitivity import default_parameter_settings


class ParameterSensitivityTests(unittest.TestCase):
    def test_default_settings_cover_each_requested_parameter_around_baseline(self):
        settings = default_parameter_settings()

        self.assertEqual({item.distance_scale for item in settings if item.dimension == "peak_distance"}, {0.5, 1.0, 1.5, 2.0})
        self.assertEqual({item.max_observed_lines for item in settings if item.dimension == "observed_lines"}, {10, 20, 32, 48})
        self.assertEqual({item.max_reference_lines for item in settings if item.dimension == "reference_lines"}, {16, 32, 48, 64})
        self.assertEqual({item.line_tolerance for item in settings if item.dimension == "position_tolerance"}, {0.25, 0.40, 0.55, 0.75})


if __name__ == "__main__":
    unittest.main()
