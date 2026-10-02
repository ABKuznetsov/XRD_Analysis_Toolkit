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


def _line_candidate(
    x: np.ndarray,
    *,
    key: str,
    family_key: str,
    lines: tuple[tuple[int, float], ...],
) -> JointPhaseCandidate:
    profile = np.zeros(len(x), dtype=float)
    for index, height in lines:
        profile[index] = height
    return JointPhaseCandidate(
        key=key,
        family_key=family_key,
        profile=profile,
        peak_positions=np.asarray([x[index] for index, _height in lines]),
        peak_amplitudes=np.asarray([height for _index, height in lines]),
    )


def _permissive_config(*, max_added_phases: int = 2) -> JointPhaseSearchConfig:
    return JointPhaseSearchConfig(
        beam_width=5,
        max_added_phases=max_added_phases,
        derivative_weight=0.0,
        complexity_penalty=0.0,
        minimum_phase_snr=0.0,
        minimum_relative_improvement=0.0,
        minimum_reported_gain=0.0,
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


class JointPhaseBeamSearchTests(unittest.TestCase):
    def test_candidate_iteration_order_does_not_change_ranked_families(self):
        x = np.linspace(10.0, 30.0, 9)
        first = _line_candidate(
            x,
            key="first",
            family_key="family-first",
            lines=((1, 4.0), (6, 1.0)),
        )
        second = _line_candidate(
            x,
            key="second",
            family_key="family-second",
            lines=((3, 3.0), (7, 1.0)),
        )
        target = first.profile + second.profile
        arguments = dict(
            x=x,
            target=target,
            weights=np.ones(len(x)),
            config=_permissive_config(),
        )

        forward = search_phase_combinations(
            candidates=(first, second),
            **arguments,
        )
        reverse = search_phase_combinations(
            candidates=(second, first),
            **arguments,
        )

        forward_ranking = tuple(
            (gain.family_key, gain.gain, gain.reportable)
            for gain in forward.candidate_gains
        )
        reverse_ranking = tuple(
            (gain.family_key, gain.gain, gain.reportable)
            for gain in reverse.candidate_gains
        )
        self.assertEqual(
            {item[0] for item in forward_ranking},
            {"family-first", "family-second"},
        )
        self.assertEqual(forward_ranking, reverse_ranking)

    def test_required_phase_order_does_not_change_best_combination(self):
        x = np.linspace(10.0, 30.0, 9)
        first = _line_candidate(
            x,
            key="accepted-a",
            family_key="family-a",
            lines=((1, 4.0),),
        )
        second = _line_candidate(
            x,
            key="accepted-b",
            family_key="family-b",
            lines=((3, 3.0),),
        )
        additional = _line_candidate(
            x,
            key="additional",
            family_key="family-additional",
            lines=((5, 2.0), (7, 1.0)),
        )
        target = first.profile + second.profile + additional.profile
        arguments = dict(
            x=x,
            target=target,
            weights=np.ones(len(x)),
            candidates=(first, second, additional),
            config=_permissive_config(max_added_phases=1),
        )

        first_order = search_phase_combinations(
            required_keys=("accepted-a", "accepted-b"),
            **arguments,
        )
        second_order = search_phase_combinations(
            required_keys=("accepted-b", "accepted-a"),
            **arguments,
        )

        self.assertEqual(
            {gain.family_key for gain in first_order.candidate_gains},
            {"family-additional"},
        )
        self.assertEqual(first_order.combinations, second_order.combinations)
        self.assertEqual(first_order.candidate_gains, second_order.candidate_gains)

    def test_same_family_cards_never_share_a_combination(self):
        x = np.linspace(10.0, 30.0, 9)
        first_card = _line_candidate(
            x,
            key="card-a",
            family_key="same-family",
            lines=((1, 4.0), (5, 1.0)),
        )
        second_card = _line_candidate(
            x,
            key="card-b",
            family_key="same-family",
            lines=((1, 4.0), (7, 1.0)),
        )

        result = search_phase_combinations(
            x=x,
            target=first_card.profile + second_card.profile,
            weights=np.ones(len(x)),
            candidates=(first_card, second_card),
            config=_permissive_config(),
        )

        for combination in result.combinations:
            self.assertEqual(
                len(combination.family_keys),
                len(set(combination.family_keys)),
            )
        self.assertTrue(
            any(combination.family_keys == ("same-family",) for combination in result.combinations)
        )

    def test_accepted_family_is_not_returned_as_gain_candidate(self):
        x = np.linspace(10.0, 30.0, 9)
        accepted = _line_candidate(
            x,
            key="accepted",
            family_key="accepted-family",
            lines=((1, 4.0), (5, 1.0)),
        )
        duplicate_card = _line_candidate(
            x,
            key="other-entry",
            family_key="accepted-family",
            lines=((1, 4.0), (5, 1.0)),
        )
        other = _line_candidate(
            x,
            key="other-phase",
            family_key="other-family",
            lines=((7, 2.0),),
        )

        result = search_phase_combinations(
            x=x,
            target=accepted.profile + other.profile,
            weights=np.ones(len(x)),
            candidates=(accepted, duplicate_card, other),
            required_keys=("accepted",),
            config=_permissive_config(),
        )

        self.assertIn(
            "other-family",
            {gain.family_key for gain in result.candidate_gains},
        )
        self.assertNotIn(
            "accepted-family",
            {gain.family_key for gain in result.candidate_gains},
        )

    def test_overlap_candidate_can_win_without_independent_direct_gate(self):
        x = np.linspace(10.0, 30.0, 11)
        accepted = _line_candidate(
            x,
            key="accepted",
            family_key="accepted-family",
            lines=((4, 8.0), (8, 2.0)),
        )
        overlap = _line_candidate(
            x,
            key="overlap",
            family_key="overlap-family",
            lines=((4, 6.0), (9, 1.0)),
        )

        result = search_phase_combinations(
            x=x,
            target=accepted.profile + 0.5 * overlap.profile,
            weights=np.ones(len(x)),
            candidates=(accepted, overlap),
            required_keys=("accepted",),
            config=_permissive_config(max_added_phases=1),
        )

        gain = next(
            item for item in result.candidate_gains
            if item.family_key == "overlap-family"
        )
        self.assertTrue(gain.reportable)
        self.assertGreater(gain.gain, 0.0)

    def test_noise_only_candidate_fails_phase_snr_and_reporting_floor(self):
        rng = np.random.default_rng(41)
        x = np.linspace(10.0, 50.0, 401)
        target = rng.normal(0.0, 1.0, size=len(x))
        index = int(np.argmax(target))
        candidate = _line_candidate(
            x,
            key="noise-line",
            family_key="noise-family",
            lines=((index, 1.0),),
        )

        result = search_phase_combinations(
            x=x,
            target=target,
            weights=np.ones(len(x)),
            candidates=(candidate,),
            config=JointPhaseSearchConfig(
                derivative_weight=0.0,
                complexity_penalty=0.0,
                minimum_relative_improvement=0.0,
                minimum_reported_gain=0.0,
            ),
        )

        gain = result.candidate_gains[0]
        self.assertFalse(gain.reportable)
        self.assertLess(gain.phase_snr, 3.0)
        self.assertEqual(gain.rejection_reason, "phase_snr_below_threshold")

    def test_candidate_gain_uses_parent_to_child_edge_not_companion_credit(self):
        x = np.linspace(10.0, 30.0, 9)
        major = _line_candidate(
            x,
            key="major",
            family_key="family-major",
            lines=((1, 5.0), (3, 3.0)),
        )
        minor = _line_candidate(
            x,
            key="minor",
            family_key="family-minor",
            lines=((5, 2.0), (7, 1.0)),
        )
        result = search_phase_combinations(
            x=x,
            target=major.profile + minor.profile,
            weights=np.ones(len(x)),
            candidates=(major, minor),
            config=_permissive_config(),
        )
        minor_gain = next(
            gain for gain in result.candidate_gains
            if gain.family_key == "family-minor"
        )
        full = next(
            combination for combination in result.combinations
            if set(combination.family_keys) == {"family-major", "family-minor"}
        )
        baseline_to_full = (
            100.0
            * (result.baseline.score - full.score)
            / result.baseline.score
        )

        self.assertLess(minor_gain.gain, baseline_to_full)
        self.assertIn("family-minor", minor_gain.supporting_family_keys)

    def test_beam_stops_when_no_child_reaches_minimum_improvement(self):
        x = np.linspace(10.0, 30.0, 9)
        unexplained = _line_candidate(
            x,
            key="unexplained",
            family_key="unexplained-family",
            lines=((7, 2.0),),
        )
        target = np.zeros(len(x))
        target[1] = 5.0

        result = search_phase_combinations(
            x=x,
            target=target,
            weights=np.ones(len(x)),
            candidates=(unexplained,),
            config=JointPhaseSearchConfig(
                derivative_weight=0.0,
                minimum_phase_snr=0.0,
            ),
        )

        self.assertEqual(result.combinations, (result.baseline,))
        self.assertEqual(result.candidate_gains[0].gain, 0.0)
        self.assertEqual(
            result.candidate_gains[0].rejection_reason,
            "minimum_improvement",
        )


if __name__ == "__main__":
    unittest.main()
