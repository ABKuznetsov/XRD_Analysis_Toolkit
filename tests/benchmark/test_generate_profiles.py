from __future__ import annotations

import unittest

import numpy as np

from benchmarks.match.generate_profiles import (
    ReferenceLine,
    benchmark_instrument_fwhm,
    generate_profile,
)
from benchmarks.match.scenarios import ScenarioComponent, ScenarioDefinition


class GenerateProfileTests(unittest.TestCase):
    def test_component_diffraction_power_scales_its_profile(self):
        references = {
            "strong": (ReferenceLine(30.0, 100.0),),
            "weak": (ReferenceLine(60.0, 100.0),),
        }
        scenario = ScenarioDefinition(
            scenario_id="diffraction-power",
            split="test",
            seed=1,
            components=(
                ScenarioComponent("strong", "strong-family", 0.5, diffraction_power=1.0),
                ScenarioComponent("weak", "weak-family", 0.5, diffraction_power=0.1),
            ),
            fwhm=0.10,
            noise="none",
            overlap="ordinary",
            background="flat",
            zero_shift=0.0,
            axis_scale=0.0,
            intensity_distortion="none",
            category="inorganic",
        )

        generated = generate_profile(references, scenario, x_grid=np.arange(20.0, 70.0, 0.01))

        strong_height = float(np.max(generated.component_profiles["strong"]))
        weak_height = float(np.max(generated.component_profiles["weak"]))
        self.assertAlmostEqual(weak_height / strong_height, 0.1, places=6)

    def test_instrument_resolution_sets_an_angle_dependent_minimum_width(self):
        self.assertGreater(benchmark_instrument_fwhm(100.0), benchmark_instrument_fwhm(20.0))
        references = {
            "phase": (
                ReferenceLine(20.0, 100.0),
                ReferenceLine(100.0, 100.0),
            )
        }
        scenario = ScenarioDefinition(
            scenario_id="instrument-floor",
            split="test",
            seed=1,
            components=(ScenarioComponent("phase", "family", 1.0, fwhm=0.04),),
            fwhm=0.04,
            noise="none",
            overlap="ordinary",
            background="flat",
            zero_shift=0.0,
            axis_scale=0.0,
            intensity_distortion="none",
            category="inorganic",
        )

        generated = generate_profile(
            references,
            scenario,
            x_grid=np.arange(15.0, 105.0, 0.002),
            instrument_resolution=True,
        )
        profile = generated.component_profiles["phase"]
        low_support = np.count_nonzero(profile[(generated.x > 19.5) & (generated.x < 20.5)] > 2500.0)
        high_support = np.count_nonzero(profile[(generated.x > 99.5) & (generated.x < 100.5)] > 2500.0)

        self.assertGreater(high_support, low_support)

    def test_components_can_have_independent_peak_widths(self):
        references = {
            "narrow": (ReferenceLine(30.0, 100.0),),
            "broad": (ReferenceLine(60.0, 100.0),),
        }
        scenario = ScenarioDefinition(
            scenario_id="phase-widths",
            split="test",
            seed=1,
            components=(
                ScenarioComponent("narrow", "narrow-family", 0.5, fwhm=0.10),
                ScenarioComponent("broad", "broad-family", 0.5, fwhm=0.50),
            ),
            fwhm=0.25,
            noise="none",
            overlap="ordinary",
            background="flat",
            zero_shift=0.0,
            axis_scale=0.0,
            intensity_distortion="none",
            category="inorganic",
        )

        generated = generate_profile(references, scenario, x_grid=np.arange(20.0, 70.0, 0.01))

        self.assertEqual(generated.component_fwhm, {"narrow": 0.10, "broad": 0.50})
        narrow_support = np.count_nonzero(generated.component_profiles["narrow"] > 250.0)
        broad_support = np.count_nonzero(generated.component_profiles["broad"] > 250.0)
        self.assertGreater(broad_support, narrow_support * 3)

    def test_lattice_scale_is_phase_specific_but_zero_shift_is_global(self):
        wavelength = 1.5406
        cell = 4.0

        def line(h, k, l, intensity):
            d_spacing = cell / np.sqrt(h * h + k * k + l * l)
            two_theta = np.rad2deg(2.0 * np.arcsin(wavelength / (2.0 * d_spacing)))
            return ReferenceLine(two_theta, intensity, d_spacing, h, k, l, 1)

        indexed = tuple(
            line(h, k, l, intensity)
            for (h, k, l), intensity in zip(
                ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1)),
                (100, 90, 80, 70, 60, 50, 40),
                strict=True,
            )
        )
        references = {
            "fixed": indexed,
            "scaled": indexed,
        }
        scenario = ScenarioDefinition(
            scenario_id="phase-shifts",
            split="test",
            seed=2,
            components=(
                ScenarioComponent("fixed", "fixed-family", 0.5, fwhm=0.08),
                ScenarioComponent(
                    "scaled",
                    "scaled-family",
                    0.5,
                    reciprocal_strain=(0.006, -0.004, 0.002, 0.0, 0.0, 0.0),
                    fwhm=0.08,
                ),
            ),
            fwhm=0.25,
            noise="none",
            overlap="ordinary",
            background="flat",
            zero_shift=0.22,
            axis_scale=0.0,
            intensity_distortion="none",
            category="inorganic",
        )

        generated = generate_profile(references, scenario, x_grid=np.arange(15.0, 75.0, 0.002))
        fixed = generated.component_profiles["fixed"]
        scaled = generated.component_profiles["scaled"]
        base_position = indexed[0].two_theta + 0.22
        fixed_x = generated.x[np.argmax(fixed)]
        scaled_x = generated.x[np.argmax(scaled)]

        self.assertAlmostEqual(float(fixed_x), base_position, delta=0.01)
        self.assertGreater(float(scaled_x), float(fixed_x))
        self.assertEqual(
            generated.component_reciprocal_strain["fixed"],
            (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        )
        self.assertEqual(
            generated.component_reciprocal_strain["scaled"],
            (0.006, -0.004, 0.002, 0.0, 0.0, 0.0),
        )

    def test_generation_is_deterministic_and_preserves_minor_component(self):
        references = {
            "major": (ReferenceLine(20.0, 100.0), ReferenceLine(30.0, 60.0), ReferenceLine(40.0, 40.0)),
            "minor": (ReferenceLine(25.0, 100.0), ReferenceLine(35.0, 50.0), ReferenceLine(45.0, 20.0)),
        }
        scenario = ScenarioDefinition(
            scenario_id="test",
            split="train",
            seed=42,
            components=(
                ScenarioComponent("major", "major-family", 0.92),
                ScenarioComponent("minor", "minor-family", 0.08),
            ),
            fwhm=0.30,
            noise="none",
            overlap="ordinary",
            background="flat",
            zero_shift=0.10,
            axis_scale=0.005,
            intensity_distortion="none",
            category="inorganic",
        )

        first = generate_profile(references, scenario)
        second = generate_profile(references, scenario)

        np.testing.assert_array_equal(first.x, second.x)
        np.testing.assert_array_equal(first.y, second.y)
        self.assertAlmostEqual(first.component_fractions["minor"], 0.08)
        self.assertGreater(len(first.observed_records), 0)
        self.assertAlmostEqual(first.fwhm, 0.30)

    def test_high_noise_broad_profile_is_kept_when_no_peaks_are_recovered(self):
        references = {"phase": (ReferenceLine(30.0, 1.0), ReferenceLine(40.0, 0.8), ReferenceLine(50.0, 0.6))}
        scenario = ScenarioDefinition(
            scenario_id="hard",
            split="test",
            seed=7,
            components=(ScenarioComponent("phase", "family", 1.0),),
            fwhm=0.50,
            noise="high",
            overlap="ordinary",
            background="curved",
            zero_shift=0.0,
            axis_scale=0.0,
            intensity_distortion="strong",
            category="inorganic",
        )

        generated = generate_profile(references, scenario)

        self.assertEqual(generated.scenario_id, "hard")
        self.assertEqual(len(generated.x), len(generated.y))
        self.assertTrue(np.all(np.isfinite(generated.y)))


if __name__ == "__main__":
    unittest.main()
