from __future__ import annotations

from dataclasses import dataclass, replace
from inspect import signature
from pathlib import Path
import math
import re

import numpy as np

import cristma
from cristma.crystallography import (
    SpaceGroupCatalog,
    resolve_space_group_setting,
)
from cristma.diffraction import (
    BraggBrentanoGeometry,
    ConstantWidthProfile,
    IsotropicSampleBroadening,
    PowderCorrectionCalculator,
    PowderLineCalculator,
    PowderPatternCalculator,
    RadiationSpectrum,
    TchProfile,
    UniformTwoThetaGrid,
    XRayScatteringContext,
)

from xrd_finder.core.structure import CellParameters
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.instrument.radiation_catalog import cristma_spectrum_from_profile
from xrd_finder.services.calculated_pattern_service import HKLPeak


class CristmaPowderError(RuntimeError):
    """Raised when a CIF cannot be passed safely to the CrIStMa powder API."""


@dataclass(frozen=True, slots=True)
class CristmaPowderResult:
    profile_x: np.ndarray
    profile_y: np.ndarray
    peaks: tuple[HKLPeak, ...]
    backend: str = "cristma"
    setting_id: int | None = None


@dataclass(frozen=True, slots=True)
class CristmaLineResult:
    intrinsic_lines: object
    corrected_lines: object | None
    radiation: RadiationSpectrum
    peaks: tuple[HKLPeak, ...]
    setting_id: int

    @property
    def profile_lines(self):
        return self.intrinsic_lines if self.corrected_lines is None else self.corrected_lines


