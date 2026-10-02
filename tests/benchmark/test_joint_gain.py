from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.joint_gain import (
    build_joint_candidate_pool,
    build_joint_fit_mask,
    evaluate_joint_gain,
    prefilter_joint_profile_ids,
    select_informative_residual_peaks,
)
from xrd_finder.finder.joint_phase_search import JointPhaseSearchConfig


class JointGainAdapterTests(unittest.TestCase):
    def test_fast_residual_selector_keeps_only_strongest_maxima(self):
        peaks = tuple(
            SimpleNamespace(two_theta=float(index), intensity=float(index))
            for index in range(1, 21)
        )

        selected = select_informative_residual_peaks(peaks, limit=8)

        self.assertEqual(len(selected), 8)
        self.assertEqual(
            tuple(item.intensity for item in selected),
            tuple(float(value) for value in range(13, 21)),
        )

    def test_fast_prefilter_keeps_best_residual_matches_and_retrieval_rescue(self):
        references = {
            key: (ReferenceLine(20.0 + index, 100.0),)
            for index, key in enumerate(("a", "b", "c", "rare"))
        }
        pool = build_joint_candidate_pool(
            references,
            original_scores={"a": 10.0, "rare": 9.0, "b": 8.0, "c": 7.0},
            residual_scores={"a": 1.0, "b": 4.0, "c": 3.0, "rare": 0.0},
            rare_candidate_ids=("rare",),
            accepted_phase_ids=(),
            optional_limit=4,
        )

        selected = prefilter_joint_profile_ids(
            pool,
            residual_scores={
                "a": SimpleNamespace(score=1.0),
                "b": SimpleNamespace(score=4.0),
                "c": SimpleNamespace(score=3.0),
                "rare": SimpleNamespace(score=0.0),
            },
            limit=3,
            rescue_count=1,
        )

        self.assertEqual(selected[:2], ("b", "c"))
        self.assertEqual(len(selected), 3)
        self.assertIn(pool.optional_ids[0], selected)

    def test_peak_window_mask_uses_explicit_residual_maxima(self):
        x = np.linspace(10.0, 80.0, 7001)
        target = np.exp(-0.5 * ((x - 25.0) / 0.08) ** 2)
        references = {
            "candidate": (
                ReferenceLine(25.0, 100.0),
                ReferenceLine(63.0, 80.0),
                ReferenceLine(70.01, 0.5),
            ),
        }

        mask = build_joint_fit_mask(
            x=x,
            target=target,
            references=references,
            phase_ids=("candidate",),
            mode="peak-windows",
            window_centers=(25.0,),
        )

        self.assertLess(np.count_nonzero(mask), len(x) // 3)
        self.assertTrue(mask[np.argmin(np.abs(x - 25.0))])
        self.assertFalse(mask[np.argmin(np.abs(x - 63.0))])
        self.assertFalse(mask[np.argmin(np.abs(x - 70.01))])
        self.assertTrue(mask[0])
        self.assertTrue(mask[-1])

    def test_full_fit_mask_keeps_every_profile_point(self):
        x = np.linspace(10.0, 30.0, 101)

        mask = build_joint_fit_mask(
            x=x,
            target=np.zeros_like(x),
            references={},
            phase_ids=(),
            mode="full",
        )

        np.testing.assert_array_equal(mask, np.ones(len(x), dtype=bool))

    def test_adapter_converts_prepared_profiles_and_ranks_conditional_gain(self):
        x = np.linspace(10.0, 30.0, 9)
        accepted_profile = np.zeros(len(x))
        accepted_profile[[1, 4]] = (5.0, 2.0)
        target_profile = np.zeros(len(x))
        target_profile[[4, 7]] = (4.0, 1.5)
        references = {
            "accepted": (
                ReferenceLine(float(x[1]), 100.0),
                ReferenceLine(float(x[4]), 40.0),
            ),
            "target": (
                ReferenceLine(float(x[4]), 100.0),
                ReferenceLine(float(x[7]), 35.0),
            ),
        }
        pool = build_joint_candidate_pool(
            references,
            original_scores={"accepted": 10.0, "target": 9.0},
            residual_scores={"target": 10.0},
            rare_candidate_ids=(),
            accepted_phase_ids=("accepted",),
        )

        evaluation = evaluate_joint_gain(
            x=x,
            target=accepted_profile + target_profile,
            weights=np.ones(len(x)),
            profiles={"accepted": accepted_profile, "target": target_profile},
            references=references,
            pool=pool,
            config=JointPhaseSearchConfig(
                derivative_weight=0.0,
                complexity_penalty=0.0,
                minimum_phase_snr=0.0,
                minimum_relative_improvement=0.0,
                minimum_reported_gain=0.0,
            ),
        )

        self.assertEqual(evaluation.ranked_phase_ids[0], "target")
        self.assertEqual(evaluation.ranked_family_keys[0], pool.family_for("target"))
        self.assertGreater(evaluation.search_result.candidate_gains[0].gain, 0.0)
        self.assertGreaterEqual(evaluation.evaluated_combinations, 2)
        self.assertGreaterEqual(evaluation.search_seconds, 0.0)
        self.assertEqual(evaluation.active_fit_points, len(x))

    def test_adapter_can_fit_only_peak_windows(self):
        x = np.linspace(10.0, 80.0, 7001)
        profile = np.exp(-0.5 * ((x - 25.0) / 0.08) ** 2)
        references = {
            "target": (
                ReferenceLine(25.0, 100.0),
                ReferenceLine(63.0, 25.0),
            ),
        }
        pool = build_joint_candidate_pool(
            references,
            original_scores={"target": 10.0},
            residual_scores={"target": 10.0},
            rare_candidate_ids=(),
            accepted_phase_ids=(),
        )

        evaluation = evaluate_joint_gain(
            x=x,
            target=profile,
            weights=np.ones(len(x)),
            profiles={"target": profile},
            references=references,
            pool=pool,
            profile_mode="peak-windows",
            config=JointPhaseSearchConfig(
                max_added_phases=1,
                derivative_weight=0.0,
                complexity_penalty=0.0,
                minimum_phase_snr=0.0,
                minimum_relative_improvement=0.0,
                minimum_reported_gain=0.0,
            ),
        )

        self.assertLess(evaluation.active_fit_points, len(x) // 3)
        self.assertEqual(evaluation.ranked_phase_ids, ("target",))


if __name__ == "__main__":
    unittest.main()
