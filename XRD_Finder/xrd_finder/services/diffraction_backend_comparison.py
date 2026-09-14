from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import math
import time

import numpy as np

from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.services.calculated_pattern_service import (
    CalculatedPatternService,
    calculated_profile_from_peaks,
)
from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter


@dataclass(frozen=True, slots=True)
class DiffractionBackendComparison:
    cif_path: str
    legacy_line_count: int
    cristma_line_count: int
    legacy_seconds: float
    cristma_seconds: float
    legacy_profile_finite: bool
    cristma_profile_finite: bool
    strong_line_match_fraction: float
    median_position_delta_deg: float
    maximum_position_delta_deg: float
    profile_correlation: float
    normalized_profile_rmse: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _nearest_position_deltas(source_positions, target_positions) -> np.ndarray:
    source = np.sort(np.asarray(source_positions, dtype=float))
    target = np.sort(np.asarray(target_positions, dtype=float))
    if not len(source) or not len(target):
        return np.full(len(source), np.inf, dtype=float)

    insertion = np.searchsorted(target, source)
    left = np.clip(insertion - 1, 0, len(target) - 1)
    right = np.clip(insertion, 0, len(target) - 1)
    return np.minimum(np.abs(source - target[left]), np.abs(source - target[right]))


def _strongest_positions(peaks, limit: int) -> np.ndarray:
    ordered = sorted(
        peaks,
        key=lambda peak: float(getattr(peak, "intensity", 0.0)),
        reverse=True,
    )[: max(1, int(limit))]
    return np.asarray([float(peak.two_theta) for peak in ordered], dtype=float)


def _profile_metrics(legacy_y: np.ndarray, cristma_y: np.ndarray) -> tuple[float, float]:
    legacy = np.asarray(legacy_y, dtype=float)
    cristma = np.asarray(cristma_y, dtype=float)
    if not len(legacy) or len(legacy) != len(cristma):
        return 0.0, math.inf

    legacy_scale = float(np.max(np.abs(legacy)))
    cristma_scale = float(np.max(np.abs(cristma)))
    if legacy_scale <= 0.0 or cristma_scale <= 0.0:
        return 0.0, math.inf
    legacy = legacy / legacy_scale
    cristma = cristma / cristma_scale
    correlation = float(np.corrcoef(legacy, cristma)[0, 1])
    rmse = float(np.sqrt(np.mean(np.square(legacy - cristma))))
    return correlation, rmse


def compare_cif_backends(
    cif_path: str | Path,
    *,
    instrument_profile: InstrumentProfile,
    two_theta_min: float = 10.0,
    two_theta_max: float = 80.0,
    grid_points: int = 3501,
    strongest_lines: int = 20,
    position_tolerance_deg: float = 0.15,
    use_lp: bool = True,
) -> DiffractionBackendComparison:
    """Compare the legacy and CrIStMa forward calculations without changing scoring."""
    source = Path(cif_path).expanduser().resolve()
    if grid_points < 2:
        raise ValueError("grid_points must be at least 2")
    if position_tolerance_deg <= 0.0:
        raise ValueError("position_tolerance_deg must be positive")

    grid = np.linspace(float(two_theta_min), float(two_theta_max), int(grid_points))
    radiation = instrument_profile.radiation
    primary_wavelength = float(radiation.components[0].wavelength_angstrom)
    include_kalpha2 = radiation.mode == "kalpha_doublet" and len(radiation.components) > 1
    fwhm = float(instrument_profile.resolution.constant_fwhm_deg)

    legacy_started = time.perf_counter()
    _phase, structure = create_phase_from_cif(source)
    legacy_peaks = CalculatedPatternService().calculate_sticks(
        structure,
        two_theta_min=float(two_theta_min),
        two_theta_max=float(two_theta_max),
        wavelength=primary_wavelength,
        use_lp=use_lp,
    )
    _legacy_x, legacy_y = calculated_profile_from_peaks(
        legacy_peaks,
        grid,
        fwhm=fwhm,
        wavelength=primary_wavelength,
        include_kalpha2=include_kalpha2,
    )
    legacy_seconds = time.perf_counter() - legacy_started

    cristma_started = time.perf_counter()
    cristma_result = CristmaPowderAdapter().calculate_from_cif(
        source,
        x_grid=grid,
        instrument_profile=instrument_profile,
        use_lp=use_lp,
    )
    cristma_seconds = time.perf_counter() - cristma_started

    strongest_legacy = _strongest_positions(legacy_peaks, strongest_lines)
    cristma_positions = [peak.two_theta for peak in cristma_result.peaks]
    deltas = _nearest_position_deltas(strongest_legacy, cristma_positions)
    finite_deltas = deltas[np.isfinite(deltas)]
    matched = float(np.mean(deltas <= float(position_tolerance_deg))) if len(deltas) else 0.0
    median_delta = float(np.median(finite_deltas)) if len(finite_deltas) else math.inf
    maximum_delta = float(np.max(finite_deltas)) if len(finite_deltas) else math.inf
    correlation, rmse = _profile_metrics(legacy_y, cristma_result.profile_y)

    return DiffractionBackendComparison(
        cif_path=str(source),
        legacy_line_count=len(legacy_peaks),
        cristma_line_count=len(cristma_result.peaks),
        legacy_seconds=float(legacy_seconds),
        cristma_seconds=float(cristma_seconds),
        legacy_profile_finite=bool(np.all(np.isfinite(legacy_y))),
        cristma_profile_finite=bool(np.all(np.isfinite(cristma_result.profile_y))),
        strong_line_match_fraction=matched,
        median_position_delta_deg=median_delta,
        maximum_position_delta_deg=maximum_delta,
        profile_correlation=correlation,
        normalized_profile_rmse=rmse,
    )


__all__ = ["DiffractionBackendComparison", "compare_cif_backends"]
