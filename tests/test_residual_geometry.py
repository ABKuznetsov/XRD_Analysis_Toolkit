from __future__ import annotations

import math
import unittest
from dataclasses import replace
from types import SimpleNamespace

from xrd_finder.services.residual_geometry import (
    build_residual_geometry_index,
    powder_d_shells,
    residual_geometry_scores,
)


class ResidualGeometryTests(unittest.TestCase):
    @staticmethod
    def _lines(*positions):
        return [
            SimpleNamespace(two_theta=position, intensity=100.0 - index * 5.0)
            for index, position in enumerate(positions)
        ]

    @staticmethod
    def _residual(*positions):
        return [
            SimpleNamespace(
                two_theta=position,
                area=100.0 - index * 5.0,
                height=80.0 - index * 4.0,
                local_snr=8.0,
            )
            for index, position in enumerate(positions)
        ]

    def test_pair_geometry_is_invariant_to_common_zero_shift(self):
        index = build_residual_geometry_index(
            {"phase": self._lines(20.0, 25.0)}, pair_bin_deg=0.08
        )

        scores, counts = residual_geometry_scores(
            index, self._residual(20.37, 25.37)
        )

        self.assertGreater(scores["phase"], 0.0)
        self.assertGreaterEqual(counts["phase"], 1)

    def test_triplet_geometry_tolerates_uniform_cell_scaling(self):
        wavelength = 1.5406
        d_spacings = (4.437, 2.976, 2.014)
        reference = [
            SimpleNamespace(d=d_spacing, intensity=100.0)
            for d_spacing in d_spacings
        ]
        index = build_residual_geometry_index(
            {"phase": reference}, triplet_ratio_bin=0.02
        )
        transformed = [
            math.degrees(
                2.0 * math.asin(wavelength / (2.0 * d_spacing * 1.004))
            )
            for d_spacing in d_spacings
        ]

        triplet_only = replace(index, shell_postings={}, pair_postings={})
        scores, counts = residual_geometry_scores(
            triplet_only, self._residual(*transformed)
        )

        self.assertGreater(scores["phase"], 0.0)
        self.assertEqual(counts["phase"], 3)

    def test_same_d_shell_fingerprint_is_independent_of_xray_tube(self):
        copper_wavelength = 1.5406
        cobalt_wavelength = 1.7890
        d_spacings = (4.437, 2.976, 2.014)
        reference = [
            SimpleNamespace(
                d=d_spacing,
                two_theta=math.degrees(
                    2.0 * math.asin(copper_wavelength / (2.0 * d_spacing))
                ),
                intensity=100.0 - index * 10.0,
            )
            for index, d_spacing in enumerate(d_spacings)
        ]
        cobalt_pattern = self._residual(
            *(
                math.degrees(
                    2.0 * math.asin(cobalt_wavelength / (2.0 * d_spacing))
                )
                for d_spacing in d_spacings
            )
        )
        index = build_residual_geometry_index({"phase": reference})

        scores, counts = residual_geometry_scores(
            index,
            cobalt_pattern,
            wavelength=cobalt_wavelength,
        )

        self.assertGreater(scores["phase"], 0.0)
        self.assertEqual(counts["phase"], 3)

    def test_neighbor_bins_tolerate_small_angle_dependent_displacement(self):
        index = build_residual_geometry_index(
            {"phase": self._lines(20.0, 25.0)}, pair_bin_deg=0.08
        )

        scores, _counts = residual_geometry_scores(
            index, self._residual(20.01, 25.06)
        )

        self.assertGreater(scores["phase"], 0.0)

    def test_coherent_geometry_outranks_a_different_line_set(self):
        index = build_residual_geometry_index(
            {
                "correct": self._lines(20.0, 25.0, 33.0),
                "different": self._lines(20.0, 27.0, 33.0),
            }
        )

        scores, counts = residual_geometry_scores(
            index, self._residual(20.2, 25.2, 33.2)
        )

        self.assertGreater(scores["correct"], scores.get("different", 0.0))
        self.assertGreater(counts["correct"], counts.get("different", 0))

    def test_zero_or_one_usable_line_has_no_geometry_votes(self):
        index = build_residual_geometry_index(
            {"phase": self._lines(20.0, 25.0, 33.0)}
        )

        for residual in ([], self._residual(20.0)):
            with self.subTest(count=len(residual)):
                self.assertEqual(residual_geometry_scores(index, residual), ({}, {}))

    def test_invalid_and_duplicate_lines_are_ignored_deterministically(self):
        index = build_residual_geometry_index(
            {
                "phase": [
                    *self._lines(20.0, 20.0, 25.0, 33.0),
                    SimpleNamespace(two_theta=math.nan, intensity=100.0),
                ]
            }
        )
        residual = [
            *self._residual(20.0, 20.0, 25.0, 33.0),
            SimpleNamespace(two_theta=math.nan, area=100.0, height=100.0),
        ]

        first = residual_geometry_scores(index, residual)
        second = residual_geometry_scores(index, residual)

        self.assertEqual(first, second)
        self.assertGreater(first[0]["phase"], 0.0)

    def test_coincident_reflections_collapse_into_one_powder_d_shell(self):
        lines = [
            SimpleNamespace(two_theta=30.0, d=2.976, intensity=60.0, multiplicity=2, h=1, k=0, l=0),
            SimpleNamespace(two_theta=30.01, d=2.975, intensity=40.0, multiplicity=4, h=0, k=1, l=0),
            SimpleNamespace(two_theta=42.0, d=2.150, intensity=30.0, multiplicity=2, h=1, k=1, l=0),
        ]

        shells = powder_d_shells(lines)

        self.assertEqual(len(shells), 2)
        self.assertEqual(shells[0].family_count, 2)
        self.assertEqual(shells[0].multiplicity, 6)
        self.assertAlmostEqual(shells[0].intensity, 100.0)

    def test_low_q_selection_keeps_first_observable_shells_not_strongest(self):
        lines = [
            SimpleNamespace(d=5.0, intensity=5.0),
            SimpleNamespace(d=4.0, intensity=10.0),
            SimpleNamespace(d=3.0, intensity=100.0),
        ]

        shells = powder_d_shells(
            lines,
            max_shells=2,
            selection="low_q",
            minimum_relative_intensity=0.05,
        )

        self.assertEqual(tuple(round(shell.d, 3) for shell in shells), (5.0, 4.0))

    def test_geometry_uses_d_spacing_and_common_zero_correction(self):
        lines = [
            SimpleNamespace(two_theta=20.0, d=4.437, intensity=100.0),
            SimpleNamespace(two_theta=30.0, d=2.976, intensity=80.0),
            SimpleNamespace(two_theta=45.0, d=2.014, intensity=60.0),
        ]
        index = build_residual_geometry_index({"phase": lines})
        shifted = self._residual(20.24, 30.24, 45.24)

        scores, counts = residual_geometry_scores(
            index,
            shifted,
            zero_shift=0.24,
        )

        self.assertGreater(scores["phase"], 0.0)
        self.assertEqual(counts["phase"], 3)

    def test_harmonic_hkl_sequence_is_weaker_than_diverse_shell_families(self):
        positions = (20.0, 32.0, 47.0)
        harmonic = [
            SimpleNamespace(two_theta=value, intensity=100.0, h=index, k=0, l=0)
            for index, value in enumerate(positions, start=1)
        ]
        diverse_hkl = ((1, 0, 0), (1, 1, 0), (1, 1, 1))
        diverse = [
            SimpleNamespace(two_theta=value, intensity=100.0, h=h, k=k, l=l)
            for value, (h, k, l) in zip(positions, diverse_hkl, strict=True)
        ]
        index = build_residual_geometry_index(
            {"harmonic": harmonic, "diverse": diverse}
        )

        scores, counts = residual_geometry_scores(
            index,
            self._residual(*positions),
        )

        self.assertGreater(scores["diverse"], scores["harmonic"])
        self.assertEqual(counts["diverse"], 3)


if __name__ == "__main__":
    unittest.main()
