from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping, Sequence

import numpy as np

from benchmarks.match.scenarios import ScenarioDefinition
from xrd_finder.services.calculated_pattern_service import pseudo_voigt_values
from xrd_finder.instrument.models import (
    GeometryProfile,
    InstrumentProfile,
    RadiationProfile,
    ResolutionProfile,
)


@dataclass(frozen=True, slots=True)
class ReferenceLine:
    two_theta: float
    intensity: float
    d: float | None = None
    h: int | None = None
    k: int | None = None
    l: int | None = None
    multiplicity: int | None = None


@dataclass(frozen=True, slots=True)
class DetectedLine:
    two_theta: float
    area: float
    fwhm: float
    height: float


@dataclass(frozen=True, slots=True)
class GeneratedPattern:
    scenario_id: str
    x: np.ndarray
    y: np.ndarray
    background: np.ndarray
    clean_y: np.ndarray
    component_profiles: Mapping[str, np.ndarray]
    component_fractions: Mapping[str, float]
    component_diffraction_power: Mapping[str, float]
    component_fwhm: Mapping[str, float]
    component_reciprocal_strain: Mapping[str, tuple[float, float, float, float, float, float]]
    ground_truth_positions: tuple[float, ...]
    observed_records: tuple[object, ...]
    fwhm: float


def benchmark_instrument_fwhm(two_theta: float) -> float:
    """Synthetic Caglioti resolution floor used by the benchmark instrument."""

    theta = np.deg2rad(float(two_theta) * 0.5)
    variance = 0.012 * np.tan(theta) ** 2 - 0.002 * np.tan(theta) + 0.0064
    return float(np.sqrt(max(float(variance), 0.0025)))


def benchmark_instrument_profile() -> InstrumentProfile:
    """Instrument model matching the synthetic Caglioti resolution floor."""

    return InstrumentProfile(
        radiation=RadiationProfile.custom_monochromatic(1.5406),
        geometry=GeometryProfile(apply_lorentz_polarization=False),
        resolution=ResolutionProfile.tch(
            u=0.012,
            v=-0.002,
            w=0.0064,
            x=0.0,
            y=0.0,
        ),
        profile_id="benchmark-cu-monochromatic",
    )


