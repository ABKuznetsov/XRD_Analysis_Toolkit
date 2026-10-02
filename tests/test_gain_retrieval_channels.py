from __future__ import annotations

import math
import unittest

from xrd_finder.services.gain_retrieval_channels import (
    RETRIEVAL_CHANNELS,
    rank_channel_scores,
)


class GainRetrievalChannelResultTests(unittest.TestCase):
    def test_rank_filters_invalid_scores_and_assigns_one_based_ranks(self):
        run = rank_channel_scores(
            "strong",
            {
                "phase-b": 2.0,
                "phase-a": 2.0,
                "phase-c": 1.0,
                "zero": 0.0,
                "negative": -1.0,
                "nan": math.nan,
                "inf": math.inf,
            },
            {"phase-a": 3, "phase-b": 2, "phase-c": 1},
            limit=2,
        )

        self.assertEqual(run.channel, "strong")
        self.assertEqual(
            [(hit.phase_id, hit.rank) for hit in run.hits],
            [("phase-a", 1), ("phase-b", 2)],
        )
        self.assertEqual([hit.evidence_count for hit in run.hits], [3, 2])
        self.assertTrue(all(math.isfinite(hit.score) for hit in run.hits))
        self.assertTrue(math.isfinite(run.elapsed_seconds))
        self.assertGreaterEqual(run.elapsed_seconds, 0.0)

    def test_identifiers_are_normalized_and_missing_evidence_is_zero(self):
        run = rank_channel_scores(
            "rare",
            {20: 4.0, 10: 5.0},
            {10: -4},
            limit=10,
        )

        self.assertEqual([hit.phase_id for hit in run.hits], ["10", "20"])
        self.assertEqual([hit.evidence_count for hit in run.hits], [0, 0])
        self.assertTrue(all(hit.channel == "rare" for hit in run.hits))

    def test_empty_or_zero_limit_returns_empty_timed_run(self):
        for scores, limit in (({}, 5), ({"phase": 1.0}, 0)):
            with self.subTest(scores=scores, limit=limit):
                run = rank_channel_scores(
                    "geometry", scores, {}, limit=limit
                )
                self.assertEqual(run.hits, ())
                self.assertTrue(math.isfinite(run.elapsed_seconds))
                self.assertGreaterEqual(run.elapsed_seconds, 0.0)

    def test_stable_channel_names_are_public(self):
        self.assertEqual(
            RETRIEVAL_CHANNELS,
            ("strong", "rare", "geometry", "overlap"),
        )


if __name__ == "__main__":
    unittest.main()
