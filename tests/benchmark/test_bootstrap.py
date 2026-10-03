from __future__ import annotations

import unittest

from benchmarks.match.bootstrap import paired_bootstrap


class BootstrapTests(unittest.TestCase):
    def test_paired_interval_is_deterministic_and_preserves_positive_delta(self):
        baseline = (0.0, 0.0, 1.0, 0.0, 1.0)
        candidate = (1.0, 0.0, 1.0, 1.0, 1.0)

        first = paired_bootstrap(baseline, candidate, seed=5036, iterations=2000)
        second = paired_bootstrap(baseline, candidate, seed=5036, iterations=2000)

        self.assertEqual(first, second)
        self.assertAlmostEqual(first.mean_difference, 0.4)
        self.assertGreaterEqual(first.high, first.low)


if __name__ == "__main__":
    unittest.main()
