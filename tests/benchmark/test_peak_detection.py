from __future__ import annotations

import math
import unittest

from benchmarks.match.evaluate_peak_detection import run_peak_detection_benchmark


class PeakDetectionBenchmarkTests(unittest.TestCase):
    def test_reports_finite_recall_precision_and_latency(self):
        result = run_peak_detection_benchmark(cases=3, seed=5036)

        self.assertEqual(result.cases, 3)
        self.assertGreater(result.true_peaks, 0)
        for value in (
            result.legacy_recall,
            result.matched_recall,
            result.legacy_precision,
            result.matched_precision,
        ):
            self.assertTrue(math.isfinite(value))
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)
        self.assertGreaterEqual(result.legacy_median_seconds, 0.0)
        self.assertGreaterEqual(result.matched_median_seconds, 0.0)
        self.assertEqual(len(result.rescue_features), result.matched_unique_rescues)
        for rescue in result.rescue_features:
            for value in (
                rescue.prominence,
                rescue.local_snr,
                rescue.area_snr,
                rescue.width_ratio,
                rescue.profile_match,
                rescue.curvature,
                rescue.centroid_offset,
            ):
                self.assertTrue(math.isfinite(value))


if __name__ == "__main__":
    unittest.main()