def _normalized_symbol(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _cell_angle(cell, name: str) -> float:
    measured = getattr(cell, name)
    return float(measured.value)


def _rhombohedral_choice(cell) -> str | None:
    alpha = _cell_angle(cell, "alpha")
    beta = _cell_angle(cell, "beta")
    gamma = _cell_angle(cell, "gamma")
    if abs(alpha - 90.0) < 0.05 and abs(beta - 90.0) < 0.05 and abs(gamma - 120.0) < 0.05:
        return "H"
    if max(abs(alpha - beta), abs(alpha - gamma), abs(beta - gamma)) < 0.05:
        return "R"
    return None


class CristmaPowderAdapter:
    """Translate Finder instrument state into CrIStMa's powder facade."""

    def __init__(self, calculator: PowderPatternCalculator | None = None) -> None:
        self._calculator = calculator or PowderPatternCalculator()
        self._profile_calculator_supports_d_scale = (
            "d_spacing_scale"
            in signature(self._calculator.profile_calculator.calculate).parameters
        )

    @staticmethod
    def radiation_from_profile(profile: InstrumentProfile) -> RadiationSpectrum:
        return cristma_spectrum_from_profile(
            profile.radiation,
            source_id=f"xrd-finder:{profile.calculation_key()}",
        )

    @staticmethod
    def resolution_from_profile(profile: InstrumentProfile) -> ConstantWidthProfile | TchProfile:
        resolution = profile.resolution
        if resolution.model == "constant_fwhm":
            return ConstantWidthProfile(float(resolution.constant_fwhm_deg))
        return TchProfile(
            u=float(resolution.u),
            v=float(resolution.v),
            w=float(resolution.w),
            x=float(resolution.x),
            y=float(resolution.y),
        )

    @staticmethod
    def _geometry_from_profile(profile: InstrumentProfile, use_lp: bool):
        if not use_lp or not profile.geometry.apply_lorentz_polarization:
            return None
        if profile.geometry.geometry != "bragg_brentano":
            raise CristmaPowderError(
                f"Unsupported diffraction geometry: {profile.geometry.geometry}"
            )
        return BraggBrentanoGeometry(
            perpendicular_polarization_fraction=float(
                profile.geometry.polarization_fraction
            )
        )

    @staticmethod
    def _uniform_grid(x_grid: np.ndarray) -> UniformTwoThetaGrid:
        if x_grid.ndim != 1 or len(x_grid) < 2:
            raise CristmaPowderError("The two-theta grid must contain at least two points")
        differences = np.diff(x_grid)
        if not np.all(np.isfinite(x_grid)) or np.any(differences <= 0.0):
            raise CristmaPowderError("The two-theta grid must be finite and strictly increasing")
        step = float(np.median(differences))
        return UniformTwoThetaGrid(
            start_deg=float(x_grid[0]),
            stop_deg=float(x_grid[-1]),
            step_deg=step,
        )

    @staticmethod
    def _structure_and_setting(
        cif_path: str | Path,
        cell_override: CellParameters | None = None,
    ):
        read_result = cristma.read(cif_path)
        if not read_result.structures:
            raise CristmaPowderError(f"CrIStMa did not read a structure from {cif_path}")
        structure = read_result.structures[0]
        definition = structure.space_group
        if definition is None:
            raise CristmaPowderError("The CIF does not define a space group")

        catalog = SpaceGroupCatalog.default()
        resolution = resolve_space_group_setting(definition, catalog)
        setting = resolution.setting
        if setting is None and definition.number is not None:
            candidates = list(catalog.by_number(int(definition.number)))
            reported_choice = _normalized_symbol(definition.setting or definition.origin_choice)
            if reported_choice:
                candidates = [
                    candidate
                    for candidate in candidates
                    if _normalized_symbol(candidate.choice) == reported_choice
                ]
            reported_symbol = _normalized_symbol(definition.hm_symbol)
            if reported_symbol:
                symbol_matches = [
                    candidate
                    for candidate in candidates
                    if reported_symbol
                    in {
                        _normalized_symbol(candidate.hm_short),
                        _normalized_symbol(candidate.hm_full),
                    }
                ]
                if symbol_matches:
                    candidates = symbol_matches
            if len(candidates) > 1:
                basis_choice = _rhombohedral_choice(structure.cell)
                basis_matches = [candidate for candidate in candidates if candidate.choice == basis_choice]
                if len(basis_matches) == 1:
                    candidates = basis_matches
            if len(candidates) == 1:
                setting = candidates[0]

        if setting is None:
            raise CristmaPowderError(
                "The reported CIF symmetry cannot be resolved to one CrIStMa setting"
            )
        canonical_structure = replace(
            structure,
            space_group=setting.definition(provenance="derived"),
        )
        if cell_override is not None:
            canonical_structure = replace(
                canonical_structure,
                cell=CristmaPowderAdapter._cell_with_override(
                    canonical_structure.cell,
                    cell_override,
                ),
            )
        return canonical_structure, setting

    @staticmethod
    def _cell_with_override(cell, override: CellParameters):
        replacements = {}
        for name in ("a", "b", "c", "alpha", "beta", "gamma"):
            value = getattr(override, name)
            if value is None or not math.isfinite(float(value)):
                raise CristmaPowderError(f"Invalid fitted cell parameter: {name}")
            measured = getattr(cell, name)
            replacements[name] = replace(
                measured,
                value=float(value),
                uncertainty=None,
                raw=f"{float(value):.12g}",
            )
        return replace(cell, **replacements)

    def calculate_from_cif(
        self,
        cif_path: str | Path,
        *,
        x_grid,
        instrument_profile: InstrumentProfile,
        use_lp: bool,
        zero_shift_deg: float = 0.0,
        crystallite_size_nm: float | None = None,
        microstrain: float | None = None,
        d_spacing_scale: float = 1.0,
        cell_override: CellParameters | None = None,
    ) -> CristmaPowderResult:
        requested_x = np.asarray(x_grid, dtype=float)
        lines = self.lines_from_cif(
            cif_path,
            two_theta_min=float(requested_x[0]),
            two_theta_max=float(requested_x[-1]),
            instrument_profile=instrument_profile,
            use_lp=use_lp,
            cell_override=cell_override,
        )
        return self.profile_from_lines(
            lines,
            x_grid=requested_x,
            instrument_profile=instrument_profile,
            zero_shift_deg=zero_shift_deg,
            crystallite_size_nm=crystallite_size_nm,
            microstrain=microstrain,
            d_spacing_scale=d_spacing_scale,
        )

    def profile_from_lines(
        self,
        lines: CristmaLineResult,
        *,
        x_grid,
        instrument_profile: InstrumentProfile,
        zero_shift_deg: float = 0.0,
        crystallite_size_nm: float | None = None,
        microstrain: float | None = None,
        d_spacing_scale: float = 1.0,
    ) -> CristmaPowderResult:
        requested_x = np.asarray(x_grid, dtype=float)
        grid = self._uniform_grid(requested_x)
        sample_broadening = None
        if crystallite_size_nm is not None or microstrain not in (None, 0.0):
            sample_broadening = IsotropicSampleBroadening(
                crystallite_size_nm=crystallite_size_nm,
                microstrain=microstrain,
            )
        scale = float(d_spacing_scale)
        if not math.isfinite(scale) or scale <= 0.0:
            raise CristmaPowderError("The d-spacing scale must be positive and finite")
        profile_lines = lines.profile_lines
        profile_kwargs = {
            "sample_broadening": sample_broadening,
            "zero_shift_deg": float(zero_shift_deg),
        }
        if self._profile_calculator_supports_d_scale:
            profile_kwargs["d_spacing_scale"] = scale
        elif not math.isclose(scale, 1.0, rel_tol=0.0, abs_tol=1.0e-12):
            profile_lines = self._scaled_profile_lines(profile_lines, scale)
        profile = self._calculator.profile_calculator.calculate(
            profile_lines,
            grid,
            self.resolution_from_profile(instrument_profile),
            **profile_kwargs,
        )

        calculated_x = np.asarray(profile.two_theta_deg, dtype=float)
        calculated_y = np.asarray(profile.intensity, dtype=float)
        if len(calculated_y) and float(np.max(calculated_y)) > 0.0:
            calculated_y = 100.0 * calculated_y / float(np.max(calculated_y))
        if len(calculated_x) != len(requested_x) or not np.allclose(
            calculated_x,
            requested_x,
            rtol=0.0,
            atol=max(1.0e-8, grid.step_deg * 1.0e-6),
        ):
            calculated_y = np.interp(requested_x, calculated_x, calculated_y)
            calculated_x = requested_x.copy()

        raw_peaks = self._peaks_from_line_sets(
            lines.intrinsic_lines,
            lines.corrected_lines,
            lines.radiation,
            two_theta_min=float(requested_x[0]),
            two_theta_max=float(requested_x[-1]),
            zero_shift_deg=float(zero_shift_deg),
            d_spacing_scale=float(d_spacing_scale),
        )

        calculated_x.setflags(write=False)
        calculated_y.setflags(write=False)
        return CristmaPowderResult(
            profile_x=calculated_x,
            profile_y=calculated_y,
            peaks=raw_peaks,
            setting_id=lines.setting_id,
        )

    @classmethod
    def _scaled_profile_lines(cls, line_set, d_spacing_scale: float):
        if hasattr(line_set, "powder_lines"):
            powder_lines = cls._scaled_powder_line_set(
                line_set.powder_lines,
                d_spacing_scale,
            )
            two_theta_by_id = {
                line.line_id: float(line.two_theta_deg)
                for family in powder_lines.families
                for line in family.lines
            }
            corrected = tuple(
                replace(
                    line,
                    two_theta_deg=two_theta_by_id.get(
                        line.powder_line_id,
                        float(line.two_theta_deg),
                    ),
                )
                for line in line_set.lines
            )
            return replace(line_set, powder_lines=powder_lines, lines=corrected)
        return cls._scaled_powder_line_set(line_set, d_spacing_scale)

    @classmethod
    def _scaled_powder_line_set(cls, line_set, d_spacing_scale: float):
        families = tuple(
            cls._scaled_powder_family(family, d_spacing_scale)
            for family in line_set.families
        )
        return replace(line_set, families=families)

    @classmethod
    def _scaled_powder_family(cls, family, d_spacing_scale: float):
        scaled_d = float(family.d_spacing) * float(d_spacing_scale)
        if not math.isfinite(scaled_d) or scaled_d <= 0.0:
            raise CristmaPowderError("Scaled d spacing must be positive and finite")
        lines = tuple(
            replace(
                line,
                two_theta_deg=cls._two_theta_from_d(
                    float(line.wavelength_angstrom),
                    scaled_d,
                ),
            )
            for line in family.lines
        )
        return replace(family, d_spacing=scaled_d, lines=lines)

    @staticmethod
    def _two_theta_from_d(wavelength_angstrom: float, d_spacing: float) -> float:
        bragg_argument = float(wavelength_angstrom) / (2.0 * float(d_spacing))
        if not 0.0 < bragg_argument <= 1.0:
            raise CristmaPowderError("Scaled d spacing violates the Bragg condition")
        return float(math.degrees(2.0 * math.asin(bragg_argument)))

    @staticmethod
    def _peaks_from_line_sets(
        intrinsic_lines,
        corrected_lines,
        radiation: RadiationSpectrum,
        *,
        two_theta_min: float,
        two_theta_max: float,
        zero_shift_deg: float,
        d_spacing_scale: float = 1.0,
    ) -> tuple[HKLPeak, ...]:
        corrected_by_id = {
            line.powder_line_id: line
            for line in (() if corrected_lines is None else corrected_lines.lines)
        }
        primary_component_id = radiation.components[0].component_id
        raw_peaks: list[HKLPeak] = []
        for family in intrinsic_lines.families:
            primary_line = next(
                (
                    line
                    for line in family.lines
                    if line.radiation_component_id == primary_component_id
                ),
                family.lines[0],
            )
            scaled_d = float(family.d_spacing) * float(d_spacing_scale)
            bragg_argument = float(primary_line.wavelength_angstrom) / (2.0 * scaled_d)
            if not 0.0 < bragg_argument <= 1.0:
                raise CristmaPowderError("Scaled d spacing violates the Bragg condition")
            shifted_two_theta = float(
                math.degrees(2.0 * math.asin(bragg_argument)) + zero_shift_deg
            )
            if not two_theta_min <= shifted_two_theta <= two_theta_max:
                continue
            hkl = family.representative_hkls[0]
            corrected = corrected_by_id.get(primary_line.line_id)
            raw_intensity = float(
                primary_line.intrinsic_line_intensity
                if corrected is None
                else corrected.corrected_line_intensity
            )
            intrinsic = float(primary_line.intrinsic_line_intensity)
            lp = raw_intensity / intrinsic if intrinsic > 0.0 else 1.0
            raw_peaks.append(
                HKLPeak(
                    h=int(hkl.h),
                    k=int(hkl.k),
                    l=int(hkl.l),
                    d=scaled_d,
                    two_theta=shifted_two_theta,
                    intensity=raw_intensity,
                    multiplicity=int(family.multiplicity_crystallographic),
                    f2=float(family.family_strength),
                    lp=float(lp),
                    raw_intensity=raw_intensity,
                )
            )
        maximum = max((peak.raw_intensity for peak in raw_peaks), default=0.0)
        if maximum > 0.0:
            for peak in raw_peaks:
                peak.intensity = 100.0 * peak.raw_intensity / maximum
        return tuple(raw_peaks)

    def sticks_from_cif(
        self,
        cif_path: str | Path,
        *,
        two_theta_min: float,
        two_theta_max: float,
        instrument_profile: InstrumentProfile,
        use_lp: bool,
        cell_override: CellParameters | None = None,
    ) -> tuple[HKLPeak, ...]:
        return self.lines_from_cif(
            cif_path,
            two_theta_min=two_theta_min,
            two_theta_max=two_theta_max,
            instrument_profile=instrument_profile,
            use_lp=use_lp,
            cell_override=cell_override,
        ).peaks

    def lines_from_cif(
        self,
        cif_path: str | Path,
        *,
        two_theta_min: float,
        two_theta_max: float,
        instrument_profile: InstrumentProfile,
        use_lp: bool,
        cell_override: CellParameters | None = None,
    ) -> CristmaLineResult:
        structure, setting = self._structure_and_setting(cif_path, cell_override)
        radiation = self.radiation_from_profile(instrument_profile)
        if not 0.0 < two_theta_max < 180.0:
            raise CristmaPowderError("The upper two-theta limit must lie within (0, 180)")
        theta_max = math.radians(float(two_theta_max) / 2.0)
        d_min = min(
            component.wavelength_angstrom for component in radiation.components
        ) / (2.0 * math.sin(theta_max))
        reflections = self._calculator.reflection_generator.generate(
            structure.cell,
            setting,
            d_min,
        )
        factors = self._calculator.structure_factor_calculator.calculate(
            structure,
            setting,
            reflections,
            XRayScatteringContext.default(),
        )
        intrinsic_lines = PowderLineCalculator().calculate(factors, radiation)
        geometry = self._geometry_from_profile(instrument_profile, use_lp)
        corrected_lines = (
            None
            if geometry is None
            else PowderCorrectionCalculator().calculate(intrinsic_lines, geometry)
        )
        peaks = self._peaks_from_line_sets(
            intrinsic_lines,
            corrected_lines,
            radiation,
            two_theta_min=float(two_theta_min),
            two_theta_max=float(two_theta_max),
            zero_shift_deg=0.0,
        )
        return CristmaLineResult(
            intrinsic_lines=intrinsic_lines,
            corrected_lines=corrected_lines,
            radiation=radiation,
            peaks=peaks,
            setting_id=int(setting.setting_id),
        )


__all__ = [
    "CristmaPowderAdapter",
    "CristmaPowderError",
    "CristmaLineResult",
    "CristmaPowderResult",
]
