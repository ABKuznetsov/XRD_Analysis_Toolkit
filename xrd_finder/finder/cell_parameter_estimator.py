from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from xrd_finder.core.structure import CellParameters
from xrd_finder.finder.models import ObservedPeak
from xrd_finder.services.calculated_pattern_service import HKLPeak


@dataclass(frozen=True, slots=True)
class CellParameterEstimate:
    cell: CellParameters
    crystal_system: str
    matched_peaks: int
    zero_shift_deg: float
    initial_rms_deg: float
    fitted_rms_deg: float


class FastCellParameterEstimator:
    """Estimate a starting unit cell from a small set of matched indexed peaks."""

    def __init__(
        self,
        *,
        minimum_relative_length: float = 0.92,
        maximum_relative_length: float = 1.08,
        maximum_angle_change_deg: float = 3.0,
    ) -> None:
        self.minimum_relative_length = float(minimum_relative_length)
        self.maximum_relative_length = float(maximum_relative_length)
        self.maximum_angle_change_deg = float(maximum_angle_change_deg)

    def estimate(
        self,
        *,
        initial_cell: CellParameters,
        calculated_peaks: list[HKLPeak],
        observed_peaks: list[ObservedPeak],
        wavelength: float,
        zero_shift_deg: float = 0.0,
        tolerance_deg: float = 0.55,
        refine_zero_shift: bool = True,
    ) -> CellParameterEstimate | None:
        if not self._valid_cell(initial_cell) or not observed_peaks:
            return None
        crystal_system = self._crystal_system(initial_cell)
        pairs = self._matched_pairs(
            calculated_peaks,
            observed_peaks,
            zero_shift_deg=float(zero_shift_deg),
            tolerance_deg=float(tolerance_deg),
        )
        parameter_count = self._parameter_count(crystal_system, initial_cell)
        minimum_matches = max(3, parameter_count + 1)
        if len(pairs) < minimum_matches:
            return None

        fitted = self._fit_reciprocal_metric(
            pairs,
            crystal_system,
            initial_cell,
            wavelength,
            zero_shift_deg=float(zero_shift_deg),
            refine_zero_shift=bool(refine_zero_shift),
        )
        if fitted is None:
            return None
        reciprocal_metric, keep, fitted_zero_shift = fitted
        if np.count_nonzero(keep) < minimum_matches:
            return None
        cell = self._cell_from_reciprocal_metric(reciprocal_metric)
        if cell is None or not self._plausible_change(initial_cell, cell):
            return None

        initial_residuals = np.asarray(
            [
                observed.two_theta - (calculated.two_theta + fitted_zero_shift)
                for calculated, observed in pairs
            ],
            dtype=float,
        )[keep]
        fitted_residuals = self._two_theta_residuals(
            [pair for pair, selected in zip(pairs, keep) if selected],
            reciprocal_metric,
            wavelength=float(wavelength),
            zero_shift_deg=float(fitted_zero_shift),
        )
        if fitted_residuals is None:
            return None
        weights = np.asarray(
            [self._pair_weight(pair) for pair, selected in zip(pairs, keep) if selected],
            dtype=float,
        )
        initial_rms = self._weighted_rms(initial_residuals, weights)
        fitted_rms = self._weighted_rms(fitted_residuals, weights)
        required_improvement = max(0.005, initial_rms * 0.12)
        if not np.isfinite(fitted_rms) or fitted_rms + required_improvement >= initial_rms:
            return None
        return CellParameterEstimate(
            cell=cell,
            crystal_system=crystal_system,
            matched_peaks=int(np.count_nonzero(keep)),
            zero_shift_deg=float(fitted_zero_shift),
            initial_rms_deg=float(initial_rms),
            fitted_rms_deg=float(fitted_rms),
        )

    @staticmethod
    def _valid_cell(cell: CellParameters) -> bool:
        values = (cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma)
        try:
            numeric = np.asarray(values, dtype=float)
        except (TypeError, ValueError):
            return False
        return bool(
            np.all(np.isfinite(numeric))
            and np.all(numeric[:3] > 0.0)
            and np.all((numeric[3:] > 0.0) & (numeric[3:] < 180.0))
        )

    @staticmethod
    def _crystal_system(cell: CellParameters) -> str:
        a, b, c = float(cell.a), float(cell.b), float(cell.c)
        alpha, beta, gamma = float(cell.alpha), float(cell.beta), float(cell.gamma)
        length_tolerance = 0.015
        angle_tolerance = 0.35

        def close_length(left: float, right: float) -> bool:
            return abs(left - right) <= length_tolerance * max(left, right)

        def close_angle(value: float, target: float) -> bool:
            return abs(value - target) <= angle_tolerance

        if close_angle(alpha, 90.0) and close_angle(beta, 90.0) and close_angle(gamma, 120.0):
            return "hexagonal"
        all_right = all(close_angle(value, 90.0) for value in (alpha, beta, gamma))
        if all_right and close_length(a, b) and close_length(a, c):
            return "cubic"
        if all_right and close_length(a, b):
            return "tetragonal"
        if all_right:
            return "orthorhombic"
        if close_length(a, b) and close_length(a, c) and max(alpha, beta, gamma) - min(alpha, beta, gamma) <= angle_tolerance:
            return "rhombohedral"
        right_angles = sum(close_angle(value, 90.0) for value in (alpha, beta, gamma))
        if right_angles == 2:
            return "monoclinic"
        return "triclinic"

    @staticmethod
    def _parameter_count(crystal_system: str, cell: CellParameters) -> int:
        if crystal_system == "cubic":
            return 1
        if crystal_system in {"tetragonal", "hexagonal", "rhombohedral"}:
            return 2
        if crystal_system == "orthorhombic":
            return 3
        if crystal_system == "monoclinic":
            return 4
        return 6

    @staticmethod
    def _matched_pairs(
        calculated_peaks: list[HKLPeak],
        observed_peaks: list[ObservedPeak],
        *,
        zero_shift_deg: float,
        tolerance_deg: float,
    ) -> list[tuple[HKLPeak, ObservedPeak]]:
        indexed = [
            peak
            for peak in calculated_peaks
            if (int(peak.h), int(peak.k), int(peak.l)) != (0, 0, 0)
            and float(peak.intensity) >= 4.0
            and np.isfinite(float(peak.two_theta))
        ]
        indexed.sort(key=lambda peak: float(peak.intensity), reverse=True)
        available = set(range(len(observed_peaks)))
        pairs: list[tuple[HKLPeak, ObservedPeak]] = []
        seen_hkl: set[tuple[int, int, int]] = set()
        for calculated in indexed[:48]:
            hkl = (int(calculated.h), int(calculated.k), int(calculated.l))
            if hkl in seen_hkl or not available:
                continue
            predicted = float(calculated.two_theta) + zero_shift_deg
            nearest = min(
                available,
                key=lambda index: abs(float(observed_peaks[index].two_theta) - predicted),
            )
            observed = observed_peaks[nearest]
            local_tolerance = max(float(tolerance_deg), min(0.8, 2.5 * float(observed.fwhm)))
            if abs(float(observed.two_theta) - predicted) > local_tolerance:
                continue
            seen_hkl.add(hkl)
            available.remove(nearest)
            pairs.append((calculated, observed))
        return pairs

    def _fit_reciprocal_metric(
        self,
        pairs: list[tuple[HKLPeak, ObservedPeak]],
        crystal_system: str,
        initial_cell: CellParameters,
        wavelength: float,
        *,
        zero_shift_deg: float,
        refine_zero_shift: bool,
    ) -> tuple[np.ndarray, np.ndarray, float] | None:
        design = np.asarray(
            [self._design_row(peak.h, peak.k, peak.l, crystal_system, initial_cell) for peak, _observed in pairs],
            dtype=float,
        )
        weights = np.asarray([self._pair_weight(pair) for pair in pairs], dtype=float)
        keep = np.ones(len(pairs), dtype=bool)
        reciprocal_metric = None
        fitted_zero_shift = float(zero_shift_deg)
        for _iteration in range(2):
            fit = self._best_metric_and_zero_shift(
                pairs=pairs,
                design=design,
                weights=weights,
                keep=keep,
                crystal_system=crystal_system,
                initial_cell=initial_cell,
                wavelength=float(wavelength),
                initial_zero_shift=float(fitted_zero_shift),
                refine_zero_shift=bool(refine_zero_shift),
            )
            if fit is None:
                return None
            reciprocal_metric, fitted_zero_shift = fit
            residuals = self._two_theta_residuals(
                pairs,
                reciprocal_metric,
                wavelength=float(wavelength),
                zero_shift_deg=float(fitted_zero_shift),
            )
            if residuals is None:
                return None
            absolute = np.abs(residuals)
            median = float(np.median(absolute[keep]))
            mad = float(np.median(np.abs(absolute[keep] - median)))
            threshold = max(0.12, median + 3.5 * max(mad, 0.01))
            refined_keep = absolute <= threshold
            if (
                np.array_equal(refined_keep, keep)
                or np.count_nonzero(refined_keep) < design.shape[1] + 1
            ):
                break
            keep = refined_keep
        if reciprocal_metric is None:
            return None
        try:
            if np.min(np.linalg.eigvalsh(reciprocal_metric)) <= 0.0:
                return None
        except np.linalg.LinAlgError:
            return None
        return reciprocal_metric, keep, float(fitted_zero_shift)

    def _best_metric_and_zero_shift(
        self,
        *,
        pairs: list[tuple[HKLPeak, ObservedPeak]],
        design: np.ndarray,
        weights: np.ndarray,
        keep: np.ndarray,
        crystal_system: str,
        initial_cell: CellParameters,
        wavelength: float,
        initial_zero_shift: float,
        refine_zero_shift: bool,
    ) -> tuple[np.ndarray, float] | None:
        if refine_zero_shift:
            coarse = np.linspace(-0.65, 0.65, 53)
            zero_candidates = np.unique(np.append(coarse, initial_zero_shift))
        else:
            zero_candidates = np.asarray([initial_zero_shift], dtype=float)

        best = None
        for candidate_zero in zero_candidates:
            fit = self._metric_at_zero_shift(
                pairs=pairs,
                design=design,
                weights=weights,
                keep=keep,
                crystal_system=crystal_system,
                initial_cell=initial_cell,
                wavelength=wavelength,
                zero_shift=float(candidate_zero),
            )
            if fit is None:
                continue
            metric, score = fit
            if best is None or score < best[0]:
                best = (score, metric, float(candidate_zero))
        if best is None or not refine_zero_shift:
            return None if best is None else (best[1], best[2])

        fine = np.linspace(best[2] - 0.035, best[2] + 0.035, 29)
        for candidate_zero in fine:
            fit = self._metric_at_zero_shift(
                pairs=pairs,
                design=design,
                weights=weights,
                keep=keep,
                crystal_system=crystal_system,
                initial_cell=initial_cell,
                wavelength=wavelength,
                zero_shift=float(candidate_zero),
            )
            if fit is None:
                continue
            metric, score = fit
            if score < best[0]:
                best = (score, metric, float(candidate_zero))
        return best[1], best[2]

    def _metric_at_zero_shift(
        self,
        *,
        pairs: list[tuple[HKLPeak, ObservedPeak]],
        design: np.ndarray,
        weights: np.ndarray,
        keep: np.ndarray,
        crystal_system: str,
        initial_cell: CellParameters,
        wavelength: float,
        zero_shift: float,
    ) -> tuple[np.ndarray, float] | None:
        q_values = []
        for _calculated, observed in pairs:
            d_spacing = self._d_from_two_theta(float(observed.two_theta) - zero_shift, wavelength)
            if d_spacing is None:
                return None
            q_values.append(1.0 / (d_spacing * d_spacing))
        target = np.asarray(q_values, dtype=float)
        selected_weights = np.sqrt(weights[keep])
        selected_design = design[keep]
        try:
            parameters, _residuals, rank, _singular = np.linalg.lstsq(
                selected_design * selected_weights[:, None],
                target[keep] * selected_weights,
                rcond=None,
            )
        except np.linalg.LinAlgError:
            return None
        if rank < selected_design.shape[1]:
            return None
        metric = self._metric_from_parameters(parameters, crystal_system, initial_cell)
        try:
            if np.min(np.linalg.eigvalsh(metric)) <= 0.0:
                return None
        except np.linalg.LinAlgError:
            return None
        residuals = self._two_theta_residuals(
            [pair for pair, selected in zip(pairs, keep) if selected],
            metric,
            wavelength=wavelength,
            zero_shift_deg=zero_shift,
        )
        if residuals is None:
            return None
        return metric, self._weighted_rms(residuals, weights[keep])

    @staticmethod
    def _design_row(h: int, k: int, l: int, crystal_system: str, cell: CellParameters) -> list[float]:
        h2, k2, l2 = float(h * h), float(k * k), float(l * l)
        if crystal_system == "cubic":
            return [h2 + k2 + l2]
        if crystal_system == "tetragonal":
            return [h2 + k2, l2]
        if crystal_system == "hexagonal":
            return [h2 + float(h * k) + k2, l2]
        if crystal_system == "rhombohedral":
            return [h2 + k2 + l2, 2.0 * float(h * k + h * l + k * l)]
        if crystal_system == "orthorhombic":
            return [h2, k2, l2]
        if crystal_system == "monoclinic":
            angles = (float(cell.alpha), float(cell.beta), float(cell.gamma))
            unique = int(np.argmax(np.abs(np.asarray(angles) - 90.0)))
            cross = (2.0 * k * l, 2.0 * h * l, 2.0 * h * k)[unique]
            return [h2, k2, l2, float(cross)]
        return [h2, k2, l2, 2.0 * h * k, 2.0 * h * l, 2.0 * k * l]

    @staticmethod
    def _metric_from_parameters(parameters, crystal_system: str, cell: CellParameters) -> np.ndarray:
        values = np.asarray(parameters, dtype=float)
        if crystal_system == "cubic":
            return np.diag([values[0], values[0], values[0]])
        if crystal_system == "tetragonal":
            return np.diag([values[0], values[0], values[1]])
        if crystal_system == "hexagonal":
            return np.asarray(
                [[values[0], values[0] / 2.0, 0.0], [values[0] / 2.0, values[0], 0.0], [0.0, 0.0, values[1]]],
                dtype=float,
            )
        if crystal_system == "rhombohedral":
            return np.asarray(
                [[values[0], values[1], values[1]], [values[1], values[0], values[1]], [values[1], values[1], values[0]]],
                dtype=float,
            )
        if crystal_system == "orthorhombic":
            return np.diag(values[:3])
        metric = np.diag(values[:3])
        if crystal_system == "monoclinic":
            unique = int(np.argmax(np.abs(np.asarray((cell.alpha, cell.beta, cell.gamma), dtype=float) - 90.0)))
            row, column = ((1, 2), (0, 2), (0, 1))[unique]
            metric[row, column] = metric[column, row] = values[3]
            return metric
        metric[0, 1] = metric[1, 0] = values[3]
        metric[0, 2] = metric[2, 0] = values[4]
        metric[1, 2] = metric[2, 1] = values[5]
        return metric

    @staticmethod
    def _cell_from_reciprocal_metric(reciprocal_metric: np.ndarray) -> CellParameters | None:
        try:
            direct = np.linalg.inv(reciprocal_metric)
            lengths = np.sqrt(np.diag(direct))
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            return None
        if not np.all(np.isfinite(lengths)) or np.any(lengths <= 0.0):
            return None

        def angle(numerator: float, denominator: float) -> float:
            return math.degrees(math.acos(float(np.clip(numerator / denominator, -1.0, 1.0))))

        a, b, c = (float(value) for value in lengths)
        alpha = angle(float(direct[1, 2]), b * c)
        beta = angle(float(direct[0, 2]), a * c)
        gamma = angle(float(direct[0, 1]), a * b)
        determinant = float(np.linalg.det(direct))
        if determinant <= 0.0:
            return None
        return CellParameters(
            a=a,
            b=b,
            c=c,
            alpha=alpha,
            beta=beta,
            gamma=gamma,
            volume=math.sqrt(determinant),
        )

    def _plausible_change(self, initial: CellParameters, fitted: CellParameters) -> bool:
        for name in ("a", "b", "c"):
            ratio = float(getattr(fitted, name)) / float(getattr(initial, name))
            if not self.minimum_relative_length <= ratio <= self.maximum_relative_length:
                return False
        return all(
            abs(float(getattr(fitted, name)) - float(getattr(initial, name))) <= self.maximum_angle_change_deg
            for name in ("alpha", "beta", "gamma")
        )

    @staticmethod
    def _two_theta_residuals(
        pairs: list[tuple[HKLPeak, ObservedPeak]],
        reciprocal_metric: np.ndarray,
        *,
        wavelength: float,
        zero_shift_deg: float,
    ) -> np.ndarray | None:
        residuals = []
        for calculated, observed in pairs:
            vector = np.asarray([calculated.h, calculated.k, calculated.l], dtype=float)
            reciprocal_square = float(vector @ reciprocal_metric @ vector)
            if reciprocal_square <= 0.0:
                return None
            d_spacing = 1.0 / math.sqrt(reciprocal_square)
            argument = float(wavelength) / (2.0 * d_spacing)
            if not 0.0 < argument <= 1.0:
                return None
            predicted = math.degrees(2.0 * math.asin(argument)) + zero_shift_deg
            residuals.append(float(observed.two_theta) - predicted)
        return np.asarray(residuals, dtype=float)

    @staticmethod
    def _d_from_two_theta(two_theta: float, wavelength: float) -> float | None:
        sine = math.sin(math.radians(float(two_theta) / 2.0))
        if sine <= 0.0:
            return None
        return float(wavelength) / (2.0 * sine)

    @staticmethod
    def _pair_weight(pair: tuple[HKLPeak, ObservedPeak]) -> float:
        calculated, observed = pair
        return max(math.sqrt(max(float(calculated.intensity), 1.0) * max(float(observed.intensity), 1.0)), 1.0)

    @staticmethod
    def _weighted_rms(residuals: np.ndarray, weights: np.ndarray) -> float:
        return float(math.sqrt(np.average(np.asarray(residuals) ** 2, weights=np.asarray(weights))))


__all__ = ["CellParameterEstimate", "FastCellParameterEstimator"]
