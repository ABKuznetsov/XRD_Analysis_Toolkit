from __future__ import annotations

import unittest

from benchmarks.match.evaluate import compare_weight_sets, compare_weight_sets_by_stratum
from benchmarks.match.extract_features import FeatureMatrix, FeatureRow
from xrd_finder.finder.fingerprint_matching import FingerprintMatchFeatures, MatchWeights


class SensitivityTests(unittest.TestCase):
    def test_comparison_contains_all_fixed_baselines_and_selected_weights(self):
        rows = (
            FeatureRow(
                "q", "true", "f1", "f1", ("f1",), "test", "clean",
                FingerprintMatchFeatures(0.9, 0.8, 1.0, 1.0, 8, 8, 10),
            ),
            FeatureRow(
                "q", "false", "f2", "f1", ("f1",), "test", "clean",
                FingerprintMatchFeatures(0.4, 0.5, 0.5, 0.5, 6, 6, 10),
            ),
        )

        comparison = compare_weight_sets(FeatureMatrix(rows), MatchWeights(0.5, 0.4, 0.05, 0.05))

        self.assertEqual(set(comparison), {"manuscript", "current", "equal", "selected"})
        self.assertTrue(all(item.top1 == 1.0 for item in comparison.values()))

    def test_breaks_metrics_out_by_noise_and_fwhm(self):
        rows = (
            FeatureRow(
                "q1", "true", "f1", "f1", ("f1",), "test",
                "phases=1;fwhm=0.08;noise=none;overlap=ordinary",
                FingerprintMatchFeatures(0.9, 0.8, 1.0, 1.0, 8, 8, 10),
            ),
            FeatureRow(
                "q2", "true", "f1", "f1", ("f1",), "test",
                "phases=1;fwhm=0.50;noise=high;overlap=ordinary",
                FingerprintMatchFeatures(0.7, 0.6, 1.0, 1.0, 8, 8, 10),
            ),
        )

        rows_by_stratum = compare_weight_sets_by_stratum(
            FeatureMatrix(rows), MatchWeights(0.5, 0.4, 0.05, 0.05)
        )

        self.assertIn(("noise", "none", "current"), rows_by_stratum)
        self.assertIn(("noise", "high", "current"), rows_by_stratum)
        self.assertIn(("fwhm", "0.08", "manuscript"), rows_by_stratum)


if __name__ == "__main__":
    unittest.main()