def generate_profile(
    references: Mapping[str, Sequence[ReferenceLine]],
    scenario: ScenarioDefinition,
    *,
    x_grid: np.ndarray | None = None,
    detector_distance_scale: float = 1.0,
    instrument_resolution: bool = False,
) -> GeneratedPattern:
    x = np.asarray(x_grid if x_grid is not None else np.arange(5.0, 120.0001, 0.02), dtype=float)
    rng = np.random.default_rng(int(scenario.seed))
    total = np.zeros_like(x)
    profiles: dict[str, np.ndarray] = {}
    fractions: dict[str, float] = {}
    diffraction_power: dict[str, float] = {}
    component_fwhm: dict[str, float] = {}
    component_reciprocal_strain: dict[str, tuple[float, float, float, float, float, float]] = {}
    ground_truth = []
    distortion_sigma = {"none": 0.0, "moderate": 0.15, "strong": 0.35}[scenario.intensity_distortion]
    for component in scenario.components:
        profile = np.zeros_like(x)
        phase_fwhm = float(component.fwhm if component.fwhm is not None else scenario.fwhm)
        lines = references.get(component.phase_id, ())
        reciprocal_metric = _fit_reciprocal_metric(lines)
        maximum = max((max(float(line.intensity), 0.0) for line in lines), default=1.0)
        representative_width = phase_fwhm
        representative_intensity = -1.0
        for line in lines:
            center = _strained_two_theta(
                line,
                reciprocal_metric,
                component.reciprocal_strain,
                fallback_scale=1.0 + float(scenario.axis_scale),
            ) + float(scenario.zero_shift)
            if not x[0] <= center <= x[-1]:
                continue
            distortion = float(rng.lognormal(0.0, distortion_sigma)) if distortion_sigma else 1.0
            intensity = max(float(line.intensity), 0.0) / max(maximum, 1.0e-12) * distortion
            line_fwhm = max(phase_fwhm, benchmark_instrument_fwhm(center)) if instrument_resolution else phase_fwhm
            profile += intensity * pseudo_voigt_values(x, center, line_fwhm, 0.35)
            if float(line.intensity) > representative_intensity:
                representative_intensity = float(line.intensity)
                representative_width = line_fwhm
            ground_truth.append(center)
        power = max(float(component.diffraction_power), 0.0)
        profile *= float(component.fraction) * power * 10_000.0
        profiles[component.phase_id] = profile
        fractions[component.phase_id] = float(component.fraction)
        diffraction_power[component.phase_id] = power
        component_fwhm[component.phase_id] = representative_width
        component_reciprocal_strain[component.phase_id] = component.reciprocal_strain
        total += profile
    background = _background(x, total, scenario.background)
    y = _add_noise(total + background, scenario.noise, rng)
    corrected = np.clip(y - background, 0.0, None)
    records = _detect_observed_records(
        x,
        corrected,
        limit=80,
        distance_scale=detector_distance_scale,
        instrument_profile=(
            benchmark_instrument_profile() if instrument_resolution else None
        ),
    )
    return GeneratedPattern(
        scenario_id=scenario.scenario_id,
        x=x,
        y=np.asarray(y, dtype=float),
        background=np.asarray(background, dtype=float),
        clean_y=np.asarray(total, dtype=float),
        component_profiles=profiles,
        component_fractions=fractions,
        component_diffraction_power=diffraction_power,
        component_fwhm=component_fwhm,
        component_reciprocal_strain=component_reciprocal_strain,
        ground_truth_positions=tuple(sorted(ground_truth)),
        observed_records=tuple(records),
        fwhm=float(scenario.fwhm),
    )


def _strained_two_theta(
    line: ReferenceLine,
    reciprocal_metric: np.ndarray | None,
    strain: tuple[float, float, float, float, float, float],
    *,
    fallback_scale: float,
) -> float:
    """Move an indexed line with a phase-specific reciprocal-metric strain."""

    indexed = line.h is not None and line.k is not None and line.l is not None
    if reciprocal_metric is not None and indexed and any(abs(float(value)) > 0.0 for value in strain):
        xx, yy, zz, xy, xz, yz = (float(value) for value in strain)
        deformation = np.asarray(
            [[1.0 + xx, xy, xz], [xy, 1.0 + yy, yz], [xz, yz, 1.0 + zz]],
            dtype=float,
        )
        strained_metric = deformation.T @ reciprocal_metric @ deformation
        vector = np.asarray([line.h, line.k, line.l], dtype=float)
        reciprocal_square = float(vector @ strained_metric @ vector)
        if reciprocal_square > 0.0:
            d_spacing = 1.0 / np.sqrt(reciprocal_square)
            argument = 1.5406 / (2.0 * d_spacing)
            if 0.0 < argument < 1.0:
                return float(np.rad2deg(2.0 * np.arcsin(argument)))
    theta = np.deg2rad(float(line.two_theta) * 0.5)
    scaled_sine = np.clip(np.sin(theta) * float(fallback_scale), -1.0, 1.0)
    return float(np.rad2deg(2.0 * np.arcsin(scaled_sine)))


