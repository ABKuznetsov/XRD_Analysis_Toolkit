from __future__ import annotations

import unittest

from benchmarks.match.extract_features import FeatureMatrix, FeatureRow
from benchmarks.match.optimize_weights import WeightSearchConfig, optimize_weights
from xrd_finder.finder.fingerprint_matching import FingerprintMatchFeatures


def _features(observed: float, reference: float) -> FingerprintMatchFeatures:
    return FingerprintMatchFeatures(observed, reference, 0.5, 0.5, 8, 8, 10)


class WeightSearchTests(unittest.TestCase):
    def test_selects_observed_coverage_when_it_generalizes(self):
        rows = []
        for split in ("train", "validation"):
            for index in range(3):
                query = f"{split}-{index}"
                rows.extend(
                    (
                        FeatureRow(query, "true", "true-family", "true-family", ("true-family",), split, "mixed", _features(0.95, 0.30)),
                        FeatureRow(query, "false", "false-family", "true-family", ("true-family",), split, "mixed", _features(0.40, 0.95)),
                    )
                )
        selection = optimize_weights(
            FeatureMatrix(tuple(rows)),
            WeightSearchConfig(coarse_step=0.25, refinement_step=0.05, refinement_radius=0.10),
        )

        self.assertGreater(selection.weights.observed_coverage, selection.weights.reference_coverage)
        self.assertAlmostEqual(sum(selection.weights.as_tuple()), 1.0)
        self.assertEqual(selection.validation_metrics.top1, 1.0)

    def test_rejects_test_rows_during_optimization(self):
        row = FeatureRow(
            "test-query", "candidate", "family", "family", ("family",), "test", "clean", _features(1.0, 1.0)
        )

        with self.assertRaises(ValueError):
            optimize_weights(FeatureMatrix((row,)), WeightSearchConfig(coarse_step=0.5, refinement_step=0.1))


if __name__ == "__main__":
    unittest.main()
