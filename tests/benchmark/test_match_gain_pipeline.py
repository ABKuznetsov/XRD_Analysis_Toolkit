from __future__ import annotations

from types import SimpleNamespace
import unittest

from benchmarks.match.evaluate_gain import _select_match_candidate, evaluate_gain_scenario
from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.scenarios import ScenarioComponent, ScenarioDefinition


class MatchGainPipelineTests(unittest.TestCase):
    def test_match_selects_the_supported_family_before_gain(self):
        references = {
            "correct": tuple(
                ReferenceLine(position, intensity)
                for position, intensity in ((20.0, 100.0), (30.0, 80.0), (40.0, 60.0), (50.0, 40.0))
            ),
            "distractor": tuple(
                ReferenceLine(position, intensity)
                for position, intensity in ((23.0, 100.0), (34.0, 80.0), (46.0, 60.0), (58.0, 40.0))
            ),
        }
        observed = tuple(
            SimpleNamespace(two_theta=position, area=intensity, height=intensity, fwhm=0.12)
            for position, intensity in ((20.0, 100.0), (30.0, 80.0), (40.0, 60.0), (50.0, 40.0))
        )

        selected, rank = _select_match_candidate(
            references,
            {"correct": "correct-family", "distractor": "other-family"},
            observed,
            "correct-family",
        )

        self.assertEqual(selected, "correct")
        self.assertEqual(rank, 1)

    def test_joint_gain_keeps_the_match_accepted_phase_required(self):
        references = {
            "accepted": tuple(ReferenceLine(position, intensity) for position, intensity in ((20, 100), (30, 80), (40, 60))),
            "next": tuple(ReferenceLine(position, intensity) for position, intensity in ((25, 100), (35, 80), (45, 60))),
        }
        scenario = ScenarioDefinition(
            "pipeline-joint", "test", 41,
            (
                ScenarioComponent("accepted", "accepted-family", 0.7),
                ScenarioComponent("next", "next-family", 0.3),
            ),
            0.15, "none", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
        )

        result = evaluate_gain_scenario(
            references,
            {"accepted": "accepted-family", "next": "next-family"},
            scenario,
            accepted_from_match=True,
            gain_engine="joint-beam",
            shortlist_limit=2,
        )

        self.assertIn(result.accepted_phase_id, result.best_combination)
        self.assertNotEqual(result.top_candidate_id, result.accepted_phase_id)


if __name__ == "__main__":
    unittest.main()
