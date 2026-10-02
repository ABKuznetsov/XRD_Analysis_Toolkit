from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from benchmarks.match.gain_retrieval import (
    JointGainCandidatePool,
    adaptive_gain_shortlist,
    dual_score_gain_shortlist,
    dominant_line_gain_shortlist,
    fused_line_gain_shortlist,
    hybrid_gain_shortlist,
    joint_gain_candidate_pool,
    rare_line_gain_shortlist,
)
from benchmarks.match.generate_profiles import ReferenceLine


class GainRetrievalTests(unittest.TestCase):
    def test_joint_pool_does_not_compare_unselected_database_tail_for_diagnostics(self):
        references = {
            "accepted": self._lines(10, 20, 30, 40),
            "leader": self._lines(12, 24, 36, 48),
            **{
                f"tail-{index}": self._lines(50 + index, 80 + index)
                for index in range(100)
            },
        }
        scores = {key: 0.0 for key in references}
        scores["leader"] = 100.0
        from benchmarks.match import gain_retrieval

        original = gain_retrieval.phase_patterns_equivalent
        with patch(
            "benchmarks.match.gain_retrieval.phase_patterns_equivalent",
            wraps=original,
        ) as equivalent:
            joint_gain_candidate_pool(
                references,
                original_scores=scores,
                residual_scores=scores,
                rare_candidate_ids=(),
                accepted_phase_ids=("accepted",),
                original_limit=1,
                residual_limit=1,
                rare_limit=0,
                optional_limit=1,
            )

        self.assertLess(equivalent.call_count, 30)

    def test_joint_pool_combines_channels_and_keeps_required_outside_cap(self):
        references = {
            "accepted": self._lines(10.0, 20.0, 31.0, 43.0),
            "match-a": self._lines(11.0, 23.0, 37.0, 52.0),
            "match-b": self._lines(12.0, 26.0, 41.0, 59.0),
            "residual": self._lines(14.0, 29.0, 47.0, 68.0),
            "rare": self._lines(16.0, 34.0, 55.0, 79.0),
        }

        pool = joint_gain_candidate_pool(
            references,
            original_scores={
                "match-a": 10.0,
                "match-b": 9.0,
                "residual": 1.0,
                "rare": 0.0,
            },
            residual_scores={"residual": 10.0, "match-b": 2.0},
            rare_candidate_ids=("rare",),
            accepted_phase_ids=("accepted",),
            original_limit=2,
            residual_limit=1,
            rare_limit=1,
            optional_limit=3,
        )

        self.assertIsInstance(pool, JointGainCandidatePool)
        self.assertEqual(pool.required_ids, ("accepted",))
        self.assertEqual(len(pool.optional_ids), 3)
        self.assertIn("match-a", pool.optional_ids)
        self.assertIn("residual", pool.optional_ids)
        self.assertIn("rare", pool.optional_ids)

    def test_joint_pool_collapses_equivalent_cards_without_using_names(self):
        references = {
            "accepted-na": self._lines(12.0, 20.0, 31.0, 47.0, 63.0),
            "different-name-and-id": self._lines(12.03, 19.98, 31.02, 46.98, 63.02),
            "other": self._lines(15.0, 27.0, 42.0, 58.0, 77.0),
        }

        pool = joint_gain_candidate_pool(
            references,
            original_scores={"different-name-and-id": 10.0, "other": 9.0},
            residual_scores={"different-name-and-id": 10.0, "other": 9.0},
            rare_candidate_ids=(),
            accepted_phase_ids=("accepted-na",),
        )

        self.assertEqual(pool.required_ids, ("accepted-na",))
        self.assertEqual(pool.optional_ids, ("other",))
        self.assertEqual(
            pool.family_for("accepted-na"),
            pool.family_for("different-name-and-id"),
        )

    def test_joint_pool_uses_best_original_match_as_family_representative(self):
        references = {
            "card-z": self._lines(12.0, 20.0, 31.0, 47.0, 63.0),
            "card-a": self._lines(12.02, 20.01, 30.99, 47.01, 62.98),
            "other": self._lines(15.0, 27.0, 42.0, 58.0, 77.0),
        }

        pool = joint_gain_candidate_pool(
            references,
            original_scores={"card-z": 4.0, "card-a": 8.0, "other": 1.0},
            residual_scores={"card-z": 9.0, "card-a": 1.0, "other": 2.0},
            rare_candidate_ids=(),
            accepted_phase_ids=(),
        )

        self.assertIn("card-a", pool.optional_ids)
        self.assertNotIn("card-z", pool.optional_ids)
        self.assertEqual(pool.family_for("card-a"), pool.family_for("card-z"))

    def test_joint_pool_reports_target_loss_before_and_after_collapse(self):
        references = {
            "leader": self._lines(12.0, 20.0, 31.0, 47.0, 63.0),
            "target": self._lines(15.0, 27.0, 42.0, 58.0, 77.0),
            "other": self._lines(17.0, 30.0, 49.0, 69.0, 88.0),
        }

        lost = joint_gain_candidate_pool(
            references,
            original_scores={"leader": 10.0, "other": 9.0, "target": 0.0},
            residual_scores={"leader": 10.0, "other": 9.0, "target": 0.0},
            rare_candidate_ids=(),
            accepted_phase_ids=(),
            original_limit=1,
            residual_limit=1,
            optional_limit=1,
            target_phase_id="target",
        )
        retained = joint_gain_candidate_pool(
            references,
            original_scores={"leader": 10.0, "target": 9.0, "other": 0.0},
            residual_scores={"target": 10.0, "leader": 9.0, "other": 0.0},
            rare_candidate_ids=(),
            accepted_phase_ids=(),
            original_limit=2,
            residual_limit=1,
            optional_limit=2,
            target_phase_id="target",
        )

        self.assertFalse(lost.target_present_before_collapse)
        self.assertFalse(lost.target_present_after_collapse)
        self.assertTrue(retained.target_present_before_collapse)
        self.assertTrue(retained.target_present_after_collapse)

    def test_adaptive_shortlist_keeps_quick_only_for_rich_residual(self):
        references = {f"p{index}": self._lines(10 + index) for index in range(5)}
        references["rare-target"] = self._lines(30.0)
        quick_scores = {key: float(100 - index) for index, key in enumerate(references)}
        quick_scores["rare-target"] = -10.0
        observed = tuple(
            SimpleNamespace(two_theta=30.0 + index, area=100.0, height=100.0, fwhm=0.18)
            for index in range(8)
        )

        shortlist = adaptive_gain_shortlist(
            references, observed, quick_scores, limit=3
        )

        self.assertEqual(shortlist, ("p0", "p1", "p2"))

    def test_adaptive_shortlist_reserves_half_for_sparse_residual(self):
        references = {
            "quick-a": self._lines(10.0),
            "quick-b": self._lines(11.0),
            "quick-c": self._lines(12.0),
            "rare-target": self._lines(30.0),
        }
        quick_scores = {
            "quick-a": 9.0,
            "quick-b": 8.0,
            "quick-c": 7.0,
            "rare-target": 0.0,
        }
        observed = (
            SimpleNamespace(two_theta=30.02, area=100.0, height=100.0, fwhm=0.18),
        )

        shortlist = adaptive_gain_shortlist(
            references, observed, quick_scores, limit=3
        )

        self.assertIn("quick-a", shortlist)
        self.assertIn("rare-target", shortlist)

    def test_fused_shortlist_competes_two_top24_channels_without_growing_limit(self):
        references = {f"p{index}": self._lines(10 + index, 40 + index) for index in range(40)}
        observed = self._lines(16.05)
        references["rare-target"] = self._lines(16.0, 49.0, 63.0)
        quick_scores = {key: float(100 - index) for index, key in enumerate(references)}
        quick_scores["rare-target"] = -10.0

        shortlist = fused_line_gain_shortlist(
            references,
            observed,
            quick_scores,
            limit=24,
        )

        self.assertEqual(len(shortlist), 24)
        self.assertIn("p0", shortlist)
        self.assertIn("rare-target", shortlist)

    def test_hybrid_shortlist_keeps_quick_and_geometric_candidates_with_fixed_limit(self):
        references = {
            "quick-a": self._lines(10, 20, 30, 40),
            "quick-b": self._lines(11, 21, 31, 41),
            "geometric": self._lines(15, 25, 35, 45),
            "other": self._lines(17, 29, 43, 58),
        }
        observed = self._lines(16, 26, 36, 46)
        quick_scores = {"quick-a": 0.9, "quick-b": 0.8, "geometric": 0.1, "other": 0.0}

        shortlist = hybrid_gain_shortlist(
            references,
            observed,
            quick_scores,
            limit=3,
            geometric_fraction=1 / 3,
        )

        self.assertEqual(len(shortlist), 3)
        self.assertIn("quick-a", shortlist)
        self.assertIn("geometric", shortlist)

    def test_rare_line_shortlist_keeps_quick_leaders_and_selective_match(self):
        references = {
            "quick-a": self._lines(10, 20, 30, 40),
            "quick-b": self._lines(11, 21, 31, 41),
            "selective": self._lines(16, 49, 63, 78),
            "other": self._lines(17, 29, 43, 58),
        }
        observed = self._lines(16.05)
        quick_scores = {"quick-a": 0.9, "quick-b": 0.8, "selective": 0.1, "other": 0.2}

        shortlist = rare_line_gain_shortlist(
            references,
            observed,
            quick_scores,
            limit=3,
            rare_fraction=1 / 3,
        )

        self.assertEqual(len(shortlist), 3)
        self.assertIn("quick-a", shortlist)
        self.assertIn("selective", shortlist)

    def test_dominant_line_shortlist_reserves_space_for_sparse_candidate(self):
        references = {
            "quick-a": self._lines(10, 20, 30, 40),
            "quick-b": self._lines(11, 21, 31, 41),
            "sparse": (
                ReferenceLine(26.6, 100.0),
                ReferenceLine(36.5, 8.0),
                ReferenceLine(50.1, 5.0),
            ),
            "other": self._lines(17, 29, 43, 58),
        }
        observed = (ReferenceLine(26.65, 100.0),)
        quick_scores = {"quick-a": 0.9, "quick-b": 0.8, "sparse": 0.1, "other": 0.2}

        shortlist = dominant_line_gain_shortlist(
            references, observed, quick_scores, limit=3, dominant_fraction=1 / 3
        )

        self.assertIn("quick-a", shortlist)
        self.assertIn("sparse", shortlist)

    def test_dual_score_shortlist_preserves_residual_and_original_match_candidates(self):
        shortlist = dual_score_gain_shortlist(
            ("residual-a", "residual-b", "target", "other"),
            residual_scores={"residual-a": 9.0, "residual-b": 8.0, "target": 1.0, "other": 2.0},
            original_scores={"residual-a": 1.0, "residual-b": 2.0, "target": 10.0, "other": 0.0},
            limit=3,
            original_fraction=1 / 3,
        )

        self.assertEqual(len(shortlist), 3)
        self.assertIn("residual-a", shortlist)
        self.assertIn("target", shortlist)

    @staticmethod
    def _lines(*positions):
        return tuple(
            ReferenceLine(float(position), float(100 - index * 10))
            for index, position in enumerate(positions)
        )


if __name__ == "__main__":
    unittest.main()
