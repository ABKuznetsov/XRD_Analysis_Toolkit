from __future__ import annotations

import unittest

import numpy as np

from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.joint_gain import (
    build_joint_candidate_pool,
    evaluate_joint_gain,
)
from xrd_finder.finder.joint_phase_search import JointPhaseSearchConfig


class JointGainAdapterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
