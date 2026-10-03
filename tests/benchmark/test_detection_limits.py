from __future__ import annotations

import unittest

import numpy as np

from benchmarks.match.detection_limits import (
    build_detection_manifest,
    measure_component_observability,
)
from benchmarks.match.evaluate_detection_limits import build_sequential_gain_requests
from benchmarks.match.generate_profiles import DetectedLine, GeneratedPattern
from benchmarks.match.scenarios import ScenarioComponent, ScenarioDefinition


def scenario(*components):
    return ScenarioDefinition(
        scenario_id="test-0001",
        split="test",
        seed=1,
        components=tuple(components),
        fwhm=0.10,
        noise="low",
        overlap="ordinary",
        background="flat",
        zero_shift=0.0,
        axis_scale=0.0,
        intensity_distortion="none",
        category="inorganic",
    )


class DetectionLimitTests(unittest.TestCase):
    def test_sequential_gain_requests_grow_the_accepted_phase_set(self):
        scenario = ScenarioDefinition(
            "four", "test", 7,
            tuple(
                ScenarioComponent(f"p{index}", f"f{index}", fraction)
                for index, fraction in enumerate((0.52, 0.20, 0.20, 0.08), start=1)
            ),
            0.15, "low", "ordinary", "flat", 0.0, 0.0, "none", "inorganic",
        )

        requests = build_sequential_gain_requests((scenario,))

        self.assertEqual([item[2] for item in requests], [1, 2, 3])
        self.assertEqual(requests[0][1], ("p1",))
        self.assertEqual(requests[1][1], ("p1", "p2"))
        self.assertEqual(requests[2][1], ("p1", "p2", "p3"))

    def test_manifest_sweeps_minor_diffraction_power_only_for_mixtures(self):
        single = scenario(ScenarioComponent("a", "fa", 1.0))
        mixture = scenario(
            ScenarioComponent("a", "fa", 0.8),
            ScenarioComponent("b", "fb", 0.2),
        )

        manifest = build_detection_manifest((single, mixture), power_levels=(0.1, 1.0))

        self.assertEqual(len(manifest), 3)
        self.assertEqual(manifest[0].components[0].diffraction_power, 1.0)
        self.assertEqual(
            [item.components[1].diffraction_power for item in manifest[1:]],
            [0.1, 1.0],
        )

    def test_observability_requires_detected_lines_above_noise(self):
        x = np.arange(0.0, 10.0, 0.1)
        component = np.zeros_like(x)
        component[20] = 20.0
        component[70] = 15.0
        clean = component.copy()
        background = np.full_like(x, 5.0)
        noise = np.tile(np.asarray((-1.0, 1.0)), len(x) // 2)
        generated = GeneratedPattern(
            scenario_id="visibility",
            x=x,
            y=clean + background + noise,
            background=background,
            clean_y=clean,
            component_profiles={"phase": component},
            component_fractions={"phase": 0.2},
            component_diffraction_power={"phase": 0.3},
            component_fwhm={"phase": 0.1},
            component_reciprocal_strain={"phase": (0.0,) * 6},
            ground_truth_positions=(2.0, 7.0),
            observed_records=(
                DetectedLine(2.0, 20.0, 0.1, 20.0),
                DetectedLine(7.0, 15.0, 0.1, 15.0),
            ),
            fwhm=0.1,
        )

        result = measure_component_observability(generated, "phase")

        self.assertTrue(result.observable)
        self.assertEqual(result.visible_lines, 2)
        self.assertAlmostEqual(result.nominal_signal_fraction, 0.06)

    def test_component_below_noise_is_not_observable(self):
        x = np.arange(0.0, 10.0, 0.1)
        component = np.zeros_like(x)
        component[20] = 1.0
        component[70] = 0.8
        background = np.full_like(x, 5.0)
        noise = np.tile(np.asarray((-2.0, 2.0)), len(x) // 2)
        generated = GeneratedPattern(
            scenario_id="invisible",
            x=x,
            y=component + background + noise,
            background=background,
            clean_y=component,
            component_profiles={"phase": component},
            component_fractions={"phase": 0.2},
            component_diffraction_power={"phase": 0.1},
            component_fwhm={"phase": 0.1},
            component_reciprocal_strain={"phase": (0.0,) * 6},
            ground_truth_positions=(2.0, 7.0),
            observed_records=(
                DetectedLine(2.0, 1.0, 0.1, 1.0),
                DetectedLine(7.0, 0.8, 0.1, 0.8),
            ),
            fwhm=0.1,
        )

        result = measure_component_observability(generated, "phase")

        self.assertFalse(result.observable)
        self.assertEqual(result.visible_lines, 0)


if __name__ == "__main__":
    unittest.main()
