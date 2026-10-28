from __future__ import annotations

from dataclasses import replace
from typing import Protocol
import math

import numpy as np
from cristma.diffraction import ConstantWidthProfile

from xrd_finder.finder.context import CalculationContext
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.instrument.resolution import cristma_tch_profile
from xrd_finder.services.calculated_pattern_service import (
    HKLPeak,
    calculated_profile_from_peaks,
    add_integrated_peak,
)


class PeakProfileBackend(Protocol):
    cache_key: str

    def calculate(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
        *, normalize: bool = True,
    ) -> np.ndarray: ...


def validate_instrument_eta(context: CalculationContext) -> None:
    """CrIStMa instrument models do not expose a separate constant PV mixing."""
    eta = 0.0 if context.profile_eta is None else float(context.profile_eta)
    if not math.isfinite(eta) or eta != 0.0:
        raise ValueError('Free profile eta is unsupported with an instrument model; use its resolution parameters')


def profile_reference_angle(peaks, instrument_profile: InstrumentProfile, d_spacing_scale=1.0) -> float:
    """Resolution is evaluated at the Bragg angle, before the scan zero shift."""
    if not peaks:
        return 40.0
    peak = max(peaks, key=lambda p: float(p.intensity))
    d = float(peak.d) * float(d_spacing_scale)
    wavelength = float(instrument_profile.radiation.components[0].wavelength_angstrom)
    ratio = wavelength / (2. * d) if d > 0. else 0.
    if 0. < ratio < 1.:
        return math.degrees(2. * math.asin(ratio))
    return float(peak.two_theta)


def instrument_fwhm_at(instrument_profile: InstrumentProfile, two_theta: float) -> float:
    resolution = instrument_profile.resolution
    if resolution.model == 'constant_fwhm':
        return float(resolution.constant_fwhm_deg)
    return float(cristma_tch_profile(resolution).fwhm_deg_at(two_theta))


def instrument_profile_with_width_floor(
    instrument_profile: InstrumentProfile,
    minimum_fwhm: float,
    two_theta: float,
) -> InstrumentProfile:
    """Return a calculation copy whose resolution is at least the observed width."""
    floor = max(float(minimum_fwhm), 1.0e-6)
    resolution = instrument_profile.resolution
    if resolution.model == "constant_fwhm":
        if float(resolution.constant_fwhm_deg) >= floor:
            return instrument_profile
        return replace(
            instrument_profile,
            resolution=replace(resolution, constant_fwhm_deg=floor),
        )

    broadening = cristma_tch_profile(resolution)
    current = max(float(broadening.fwhm_deg_at(float(two_theta))), 1.0e-6)
    if current >= floor:
        return instrument_profile
    scale = floor / current
    return replace(
        instrument_profile,
        resolution=replace(
            resolution,
            u=float(resolution.u) * scale * scale,
            v=float(resolution.v) * scale * scale,
            w=float(resolution.w) * scale * scale,
            x=float(resolution.x) * scale,
            y=float(resolution.y) * scale,
        ),
    )


class FinderPeakProfileBackend:
    """Fast area-normalized profiles for explicit and relative peak lists."""

    cache_key = "finder-integrated-peaks-v3-instrument-model"

    def calculate(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
        *, normalize: bool = True,
    ) -> np.ndarray:
        _x, profile = calculated_profile_from_peaks(
            peaks,
            x_grid,
            fwhm=context.fwhm,
            eta=context.profile_eta,
            wavelength=context.wavelength,
            include_kalpha2=context.include_kalpha2,
            normalize=normalize,
        )
        return np.asarray(profile, dtype=float)

    def calculate_with_instrument(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
        instrument_profile: InstrumentProfile,
        *, normalize: bool = True,
    ) -> np.ndarray:
        """Build a fast profile from indexed lines using the full instrument state."""
        validate_instrument_eta(context)
        x = np.asarray(x_grid, dtype=float)
        y = np.zeros_like(x, dtype=float)
        if not peaks or len(x) == 0:
            return y

        components = instrument_profile.radiation.components
        if instrument_profile.radiation.mode != "kalpha_doublet":
            components = components[:1]
        representative = profile_reference_angle(peaks, instrument_profile)
        instrument_profile = instrument_profile_with_width_floor(
            instrument_profile, context.fwhm, representative)
        resolution = instrument_profile.resolution
        broadening = (
            ConstantWidthProfile(float(resolution.constant_fwhm_deg))
            if resolution.model == "constant_fwhm"
            else cristma_tch_profile(resolution)
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
                    else float(broadening.fwhm_deg_at(center - position_shift))
                )
                # The instrument profile describes the resolution floor.  A
                # real sample can be broader because of crystallite size,
                # strain, disorder, or unresolved overlap.  Finder estimates
                # that observed phase width in ``context.fwhm``; discarding it
                # here recreated an artificially narrow instrument-only line.
                eta = (float(broadening._width_and_mixing_at(center - position_shift)[1])
                       if not isinstance(broadening, ConstantWidthProfile)
                       else 0.0)
                self._add_peak(
                    x,
                    y,
                    center=center,
                    # Sticks already include the primary component's weight.
                    intensity=float(peak.intensity) * float(component.weight) / float(components[0].weight),
                    fwhm=width,
                    eta=eta,
                )
        maximum = float(np.nanmax(y)) if len(y) else 0.0
        if normalize and maximum > 0.0:
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
        add_integrated_peak(x, y, center=center, intensity=intensity, fwhm=fwhm, eta=eta)


__all__ = ["FinderPeakProfileBackend", "PeakProfileBackend"]
