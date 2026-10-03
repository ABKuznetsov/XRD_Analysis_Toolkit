from __future__ import annotations

import unittest

from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY, GainPolicy, GainStage


class GainPolicyTests(unittest.TestCase):
    def test_gain_below_noise_reporting_floor_is_hidden(self):
        self.assertEqual(DEFAULT_GAIN_POLICY.reportable_gain(2.99), 0.0)
        self.assertEqual(DEFAULT_GAIN_POLICY.reportable_gain(3.0), 3.0)

    def test_overlap_gain_without_profile_improvement_is_hidden(self):
        self.assertEqual(
            DEFAULT_GAIN_POLICY.reportable_gain(
                8.0,
                dominant_evidence=GainStage.OVERLAP,
                profile_gain=0.0,
                profile_evaluated=True,
            ),
            0.0,
        )
        self.assertEqual(
            DEFAULT_GAIN_POLICY.reportable_gain(
                8.0,
                dominant_evidence=GainStage.OVERLAP,
                profile_gain=2.0,
                profile_evaluated=True,
            ),
            8.0,
        )

    def test_direct_gain_is_not_hidden_when_profile_fit_cannot_improve(self):
        self.assertEqual(
            DEFAULT_GAIN_POLICY.reportable_gain(
                8.0,
                dominant_evidence=GainStage.DIRECT,
                profile_gain=0.0,
                profile_evaluated=True,
            ),
            8.0,
        )

    def test_combined_evidence_prioritizes_direct_over_overlap_and_hidden(self):
        policy = GainPolicy()

        direct = policy.combine_evidence(
            direct_gain=12.0,
            overlap_gain=0.0,
            hidden_gain=0.0,
            profile_gain=None,
            remaining_fit=40.0,
            residual_line_count=5,
        )
        overlap = policy.combine_evidence(
            direct_gain=0.0,
            overlap_gain=12.0,
            hidden_gain=0.0,
            profile_gain=None,
            remaining_fit=40.0,
            residual_line_count=5,
        )
        hidden = policy.combine_evidence(
            direct_gain=0.0,
            overlap_gain=0.0,
            hidden_gain=12.0,
            profile_gain=None,
            remaining_fit=40.0,
            residual_line_count=5,
        )

        self.assertGreater(direct, overlap)
        self.assertGreater(overlap, hidden)

    def test_direct_and_overlap_can_support_the_same_candidate(self):
        policy = GainPolicy()

        combined = policy.combine_evidence(
            direct_gain=10.0,
            overlap_gain=10.0,
            hidden_gain=0.0,
            profile_gain=None,
            remaining_fit=40.0,
            residual_line_count=5,
        )

        self.assertGreater(combined, 10.0)
        self.assertLess(combined, 15.0)

    def test_one_or_two_residual_lines_cannot_create_a_large_gain(self):
        policy = GainPolicy()

        limited = policy.combine_evidence(
            direct_gain=30.0,
            overlap_gain=25.0,
            hidden_gain=20.0,
            profile_gain=30.0,
            remaining_fit=40.0,
            residual_line_count=2,
        )

        self.assertLessEqual(limited, 14.0)

    def test_winner_corroboration_only_adds_a_small_secondary_bonus(self):
        policy = GainPolicy(
            evidence_combination="winner_corroboration",
            winner_overlap_weight=1.0,
        )

        combined = policy.combine_evidence(
            direct_gain=8.0,
            overlap_gain=20.0,
            hidden_gain=0.0,
            profile_gain=None,
            remaining_fit=40.0,
            residual_line_count=5,
        )

        self.assertAlmostEqual(combined, 21.6)

    def test_unreliable_direct_evidence_cannot_overrule_overlap(self):
        policy = GainPolicy(
            evidence_combination="winner_reliable_direct",
            winner_overlap_weight=1.0,
        )

        combined = policy.combine_evidence(
            direct_gain=30.0,
            overlap_gain=20.0,
            hidden_gain=0.0,
            profile_gain=None,
            remaining_fit=40.0,
            residual_line_count=5,
            direct_reliability=0.20,
        )

        self.assertAlmostEqual(combined, 21.2)

    def test_phase_snr_softly_demotes_noise_supported_candidate(self):
        policy = GainPolicy()

        weak = policy.combine_evidence(
            direct_gain=18.0,
            overlap_gain=0.0,
            hidden_gain=0.0,
            profile_gain=15.0,
            remaining_fit=40.0,
            residual_line_count=4,
            phase_snr=3.0,
        )
        supported = policy.combine_evidence(
            direct_gain=18.0,
            overlap_gain=0.0,
            hidden_gain=0.0,
            profile_gain=15.0,
            remaining_fit=40.0,
            residual_line_count=4,
            phase_snr=7.0,
        )

        self.assertGreater(weak, 0.0)
        self.assertLess(weak, supported)

    def test_phase_snr_does_not_penalize_overlap_dominated_candidate(self):
        policy = GainPolicy(evidence_combination="winner_reliable_direct")

        without_snr = policy.combine_evidence(
            direct_gain=2.0,
            overlap_gain=20.0,
            hidden_gain=0.0,
            profile_gain=12.0,
            remaining_fit=40.0,
            residual_line_count=5,
            direct_reliability=0.2,
        )
        with_low_snr = policy.combine_evidence(
            direct_gain=2.0,
            overlap_gain=20.0,
            hidden_gain=0.0,
            profile_gain=12.0,
            remaining_fit=40.0,
            residual_line_count=5,
            direct_reliability=0.2,
            phase_snr=1.0,
        )

        self.assertAlmostEqual(with_low_snr, without_snr)

    def test_sparse_candidate_can_receive_profile_support_when_enabled(self):
        policy = GainPolicy(sparse_profile_weight=0.60)

        value = policy.combine_line_and_profile(
            line_gain=8.0,
            profile_gain=28.0,
            sparse=True,
        )

        self.assertAlmostEqual(value, 20.0)

    def test_default_sparse_combination_preserves_existing_behavior(self):
        policy = GainPolicy()

        self.assertEqual(
            policy.combine_line_and_profile(line_gain=8.0, profile_gain=28.0, sparse=True),
            8.0,
        )

    def test_stage_boundaries_use_two_records(self):
        policy = DEFAULT_GAIN_POLICY

        self.assertEqual(policy.select_stage(direct_count=2, overlap_count=0), GainStage.DIRECT)
        self.assertEqual(policy.select_stage(direct_count=1, overlap_count=2), GainStage.OVERLAP)
        self.assertEqual(policy.select_stage(direct_count=1, overlap_count=1), GainStage.HIDDEN)

    def test_sparse_boundaries_are_inclusive(self):
        policy = DEFAULT_GAIN_POLICY

        self.assertTrue(policy.is_sparse([45.0, 20.0, 15.0, 10.0, 10.0]))
        self.assertTrue(policy.is_sparse([35.0, 30.0, 15.0, 10.0, 10.0]))
        self.assertFalse(policy.is_sparse([34.9, 29.9, 15.1, 10.1, 10.0]))


if __name__ == "__main__":
    unittest.main()
