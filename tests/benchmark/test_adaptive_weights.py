from __future__ import annotations

import unittest

from benchmarks.match.adaptive_weights import optimize_weights_by_stratum
from benchmarks.match.extract_features import FeatureMatrix, FeatureRow
from benchmarks.match.optimize_weights import WeightSearchConfig
from xrd_finder.finder.fingerprint_matching import FingerprintMatchFeatures


def _features(observed: float, reference: float) -> FingerprintMatchFeatures:
    return FingerprintMatchFeatures(observed, reference, 0.5, 0.5, 8, 8, 10)


class AdaptiveWeightTests(unittest.TestCase):
    def test_fits_each_noise_group_without_using_other_groups(self):
        rows = []
        for split in ("train", "validation", "test"):
            for noise, true_values, false_values in (
                ("none", (0.95, 0.30), (0.40, 0.90)),
                ("high", (0.30, 0.95), (0.90, 0.40)),
            ):
                stratum = f"phases=1;fwhm=0.15;noise={noise};overlap=ordinary"
                query = f"{split}-{noise}"
                rows.extend(
                    (
                        FeatureRow(query, "true", "true", "true", ("true",), split, stratum, _features(*true_values)),
                        FeatureRow(query, "false", "false", "true", ("true",), split, stratum, _features(*false_values)),
                    )
                )

        results = optimize_weights_by_stratum(
            FeatureMatrix(tuple(rows)),
            dimensions=("noise",),
            config=WeightSearchConfig(0.25, 0.05, 0.10),
        )

        by_value = {item.value: item for item in results}
        self.assertGreater(by_value["none"].weights.observed_coverage, by_value["none"].weights.reference_coverage)
        self.assertGreater(by_value["high"].weights.reference_coverage, by_value["high"].weights.observed_coverage)
        self.assertEqual(by_value["none"].test_metrics.top1, 1.0)
        self.assertEqual(by_value["high"].test_metrics.top1, 1.0)


if __name__ == "__main__":
    unittest.main()
