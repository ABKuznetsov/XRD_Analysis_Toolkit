from __future__ import annotations

import math
import unittest

from xrd_finder.core.structure import CellParameters
from xrd_finder.finder.cell_parameter_estimator import FastCellParameterEstimator
from xrd_finder.finder.models import ObservedPeak
from xrd_finder.services.calculated_pattern_service import CU_KA1_WAVELENGTH, HKLPeak


def _two_theta(d_spacing: float) -> float:
    argument = CU_KA1_WAVELENGTH / (2.0 * d_spacing)
    return math.degrees(2.0 * math.asin(argument))


def _tetragonal_d(a: float, c: float, h: int, k: int, l: int) -> float:
    reciprocal_square = (h * h + k * k) / (a * a) + (l * l) / (c * c)
    return 1.0 / math.sqrt(reciprocal_square)


def _calculated_peaks(cell: CellParameters) -> list[HKLPeak]:
    hkls = ((1, 0, 1), (1, 1, 0), (0, 0, 2), (2, 0, 0), (1, 1, 2), (2, 1, 1))
    peaks = []
    for index, (h, k, l) in enumerate(hkls):
        d_spacing = _tetragonal_d(float(cell.a), float(cell.c), h, k, l)
        peaks.append(
            HKLPeak(
                h=h,
                k=k,
                l=l,
                d=d_spacing,
                two_theta=_two_theta(d_spacing),
                intensity=100.0 - 10.0 * index,
                multiplicity=1,
                raw_intensity=100.0 - 10.0 * index,
            )
        )
    return peaks


class FastCellParameterEstimatorTests(unittest.TestCase):
    def test_estimates_independent_tetragonal_cell_parameters(self) -> None:
        initial = CellParameters(a=7.70, b=7.70, c=5.00, alpha=90.0, beta=90.0, gamma=90.0)
        target = CellParameters(a=7.78, b=7.78, c=4.94, alpha=90.0, beta=90.0, gamma=90.0)
        calculated = _calculated_peaks(initial)
        zero_shift = 0.11
        observed = [
            ObservedPeak(
                two_theta=(
                    _two_theta(_tetragonal_d(float(target.a), float(target.c), peak.h, peak.k, peak.l))
                    + zero_shift
                ),
                intensity=peak.intensity * 12.0,
                fwhm=0.16,
            )
            for peak in calculated
        ]

        estimate = FastCellParameterEstimator().estimate(
            initial_cell=initial,
            calculated_peaks=calculated,
            observed_peaks=observed,
            wavelength=CU_KA1_WAVELENGTH,
            zero_shift_deg=zero_shift,
            tolerance_deg=0.8,
        )

        self.assertIsNotNone(estimate)
        assert estimate is not None
        self.assertEqual(estimate.crystal_system, "tetragonal")
        self.assertGreaterEqual(estimate.matched_peaks, 5)
        self.assertLess(estimate.fitted_rms_deg, estimate.initial_rms_deg * 0.25)
        self.assertAlmostEqual(float(estimate.cell.a), float(target.a), places=2)
        self.assertAlmostEqual(float(estimate.cell.b), float(target.b), places=2)
        self.assertAlmostEqual(float(estimate.cell.c), float(target.c), places=2)

    def test_returns_none_when_too_few_indexed_peaks_match(self) -> None:
        initial = CellParameters(a=7.70, b=7.70, c=5.00, alpha=90.0, beta=90.0, gamma=90.0)
        calculated = _calculated_peaks(initial)[:2]
        observed = [
            ObservedPeak(two_theta=peak.two_theta + 0.1, intensity=100.0, fwhm=0.16)
            for peak in calculated
        ]

        estimate = FastCellParameterEstimator().estimate(
            initial_cell=initial,
            calculated_peaks=calculated,
            observed_peaks=observed,
            wavelength=CU_KA1_WAVELENGTH,
            tolerance_deg=0.8,
        )

        self.assertIsNone(estimate)


if __name__ == "__main__":
    unittest.main()
