from __future__ import annotations

import math
from pathlib import Path
import sys
import types
import unittest

import numpy as np

try:
    import cristma.diffraction  # noqa: F401
except ModuleNotFoundError:
    diffraction = types.ModuleType("cristma.diffraction")

    class ConstantWidthProfile:
        def __init__(self, fwhm_deg: float):
            self.fwhm_deg = float(fwhm_deg)

    class TchProfile:
        def __init__(self, **kwargs):
            self.u = float(kwargs.get("u", 0.0))
            self.v = float(kwargs.get("v", 0.0))
            self.w = float(kwargs.get("w", 0.0))
            self.x = float(kwargs.get("x", 0.0))
            self.y = float(kwargs.get("y", 0.0))

        def fwhm_deg_at(self, two_theta: float) -> float:
            theta = math.radians(float(two_theta) / 2.0)
            gaussian = max(
                self.u * math.tan(theta) ** 2 + self.v * math.tan(theta) + self.w,
                0.0,
            ) ** 0.5
            lorentzian = self.x / max(math.cos(theta), 1.0e-9) + self.y * math.tan(theta)
            return gaussian + max(lorentzian, 0.0)

    diffraction.ConstantWidthProfile = ConstantWidthProfile
    diffraction.TchProfile = TchProfile
    cristma = types.ModuleType("cristma")
    cristma.diffraction = diffraction
    sys.modules["cristma"] = cristma
    sys.modules["cristma.diffraction"] = diffraction

    instrument_package = types.ModuleType("xrd_finder.instrument")
    instrument_package.__path__ = [
        str(Path(__file__).resolve().parents[1] / "xrd_finder" / "instrument")
    ]
    sys.modules["xrd_finder.instrument"] = instrument_package

from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.profile_backend import (
    FinderPeakProfileBackend,
    instrument_profile_with_width_floor,
)
from xrd_finder.instrument.models import InstrumentProfile, RadiationProfile, ResolutionProfile
from xrd_finder.services.calculated_pattern_service import HKLPeak


def measured_fwhm(x: np.ndarray, y: np.ndarray) -> float:
    peak_index = int(np.argmax(y))
    half_height = float(y[peak_index]) * 0.5
    left = peak_index
    while left > 0 and y[left] >= half_height:
        left -= 1
    right = peak_index
    while right < len(y) - 1 and y[right] >= half_height:
        right += 1
    return float(x[right] - x[left])


class InstrumentProfileWidthFloorTests(unittest.TestCase):
    def test_tch_instrument_floor_changes_with_angle(self):
        instrument = InstrumentProfile(
            radiation=RadiationProfile.custom_monochromatic(1.54056),
            resolution=ResolutionProfile.tch(u=0.02, v=0.0, w=0.0064, x=0.0, y=0.0),
        )
        backend = FinderPeakProfileBackend()
        x_low = np.linspace(18.0, 22.0, 4001)
        x_high = np.linspace(98.0, 102.0, 4001)

        def profile_at(center: float, x: np.ndarray) -> np.ndarray:
            d_spacing = 1.54056 / (2.0 * math.sin(math.radians(center / 2.0)))
            peak = HKLPeak(1, 0, 0, d_spacing, center, 100.0)
            context = CalculationContext(
                wavelength=1.54056,
                primary_wavelength=1.54056,
                fwhm=0.05,
                two_theta_min=float(x[0]),
                two_theta_max=float(x[-1]),
                x_grid_fingerprint=(len(x), float(x[0]), float(x[-1]), 0),
                include_kalpha2=False,
            )
            return backend.calculate_with_instrument([peak], x, context, instrument)

        low_width = measured_fwhm(x_low, profile_at(20.0, x_low))
        high_width = measured_fwhm(x_high, profile_at(100.0, x_high))

        self.assertGreater(high_width, low_width * 1.5)

    def test_cristma_instrument_copy_uses_observed_width_floor(self):
        instrument = InstrumentProfile(
            radiation=RadiationProfile.custom_monochromatic(1.54056),
            resolution=ResolutionProfile(model="constant_fwhm", constant_fwhm_deg=0.12),
        )

        effective = instrument_profile_with_width_floor(instrument, 0.42, 30.0)

        self.assertAlmostEqual(effective.resolution.constant_fwhm_deg, 0.42)
        self.assertAlmostEqual(instrument.resolution.constant_fwhm_deg, 0.12)

    def test_observed_phase_width_can_broaden_instrument_profile(self):
        wavelength = 1.54056
        center = 30.0
        d_spacing = wavelength / (2.0 * math.sin(math.radians(center / 2.0)))
        peak = HKLPeak(1, 0, 0, d_spacing, center, 100.0)
        x = np.linspace(28.0, 32.0, 4001)
        context = CalculationContext(
            wavelength=wavelength,
            primary_wavelength=wavelength,
            fwhm=0.42,
            two_theta_min=28.0,
            two_theta_max=32.0,
            x_grid_fingerprint=(len(x), 28.0, 32.0, 0),
            include_kalpha2=False,
        )
        instrument = InstrumentProfile(
            radiation=RadiationProfile.custom_monochromatic(wavelength),
            resolution=ResolutionProfile(model="constant_fwhm", constant_fwhm_deg=0.12),
        )

        profile = FinderPeakProfileBackend().calculate_with_instrument(
            [peak], x, context, instrument
        )

        self.assertGreater(measured_fwhm(x, profile), 0.38)


if __name__ == "__main__":
    unittest.main()
