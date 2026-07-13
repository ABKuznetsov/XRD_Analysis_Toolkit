from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import math

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import find_peaks

from xrd_finder.core.refinement import RefinementResult
from xrd_finder.core.structure import CellParameters
from xrd_finder.services.calculated_pattern_service import CalculatedPatternService


LE_BAIL_STRATEGY = "le_bail"
PAWLEY_CELL_STRATEGY = "pawley_cell"
CLASSICAL_RIETVELD_STRATEGY = "classical_rietveld"


@dataclass(slots=True)
class CellFitResult:
    phase_id: str
    phase_name: str
    initial_cell: CellParameters
    refined_cell: CellParameters
    matched_peaks: int
    rms_delta_two_theta: float
    max_delta_two_theta: float
    success: bool
    message: str = ""


class RefinementService:
    available_strategies = [
        PAWLEY_CELL_STRATEGY,
        LE_BAIL_STRATEGY,
        CLASSICAL_RIETVELD_STRATEGY,
    ]

    def __init__(self, calculated_pattern_service: CalculatedPatternService | None = None) -> None:
        self.calculated_pattern_service = calculated_pattern_service or CalculatedPatternService()

    def create_job(self, pattern_id: str, phase_ids: list[str], method: str) -> RefinementResult:
        return self.create_strategy_job(pattern_id=pattern_id, phase_ids=phase_ids, strategy=method)

    def create_strategy_job(self, pattern_id: str, phase_ids: list[str], strategy: str) -> RefinementResult:
        name = f"{self.strategy_label(strategy)} refinement"
        return RefinementResult.create(name=name, pattern_id=pattern_id, phase_ids=phase_ids, method=strategy)

    def strategy_label(self, strategy: str) -> str:
        labels = {
            PAWLEY_CELL_STRATEGY: "Pawley cell",
            LE_BAIL_STRATEGY: "Le Bail",
            CLASSICAL_RIETVELD_STRATEGY: "Classical Rietveld",
        }
        return labels.get(strategy, strategy.replace("_", " ").title())

    def fit_pawley_cells(
        self,
        x_values,
        y_values,
        phase_structures: list[tuple[str, str, object]],
        *,
        wavelength: float,
        fwhm: float = 0.18,
        two_theta_tolerance: float = 0.45,
        phase_peak_matches: dict[str, list[tuple[float, float]]] | None = None,
    ) -> list[CellFitResult]:
        observed_x = np.asarray(x_values, dtype=float)
        observed_y = np.asarray(y_values, dtype=float)
        peak_positions = self._observed_peak_positions(observed_x, observed_y, fwhm=fwhm)
        has_peak_matches = any(len(matches) >= 3 for matches in (phase_peak_matches or {}).values())
        if len(peak_positions) < 3 and not has_peak_matches:
            raise ValueError("Not enough observed peaks for Pawley cell fitting.")
        results: list[CellFitResult] = []
        for phase_id, phase_name, structure in phase_structures:
            results.append(
                self.fit_pawley_cell(
                    observed_peak_positions=peak_positions,
                    phase_id=phase_id,
                    phase_name=phase_name,
                    structure=structure,
                    wavelength=wavelength,
                    two_theta_min=float(np.nanmin(observed_x)),
                    two_theta_max=float(np.nanmax(observed_x)),
                    two_theta_tolerance=two_theta_tolerance,
                    peak_matches=(phase_peak_matches or {}).get(phase_id, []),
                )
            )
        return results

    def fit_pawley_cell(
        self,
        *,
        observed_peak_positions: np.ndarray,
        phase_id: str,
        phase_name: str,
        structure,
        wavelength: float,
        two_theta_min: float,
        two_theta_max: float,
        two_theta_tolerance: float,
        peak_matches: list[tuple[float, float]] | None = None,
    ) -> CellFitResult:
        initial_cell = deepcopy(getattr(structure, "cell", CellParameters()))
        variable_names = self._cell_variable_names(initial_cell)
        if not variable_names:
            return CellFitResult(
                phase_id=phase_id,
                phase_name=phase_name,
                initial_cell=initial_cell,
                refined_cell=initial_cell,
                matched_peaks=0,
                rms_delta_two_theta=0.0,
                max_delta_two_theta=0.0,
                success=False,
                message="Incomplete unit cell.",
            )
        start = np.asarray([float(getattr(initial_cell, name)) for name in variable_names], dtype=float)
        lower, upper = self._cell_bounds(initial_cell, variable_names)
        trial_structure = deepcopy(structure)
        reference_matches = [
            (float(reference), float(observed))
            for reference, observed in (peak_matches or [])
            if np.isfinite(reference) and np.isfinite(observed)
        ]

        def residual(values: np.ndarray) -> np.ndarray:
            trial_structure.cell = self._cell_from_variables(initial_cell, variable_names, values)
            try:
                peaks = self.calculated_pattern_service.calculate_sticks(
                    trial_structure,
                    two_theta_min=two_theta_min,
                    two_theta_max=two_theta_max,
                    wavelength=wavelength,
                    use_lp=True,
                    intensity_min=2.0,
                )
            except Exception:
                return np.full(8, 4.0, dtype=float)
            if len(reference_matches) >= 3:
                return self._matched_peak_residuals(peaks, reference_matches, two_theta_tolerance)
            peaks = sorted(peaks, key=lambda peak: peak.intensity, reverse=True)[:36]
            if len(peaks) < 3:
                return np.full(8, 4.0, dtype=float)
            residuals = []
            for peak in peaks:
                delta = self._nearest_delta(observed_peak_positions, float(peak.two_theta))
                scaled = np.clip(delta / max(two_theta_tolerance, 1.0e-6), -4.0, 4.0)
                weight = math.sqrt(max(float(peak.intensity), 1.0) / 100.0)
                residuals.append(float(scaled * weight))
            return np.asarray(residuals, dtype=float)

        try:
            result = least_squares(
                residual,
                start,
                bounds=(lower, upper),
                loss="soft_l1",
                f_scale=1.0,
                max_nfev=32,
            )
            refined_cell = self._cell_from_variables(initial_cell, variable_names, result.x)
            trial_structure.cell = refined_cell
            peaks = self.calculated_pattern_service.calculate_sticks(
                trial_structure,
                two_theta_min=two_theta_min,
                two_theta_max=two_theta_max,
                wavelength=wavelength,
                use_lp=True,
                intensity_min=2.0,
            )
            if len(reference_matches) >= 3:
                deltas = self._matched_peak_deltas(peaks, reference_matches, two_theta_tolerance)
            else:
                peaks = sorted(peaks, key=lambda peak: peak.intensity, reverse=True)[:36]
                deltas = [
                    self._nearest_delta(observed_peak_positions, float(peak.two_theta))
                    for peak in peaks
                    if abs(self._nearest_delta(observed_peak_positions, float(peak.two_theta))) <= two_theta_tolerance
                ]
            if deltas:
                delta_array = np.asarray(deltas, dtype=float)
                rms = float(np.sqrt(np.nanmean(delta_array * delta_array)))
                max_delta = float(np.nanmax(np.abs(delta_array)))
            else:
                rms = 0.0
                max_delta = 0.0
            return CellFitResult(
                phase_id=phase_id,
                phase_name=phase_name,
                initial_cell=initial_cell,
                refined_cell=refined_cell,
                matched_peaks=len(deltas),
                rms_delta_two_theta=rms,
                max_delta_two_theta=max_delta,
                success=bool(result.success and len(deltas) >= 3),
                message=str(result.message),
            )
        except Exception as exc:
            return CellFitResult(
                phase_id=phase_id,
                phase_name=phase_name,
                initial_cell=initial_cell,
                refined_cell=initial_cell,
                matched_peaks=0,
                rms_delta_two_theta=0.0,
                max_delta_two_theta=0.0,
                success=False,
                message=str(exc),
            )

    def _observed_peak_positions(self, x: np.ndarray, y: np.ndarray, *, fwhm: float) -> np.ndarray:
        if len(x) < 5 or len(y) < 5:
            return np.array([], dtype=float)
        positive = np.clip(np.asarray(y, dtype=float), 0.0, None)
        if float(np.nanmax(positive)) <= 0.0:
            return np.array([], dtype=float)
        step = abs(float(np.nanmedian(np.diff(x)))) if len(x) > 1 else 0.03
        prominence = max(float(np.nanpercentile(positive, 96)) * 0.025, float(np.nanstd(positive)) * 1.2, 1.0)
        indices, properties = find_peaks(
            positive,
            prominence=prominence,
            distance=max(3, int(round(max(fwhm, 0.08) / max(step, 1.0e-6)))),
        )
        if len(indices) > 180:
            prominences = properties.get("prominences", positive[indices])
            indices = indices[np.argsort(prominences)[-180:]]
        return np.asarray(sorted(float(x[index]) for index in indices), dtype=float)

    def _cell_variable_names(self, cell: CellParameters) -> list[str]:
        required = ("a", "b", "c", "alpha", "beta", "gamma")
        if any(getattr(cell, name, None) is None for name in required):
            return []
        a, b, c = (float(getattr(cell, name)) for name in ("a", "b", "c"))
        alpha, beta, gamma = (float(getattr(cell, name)) for name in ("alpha", "beta", "gamma"))
        if self._close_angle(alpha, 90.0) and self._close_angle(beta, 90.0) and self._close_angle(gamma, 90.0):
            if self._close_length(a, b) and self._close_length(b, c):
                return ["a"]
            if self._close_length(a, b):
                return ["a", "c"]
            return ["a", "b", "c"]
        if self._close_angle(alpha, 90.0) and self._close_angle(beta, 90.0) and self._close_angle(gamma, 120.0) and self._close_length(a, b):
            return ["a", "c"]
        if self._close_angle(alpha, 90.0) and self._close_angle(gamma, 90.0):
            return ["a", "b", "c", "beta"]
        return ["a", "b", "c", "alpha", "beta", "gamma"]

    def _cell_from_variables(self, initial: CellParameters, variable_names: list[str], values) -> CellParameters:
        data = {
            "a": float(initial.a),
            "b": float(initial.b),
            "c": float(initial.c),
            "alpha": float(initial.alpha),
            "beta": float(initial.beta),
            "gamma": float(initial.gamma),
        }
        for name, value in zip(variable_names, values):
            data[name] = float(value)
        if variable_names == ["a"]:
            data["b"] = data["a"]
            data["c"] = data["a"]
        elif variable_names == ["a", "c"] and self._close_length(float(initial.a), float(initial.b)):
            data["b"] = data["a"]
        volume = self._cell_volume(
            data["a"],
            data["b"],
            data["c"],
            data["alpha"],
            data["beta"],
            data["gamma"],
        )
        return CellParameters(**data, volume=volume)

    def _cell_bounds(self, cell: CellParameters, variable_names: list[str]) -> tuple[np.ndarray, np.ndarray]:
        lower = []
        upper = []
        for name in variable_names:
            value = float(getattr(cell, name))
            if name in {"a", "b", "c"}:
                lower.append(max(value * 0.965, 0.1))
                upper.append(value * 1.035)
            else:
                lower.append(max(value - 2.5, 40.0))
                upper.append(min(value + 2.5, 140.0))
        return np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)

    def _nearest_delta(self, observed_positions: np.ndarray, two_theta: float) -> float:
        if len(observed_positions) == 0:
            return 999.0
        index = int(np.searchsorted(observed_positions, two_theta))
        candidates = []
        if index < len(observed_positions):
            candidates.append(float(observed_positions[index]) - two_theta)
        if index > 0:
            candidates.append(float(observed_positions[index - 1]) - two_theta)
        return min(candidates, key=abs) if candidates else 999.0

    def _matched_peak_residuals(
        self,
        peaks,
        reference_matches: list[tuple[float, float]],
        two_theta_tolerance: float,
    ) -> np.ndarray:
        deltas = self._matched_peak_deltas(peaks, reference_matches, two_theta_tolerance * 2.5)
        if not deltas:
            return np.full(8, 4.0, dtype=float)
        return np.asarray(
            [np.clip(delta / max(two_theta_tolerance, 1.0e-6), -4.0, 4.0) for delta in deltas],
            dtype=float,
        )

    def _matched_peak_deltas(
        self,
        peaks,
        reference_matches: list[tuple[float, float]],
        reference_tolerance: float,
    ) -> list[float]:
        if not peaks:
            return []
        peak_positions = np.asarray([float(peak.two_theta) for peak in peaks], dtype=float)
        deltas = []
        for reference_two_theta, observed_two_theta in reference_matches:
            index = int(np.argmin(np.abs(peak_positions - reference_two_theta)))
            predicted_two_theta = float(peak_positions[index])
            if abs(predicted_two_theta - reference_two_theta) <= reference_tolerance:
                deltas.append(predicted_two_theta - observed_two_theta)
        return deltas

    def _cell_volume(self, a: float, b: float, c: float, alpha: float, beta: float, gamma: float) -> float:
        ar, br, gr = map(math.radians, [alpha, beta, gamma])
        term = 1 + 2 * math.cos(ar) * math.cos(br) * math.cos(gr)
        term -= math.cos(ar) ** 2 + math.cos(br) ** 2 + math.cos(gr) ** 2
        return float(a * b * c * math.sqrt(max(term, 0.0)))

    def _close_length(self, left: float, right: float) -> bool:
        return abs(left - right) <= max(abs(left), abs(right), 1.0) * 0.004

    def _close_angle(self, value: float, target: float) -> bool:
        return abs(value - target) <= 0.35
