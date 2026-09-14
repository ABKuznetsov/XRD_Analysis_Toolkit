from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import numpy as np

from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.models import FinderCandidateInput, FinderInput
from xrd_finder.finder.profile_calculator import CachedProfileCalculator, array_fingerprint
from xrd_finder.finder.reference_lines import ReferenceLine, ReferenceLineSet
from xrd_finder.finder.service import FinderService
from xrd_finder.services.calculated_pattern_service import CU_KA1_WAVELENGTH


def _d_spacing(two_theta: float, wavelength: float = CU_KA1_WAVELENGTH) -> float:
    return wavelength / (2.0 * math.sin(math.radians(two_theta / 2.0)))


def _line_set(entry_id: str = "100") -> ReferenceLineSet:
    return ReferenceLineSet(
        source="COD",
        entry_id=entry_id,
        derived_version=7,
        provenance="test-index",
        lines=(
            ReferenceLine(
                d=_d_spacing(30.0),
                two_theta=30.0,
                intensity=100.0,
                normalized_intensity=100.0,
                raw_intensity=250.0,
                h=1,
                k=0,
                l=0,
                multiplicity=2,
            ),
            ReferenceLine(
                d=_d_spacing(42.0),
                two_theta=42.0,
                intensity=45.0,
                normalized_intensity=45.0,
                raw_intensity=112.5,
                h=1,
                k=1,
                l=0,
                multiplicity=4,
            ),
        ),
    )


def _context(x: np.ndarray, wavelength: float = CU_KA1_WAVELENGTH) -> CalculationContext:
    return CalculationContext(
        wavelength=wavelength,
        primary_wavelength=wavelength,
        fwhm=0.18,
        two_theta_min=float(x[0]),
        two_theta_max=float(x[-1]),
        x_grid_fingerprint=array_fingerprint(x),
        include_kalpha2=False,
    )


class IndexedCandidatePathTests(unittest.TestCase):
    def test_sql_fractional_intensities_are_converted_to_finder_percent_scale(self) -> None:
        x = np.linspace(20.0, 50.0, 601)
        lines = ReferenceLineSet.from_records(
            source="COD",
            entry_id="sql-scale",
            derived_version=9,
            provenance="local-phase-cache-v9",
            records=(
                {
                    "d": _d_spacing(30.0),
                    "two_theta": 30.0,
                    "intensity": 100.0,
                    "norm_intensity": 1.0,
                    "raw_intensity": 250.0,
                    "h": 1,
                    "k": 0,
                    "l": 0,
                    "multiplicity": 2,
                },
                {
                    "d": _d_spacing(42.0),
                    "two_theta": 42.0,
                    "intensity": 45.0,
                    "norm_intensity": 0.45,
                    "raw_intensity": 112.5,
                    "h": 1,
                    "k": 1,
                    "l": 0,
                    "multiplicity": 4,
                },
            ),
        )

        peaks = CachedProfileCalculator().peaks_from_reference_lines(lines, _context(x))

        self.assertEqual([peak.intensity for peak in peaks], [100.0, 45.0])

    def test_reference_lines_convert_to_stable_hkl_peaks(self) -> None:
        x = np.linspace(20.0, 50.0, 601)
        peaks = CachedProfileCalculator().peaks_from_reference_lines(_line_set(), _context(x))

        self.assertEqual([(peak.h, peak.k, peak.l) for peak in peaks], [(1, 0, 0), (1, 1, 0)])
        self.assertEqual([peak.two_theta for peak in peaks], [30.0, 42.0])
        self.assertEqual([peak.intensity for peak in peaks], [100.0, 45.0])
        self.assertEqual([peak.raw_intensity for peak in peaks], [250.0, 112.5])

    def test_profile_cache_distinguishes_line_set_fingerprints(self) -> None:
        x = np.linspace(20.0, 50.0, 601)
        calculator = CachedProfileCalculator()
        context = _context(x)
        peaks = calculator.peaks_from_reference_lines(_line_set(), context)

        calculator.profile_from_peaks(peaks, x, context, source_fingerprint=("COD", "100", 7))
        calculator.profile_from_peaks(peaks, x, context, source_fingerprint=("COD", "101", 7))

        self.assertEqual(calculator.cache_info()["profile_misses"], 2)

    def test_finder_ranks_indexed_candidate_without_touching_cif(self) -> None:
        x = np.linspace(20.0, 50.0, 1201)
        y = (
            10.0
            + 180.0 * np.exp(-0.5 * ((x - 30.0) / 0.10) ** 2)
            + 75.0 * np.exp(-0.5 * ((x - 42.0) / 0.10) ** 2)
        )
        service = FinderService()
        finder_input = FinderInput(
            pattern_path="",
            observed_x=x.tolist(),
            observed_y=y.tolist(),
            subtract_background=False,
            snap_peak_positions=False,
            include_kalpha2=False,
            candidates=[
                FinderCandidateInput(
                    source="COD",
                    entry_id="100",
                    name="Indexed phase",
                    reference_lines=_line_set(),
                )
            ],
        )

        with patch.object(
            service.profile_calculator,
            "candidate_structure_and_sticks",
            side_effect=AssertionError("CIF compatibility path was used"),
        ):
            result = service.run(finder_input)

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].candidate_key, "COD:100")

    def test_prefixed_entry_id_is_not_prefixed_twice(self) -> None:
        candidate = FinderCandidateInput(source="COD", entry_id="COD:100")

        self.assertEqual(FinderService()._candidate_key(candidate), "COD:100")


if __name__ == "__main__":
    unittest.main()
