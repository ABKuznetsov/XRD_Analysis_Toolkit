from __future__ import annotations

import unittest
from types import SimpleNamespace

from xrd_finder.services.gain_shortlist import (
    GAIN_PROFILE_CANDIDATE_LIMIT,
    adaptive_gain_secondary_scores,
    common_zero_shift,
    dominant_line_candidate_scores,
    estimate_matched_profile_fwhm,
    has_sparse_line_distribution,
    rare_line_candidate_scores,
    residual_peak_is_explained,
    significant_residual_records,
    summarize_combined_residual_evidence,
    summarize_residual_evidence,
    select_profile_candidate_indices,
)


class GainShortlistTests(unittest.TestCase):
    def test_significant_residual_records_reject_explicit_sub_three_sigma_noise(self):
        records = [
            SimpleNamespace(two_theta=20.0, area=100.0, height=80.0, local_snr=2.9),
            SimpleNamespace(two_theta=25.0, area=30.0, height=20.0, local_snr=3.1),
        ]

        significant = significant_residual_records(records)

        self.assertEqual([record.two_theta for record in significant], [25.0])

    def test_significant_residual_records_keep_legacy_records_without_snr(self):
        record = SimpleNamespace(two_theta=20.0, area=10.0, height=5.0)

        self.assertEqual(significant_residual_records([record]), (record,))

    def test_overlap_only_residual_still_enables_gain_retrieval(self):
        overlap = [
            SimpleNamespace(two_theta=26.6, area=120.0, height=120.0, fwhm=0.22)
        ]

        summary = summarize_combined_residual_evidence(
            [], overlap, expected_fwhm=0.18
        )

        self.assertEqual(summary.kind, "sparse")
        self.assertEqual(summary.significant_line_count, 1)

    def test_peak_at_accepted_stick_remains_unknown_when_intensity_is_underfit(self):
        self.assertFalse(
            residual_peak_is_explained(
                observed_height=100.0,
                calculated_height=55.0,
                residual_height=45.0,
                noise_floor=4.0,
                overlaps_accepted_phase=True,
            )
        )

    def test_peak_at_accepted_stick_is_closed_when_profile_covers_intensity(self):
        self.assertTrue(
            residual_peak_is_explained(
                observed_height=100.0,
                calculated_height=92.0,
                residual_height=8.0,
                noise_floor=4.0,
                overlaps_accepted_phase=True,
            )
        )

    def test_peak_away_from_accepted_sticks_remains_unknown(self):
        self.assertFalse(
            residual_peak_is_explained(
                observed_height=40.0,
                calculated_height=0.0,
                residual_height=40.0,
                noise_floor=4.0,
                overlaps_accepted_phase=False,
            )
        )

    def test_rich_residual_keeps_quick_retrieval_only(self):
        records = [
            SimpleNamespace(two_theta=20.0 + index, area=100.0, height=100.0, fwhm=0.18)
            for index in range(8)
        ]
        summary = summarize_residual_evidence(records, expected_fwhm=0.18)

        self.assertEqual(summary.kind, "rich")
        self.assertEqual(summary.rare_line_fraction, 0.0)
        self.assertIsNone(
            adaptive_gain_secondary_scores(
                summary,
                {"candidate": [SimpleNamespace(two_theta=33.0, intensity=100.0)]},
                records,
            )
        )

    def test_intermediate_residual_reserves_quarter_of_shortlist(self):
        records = [
            SimpleNamespace(two_theta=20.0 + index, area=100.0, height=100.0, fwhm=0.18)
            for index in range(4)
        ]

        summary = summarize_residual_evidence(records, expected_fwhm=0.18)

        self.assertEqual(summary.kind, "intermediate")
        self.assertEqual(summary.rare_line_fraction, 0.25)

    def test_sparse_residual_reserves_half_of_shortlist(self):
        records = [
            SimpleNamespace(two_theta=20.0, area=60.0, height=60.0, fwhm=0.18),
            SimpleNamespace(two_theta=30.0, area=30.0, height=30.0, fwhm=0.18),
            *[
                SimpleNamespace(two_theta=40.0 + index, area=2.0, height=2.0, fwhm=0.18)
                for index in range(6)
            ],
        ]

        summary = summarize_residual_evidence(records, expected_fwhm=0.18)

        self.assertEqual(summary.kind, "sparse")
        self.assertGreaterEqual(summary.strongest_two_fraction, 0.65)
        self.assertEqual(summary.rare_line_fraction, 0.50)

    def test_empty_residual_disables_gain_retrieval(self):
        summary = summarize_residual_evidence([], expected_fwhm=0.18)

        self.assertEqual(summary.kind, "none")
        self.assertEqual(summary.significant_line_count, 0)

    def test_sparse_residual_enables_rare_line_retrieval(self):
        observed = [SimpleNamespace(two_theta=33.0, area=100.0, fwhm=0.18)]
        candidates = {
            "unrelated": [SimpleNamespace(two_theta=20.0, intensity=100.0)],
            "selective": [SimpleNamespace(two_theta=33.05, intensity=100.0)],
        }
        summary = summarize_residual_evidence(observed, expected_fwhm=0.18)

        scores = adaptive_gain_secondary_scores(summary, candidates, observed)

        self.assertIsNotNone(scores)
        self.assertGreater(scores["selective"], scores["unrelated"])

    def test_uses_one_common_zero_shift_for_all_candidates(self):
        self.assertAlmostEqual(common_zero_shift([0.11, 0.10, 0.12]), 0.11)
        self.assertEqual(common_zero_shift([]), 0.0)

    def test_selects_highest_positive_line_scores_stably(self):
        selected = select_profile_candidate_indices(
            {0: 0.0, 1: 5.0, 2: 8.0, 3: 8.0, 4: 2.0},
            limit=3,
        )

        self.assertEqual(selected, [2, 3, 1])

    def test_excludes_nonpositive_candidates(self):
        self.assertEqual(
            select_profile_candidate_indices({0: 0.0, 1: -2.0}, limit=20),
            [],
        )

    def test_respects_zero_limit(self):
        self.assertEqual(
            select_profile_candidate_indices({0: 10.0}, limit=0),
            [],
        )

    def test_default_bounds_full_profile_stage(self):
        selected = select_profile_candidate_indices(
            {index: float(100 - index) for index in range(80)}
        )

        self.assertEqual(len(selected), GAIN_PROFILE_CANDIDATE_LIMIT)
        self.assertEqual(selected, list(range(GAIN_PROFILE_CANDIDATE_LIMIT)))

    def test_rare_residual_line_can_reserve_a_shortlist_place(self):
        line_scores = {0: 10.0, 1: 9.0, 2: 8.0, 3: 1.0}
        selected = select_profile_candidate_indices(
            line_scores,
            secondary_scores={0: 0.0, 1: 0.0, 2: 0.0, 3: 7.0},
            secondary_fraction=0.25,
            limit=4,
        )

        self.assertEqual(len(selected), 4)
        self.assertIn(3, selected)

    def test_secondary_candidates_can_expand_without_displacing_primary_shortlist(self):
        selected = select_profile_candidate_indices(
            {0: 10.0, 1: 9.0, 2: 8.0, 3: 1.0},
            secondary_scores={3: 7.0},
            secondary_extra_limit=1,
            limit=3,
        )

        self.assertEqual(selected, [0, 1, 2, 3])

    def test_rare_line_score_rewards_a_selective_residual_match(self):
        observed = [SimpleNamespace(two_theta=33.0, area=100.0, fwhm=0.18)]
        candidates = {
            "common-a": [SimpleNamespace(two_theta=20.0, intensity=100.0)],
            "common-b": [SimpleNamespace(two_theta=20.1, intensity=100.0)],
            "selective": [SimpleNamespace(two_theta=33.05, intensity=100.0)],
        }

        scores = rare_line_candidate_scores(candidates, observed, tolerance=0.30)

        self.assertGreater(scores["selective"], scores["common-a"])

    def test_dominant_line_score_retrieves_a_sparse_candidate(self):
        observed = [SimpleNamespace(two_theta=26.6, area=100.0, fwhm=0.20)]
        candidates = {
            "distributed": [
                SimpleNamespace(two_theta=value, intensity=weight)
                for value, weight in ((26.6, 100), (31, 95), (40, 90), (50, 85))
            ],
            "sparse": [
                SimpleNamespace(two_theta=value, intensity=weight)
                for value, weight in ((26.62, 100), (36.5, 10), (50.1, 6), (59.9, 4))
            ],
        }

        scores = dominant_line_candidate_scores(candidates, observed, tolerance=0.30)

        self.assertGreater(scores["sparse"], 0.0)
        self.assertEqual(scores["distributed"], 0.0)

    def test_detects_quartz_like_dominant_line_distribution(self):
        self.assertTrue(
            has_sparse_line_distribution([100.0, 22.0, 11.0, 9.8, 9.0, 8.0, 6.3, 5.0, 4.5, 3.4])
        )

    def test_does_not_mark_distributed_pattern_as_sparse(self):
        self.assertFalse(
            has_sparse_line_distribution([100.0, 90.0, 80.0, 70.0, 60.0, 50.0, 40.0, 30.0])
        )

    def test_estimates_width_from_matched_experimental_lines(self):
        references = [
            SimpleNamespace(two_theta=20.0, intensity=100.0),
            SimpleNamespace(two_theta=30.0, intensity=80.0),
            SimpleNamespace(two_theta=40.0, intensity=60.0),
            SimpleNamespace(two_theta=50.0, intensity=40.0),
        ]
        observed = [
            SimpleNamespace(two_theta=20.03, fwhm=0.39),
            SimpleNamespace(two_theta=29.98, fwhm=0.42),
            SimpleNamespace(two_theta=40.02, fwhm=0.40),
            SimpleNamespace(two_theta=50.01, fwhm=0.44),
        ]

        value = estimate_matched_profile_fwhm(
            references,
            observed,
            default_fwhm=0.18,
            tolerance=0.35,
        )

        self.assertAlmostEqual(value, 0.40, delta=0.03)

    def test_keeps_default_width_without_enough_matches(self):
        value = estimate_matched_profile_fwhm(
            [SimpleNamespace(two_theta=20.0, intensity=100.0)],
            [SimpleNamespace(two_theta=20.0, fwhm=0.50)],
            default_fwhm=0.18,
            tolerance=0.35,
        )

        self.assertEqual(value, 0.18)

    def test_estimates_a_separate_width_for_each_candidate(self):
        references = [
            SimpleNamespace(two_theta=20.0, intensity=100.0),
            SimpleNamespace(two_theta=30.0, intensity=80.0),
            SimpleNamespace(two_theta=40.0, intensity=60.0),
            SimpleNamespace(two_theta=50.0, intensity=40.0),
        ]
        narrow = [
            SimpleNamespace(two_theta=position, fwhm=0.12)
            for position in (20.0, 30.0, 40.0, 50.0)
        ]
        broad = [
            SimpleNamespace(two_theta=position, fwhm=0.46)
            for position in (20.0, 30.0, 40.0, 50.0)
        ]

        narrow_fwhm = estimate_matched_profile_fwhm(
            references,
            narrow,
            default_fwhm=0.18,
            tolerance=0.35,
        )
        broad_fwhm = estimate_matched_profile_fwhm(
            references,
            broad,
            default_fwhm=0.18,
            tolerance=0.35,
        )

        self.assertLess(narrow_fwhm, broad_fwhm)
        self.assertAlmostEqual(narrow_fwhm, 0.12, delta=0.02)
        self.assertAlmostEqual(broad_fwhm, 0.46, delta=0.03)


if __name__ == "__main__":
    unittest.main()
