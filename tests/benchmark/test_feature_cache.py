from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from benchmarks.match.extract_features import FeatureMatrix, FeatureRow, QueryTiming
from benchmarks.match.feature_cache import load_feature_matrix, save_feature_matrix
from xrd_finder.finder.fingerprint_matching import FingerprintMatchFeatures


class FeatureCacheTests(unittest.TestCase):
    def test_round_trips_rows_timings_and_cache_key(self):
        matrix = FeatureMatrix(
            (
                FeatureRow(
                    "q", "candidate", "family", "family", ("family",), "test",
                    "phases=1;fwhm=0.15;noise=low;overlap=ordinary",
                    FingerprintMatchFeatures(0.9, 0.8, 0.7, 0.6, 8, 7, 10), True,
                ),
            ),
            (QueryTiming("q", 1058, 93, 0.02, 0.01, 0.5, 0.6, 1.13),),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "features.sqlite"
            save_feature_matrix(path, matrix, cache_key="key-1")

            loaded = load_feature_matrix(path, expected_cache_key="key-1")

            self.assertEqual(loaded, matrix)
            with self.assertRaises(ValueError):
                load_feature_matrix(path, expected_cache_key="different")


if __name__ == "__main__":
    unittest.main()
