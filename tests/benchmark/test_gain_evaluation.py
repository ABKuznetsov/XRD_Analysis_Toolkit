from __future__ import annotations

import unittest

from benchmarks.match.evaluate_gain import (
    _gain_candidate_ids,
    _gain_csv_row,
    _gain_summary,
    _joint_nonnegative_scales,
    evaluate_gain_scenario,
)
from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.scenarios import ScenarioComponent, ScenarioDefinition
from xrd_finder.finder.gain_policy import GainStage


class GainEvaluationTests(unittest.TestCase):
    def _overlap_fixture(self):
        references = {
            "accepted": tuple(ReferenceLine(value, intensity) for value, intensity in ((20, 100), (30, 80), (40, 60), (50, 40))),
            "next": tuple(ReferenceLine(value, intensity) for value, intensity in ((20.08, 100), (35, 75), (50.08, 55), (65, 35))),
            "other": tuple(ReferenceLine(value, intensity) for value, intensity in ((17, 100), (29, 70), (43, 50), (71, 30))),
        }
        scenario = ScenarioDefinition(
            "gain-overlap", "test", 23,
            (
                ScenarioComponent("accepted", "family-accepted", 0.65),
                ScenarioComponent("next", "family-next", 0.35),
            ),
            0.15, "none", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
        )
        families = {
            "accepted": "family-accepted",
            "next": "family-next",
            "other": "family-other",
        }
        return references, families, scenario

    def test_excludes_every_entry_from_the_accepted_pattern_family(self):
        references = {
            "cod-1": tuple(ReferenceLine(value, intensity) for value, intensity in ((20, 100), (30, 80), (40, 60), (50, 40))),
            "mp-2": tuple(ReferenceLine(value, intensity) for value, intensity in ((20.03, 80), (29.97, 100), (40.04, 55), (49.96, 35))),
            "other": tuple(ReferenceLine(value, intensity) for value, intensity in ((18, 100), (27, 80), (43, 60), (61, 40))),
        }

        candidate_ids = _gain_candidate_ids(references, "cod-1", fwhm=0.18)

        self.assertEqual(candidate_ids, ("other",))

    def test_ranks_known_unaccepted_phase_from_synthetic_residual(self):
        references = {
            "accepted": tuple(ReferenceLine(value, intensity) for value, intensity in ((20, 100), (30, 80), (40, 60), (50, 40))),
            "next": tuple(ReferenceLine(value, intensity) for value, intensity in ((24, 100), (36, 75), (48, 55), (60, 35))),
            "other": tuple(ReferenceLine(value, intensity) for value, intensity in ((17, 100), (29, 70), (43, 50), (71, 30))),
        }
        scenario = ScenarioDefinition(
            "gain-query", "test", 17,
            (
                ScenarioComponent("accepted", "family-accepted", 0.70),
                ScenarioComponent("next", "family-next", 0.30),
            ),
            0.15, "none", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
        )

        result = evaluate_gain_scenario(
            references,
            {"accepted": "family-accepted", "next": "family-next", "other": "family-other"},
            scenario,
            shortlist_limit=3,
        )

        self.assertEqual(result.target_family, "family-next")
        self.assertEqual(result.target_retrieval_rank, 1)
        self.assertEqual(result.target_rank, 1)
        self.assertEqual(result.split, "test")
        self.assertEqual(result.scenario_mode, "ordinary")
        self.assertIn(
            result.dominant_evidence,
            {GainStage.DIRECT, GainStage.OVERLAP, GainStage.HIDDEN},
        )

    def test_greedy_engine_preserves_existing_result_fields_and_rank(self):
        references, families, scenario = self._overlap_fixture()

        result = evaluate_gain_scenario(
            references,
            families,
            scenario,
            shortlist_limit=3,
            gain_engine="greedy",
        )

        self.assertEqual(result.gain_engine, "greedy")
        self.assertEqual(result.target_rank, 1)
        self.assertEqual(result.search_seconds, 0.0)
        self.assertEqual(result.evaluated_combinations, 0)
        self.assertEqual(result.best_combination, ())

    def test_joint_engine_recovers_overlap_phase_after_joint_refit(self):
        references, families, scenario = self._overlap_fixture()

        result = evaluate_gain_scenario(
            references,
            families,
            scenario,
            shortlist_limit=3,
            gain_engine="joint-beam",
        )

        self.assertEqual(result.gain_engine, "joint-beam")
        self.assertEqual(result.target_rank, 1)
        self.assertEqual(result.top_candidate_id, "next")

    def test_joint_engine_records_retrieval_profile_and_search_timings(self):
        references, families, scenario = self._overlap_fixture()

        result = evaluate_gain_scenario(
            references,
            families,
            scenario,
            shortlist_limit=3,
            gain_engine="joint-beam",
        )

        self.assertGreaterEqual(result.retrieval_seconds, 0.0)
        self.assertGreaterEqual(result.profile_seconds, 0.0)
        self.assertGreater(result.search_seconds, 0.0)

    def test_joint_engine_records_best_combination_and_evaluated_count(self):
        references, families, scenario = self._overlap_fixture()

        result = evaluate_gain_scenario(
            references,
            families,
            scenario,
            shortlist_limit=3,
            gain_engine="joint-beam",
        )

        self.assertGreater(result.evaluated_combinations, 1)
        self.assertIn("accepted", result.best_combination)
        self.assertIn("next", result.best_combination)

    def test_unknown_gain_engine_raises_value_error(self):
        references, families, scenario = self._overlap_fixture()

        with self.assertRaisesRegex(ValueError, "Unsupported Gain engine"):
            evaluate_gain_scenario(
                references,
                families,
                scenario,
                gain_engine="unknown",
            )

    def test_joint_summary_reports_stage_timings_combinations_and_stability(self):
        references, families, scenario = self._overlap_fixture()
        result = evaluate_gain_scenario(
            references,
            families,
            scenario,
            shortlist_limit=3,
            gain_engine="joint-beam",
        )

        summary = _gain_summary((result,))

        for label in (
            "Retrieval median/p95",
            "Profile build median/p95",
            "Beam search median/p95",
            "Evaluated combinations",
            "Pool recall",
            "Top-1/Top-5/Top-10",
            "Full-set recovery",
            "False-positive families",
            "Order stability",
            "Card-variant stability",
        ):
            self.assertIn(label, summary)

    def test_csv_row_round_trips_combination_and_family_keys(self):
        references, families, scenario = self._overlap_fixture()
        result = evaluate_gain_scenario(
            references,
            families,
            scenario,
            shortlist_limit=3,
            gain_engine="joint-beam",
        )

        row = _gain_csv_row(result)

        import json

        self.assertEqual(tuple(json.loads(row["best_combination"])), result.best_combination)
        self.assertEqual(tuple(json.loads(row["ranked_families"])), result.ranked_families)

    def test_joint_scales_recover_two_selected_profiles(self):
        first = [1.0, 0.0, 1.0, 0.0]
        second = [0.0, 1.0, 0.0, 1.0]

        scales = _joint_nonnegative_scales(
            target=[2.0, 3.0, 2.0, 3.0],
            profiles=[first, second],
        )

        self.assertAlmostEqual(scales[0], 2.0, places=6)
        self.assertAlmostEqual(scales[1], 3.0, places=6)

    def test_gain_can_refit_two_accepted_phases_before_ranking_third(self):
        references = {
            "first": tuple(ReferenceLine(value, intensity) for value, intensity in ((20, 100), (30, 80), (40, 60))),
            "second": tuple(ReferenceLine(value, intensity) for value, intensity in ((24, 100), (34, 75), (54, 55))),
            "third": tuple(ReferenceLine(value, intensity) for value, intensity in ((27, 100), (47, 70), (67, 50))),
            "other": tuple(ReferenceLine(value, intensity) for value, intensity in ((18, 100), (38, 70), (58, 50))),
        }
        scenario = ScenarioDefinition(
            "gain-stage-2", "test", 31,
            (
                ScenarioComponent("first", "family-first", 0.55),
                ScenarioComponent("second", "family-second", 0.30),
                ScenarioComponent("third", "family-third", 0.15),
            ),
            0.15, "none", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
        )

        result = evaluate_gain_scenario(
            references,
            {key: f"family-{key}" for key in references},
            scenario,
            shortlist_limit=4,
            accepted_phase_ids=("first", "second"),
        )

        self.assertEqual(result.target_phase_id, "third")
        self.assertEqual(result.target_rank, 1)
        self.assertNotIn(result.top_candidate_id, {"first", "second"})


if __name__ == "__main__":
    unittest.main()
