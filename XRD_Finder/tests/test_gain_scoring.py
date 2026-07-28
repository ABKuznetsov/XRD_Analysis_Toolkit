from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from xrd_finder.ui.gain_scoring import (
    GainPolicy,
    GainStage,
    build_gain_indexed_evidence,
    profile_residual_gain,
)


class GainPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = GainPolicy()

    def test_stage_order_is_direct_then_overlap_then_hidden(self) -> None:
        self.assertEqual(
            self.policy.select_stage(direct_count=2, overlap_count=5),
            GainStage.DIRECT,
        )
        self.assertEqual(
            self.policy.select_stage(direct_count=1, overlap_count=2),
            GainStage.OVERLAP,
        )
        self.assertEqual(
            self.policy.select_stage(direct_count=1, overlap_count=1),
            GainStage.HIDDEN,
        )

    def test_profile_support_cannot_erase_valid_line_gain(self) -> None:
        self.assertAlmostEqual(
            self.policy.combine_line_and_profile(line_gain=20.0, profile_gain=0.0),
            7.0,
        )
        self.assertAlmostEqual(
            self.policy.combine_line_and_profile(line_gain=20.0, profile_gain=None),
            20.0,
        )

    def test_hidden_gain_is_capped_by_remaining_fit(self) -> None:
        self.assertAlmostEqual(
            self.policy.hidden_gain(before_fit=80.0, presence=1.0),
            9.0,
        )
        self.assertLessEqual(
            self.policy.hidden_gain(before_fit=99.0, presence=10.0),
            1.0,
        )

    def test_profile_gain_rewards_covered_residual_and_penalizes_excess(self) -> None:
        residual = np.asarray([0.0, 2.0, 4.0, 2.0, 0.0])
        weights = np.ones_like(residual)
        good = profile_residual_gain(
            residual_target=residual,
            calculated=residual,
            weights=weights,
            residual_area=float(np.trapezoid(residual)),
            before_fit=60.0,
        )
        excess = profile_residual_gain(
            residual_target=residual,
            calculated=residual * 3.0,
            weights=weights,
            residual_area=float(np.trapezoid(residual)),
            before_fit=60.0,
        )
        self.assertGreater(good, excess)
        self.assertLessEqual(good, 40.0)

    def test_gain_evidence_assigns_each_residual_peak_once(self) -> None:
        peaks = [
            SimpleNamespace(h=1, k=0, l=0, two_theta=20.00, intensity=100.0),
            SimpleNamespace(h=2, k=0, l=0, two_theta=20.04, intensity=80.0),
            SimpleNamespace(h=1, k=1, l=0, two_theta=31.00, intensity=60.0),
        ]
        records = [
            SimpleNamespace(two_theta=20.02, area=100.0, fwhm=0.15),
            SimpleNamespace(two_theta=31.03, area=40.0, fwhm=0.18),
        ]
        evidence = build_gain_indexed_evidence(
            peaks=peaks,
            records=records,
            stage=GainStage.DIRECT,
            base_fwhm=0.18,
        )
        self.assertEqual(len(evidence.indexed_matches), 2)
        self.assertEqual(len({match[3] for match in evidence.indexed_matches}), 2)


if __name__ == "__main__":
    unittest.main()
