from __future__ import annotations

import unittest

from benchmarks.match.gain_scenarios import (
    GainScenarioConfig,
    build_gain_scenario_manifest,
    build_joint_gain_stress_manifest,
)
from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.splits import PhaseDescriptor, SplitAssignment
from xrd_finder.services.phase_pattern_equivalence import phase_patterns_equivalent


class GainScenarioTests(unittest.TestCase):
    def test_joint_stress_variants_isolate_order_card_noise_and_overlap_dimensions(self):
        phases = (
            PhaseDescriptor("card-na", "accepted-family", "inorganic"),
            PhaseDescriptor("card-ca", "accepted-variant-family", "inorganic"),
            PhaseDescriptor("target", "target-family", "inorganic"),
            PhaseDescriptor("helper-a", "helper-a-family", "inorganic"),
            PhaseDescriptor("helper-b", "helper-b-family", "inorganic"),
        )
        assignments = tuple(
            SplitAssignment(item.phase_id, item.family_id, "validation") for item in phases
        )
        references = {
            "card-na": self._lines((20, 30, 40, 50), (100, 80, 60, 40)),
            "card-ca": self._lines((20.02, 30.02, 40.02, 50.02), (55, 100, 35, 70)),
            "target": self._lines((20.08, 35, 50.08, 65), (100, 45, 35, 18)),
            "helper-a": self._lines((24, 34, 44, 54), (100, 70, 50, 30)),
            "helper-b": self._lines((27, 37, 47, 57), (100, 70, 50, 30)),
        }

        cases = build_joint_gain_stress_manifest(phases, assignments, references, seed=71)
        by_kind = {}
        for case in cases:
            by_kind.setdefault(case.variant_kind, []).append(case)

        self.assertEqual({case.target_family for case in cases}, {"target-family"})
        self.assertEqual(len(by_kind["accepted-order"]), 2)
        self.assertEqual(
            by_kind["accepted-order"][0].scenario,
            by_kind["accepted-order"][1].scenario,
        )
        self.assertEqual(
            by_kind["accepted-order"][0].accepted_phase_ids,
            tuple(reversed(by_kind["accepted-order"][1].accepted_phase_ids)),
        )
        self.assertEqual(len(by_kind["card-variant"]), 2)
        self.assertNotEqual(
            by_kind["card-variant"][0].accepted_phase_ids,
            by_kind["card-variant"][1].accepted_phase_ids,
        )
        self.assertIn("noise-only", by_kind)
        self.assertIn("weak-overlap", by_kind)

    def test_builds_deterministic_targeted_modes_without_crossing_splits(self):
        phases = tuple(
            PhaseDescriptor(f"p{index}", f"f{index}", "inorganic")
            for index in range(9)
        )
        assignments = tuple(
            SplitAssignment(phase.phase_id, phase.family_id, ("train", "validation", "test")[index // 3])
            for index, phase in enumerate(phases)
        )
        references = {
            "p0": self._lines((20, 30, 40, 50), (100, 80, 60, 40)),
            "p1": self._lines((20.05, 30.05, 40.05, 50.05), (100, 70, 50, 30)),
            "p2": self._lines((23, 37, 53, 69), (100, 6, 4, 2)),
            "p3": self._lines((21, 31, 41, 51), (100, 80, 60, 40)),
            "p4": self._lines((21.05, 31.05, 41.05, 51.05), (100, 70, 50, 30)),
            "p5": self._lines((24, 38, 54, 70), (100, 6, 4, 2)),
            "p6": self._lines((22, 32, 42, 52), (100, 80, 60, 40)),
            "p7": self._lines((22.05, 32.05, 42.05, 52.05), (100, 70, 50, 30)),
            "p8": self._lines((25, 39, 55, 71), (100, 6, 4, 2)),
        }
        config = GainScenarioConfig(seed=19, scenarios_per_mode=1)

        first = build_gain_scenario_manifest(phases, assignments, references, config)
        second = build_gain_scenario_manifest(phases, assignments, references, config)

        self.assertEqual(first, second)
        self.assertEqual({item.split for item in first}, {"train", "validation", "test"})
        self.assertEqual(
            {item.overlap for item in first},
            {"direct", "overlap", "hidden", "sparse", "low_fraction"},
        )
        split_by_phase = {item.phase_id: item.split for item in assignments}
        for scenario in first:
            self.assertEqual(
                {split_by_phase[component.phase_id] for component in scenario.components},
                {scenario.split},
            )
            accepted, target = scenario.components
            self.assertFalse(
                phase_patterns_equivalent(
                    references[accepted.phase_id],
                    references[target.phase_id],
                    fwhm=scenario.fwhm,
                )
            )

    @staticmethod
    def _lines(positions, intensities):
        return tuple(
            ReferenceLine(float(position), float(intensity))
            for position, intensity in zip(positions, intensities, strict=True)
        )


if __name__ == "__main__":
    unittest.main()
