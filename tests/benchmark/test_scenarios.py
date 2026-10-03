from __future__ import annotations

import unittest

from benchmarks.match.scenarios import ScenarioConfig, build_scenario_manifest
from benchmarks.match.splits import PhaseDescriptor, assign_split_families


class ScenarioTests(unittest.TestCase):
    def test_manifest_covers_phase_count_fwhm_minor_fraction_and_organic_strata(self):
        phases = [
            PhaseDescriptor(f"phase-{index}", f"family-{index}", "organic" if index in {2, 9, 16} else "inorganic")
            for index in range(24)
        ]
        assignments = assign_split_families(phases, seed=5036)

        scenarios = build_scenario_manifest(phases, assignments, ScenarioConfig(seed=5036))

        self.assertEqual({len(item.components) for item in scenarios}, {1, 2, 3, 4})
        self.assertEqual({item.fwhm for item in scenarios}, {0.08, 0.15, 0.30, 0.50})
        self.assertEqual({item.noise for item in scenarios}, {"none", "low", "medium", "high"})
        combinations = {
            (item.split, item.fwhm, item.noise, len(item.components))
            for item in scenarios
        }
        self.assertEqual(len(combinations), 3 * 4 * 4 * 4)
        self.assertTrue(any(min(component.fraction for component in item.components) == 0.08 for item in scenarios))
        self.assertTrue(any(item.category == "organic" for item in scenarios))
        self.assertEqual(scenarios, build_scenario_manifest(phases, assignments, ScenarioConfig(seed=5036)))


if __name__ == "__main__":
    unittest.main()