def _fit_reciprocal_metric(lines: Sequence[ReferenceLine]) -> np.ndarray | None:
    design = []
    target = []
    for line in lines:
        if line.d is None or line.h is None or line.k is None or line.l is None:
            continue
        d_spacing = float(line.d)
        if d_spacing <= 0.0 or (line.h, line.k, line.l) == (0, 0, 0):
            continue
        h, k, l = float(line.h), float(line.k), float(line.l)
        design.append((h * h, k * k, l * l, 2.0 * h * k, 2.0 * h * l, 2.0 * k * l))
        target.append(1.0 / (d_spacing * d_spacing))
    if len(design) < 3:
        return None
    matrix = np.asarray(design, dtype=float)
    values = np.asarray(target, dtype=float)
    try:
        parameters, _residuals, _rank, _singular = np.linalg.lstsq(matrix, values, rcond=None)
    except np.linalg.LinAlgError:
        return None
    metric = np.asarray(
        [
            [parameters[0], parameters[3], parameters[4]],
            [parameters[3], parameters[1], parameters[5]],
            [parameters[4], parameters[5], parameters[2]],
        ],
        dtype=float,
    )
    try:
        if np.min(np.linalg.eigvalsh(metric)) <= 0.0:
            return None
    except np.linalg.LinAlgError:
        return None
    return metric


def _background(x: np.ndarray, signal: np.ndarray, kind: str) -> np.ndarray:
    scale = max(float(np.nanmax(signal)), 1.0)
    normalized = (x - x[0]) / max(float(x[-1] - x[0]), 1.0e-12)
    if kind == "sloped":
        return scale * (0.015 + 0.025 * normalized)
    if kind == "curved":
        return scale * (0.012 + 0.035 * (normalized - 0.55) ** 2)
    if kind == "amorphous":
        hump = np.exp(-0.5 * ((x - 28.0) / 7.5) ** 2)
        return scale * (0.012 + 0.08 * hump)
    return np.full_like(x, scale * 0.015)


def _add_noise(values: np.ndarray, level: str, rng: np.random.Generator) -> np.ndarray:
    count_scale, gaussian_fraction = {
        "none": (0.0, 0.0),
        "low": (4.0, 0.0015),
        "medium": (1.0, 0.004),
        "high": (0.25, 0.010),
    }[level]
    if count_scale <= 0.0:
        return np.asarray(values, dtype=float).copy()
    counts = rng.poisson(np.clip(values, 0.0, None) * count_scale) / count_scale
    sigma = max(float(np.nanmax(values)) * gaussian_fraction, 1.0e-12)
    return counts + rng.normal(0.0, sigma, size=len(values))


def _detect_observed_records(
    x: np.ndarray,
    y: np.ndarray,
    *,
    limit: int,
    distance_scale: float,
    instrument_profile: InstrumentProfile | None = None,
) -> list[object]:
    try:
        from xrd_finder.ui.peak_matching import observed_peak_records

        return list(
            observed_peak_records(
                x,
                y,
                limit=limit,
                distance_scale=distance_scale,
                instrument_profile=instrument_profile,
            )
        )
    except ModuleNotFoundError as error:
        if error.name != "scipy" and not str(error.name or "").startswith("scipy."):
            raise
    if len(y) < 3:
        return []
    indices = np.flatnonzero((y[1:-1] > y[:-2]) & (y[1:-1] >= y[2:])) + 1
    if not len(indices):
        return []
    floor = float(np.nanpercentile(y, 75))
    indices = indices[y[indices] >= floor]
    minimum_samples = max(1, int(round((0.045 * max(float(distance_scale), 0.05)) / max(float(np.median(np.diff(x))), 1.0e-6))))
    ordered = indices[np.argsort(y[indices])[::-1]]
    kept = []
    for index in ordered:
        if all(abs(int(index) - int(existing)) >= minimum_samples for existing in kept):
            kept.append(int(index))
        if len(kept) >= max(int(limit), 1):
            break
    strongest = np.asarray(kept, dtype=int)
    return [
        DetectedLine(float(x[index]), float(y[index]), 0.05, float(y[index]))
        for index in strongest[np.argsort(y[strongest])[::-1]]
    ]


__all__ = [
    "DetectedLine",
    "GeneratedPattern",
    "ReferenceLine",
    "benchmark_instrument_fwhm",
    "benchmark_instrument_profile",
    "generate_profile",
]
