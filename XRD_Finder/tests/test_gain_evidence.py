from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.finder.gain_evidence import evaluate_gain_evidence


def _peak(x: np.ndarray, center: float, height: float = 5.0) -> np.ndarray:
    return height * np.exp(-0.5 * ((x - center) / 0.08) ** 2)


class GainEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.x = np.linspace(20.0, 50.0, 6001)

    def test_two_independent_lines_are_accepted(self) -> None:
        candidate = _peak(self.x, 28.0, 6.0) + _peak(self.x, 41.0, 4.5)
        evidence = evaluate_gain_evidence(
            x=self.x,
            target=candidate,
            model_before=np.zeros_like(candidate),
            model_after=candidate,
            candidate_curve=candidate,
            peak_positions=np.asarray([28.0, 41.0]),
            peak_amplitudes=np.asarray([6.0, 4.5]),
            selected_peak_positions=np.asarray([]),
            fwhm=0.19,
            stage="direct",
            noise_sigma=0.10,
        )

        self.assertTrue(evidence.accepted)
        self.assertEqual(evidence.independent_lines, 2)

    def test_one_line_is_not_specific_enough_for_database_search(self) -> None:
        candidate = _peak(self.x, 31.0, 6.0)
        evidence = evaluate_gain_evidence(
            x=self.x,
            target=candidate,
            model_before=np.zeros_like(candidate),
            model_after=candidate,
            candidate_curve=candidate,
            peak_positions=np.asarray([31.0]),
            peak_amplitudes=np.asarray([6.0]),
            selected_peak_positions=np.asarray([]),
            fwhm=0.19,
            stage="direct",
            noise_sigma=0.10,
        )

        self.assertFalse(evidence.accepted)

    def test_overlapped_lines_are_not_direct_evidence(self) -> None:
        candidate = _peak(self.x, 27.0, 6.0) + _peak(self.x, 39.0, 5.0)
        common = dict(
            x=self.x,
            target=candidate,
            model_before=0.55 * candidate,
            model_after=candidate,
            candidate_curve=0.45 * candidate,
            peak_positions=np.asarray([27.0, 39.0]),
            peak_amplitudes=np.asarray([2.7, 2.25]),
            selected_peak_positions=np.asarray([27.0, 39.0]),
            fwhm=0.19,
            noise_sigma=0.10,
        )

        direct = evaluate_gain_evidence(stage="direct", **common)
        overlap = evaluate_gain_evidence(stage="overlap", **common)

        self.assertFalse(direct.accepted)
        self.assertTrue(overlap.accepted)

    def test_missing_testable_lines_reject_candidate(self) -> None:
        positions = np.asarray([24.0, 29.0, 34.0, 39.0, 44.0])
        candidate = sum((_peak(self.x, position, 5.0) for position in positions))
        target = _peak(self.x, 24.0, 5.0) + _peak(self.x, 29.0, 5.0)
        evidence = evaluate_gain_evidence(
            x=self.x,
            target=target,
            model_before=np.zeros_like(target),
            model_after=candidate,
            candidate_curve=candidate,
            peak_positions=positions,
            peak_amplitudes=np.full(len(positions), 5.0),
            selected_peak_positions=np.asarray([]),
            fwhm=0.19,
            stage="direct",
            noise_sigma=0.10,
        )

        self.assertFalse(evidence.accepted)
        self.assertGreaterEqual(evidence.missing_lines, 3)


if __name__ == "__main__":
    unittest.main()
