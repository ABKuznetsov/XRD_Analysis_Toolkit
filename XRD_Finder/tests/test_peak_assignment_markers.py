from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.finder.assignment_builder import AssignmentBuilder
from xrd_finder.finder.models import FinderCandidateResult, ObservedPeak, PeakStatus
from xrd_finder.services.calculated_pattern_service import HKLPeak
from xrd_finder.ui.peak_marker_renderer import _is_significant_peak


def _candidate(key: str, contribution: float) -> FinderCandidateResult:
    return FinderCandidateResult(
        candidate_key=key,
        entry_id=key,
        name=key,
        formula=key,
        source="USER",
        scale=1.0,
        two_theta=[28.8, 29.0, 29.2],
        profile=[0.0, contribution, 0.0],
    )


def _peak(intensity: float = 50.0) -> HKLPeak:
    return HKLPeak(
        h=1,
        k=0,
        l=0,
        d=3.0,
        two_theta=29.0,
        intensity=float(intensity),
        raw_intensity=float(intensity),
    )


class AssignmentContributionTests(unittest.TestCase):
    def test_tiny_fitted_contribution_does_not_create_false_overlap(self) -> None:
        observed = ObservedPeak(two_theta=29.0, intensity=1000.0, fwhm=0.12)
        assigned = AssignmentBuilder().assign_observed_peaks(
            [observed],
            [
                (_candidate("dominant", 800.0), [_peak(55.0)]),
                (_candidate("weak", 10.0), [_peak(100.0)]),
            ],
            tolerance=0.2,
        )

        self.assertEqual(assigned[0].status, PeakStatus.MATCHED)
        self.assertEqual(
            [assignment.candidate_key for assignment in assigned[0].assignments],
            ["dominant"],
        )

    def test_two_material_fitted_contributions_remain_overlapping(self) -> None:
        observed = ObservedPeak(two_theta=29.0, intensity=1000.0, fwhm=0.12)
        assigned = AssignmentBuilder().assign_observed_peaks(
            [observed],
            [
                (_candidate("first", 800.0), [_peak(55.0)]),
                (_candidate("second", 100.0), [_peak(25.0)]),
            ],
            tolerance=0.2,
        )

        self.assertEqual(assigned[0].status, PeakStatus.OVERLAPPING)
        self.assertEqual(len(assigned[0].assignments), 2)


class MarkerSignificanceTests(unittest.TestCase):
    def test_supported_peak_survives_structured_local_neighbourhood(self) -> None:
        x = np.arange(20.0, 30.0, 0.01)
        corrected_y = np.zeros_like(x)
        local = (x >= 26.2) & (x <= 27.1)
        corrected_y[local] = 12.0 * np.sin((x[local] - 26.2) * 2.0 * np.pi / 0.07)
        corrected_y += 40.0 * np.exp(-0.5 * ((x - 26.65) / 0.025) ** 2)
        peak_index = int(np.argmin(np.abs(x - 26.65)))

        # Mirrors the real 0.6BaGeO3-0.4BaSiO3 pattern: the supported
        # BaSiO3 maximum has about 56 counts of signal while the global
        # robust noise estimate is about 9.5 counts.
        self.assertTrue(_is_significant_peak(x, corrected_y, peak_index, sigma=9.5))


if __name__ == "__main__":
    unittest.main()
