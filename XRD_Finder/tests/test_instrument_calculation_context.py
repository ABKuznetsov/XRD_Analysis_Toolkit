from __future__ import annotations

import unittest

import numpy as np

from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.profile_calculator import CachedProfileCalculator, array_fingerprint
from xrd_finder.instrument.models import InstrumentProfile, ResolutionProfile
from xrd_finder.services.calculated_pattern_service import HKLPeak
from xrd_finder.ui.pattern_plot_helpers import calculate_profile_for_structure


class InstrumentCalculationContextTests(unittest.TestCase):
    def _context(self, x_grid: np.ndarray, *, include_kalpha2: bool) -> CalculationContext:
        return CalculationContext(
            wavelength=1.54056,
            primary_wavelength=1.54056,
            fwhm=0.04,
            two_theta_min=float(x_grid[0]),
            two_theta_max=float(x_grid[-1]),
            x_grid_fingerprint=array_fingerprint(x_grid),
            include_kalpha2=include_kalpha2,
        )

    def test_radiation_mode_is_part_of_profile_cache_key(self) -> None:
        x_grid = np.linspace(59.5, 60.5, 2001)

        doublet = self._context(x_grid, include_kalpha2=True)
        kalpha1 = self._context(x_grid, include_kalpha2=False)

        self.assertNotEqual(doublet.profile_key, kalpha1.profile_key)

    def test_cached_profile_calculator_respects_kalpha1_only(self) -> None:
        x_grid = np.linspace(59.5, 60.5, 2001)
        peak = HKLPeak(h=1, k=0, l=0, d=1.54056, two_theta=60.0, intensity=100.0)
        calculator = CachedProfileCalculator()

        doublet = calculator.profile_from_peaks(
            [peak],
            x_grid,
            context=self._context(x_grid, include_kalpha2=True),
        )
        kalpha1 = calculator.profile_from_peaks(
            [peak],
            x_grid,
            context=self._context(x_grid, include_kalpha2=False),
        )
        kalpha2_index = int(np.argmin(np.abs(x_grid - 60.171)))

        self.assertGreater(float(doublet[kalpha2_index]), 10.0)
        self.assertLess(float(kalpha1[kalpha2_index]), 0.1)

    def test_profile_backend_is_replaceable_and_cached(self) -> None:
        class RecordingBackend:
            cache_key = "recording-v1"

            def __init__(self) -> None:
                self.calls = 0

            def calculate(self, peaks, x_grid, context):
                self.calls += 1
                return np.full_like(np.asarray(x_grid, dtype=float), 7.0)

        x_grid = np.linspace(10.0, 20.0, 101)
        context = self._context(x_grid, include_kalpha2=False)
        peak = HKLPeak(h=1, k=0, l=0, d=1.0, two_theta=15.0, intensity=100.0)
        backend = RecordingBackend()
        calculator = CachedProfileCalculator(profile_backend=backend)

        first = calculator.profile_from_peaks([peak], x_grid, context)
        second = calculator.profile_from_peaks([peak], x_grid, context)

        self.assertEqual(backend.calls, 1)
        self.assertIs(first, second)
        np.testing.assert_allclose(first, 7.0)

    def test_indexed_peak_profile_uses_instrument_tch_resolution(self) -> None:
        x_grid = np.linspace(20.0, 80.0, 6001)
        peaks = [
            HKLPeak(h=1, k=0, l=0, d=3.0, two_theta=29.75, intensity=100.0),
            HKLPeak(h=2, k=0, l=0, d=1.2, two_theta=79.82, intensity=100.0),
        ]
        context = self._context(x_grid, include_kalpha2=False)
        calculator = CachedProfileCalculator()
        constant = InstrumentProfile(
            resolution=ResolutionProfile(constant_fwhm_deg=0.04),
        )
        tch = InstrumentProfile(
            resolution=ResolutionProfile.tch(
                u=2.0,
                v=-2.0,
                w=5.0,
                x=3.9697460181849933,
                y=3.6562103496734855,
            ),
        )

        constant_profile = calculator.profile_from_peaks(
            peaks,
            x_grid,
            context,
            instrument_profile=constant,
        )
        tch_profile = calculator.profile_from_peaks(
            peaks,
            x_grid,
            context,
            instrument_profile=tch,
        )

        self.assertFalse(np.allclose(constant_profile, tch_profile))
        high_angle_tail = int(np.argmin(np.abs(x_grid - 79.92)))
        self.assertGreater(float(tch_profile[high_angle_tail]), float(constant_profile[high_angle_tail]))

    def test_structure_preview_forwards_instrument_radiation_and_width(self) -> None:
        class RecordingService:
            def __init__(self) -> None:
                self.kwargs = {}

            def calculate_profile(self, _structure, **kwargs):
                self.kwargs = kwargs
                x_grid = np.asarray(kwargs["x_grid"], dtype=float)
                return x_grid, np.zeros_like(x_grid), []

        class Structure:
            wavelength = 1.54056

        service = RecordingService()
        x_grid = np.linspace(10.0, 80.0, 101)

        calculate_profile_for_structure(
            service,
            Structure(),
            x_grid,
            fwhm=0.21,
            wavelength=0.71073,
            include_kalpha2=False,
        )

        self.assertEqual(service.kwargs["wavelength"], 0.71073)
        self.assertFalse(service.kwargs["include_kalpha2"])
        self.assertEqual(service.kwargs["fwhm"], 0.21)


if __name__ == "__main__":
    unittest.main()
