from __future__ import annotations

import unittest

from benchmarks.match.extract_features import (
    FeatureExtractionConfig,
    FeatureMatrix,
    FeatureRow,
    extract_match_features,
    extract_match_features_parallel,
)
from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.metrics import evaluate_rankings, rank_feature_matrix
from benchmarks.match.scenarios import ScenarioComponent, ScenarioDefinition
from xrd_finder.finder.fingerprint_matching import FingerprintMatchFeatures, MatchWeights


def _features(observed: float, reference: float) -> FingerprintMatchFeatures:
    return FingerprintMatchFeatures(observed, reference, 1.0, 1.0, 8, 8, 10)


class MatchEvaluationTests(unittest.TestCase):
    def test_extracts_production_match_features_for_every_candidate(self):
        references = {
            "true": (ReferenceLine(20, 100), ReferenceLine(30, 80), ReferenceLine(40, 60), ReferenceLine(50, 40)),
            "other": (ReferenceLine(22, 100), ReferenceLine(33, 80), ReferenceLine(44, 60), ReferenceLine(55, 40)),
        }
        scenario = ScenarioDefinition(
            "query", "train", 11, (ScenarioComponent("true", "family-true", 1.0),),
            0.15, "none", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
        )

        matrix = extract_match_features(
            references,
            {"true": "family-true", "other": "family-other"},
            (scenario,),
        )

        self.assertEqual(len(matrix.rows), 2)
        self.assertEqual({row.query_id for row in matrix.rows}, {"query"})
        self.assertTrue(all(row.features.anchor_count > 0 for row in matrix.rows))
        self.assertEqual(len(matrix.timings), 1)
        timing = matrix.timings[0]
        self.assertEqual(timing.query_id, "query")
        self.assertEqual(timing.candidate_count, 2)
        self.assertGreaterEqual(timing.total_seconds, timing.quick_seconds)

    def test_refines_only_bounded_union_and_keeps_quick_features_for_tail(self):
        references = {
            "true": (ReferenceLine(20, 100), ReferenceLine(30, 80), ReferenceLine(40, 60), ReferenceLine(50, 40)),
            "near": (ReferenceLine(20.1, 100), ReferenceLine(30.1, 80), ReferenceLine(40.1, 60), ReferenceLine(50.1, 40)),
            "tail": (ReferenceLine(22, 100), ReferenceLine(33, 80), ReferenceLine(44, 60), ReferenceLine(55, 40)),
        }
        scenario = ScenarioDefinition(
            "query", "train", 11, (ScenarioComponent("true", "family-true", 1.0),),
            0.15, "none", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
        )

        matrix = extract_match_features(
            references,
            {"true": "family-true", "near": "family-near", "tail": "family-tail"},
            (scenario,),
            config=FeatureExtractionConfig(
                fingerprint_refine_limit=1,
                quick_refine_limit=0,
            ),
        )

        rows = {row.candidate_id: row for row in matrix.rows}
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(row.refined for row in rows.values()), 1)
        self.assertTrue(rows["true"].refined or rows["near"].refined)
        self.assertFalse(rows["tail"].refined)

    def test_reports_hand_checkable_mrr_and_top_k(self):
        matrix = FeatureMatrix(
            (
                FeatureRow("q1", "true-1", "f1", "f1", ("f1",), "test", "clean", _features(0.9, 0.7)),
                FeatureRow("q1", "other", "f2", "f1", ("f1",), "test", "clean", _features(0.7, 0.9)),
                FeatureRow("q2", "other", "f2", "f3", ("f3",), "test", "noisy", _features(0.8, 0.8)),
                FeatureRow("q2", "true-2", "f3", "f3", ("f3",), "test", "noisy", _features(0.7, 0.7)),
            )
        )

        rankings = rank_feature_matrix(matrix, MatchWeights(0.8, 0.1, 0.05, 0.05))
        metrics = evaluate_rankings(rankings)

        self.assertEqual(rankings[0].dominant_rank, 1)
        self.assertEqual(rankings[1].dominant_rank, 2)
        self.assertAlmostEqual(metrics.mrr, 0.75)
        self.assertAlmostEqual(metrics.top1, 0.5)
        self.assertAlmostEqual(metrics.top5, 1.0)

    def test_parallel_extraction_preserves_feature_rows(self):
        references = {
            "true": (ReferenceLine(20, 100), ReferenceLine(30, 80), ReferenceLine(40, 60), ReferenceLine(50, 40)),
            "other": (ReferenceLine(22, 100), ReferenceLine(33, 80), ReferenceLine(44, 60), ReferenceLine(55, 40)),
        }
        scenarios = tuple(
            ScenarioDefinition(
                f"query-{seed}", "train", seed,
                (ScenarioComponent("true", "family-true", 1.0),),
                0.15, "none", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
            )
            for seed in (11, 12)
        )
        families = {"true": "family-true", "other": "family-other"}

        sequential = extract_match_features(references, families, scenarios)
        parallel = extract_match_features_parallel(references, families, scenarios, workers=2)

        self.assertEqual(parallel.rows, sequential.rows)
        self.assertEqual({item.query_id for item in parallel.timings}, {"query-11", "query-12"})


if __name__ == "__main__":
    unittest.main()
