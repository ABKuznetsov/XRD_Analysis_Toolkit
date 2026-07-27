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
INDEXED_CELL_STRATEGY = "indexed_cell"
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
        INDEXED_CELL_STRATEGY,
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
            INDEXED_CELL_STRATEGY: "Indexed cell",
            LE_BAIL_STRATEGY: "Le Bail",
            CLASSICAL_RIETVELD_STRATEGY: "Classical Rietveld",
        }
        return labels.get(strategy, strategy.replace("_", " ").title())

    def fit_indexed_cells(
        self,
        phase_structures: list[tuple[str, str, object]],
        *,
        wavelength: float,
        indexed_peak_matches: dict[str, list[tuple[int, int, int, float, float]]] | None = None,
    ) -> list[CellFitResult]:
        results: list[CellFitResult] = []
        matches_by_phase = indexed_peak_matches or {}
        for phase_id, phase_name, structure in phase_structures:
            results.append(
                self.fit_indexed_cell(
                    phase_id=phase_id,
                    phase_name=phase_name,
                    structure=structure,
                    wavelength=wavelength,
                    indexed_matches=matches_by_phase.get(phase_id, []),
                )
            )
        return results

    def fit_indexed_cell(
        self,
        *,
        phase_id: str,
        phase_name: str,
        structure,
        wavelength: float,
        indexed_matches: list[tuple[int, int, int, float, float]],
    ) -> CellFitResult:
        initial_cell = deepcopy(getattr(structure, "cell", CellParameters()))
        variable_names = self._cell_variable_names(initial_cell, structure=structure)
        if not variable_names:
            return CellFitResult(phase_id, phase_name, initial_cell, initial_cell, 0, 0.0, 0.0, False, "Incomplete unit cell.")
        observations = []
        seen_hkl: set[tuple[int, int, int]] = set()
        for h, k, l, observed_two_theta, weight in indexed_matches:
            hkl = (int(h), int(k), int(l))
            if hkl == (0, 0, 0) or hkl in seen_hkl:
                continue
            d_obs = self._d_from_two_theta(float(observed_two_theta), float(wavelength))
            if d_obs is None:
                continue
            seen_hkl.add(hkl)
            observations.append((hkl, float(d_obs), max(float(weight), 1.0)))
        min_observations = max(3, len(variable_names))
        if len(observations) < min_observations:
            return CellFitResult(
                phase_id,
                phase_name,
                initial_cell,
                initial_cell,
                len(observations),
                0.0,
                0.0,
                False,
                f"Need at least {min_observations} indexed peaks.",
            )
        start = np.asarray([float(getattr(initial_cell, name)) for name in variable_names], dtype=float)
        lower, upper = self._cell_bounds(initial_cell, variable_names)
        if not self._observations_resolve_variables(initial_cell, variable_names, observations):
            return CellFitResult(
                phase_id,
                phase_name,
                initial_cell,
                initial_cell,
                len(observations),
                0.0,
                0.0,
                False,
                "Matched hkl values do not independently resolve the cell parameters.",
            )

        isolated_variables = {
            hkl: self._isolated_cell_variable(initial_cell, variable_names, hkl)
            for hkl, _d_obs, _weight in observations
        }
        direct_weight_factors = {
            hkl: (
                6.0
                if isolated_variables.get(hkl) is not None
                else 1.0
            )
            for hkl, _d_obs, _weight in observations
        }

        def residual(
            values: np.ndarray,
            active_observations: list[tuple[tuple[int, int, int], float, float]],
        ) -> np.ndarray:
            cell = self._cell_from_variables(initial_cell, variable_names, values)
            values_out = []
            for hkl, d_obs, weight in active_observations:
                d_calc = self._d_from_hkl(cell, hkl)
                if d_calc is None:
                    values_out.append(4.0)
                    continue
                effective_weight = weight * direct_weight_factors.get(hkl, 1.0)
                values_out.append(
                    ((float(d_calc) - d_obs) / max(d_obs, 1.0e-9))
                    * math.sqrt(effective_weight / 100.0)
                )
            return np.asarray(values_out, dtype=float)

        try:
            active_observations = list(observations)
            current_start = start
            result = None
            for pass_index in range(3):
                result = least_squares(
                    lambda values: residual(values, active_observations),
                    current_start,
                    bounds=(lower, upper),
                    loss="soft_l1",
                    f_scale=0.0018,
                    max_nfev=80,
                )
                current_start = np.asarray(result.x, dtype=float)
                if pass_index >= 2 or len(active_observations) <= min_observations + 1:
                    break
                trial_cell = self._cell_from_variables(initial_cell, variable_names, result.x)
                deltas_with_observations = []
                for observation in active_observations:
                    hkl, d_obs, _weight = observation
                    d_calc = self._d_from_hkl(trial_cell, hkl)
                    calc_two_theta = (
                        self._two_theta_from_d(float(d_calc), float(wavelength))
                        if d_calc is not None
                        else None
                    )
                    obs_two_theta = self._two_theta_from_d(float(d_obs), float(wavelength))
                    if calc_two_theta is None or obs_two_theta is None:
                        continue
                    deltas_with_observations.append(
                        (abs(float(calc_two_theta) - float(obs_two_theta)), observation)
                    )
                if len(deltas_with_observations) <= min_observations:
                    break
                delta_values = np.asarray(
                    [item[0] for item in deltas_with_observations],
                    dtype=float,
                )
                median_delta = float(np.nanmedian(delta_values))
                mad = float(np.nanmedian(np.abs(delta_values - median_delta)))
                clip_limit = max(0.16, median_delta + 2.8 * max(mad, 0.025))
                retained = [
                    observation
                    for delta, observation in deltas_with_observations
                    if delta <= clip_limit
                ]
                if (
                    len(retained) < min_observations
                    or len(retained) == len(active_observations)
                    or not self._observations_resolve_variables(
                        initial_cell,
                        variable_names,
                        retained,
                    )
                ):
                    break
                active_observations = retained
            assert result is not None
            refined_cell = self._cell_from_variables(initial_cell, variable_names, result.x)
            deltas = []
            for hkl, _d_obs, _weight in active_observations:
                d_calc = self._d_from_hkl(refined_cell, hkl)
                if d_calc is None:
                    continue
                two_theta_calc = self._two_theta_from_d(float(d_calc), float(wavelength))
                two_theta_obs = self._two_theta_from_d(float(_d_obs), float(wavelength))
                if two_theta_calc is not None and two_theta_obs is not None:
                    deltas.append(float(two_theta_calc) - float(two_theta_obs))
            delta_array = np.asarray(deltas, dtype=float)
            rms = float(np.sqrt(np.nanmean(delta_array * delta_array))) if len(delta_array) else 0.0
            max_delta = float(np.nanmax(np.abs(delta_array))) if len(delta_array) else 0.0
            return CellFitResult(
                phase_id=phase_id,
                phase_name=phase_name,
                initial_cell=initial_cell,
                refined_cell=refined_cell,
                matched_peaks=len(active_observations),
                rms_delta_two_theta=rms,
                max_delta_two_theta=max_delta,
                success=bool(result.success and len(active_observations) >= min_observations),
                message=str(result.message),
            )
        except Exception as exc:
            return CellFitResult(phase_id, phase_name, initial_cell, initial_cell, 0, 0.0, 0.0, False, str(exc))

    def complete_direct_indexed_matches(
        self,
        *,
        structure,
        indexed_matches: list[tuple[int, int, int, float, float]],
        reference_peaks: list[tuple[int, int, int, float, float]],
        observed_peaks: list[tuple[float, float, float]],
        global_zero_shift: float = 0.0,
    ) -> list[tuple[int, int, int, float, float]]:
        """Add missing direct cell constraints without relaxing the phase Match metric."""
        initial_cell = deepcopy(getattr(structure, "cell", CellParameters()))
        variable_names = self._cell_variable_names(initial_cell, structure=structure)
        if not variable_names or not reference_peaks or not observed_peaks:
            return list(indexed_matches)

        completed = list(indexed_matches)
        prepared_observed = [
            (
                float(two_theta) - float(global_zero_shift),
                max(float(intensity), 0.0),
                max(float(fwhm), 0.05),
            )
            for two_theta, intensity, fwhm in observed_peaks
            if np.isfinite(two_theta) and np.isfinite(intensity)
        ]
        if not prepared_observed:
            return completed

        represented_variables = {
            variable
            for h, k, l, _observed_two_theta, _weight in completed
            if (
                variable := self._isolated_cell_variable(
                    initial_cell,
                    variable_names,
                    (int(h), int(k), int(l)),
                )
            )
            is not None
        }
        observed_intensities = np.asarray([item[1] for item in prepared_observed], dtype=float)
        intensity_floor = float(np.nanpercentile(observed_intensities, 20.0))
        references_by_variable: dict[str, list[tuple[int, int, int, float, float]]] = {}
        for h, k, l, reference_two_theta, reference_intensity in reference_peaks:
            hkl = (int(h), int(k), int(l))
            if hkl == (0, 0, 0):
                continue
            variable = self._isolated_cell_variable(initial_cell, variable_names, hkl)
            if variable not in {"a", "b", "c"}:
                continue
            references_by_variable.setdefault(variable, []).append(
                (
                    hkl[0],
                    hkl[1],
                    hkl[2],
                    float(reference_two_theta),
                    max(float(reference_intensity), 1.0),
                )
            )

        consensus_by_variable = {
            variable: self._direct_match_consensus(
                references=references_by_variable.get(variable, []),
                observed_peaks=prepared_observed,
                intensity_floor=intensity_floor,
            )
            for variable in variable_names
        }
        ratio_hints = []
        for variable, consensus in consensus_by_variable.items():
            if len(consensus) < 2:
                continue
            reference_positions = {
                (h, k, l): reference_two_theta
                for h, k, l, reference_two_theta, _intensity
                in references_by_variable.get(variable, [])
            }
            ratios = [
                self._cell_ratio_from_two_theta(
                    reference_positions[(h, k, l)],
                    observed_two_theta,
                )
                for h, k, l, observed_two_theta, _weight in consensus
                if (h, k, l) in reference_positions
            ]
            ratio_hints.extend(ratio for ratio in ratios if ratio is not None)
        ratio_hint = float(np.nanmedian(ratio_hints)) if ratio_hints else None

        for variable in variable_names:
            references = references_by_variable.get(variable, [])
            consensus = consensus_by_variable.get(variable, [])
            if len(consensus) < 2:
                fallback = self._single_direct_match(
                    references=references,
                    observed_peaks=prepared_observed,
                    intensity_floor=intensity_floor,
                    ratio_hint=ratio_hint,
                )
                if fallback is not None and (
                    ratio_hint is not None or variable not in represented_variables
                ):
                    completed = [
                        match
                        for match in completed
                        if self._isolated_cell_variable(
                            initial_cell,
                            variable_names,
                            (int(match[0]), int(match[1]), int(match[2])),
                        )
                        != variable
                    ]
                    completed.append(fallback)
                continue
            completed = [
                match
                for match in completed
                if self._isolated_cell_variable(
                    initial_cell,
                    variable_names,
                    (int(match[0]), int(match[1]), int(match[2])),
                )
                != variable
            ]
            completed.extend(consensus)
        return completed

    @staticmethod
    def unclaimed_observed_peaks(
        observed_peaks: list[tuple[float, float, float]],
        claimed_peaks: list[tuple[float, float]],
    ) -> list[tuple[float, float, float]]:
        """Keep experimental peaks that are not already explained by earlier phases."""
        if not claimed_peaks:
            return list(observed_peaks)
        available = []
        for two_theta, intensity, fwhm in observed_peaks:
            occupied = any(
                abs(float(two_theta) - float(claimed_two_theta))
                <= max(
                    0.12,
                    min(
                        0.75,
                        max(float(fwhm), float(claimed_fwhm), 0.05) * 1.35,
                    ),
                )
                for claimed_two_theta, claimed_fwhm in claimed_peaks
            )
            if not occupied:
                available.append((float(two_theta), float(intensity), float(fwhm)))
        return available

    def cell_consistent_indexed_matches(
        self,
        *,
        cell: CellParameters,
        indexed_matches: list[tuple[int, int, int, float, float]],
        observed_peaks: list[tuple[float, float, float]],
        wavelength: float,
        tolerance_factor: float = 1.8,
        minimum_tolerance: float = 0.12,
        maximum_tolerance: float = 0.45,
    ) -> list[tuple[int, int, int, float, float]]:
        """Keep indexed observations that agree with a provisional unit cell."""
        consistent = []
        for h, k, l, observed_two_theta, weight in indexed_matches:
            d_spacing = self._d_from_hkl(cell, (int(h), int(k), int(l)))
            calculated_two_theta = (
                self._two_theta_from_d(float(d_spacing), float(wavelength))
                if d_spacing is not None
                else None
            )
            if calculated_two_theta is None:
                continue
            nearest_fwhm = 0.05
            if observed_peaks:
                nearest_peak = min(
                    observed_peaks,
                    key=lambda peak: abs(float(peak[0]) - float(observed_two_theta)),
                )
                nearest_fwhm = max(float(nearest_peak[2]), 0.05)
            tolerance = max(
                float(minimum_tolerance),
                min(float(maximum_tolerance), nearest_fwhm * float(tolerance_factor)),
            )
            if abs(float(calculated_two_theta) - float(observed_two_theta)) <= tolerance:
                consistent.append(
                    (int(h), int(k), int(l), float(observed_two_theta), float(weight))
                )
        return consistent

    @staticmethod
    def _single_direct_match(
        *,
        references: list[tuple[int, int, int, float, float]],
        observed_peaks: list[tuple[float, float, float]],
        intensity_floor: float,
        ratio_hint: float | None = None,
    ) -> tuple[int, int, int, float, float] | None:
        options = []
        for h, k, l, reference_two_theta, reference_intensity in references:
            local = []
            for observed_two_theta, observed_intensity, observed_fwhm in observed_peaks:
                if observed_intensity < intensity_floor:
                    continue
                delta = abs(observed_two_theta - reference_two_theta)
                candidate_ratio = RefinementService._cell_ratio_from_two_theta(
                    reference_two_theta,
                    observed_two_theta,
                )
                if ratio_hint is None:
                    if delta > max(0.48, min(0.75, observed_fwhm * 4.0)):
                        continue
                elif (
                    candidate_ratio is None
                    or not 0.92 <= candidate_ratio <= 1.08
                    or abs(candidate_ratio - ratio_hint) > 0.055
                ):
                    continue
                local.append(
                    (
                        observed_two_theta,
                        observed_intensity,
                        delta,
                        candidate_ratio,
                    )
                )
            if not local:
                continue
            local_max = max(item[1] for item in local)
            observed_two_theta, observed_intensity, delta, candidate_ratio = max(
                local,
                key=lambda item: (
                    (item[1] / max(local_max, 1.0))
                    * (
                        math.exp(
                            -0.5
                            * ((item[3] - ratio_hint) / 0.035) ** 2
                        )
                        if ratio_hint is not None and item[3] is not None
                        else 1.0 / (1.0 + (item[2] / 0.18) ** 2)
                    )
                ),
            )
            score = math.sqrt(max(reference_intensity, 1.0))
            score *= observed_intensity / max(local_max, 1.0)
            if ratio_hint is not None and candidate_ratio is not None:
                score *= math.exp(-0.5 * ((candidate_ratio - ratio_hint) / 0.035) ** 2)
            else:
                score /= 1.0 + (delta / 0.18) ** 2
            options.append(
                (
                    score,
                    (h, k, l, observed_two_theta, max(reference_intensity, 1.0)),
                )
            )
        return max(options, key=lambda item: item[0])[1] if options else None

    def _direct_match_consensus(
        self,
        *,
        references: list[tuple[int, int, int, float, float]],
        observed_peaks: list[tuple[float, float, float]],
        intensity_floor: float,
    ) -> list[tuple[int, int, int, float, float]]:
        if len(references) < 2 or len(observed_peaks) < 2:
            return []
        reference_max = max((item[4] for item in references), default=1.0)
        observed_max = max((item[1] for item in observed_peaks), default=1.0)
        useful_references = [
            item for item in references if item[4] >= max(reference_max * 0.015, 1.0)
        ]
        useful_observed = [
            item for item in observed_peaks if item[1] >= max(intensity_floor, observed_max * 0.01)
        ]
        hypotheses = []
        for _h, _k, _l, reference_two_theta, _reference_intensity in useful_references:
            for observed_two_theta, _observed_intensity, _observed_fwhm in useful_observed:
                ratio = self._cell_ratio_from_two_theta(reference_two_theta, observed_two_theta)
                if ratio is not None and 0.92 <= ratio <= 1.08:
                    hypotheses.append(ratio)
        if not hypotheses:
            return []

        best_score = -1.0
        best_matches: list[tuple[int, int, int, float, float]] = []
        for ratio in hypotheses:
            available = set(range(len(useful_observed)))
            matches = []
            score = 0.0
            for h, k, l, reference_two_theta, reference_intensity in sorted(
                useful_references,
                key=lambda item: item[4],
                reverse=True,
            ):
                predicted = self._scaled_two_theta(reference_two_theta, ratio)
                if predicted is None or not available:
                    continue
                nearest = min(
                    available,
                    key=lambda index: abs(useful_observed[index][0] - predicted),
                )
                observed_two_theta, observed_intensity, observed_fwhm = useful_observed[nearest]
                delta = abs(observed_two_theta - predicted)
                tolerance = max(0.10, min(0.32, observed_fwhm * 2.2))
                if delta > tolerance:
                    continue
                available.remove(nearest)
                reference_fraction = reference_intensity / max(reference_max, 1.0)
                observed_fraction = observed_intensity / max(observed_max, 1.0)
                intensity_agreement = math.exp(
                    -abs(math.log(max(observed_fraction, 0.01) / max(reference_fraction, 0.01)))
                    / 2.2
                )
                closeness = math.exp(-0.5 * (delta / max(tolerance * 0.45, 0.04)) ** 2)
                line_score = math.sqrt(reference_fraction * observed_fraction)
                line_score *= 0.35 + 0.65 * intensity_agreement
                line_score *= closeness
                score += line_score
                matches.append((h, k, l, observed_two_theta, max(reference_intensity, 1.0)))
            if len(matches) < 2:
                continue
            score *= 1.0 + 0.18 * (len(matches) - 1)
            if score > best_score:
                best_score = score
                best_matches = matches
        return best_matches

    @staticmethod
    def _cell_ratio_from_two_theta(reference_two_theta: float, observed_two_theta: float) -> float | None:
        reference_sine = math.sin(math.radians(float(reference_two_theta) / 2.0))
        observed_sine = math.sin(math.radians(float(observed_two_theta) / 2.0))
        if reference_sine <= 0.0 or observed_sine <= 0.0:
            return None
        return reference_sine / observed_sine

    @staticmethod
    def _scaled_two_theta(reference_two_theta: float, cell_ratio: float) -> float | None:
        if cell_ratio <= 0.0:
            return None
        argument = math.sin(math.radians(float(reference_two_theta) / 2.0)) / float(cell_ratio)
        if not 0.0 < argument < 1.0:
            return None
        return math.degrees(2.0 * math.asin(argument))

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

    def _cell_variable_names(self, cell: CellParameters, *, structure=None) -> list[str]:
        required = ("a", "b", "c", "alpha", "beta", "gamma")
        if any(getattr(cell, name, None) is None for name in required):
            return []
        a, b, c = (float(getattr(cell, name)) for name in ("a", "b", "c"))
        alpha, beta, gamma = (float(getattr(cell, name)) for name in ("alpha", "beta", "gamma"))
        try:
            number = int(float(str(getattr(structure, "space_group_number", "") or "")))
        except (TypeError, ValueError):
            number = 0
        if 195 <= number <= 230:
            return ["a"]
        if 168 <= number <= 194:
            return ["a", "c"]
        if 143 <= number <= 167:
            if self._close_angle(gamma, 120.0):
                return ["a", "c"]
            if self._close_length(a, b) and self._close_length(b, c):
                return ["a", "alpha"]
        if 75 <= number <= 142:
            return ["a", "c"]
        if 16 <= number <= 74:
            return ["a", "b", "c"]
        if 3 <= number <= 15:
            return ["a", "b", "c", self._monoclinic_angle_name(alpha, beta, gamma)]
        if 1 <= number <= 2:
            return ["a", "b", "c", "alpha", "beta", "gamma"]
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
        elif variable_names == ["a", "alpha"]:
            data["b"] = data["a"]
            data["c"] = data["a"]
            data["beta"] = data["alpha"]
            data["gamma"] = data["alpha"]
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
                lower.append(max(value * 0.92, 0.1))
                upper.append(value * 1.08)
            else:
                lower.append(max(value - 2.5, 40.0))
                upper.append(min(value + 2.5, 140.0))
        return np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)

    def _isolated_cell_variable(
        self,
        initial: CellParameters,
        variable_names: list[str],
        hkl: tuple[int, int, int],
    ) -> str | None:
        start = np.asarray([float(getattr(initial, name)) for name in variable_names], dtype=float)
        base_cell = self._cell_from_variables(initial, variable_names, start)
        base_d = self._d_from_hkl(base_cell, hkl)
        if base_d is None:
            return None
        active = []
        for index, name in enumerate(variable_names):
            step = max(abs(start[index]) * 1.0e-4, 1.0e-4)
            shifted = start.copy()
            shifted[index] += step
            shifted_d = self._d_from_hkl(self._cell_from_variables(initial, variable_names, shifted), hkl)
            if shifted_d is None:
                continue
            relative_response = abs((float(shifted_d) - float(base_d)) / float(base_d)) / (step / max(abs(start[index]), 1.0))
            if relative_response > 1.0e-3:
                active.append(name)
        return active[0] if len(active) == 1 else None

    def _observations_resolve_variables(self, initial, variable_names, observations) -> bool:
        if not variable_names:
            return False
        start = np.asarray([float(getattr(initial, name)) for name in variable_names], dtype=float)
        rows = []
        for hkl, _d_obs, _weight in observations:
            base_cell = self._cell_from_variables(initial, variable_names, start)
            base_d = self._d_from_hkl(base_cell, hkl)
            if base_d is None:
                continue
            row = []
            for index, name in enumerate(variable_names):
                step = max(abs(start[index]) * 1.0e-5, 1.0e-5 if name in {"a", "b", "c"} else 1.0e-4)
                shifted = start.copy()
                shifted[index] += step
                shifted_d = self._d_from_hkl(self._cell_from_variables(initial, variable_names, shifted), hkl)
                row.append(0.0 if shifted_d is None else (float(shifted_d) - float(base_d)) / step)
            rows.append(row)
        if len(rows) < len(variable_names):
            return False
        return int(np.linalg.matrix_rank(np.asarray(rows, dtype=float), tol=1.0e-8)) >= len(variable_names)

    @staticmethod
    def _monoclinic_angle_name(alpha: float, beta: float, gamma: float) -> str:
        deviations = {
            "alpha": abs(float(alpha) - 90.0),
            "beta": abs(float(beta) - 90.0),
            "gamma": abs(float(gamma) - 90.0),
        }
        return max(deviations, key=deviations.get)

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

    def _d_from_two_theta(self, two_theta: float, wavelength: float) -> float | None:
        theta = math.radians(float(two_theta) / 2.0)
        sin_theta = math.sin(theta)
        if sin_theta <= 0.0:
            return None
        return float(wavelength) / (2.0 * sin_theta)

    def _two_theta_from_d(self, d_spacing: float, wavelength: float) -> float | None:
        d_spacing = float(d_spacing)
        if d_spacing <= 0.0:
            return None
        argument = float(wavelength) / (2.0 * d_spacing)
        if not 0.0 < argument < 1.0:
            return None
        return float(math.degrees(2.0 * math.asin(argument)))

    def _d_from_hkl(self, cell: CellParameters, hkl: tuple[int, int, int]) -> float | None:
        try:
            a = float(cell.a)
            b = float(cell.b)
            c = float(cell.c)
            alpha = math.radians(float(cell.alpha))
            beta = math.radians(float(cell.beta))
            gamma = math.radians(float(cell.gamma))
        except Exception:
            return None
        if min(a, b, c) <= 0.0:
            return None
        direct = np.asarray(
            [
                [a * a, a * b * math.cos(gamma), a * c * math.cos(beta)],
                [a * b * math.cos(gamma), b * b, b * c * math.cos(alpha)],
                [a * c * math.cos(beta), b * c * math.cos(alpha), c * c],
            ],
            dtype=float,
        )
        try:
            reciprocal = np.linalg.inv(direct)
        except np.linalg.LinAlgError:
            return None
        vector = np.asarray(hkl, dtype=float)
        inverse_d2 = float(vector @ reciprocal @ vector)
        if inverse_d2 <= 0.0 or not np.isfinite(inverse_d2):
            return None
        return 1.0 / math.sqrt(inverse_d2)

    def _cell_volume(self, a: float, b: float, c: float, alpha: float, beta: float, gamma: float) -> float:
        ar, br, gr = map(math.radians, [alpha, beta, gamma])
        term = 1 + 2 * math.cos(ar) * math.cos(br) * math.cos(gr)
        term -= math.cos(ar) ** 2 + math.cos(br) ** 2 + math.cos(gr) ** 2
        return float(a * b * c * math.sqrt(max(term, 0.0)))

    def _close_length(self, left: float, right: float) -> bool:
        return abs(left - right) <= max(abs(left), abs(right), 1.0) * 0.004

    def _close_angle(self, value: float, target: float) -> bool:
        return abs(value - target) <= 0.35
