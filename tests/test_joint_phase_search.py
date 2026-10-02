from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

import numpy as np

from xrd_finder.finder.joint_phase_search import (
    JointPhaseCandidate,
    JointPhaseSearchConfig,
    search_phase_combinations,
)


def _candidate(
    key: str = "candidate",
    family_key: str = "family-candidate",
    profile: tuple[float, ...] = (0.0, 1.0, 0.0),
) -> JointPhaseCandidate:
    return JointPhaseCandidate(
        key=key,
        family_key=family_key,
        profile=np.asarray(profile, dtype=float),
        peak_positions=np.asarray([20.0], dtype=float),
        peak_amplitudes=np.asarray([100.0], dtype=float),
    )


class JointPhaseValidationTests(unittest.TestCase):
    def test_rejects_mismatched_target_weights_and_profiles(self):
        x = np.asarray([10.0, 20.0, 30.0])

        with self.assertRaisesRegex(
            ValueError,
            "target and weights must have identical shapes",
        ):
            search_phase_combinations(
                x=x,
                target=np.ones(3),
                weights=np.ones(2),
                candidates=(),
            )

        with self.assertRaisesRegex(
            ValueError,
            "candidate profile length must match target",
        ):
            search_phase_combinations(
                x=x,
                target=np.ones(3),
                weights=np.ones(3),
                candidates=(_candidate(profile=(1.0, 0.0)),),
            )

    def test_rejects_nonfinite_candidate_profile(self):
        with self.assertRaisesRegex(
            ValueError,
            "candidate profiles must contain only finite values",
        ):
            search_phase_combinations(
                x=np.asarray([10.0, 20.0, 30.0]),
                target=np.ones(3),
                weights=np.ones(3),
                candidates=(_candidate(profile=(0.0, np.nan, 0.0)),),
            )

    def test_zero_target_returns_empty_deterministic_result(self):
        x = np.asarray([10.0, 20.0, 30.0])
        target = np.zeros(3)
        candidate = _candidate()
        original_profile = candidate.profile.copy()

        first = search_phase_combinations(
            x=x,
            target=target,
            weights=np.ones(3),
            candidates=(candidate,),
        )
        second = search_phase_combinations(
            x=x,
            target=target,
            weights=np.ones(3),
            candidates=(candidate,),
        )

        self.assertEqual(first.baseline.family_keys, ())
        self.assertEqual(first.baseline.card_keys, ())
        self.assertEqual(first.baseline.score, 0.0)
        self.assertEqual(first.candidate_gains, ())
        self.assertEqual(first.combinations, second.combinations)
        np.testing.assert_array_equal(candidate.profile, original_profile)

    def test_empty_optional_pool_returns_required_baseline_only(self):
        required = _candidate(
            key="accepted",
            family_key="family-accepted",
            profile=(0.0, 2.0, 0.0),
        )

        result = search_phase_combinations(
            x=np.asarray([10.0, 20.0, 30.0]),
            target=np.asarray([0.0, 4.0, 0.0]),
            weights=np.ones(3),
            candidates=(required,),
            required_keys=("accepted",),
        )

        self.assertEqual(result.baseline.family_keys, ("family-accepted",))
        self.assertEqual(result.baseline.card_keys, ("accepted",))
        self.assertEqual(result.baseline.scales, (2.0,))
        self.assertEqual(result.combinations, (result.baseline,))
        self.assertEqual(result.candidate_gains, ())

    def test_candidate_and_result_objects_are_immutable(self):
        candidate = _candidate()
        config = JointPhaseSearchConfig()
        result = search_phase_combinations(
            x=np.asarray([10.0, 20.0, 30.0]),
            target=np.zeros(3),
            weights=np.ones(3),
            candidates=(candidate,),
            config=config,
        )

        with self.assertRaises(FrozenInstanceError):
            candidate.key = "changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            config.beam_width = 9  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.evaluated_combinations = 99  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
