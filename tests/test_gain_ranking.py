from __future__ import annotations

import unittest

from xrd_finder.finder.gain_policy import GainStage
from xrd_finder.finder.gain_ranking import GainCandidate, GainQuery, rank_gain_candidates


class GainRankingTests(unittest.TestCase):
    def test_combines_direct_overlap_and_profile_support(self):
        results = rank_gain_candidates(
            GainQuery(before_fit=60.0, direct_count=3, overlap_count=5, residual_line_count=8),
            [
                GainCandidate("supported", direct_gain=20.0, overlap_gain=8.0, profile_gain=16.0),
                GainCandidate("weak-profile", direct_gain=22.0, overlap_gain=0.0, profile_gain=4.0),
            ],
        )

        self.assertEqual(results[0].key, "supported")
        self.assertEqual(results[0].dominant_evidence, GainStage.DIRECT)
        self.assertGreater(results[0].gain, results[1].gain)

    def test_hidden_evidence_is_combined_without_switching_mode(self):
        result = rank_gain_candidates(
            GainQuery(before_fit=80.0, direct_count=0, overlap_count=3, residual_line_count=3),
            [GainCandidate("hidden", hidden_gain=4.5)],
        )[0]

        self.assertEqual(result.dominant_evidence, GainStage.HIDDEN)
        self.assertFalse(result.limited_residual)
        self.assertAlmostEqual(result.gain, 0.9)

    def test_two_residual_lines_cap_combined_gain(self):
        result = rank_gain_candidates(
            GainQuery(before_fit=60.0, direct_count=1, overlap_count=1, residual_line_count=2),
            [GainCandidate("limited", direct_gain=30.0, overlap_gain=25.0, profile_gain=30.0)],
        )[0]

        self.assertTrue(result.limited_residual)
        self.assertLessEqual(result.gain, 14.0)

    def test_phase_snr_moves_repeatedly_supported_candidate_above_single_line_noise(self):
        results = rank_gain_candidates(
            GainQuery(before_fit=60.0, direct_count=3, overlap_count=3, residual_line_count=6),
            [
                GainCandidate(
                    "noise",
                    direct_gain=22.0,
                    profile_gain=18.0,
                    phase_snr=2.5,
                ),
                GainCandidate(
                    "phase",
                    direct_gain=18.0,
                    profile_gain=16.0,
                    phase_snr=8.0,
                ),
            ],
        )

        self.assertEqual(results[0].key, "phase")


if __name__ == "__main__":
    unittest.main()
