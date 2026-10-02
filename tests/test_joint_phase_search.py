from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

import numpy as np

from xrd_finder.finder.joint_phase_search import (
    JointPhaseCandidate,
    JointPhaseSearchConfig,
    _fit_combination,
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


class JointPhaseFitTests(unittest.TestCase):
    def test_joint_nnls_releases_shared_intensity_to_supported_second_phase(self):
        required = _candidate(
            key="accepted",
            family_key="family-accepted",
            profile=(1.0, 1.0, 0.0),
        )
        additional = _candidate(
            key="additional",
            family_key="family-additional",
            profile=(1.0, 0.0, 1.0),
        )
        target = np.asarray([5.0, 2.0, 3.0])
        config = JointPhaseSearchConfig(
            derivative_weight=0.0,
            complexity_penalty=0.0,
        )

        baseline = _fit_combination(
            target=target,
            weights=np.ones(3),
            candidates=(required,),
            required_count=1,
            config=config,
        )
        child = _fit_combination(
            target=target,
            weights=np.ones(3),
            candidates=(required, additional),
            required_count=1,
            config=config,
        )

        self.assertAlmostEqual(child.scales[0], 2.0, places=7)
        self.assertAlmostEqual(child.scales[1], 3.0, places=7)
        self.assertLess(child.score, baseline.score)

    def test_excess_profile_intensity_is_penalized_more_than_underfit(self):
        candidate = _candidate(profile=(1.0, 1.0, 0.0))
        target = np.asarray([1.0, 0.0, 1.0])

        symmetric = _fit_combination(
            target=target,
            weights=np.ones(3),
            candidates=(candidate,),
            required_count=0,
            config=JointPhaseSearchConfig(
                derivative_weight=0.0,
                complexity_penalty=0.0,
                excess_penalty=1.0,
            ),
        )
        excess_weighted = _fit_combination(
            target=target,
            weights=np.ones(3),
            candidates=(candidate,),
            required_count=0,
            config=JointPhaseSearchConfig(
                derivative_weight=0.0,
                complexity_penalty=0.0,
                excess_penalty=3.0,
            ),
        )

        self.assertGreater(excess_weighted.score, symmetric.score)

    def test_derivative_term_penalizes_a_missing_sharp_line(self):
        broad = _candidate(profile=(0.5, 0.5, 0.5, 0.5, 0.5))
        target = np.asarray([0.0, 0.0, 2.0, 0.0, 0.0])

        without_derivative = _fit_combination(
            target=target,
            weights=np.ones(5),
            candidates=(broad,),
            required_count=0,
            config=JointPhaseSearchConfig(
                derivative_weight=0.0,
                complexity_penalty=0.0,
            ),
        )
        with_derivative = _fit_combination(
            target=target,
            weights=np.ones(5),
            candidates=(broad,),
            required_count=0,
            config=JointPhaseSearchConfig(
                derivative_weight=0.5,
                complexity_penalty=0.0,
            ),
        )

        self.assertGreater(with_derivative.score, without_derivative.score)

    def test_complexity_penalty_prefers_the_smaller_equal_fit(self):
        first = _candidate(key="first", family_key="family-first")
        duplicate = _candidate(key="second", family_key="family-second")
        target = np.asarray([0.0, 4.0, 0.0])
        config = JointPhaseSearchConfig(
            derivative_weight=0.0,
            complexity_penalty=0.01,
        )

        smaller = _fit_combination(
            target=target,
            weights=np.ones(3),
            candidates=(first,),
            required_count=0,
            config=config,
        )
        larger = _fit_combination(
            target=target,
            weights=np.ones(3),
            candidates=(first, duplicate),
            required_count=0,
            config=config,
        )

        self.assertAlmostEqual(larger.score - smaller.score, 0.01, places=8)

    def test_singular_duplicate_columns_return_finite_deterministic_scales(self):
        first = _candidate(key="first", family_key="family-first")
        duplicate = _candidate(key="second", family_key="family-second")
        arguments = dict(
            target=np.asarray([0.0, 5.0, 0.0]),
            weights=np.ones(3),
            candidates=(first, duplicate),
            required_count=0,
            config=JointPhaseSearchConfig(
                derivative_weight=0.0,
                complexity_penalty=0.0,
            ),
        )

        first_fit = _fit_combination(**arguments)
        second_fit = _fit_combination(**arguments)

        self.assertTrue(np.all(np.isfinite(first_fit.scales)))
        self.assertEqual(first_fit.scales, second_fit.scales)
        self.assertAlmostEqual(sum(first_fit.scales), 5.0, places=7)


if __name__ == "__main__":
    unittest.main()
