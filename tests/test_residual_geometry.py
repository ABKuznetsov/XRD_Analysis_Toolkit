from __future__ import annotations

import math
import unittest
from dataclasses import replace
from types import SimpleNamespace

from xrd_finder.services.residual_geometry import (
    build_residual_geometry_index,
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

    def test_triplet_geometry_tolerates_small_common_affine_change(self):
        index = build_residual_geometry_index(
            {"phase": self._lines(20.0, 30.0, 45.0)}, ratio_bin=0.02
        )
        transformed = [value * 1.004 + 0.31 for value in (20.0, 30.0, 45.0)]

        triplet_only = replace(index, pair_postings={})
        scores, counts = residual_geometry_scores(
            triplet_only, self._residual(*transformed)
        )

        self.assertGreater(scores["phase"], 0.0)
        self.assertEqual(counts["phase"], 1)

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


if __name__ == "__main__":
    unittest.main()
