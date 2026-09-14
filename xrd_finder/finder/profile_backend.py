from __future__ import annotations

from typing import Protocol
import math

import numpy as np
from cristma.diffraction import ConstantWidthProfile, TchProfile

from xrd_finder.finder.context import CalculationContext
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.calculated_pattern_service import (
    HKLPeak,
    PROFILE_WINDOW_FACTOR,
    calculated_profile_from_peaks,
    pseudo_voigt_values,
)


class PeakProfileBackend(Protocol):
    cache_key: str

    def calculate(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
    ) -> np.ndarray: ...


class FinderPeakProfileBackend:
    """Compatibility profile backend used until CrIStMa accepts aligned lines."""

    cache_key = "finder-peaks-v1"

    def calculate(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
    ) -> np.ndarray:
        _x, profile = calculated_profile_from_peaks(
            peaks,
            x_grid,
            fwhm=context.fwhm,
            eta=context.profile_eta,
            wavelength=context.wavelength,
            include_kalpha2=context.include_kalpha2,
        )
        return np.asarray(profile, dtype=float)

    def calculate_with_instrument(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
        instrument_profile: InstrumentProfile,
    ) -> np.ndarray:
        """Build a fast profile from indexed lines using the full instrument state."""
        x = np.asarray(x_grid, dtype=float)
        y = np.zeros_like(x, dtype=float)
        if not peaks or len(x) == 0:
            return y

        components = instrument_profile.radiation.components
        if instrument_profile.radiation.mode != "kalpha_doublet":
            components = components[:1]
        resolution = instrument_profile.resolution
        broadening = (
            ConstantWidthProfile(float(resolution.constant_fwhm_deg))
            if resolution.model == "constant_fwhm"
            else TchProfile(
                u=float(resolution.u),
                v=float(resolution.v),
                w=float(resolution.w),
                x=float(resolution.x),
                y=float(resolution.y),
            )
        )

        for peak in peaks:
            d_spacing = float(peak.d)
            primary_center = self._two_theta_from_d(
                d_spacing,
                float(components[0].wavelength_angstrom),
            )
            position_shift = (
                float(peak.two_theta) - primary_center
                if primary_center is not None
                else 0.0
            )
            for component in components:
                center = self._two_theta_from_d(
                    d_spacing,
                    float(component.wavelength_angstrom),
                )
                if center is None:
                    continue
                center += position_shift
                width = (
                    float(broadening.fwhm_deg)
                    if isinstance(broadening, ConstantWidthProfile)
                    else float(broadening.fwhm_deg_at(center))
                )
                self._add_peak(
                    x,
                    y,
                    center=center,
                    intensity=float(peak.intensity) * float(component.weight),
                    fwhm=width,
                    eta=context.profile_eta,
                )
        maximum = float(np.nanmax(y)) if len(y) else 0.0
        if maximum > 0.0:
            y *= 100.0 / maximum
        return y

    @staticmethod
    def _two_theta_from_d(d_spacing: float, wavelength: float) -> float | None:
        argument = wavelength / (2.0 * d_spacing)
        if not 0.0 < argument < 1.0:
            return None
        return float(2.0 * math.degrees(math.asin(argument)))

    @staticmethod
    def _add_peak(
        x: np.ndarray,
        y: np.ndarray,
        *,
        center: float,
        intensity: float,
        fwhm: float,
        eta: float,
    ) -> None:
        if not (float(x[0]) <= center <= float(x[-1])):
            return
        width = max(float(fwhm), 1.0e-6)
        half_window = PROFILE_WINDOW_FACTOR * width
        left = int(np.searchsorted(x, center - half_window, side="left"))
        right = int(np.searchsorted(x, center + half_window, side="right"))
        if right <= left:
            return
        y[left:right] += max(float(intensity), 0.0) * pseudo_voigt_values(
            x[left:right],
            center,
            width,
            eta,
        )


__all__ = ["FinderPeakProfileBackend", "PeakProfileBackend"]
