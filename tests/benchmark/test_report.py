from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from benchmarks.match.extract_features import QueryTiming
from benchmarks.match.report import summarize_timings, write_summary
from benchmarks.match.metrics import RankingMetrics
from xrd_finder.finder.fingerprint_matching import MatchWeights


class ReportTests(unittest.TestCase):
    def test_joint_gain_readme_documents_smoke_sensitivity_and_latency_meaning(self):
        readme = (
            Path(__file__).parents[2] / "benchmarks" / "match" / "README.md"
        ).read_text(encoding="utf-8")

        self.assertIn("--gain-engine joint-beam", readme)
        self.assertIn("joint_gain_sensitivity", readme)
        self.assertIn("retrieval", readme.lower())
        self.assertIn("profile", readme.lower())
        self.assertIn("beam", readme.lower())
        self.assertIn("interactive", readme.lower())

    def test_summarizes_single_pattern_runtime(self):
        summary = summarize_timings(
            (
                QueryTiming("q1", 1000, 80, 0.1, 0.2, 1.0, 0.7, 2.0),
                QueryTiming("q2", 1000, 90, 0.1, 0.3, 1.4, 0.8, 2.6),
            ),
            workload_query_count=100,
        )

        self.assertEqual(summary.query_count, 2)
        self.assertAlmostEqual(summary.median_total_seconds, 2.3)
        self.assertGreaterEqual(summary.p95_total_seconds, summary.median_total_seconds)
        self.assertEqual(summary.median_candidate_count, 1000)
        self.assertEqual(summary.median_refined_count, 85)
        self.assertAlmostEqual(summary.median_quick_ms_per_candidate, 1.2)
        self.assertAlmostEqual(summary.estimated_workload_seconds, 230.0)

    def test_summary_contains_dataset_hash_weights_and_baselines(self):
        metric = RankingMetrics(2, 0.75, 0.5, 1.0, 1.0, 1.0, 1.0)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "summary.md"

            timing = summarize_timings(
                (QueryTiming("q1", 1000, 80, 0.1, 0.2, 1.0, 0.7, 2.0),),
                workload_query_count=192,
            )
            write_summary(
                output,
                "abc123",
                MatchWeights(0.5, 0.4, 0.05, 0.05),
                {"current": metric},
                timing,
            )

            text = output.read_text(encoding="utf-8")
            self.assertIn("abc123", text)
            self.assertIn("0.500/0.400/0.050/0.050", text)
            self.assertIn("current", text)
            self.assertIn("192 patterns", text)
            self.assertIn("all 1000 candidates", text)


if __name__ == "__main__":
    unittest.main()
