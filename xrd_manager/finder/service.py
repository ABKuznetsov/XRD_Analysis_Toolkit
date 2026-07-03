from __future__ import annotations

import numpy as np
from scipy.optimize import nnls
from scipy.signal import find_peaks, peak_widths, savgol_filter

from xrd_manager.finder.models import (
    FinderCandidateInput,
    FinderCandidateResult,
    FinderInput,
    FinderResult,
    ObservedPeak,
    PeakAssignment,
    PeakStatus,
)
from xrd_manager.io.cif_loader import create_phase_from_cif
from xrd_manager.io.xy_loader import load_xy
from xrd_manager.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    CalculatedPatternService,
    HKLPeak,
    calculated_profile_from_peaks,
    radiation_lines_from_wavelength,
)


class FinderService:
    """Standalone phase-finder core.

    This class intentionally knows nothing about project trees, Qt widgets, or
    ecosystem workflows. GUI apps and future command-line/packaged tools should
    translate their state into FinderInput and render FinderResult.
    """

    def __init__(self, calculated_pattern_service: CalculatedPatternService | None = None) -> None:
        self.calculated_pattern_service = calculated_pattern_service or CalculatedPatternService()

    def run(self, finder_input: FinderInput) -> FinderResult:
        x_grid, observed_y = self._observed_arrays(finder_input)
        observed_y = self._smooth_y(observed_y, finder_input.smoothing_window)
        background = self._estimate_background(observed_y) if finder_input.subtract_background else np.zeros_like(observed_y)
        target_y = np.clip(observed_y - background, 0.0, None)
        wavelength = finder_input.wavelength or CU_KA1_WAVELENGTH
        primary_wavelength = radiation_lines_from_wavelength(wavelength)[0][0]
        fwhm = finder_input.fwhm or self._estimate_fwhm(x_grid, target_y)
        observed_peak_items = self._observed_peaks(x_grid, target_y, fwhm)
        observed_peaks = np.asarray([peak.two_theta for peak in observed_peak_items], dtype=float)

        candidate_data = []
        for candidate in finder_input.candidates:
            try:
                _phase, structure = create_phase_from_cif(candidate.cif_path)
                two_theta_min = finder_input.two_theta_min or float(np.nanmin(x_grid))
                two_theta_max = finder_input.two_theta_max or float(np.nanmax(x_grid))
                peaks = self.calculated_pattern_service.calculate_sticks(
                    structure,
                    two_theta_min=two_theta_min,
                    two_theta_max=two_theta_max,
                    wavelength=primary_wavelength,
                    use_lp=True,
                )
            except Exception:
                continue
            candidate_data.append((candidate, peaks))

        trusted_zero = self._estimate_global_zero_shift_from_trusted_assignments(candidate_data, observed_peak_items)
        global_zero = (
            trusted_zero
            if trusted_zero is not None
            else self._estimate_global_zero_shift(candidate_data, observed_peaks)
        )
        profiles = []
        for candidate, peaks in candidate_data:
            cell_scale = self._estimate_phase_cell_scale(peaks, observed_peaks, global_zero, primary_wavelength)
            reference_peaks = self._apply_peak_model(peaks, zero_shift=global_zero, cell_scale=cell_scale, wavelength=primary_wavelength)
            adjusted = (
                self._snap_peaks_to_observed(reference_peaks, observed_peaks)
                if finder_input.snap_peak_positions
                else reference_peaks
            )
            _x, profile = calculated_profile_from_peaks(
                adjusted,
                x_grid,
                fwhm=fwhm,
                wavelength=wavelength,
            )
            profiles.append((candidate, reference_peaks, adjusted, profile, cell_scale))

        scales = self._fit_scales(target_y, [profile for _candidate, _reference_peaks, _peaks, profile, _cell_scale in profiles])
        total_scale = float(np.sum(scales)) if len(scales) else 0.0
        calculated_total = np.zeros_like(x_grid)
        results = []
        assignment_phase_sets = []
        for (candidate, reference_peaks, peaks, profile, cell_scale), scale in zip(profiles, scales):
            scaled_profile = profile * float(scale)
            calculated_total += scaled_profile
            matched, total = self._count_matches(peaks, observed_peaks)
            score = float(matched / max(total, 1))
            candidate_result = FinderCandidateResult(
                candidate_key=self._candidate_key(candidate),
                entry_id=candidate.entry_id,
                name=candidate.name,
                formula=candidate.formula,
                source=candidate.source,
                scale=float(scale),
                quantity_percent=float(scale / total_scale * 100.0) if total_scale else 0.0,
                score=score,
                matched_peaks=matched,
                total_peaks=total,
                status=self._status(score, matched, total),
                cell_scale=float(cell_scale),
                two_theta=x_grid.tolist(),
                profile=scaled_profile.tolist(),
                peak_two_theta=[float(peak.two_theta) for peak in peaks],
                peak_reference_two_theta=[float(peak.two_theta) for peak in reference_peaks],
                peak_intensity=[float(peak.intensity) for peak in peaks],
            )
            results.append(candidate_result)
            if float(scale) > 1e-9:
                assignment_phase_sets.append((candidate_result, peaks))

        assigned_peaks = self._assign_observed_peaks(
            observed_peak_items,
            assignment_phase_sets,
            tolerance=max(0.28, min(0.55, fwhm * 2.8)),
        )

        return FinderResult(
            pattern_x=x_grid.tolist(),
            pattern_y=observed_y.tolist(),
            background=background.tolist(),
            calculated_total=(calculated_total + background).tolist(),
            global_zero_shift=float(global_zero),
            fwhm=float(fwhm),
            candidates=results,
            observed_peaks=assigned_peaks,
        )

    def _observed_arrays(self, finder_input: FinderInput) -> tuple[np.ndarray, np.ndarray]:
        if finder_input.observed_x is not None and finder_input.observed_y is not None:
            x = np.asarray(finder_input.observed_x, dtype=float)
            y = np.asarray(finder_input.observed_y, dtype=float)
            if len(x) != len(y) or len(x) == 0:
                raise ValueError("Observed X/Y arrays must be non-empty and have equal length.")
            return x, y
        observed = load_xy(finder_input.pattern_path)
        return np.asarray(observed[:, 0], dtype=float), np.asarray(observed[:, 1], dtype=float)

    def _smooth_y(self, y: np.ndarray, window: int) -> np.ndarray:
        if window <= 2 or len(y) < 5:
            return y
        window = min(int(window), len(y) - 1 if len(y) % 2 == 0 else len(y))
        if window % 2 == 0:
            window -= 1
        if window < 5:
            return y
        try:
            return np.asarray(savgol_filter(y, window_length=window, polyorder=2, mode="interp"), dtype=float)
        except Exception:
            kernel = np.ones(window, dtype=float) / float(window)
            return np.convolve(y, kernel, mode="same")

    def _estimate_background(self, y: np.ndarray) -> np.ndarray:
        if len(y) < 5:
            return np.zeros_like(y)
        window = max(31, (len(y) // 80) | 1)
        padded = np.pad(y, (window // 2, window // 2), mode="edge")
        baseline = np.empty_like(y, dtype=float)
        for index in range(len(y)):
            baseline[index] = float(np.nanpercentile(padded[index:index + window], 15))
        return baseline

    def _estimate_fwhm(self, x: np.ndarray, y: np.ndarray) -> float:
        if len(x) < 5 or float(np.nanmax(y)) <= 0:
            return 0.18
        prominence = max(float(np.nanmax(y)) * 0.08, 1.0)
        indices, _properties = find_peaks(y, prominence=prominence, distance=max(3, len(y) // 1000))
        if len(indices) == 0:
            return 0.18
        widths = peak_widths(y, indices, rel_height=0.5)[0]
        step = abs(float(np.nanmedian(np.diff(x)))) if len(x) > 1 else 0.02
        return float(np.clip(np.nanmedian(widths) * step, 0.05, 0.35))

    def _observed_peak_positions(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        return np.asarray([peak.two_theta for peak in self._observed_peaks(x, y, 0.18)], dtype=float)

    def _observed_peaks(self, x: np.ndarray, y: np.ndarray, fwhm: float) -> list[ObservedPeak]:
        if len(x) < 5 or float(np.nanmax(y)) <= 0:
            return []
        prominence = max(float(np.nanmax(y)) * 0.03, 1.0)
        indices, _properties = find_peaks(y, prominence=prominence, distance=max(3, len(y) // 1000))
        if len(indices) > 150:
            heights = y[indices]
            indices = indices[np.argsort(heights)[-150:]]
        ordered = indices[np.argsort(np.asarray(x, dtype=float)[indices])]
        return [
            ObservedPeak(
                two_theta=float(x[index]),
                intensity=float(y[index]),
                fwhm=float(fwhm),
            )
            for index in ordered
        ]

    def _assign_observed_peaks(
        self,
        observed_peaks: list[ObservedPeak],
        phase_peak_sets: list[tuple[FinderCandidateResult, list[HKLPeak]]],
        tolerance: float,
    ) -> list[ObservedPeak]:
        assigned = []
        for observed in observed_peaks:
            assignments = []
            for candidate, peaks in phase_peak_sets:
                nearest = self._nearest_phase_peak(observed.two_theta, peaks, tolerance)
                if nearest is None:
                    continue
                peak, delta = nearest
                assignments.append(
                    PeakAssignment(
                        candidate_key=candidate.candidate_key,
                        phase_name=candidate.name or candidate.formula or candidate.entry_id,
                        hkl=(int(peak.h), int(peak.k), int(peak.l)),
                        calc_two_theta=float(peak.two_theta),
                        delta_two_theta=float(delta),
                        intensity_ratio=float(max(peak.intensity, 0.0) / 100.0),
                    )
                )
            if len(assignments) == 0:
                status = PeakStatus.UNKNOWN
            elif len(assignments) == 1:
                status = PeakStatus.MATCHED
            else:
                status = PeakStatus.OVERLAPPING
            assigned.append(
                ObservedPeak(
                    two_theta=observed.two_theta,
                    intensity=observed.intensity,
                    fwhm=observed.fwhm,
                    assignments=assignments,
                    status=status,
                )
            )
        return assigned

    def _nearest_phase_peak(
        self,
        observed_two_theta: float,
        peaks: list[HKLPeak],
        tolerance: float,
    ) -> tuple[HKLPeak, float] | None:
        usable = [peak for peak in peaks if peak.intensity >= 0.8]
        if not usable:
            return None
        deltas = np.asarray([float(observed_two_theta) - float(peak.two_theta) for peak in usable], dtype=float)
        index = int(np.argmin(np.abs(deltas)))
        delta = float(deltas[index])
        if abs(delta) > tolerance:
            return None
        return usable[index], delta

    def _candidate_key(self, candidate: FinderCandidateInput) -> str:
        if candidate.entry_id:
            return candidate.entry_id
        if candidate.source and candidate.formula:
            return f"{candidate.source}:{candidate.formula}"
        return candidate.cif_path

    def _estimate_global_zero_shift(
        self,
        candidate_data: list[tuple[FinderCandidateInput, list[HKLPeak]]],
        observed_positions: np.ndarray,
    ) -> float:
        if len(observed_positions) == 0:
            return 0.0
        estimates = []
        for _candidate, peaks in candidate_data:
            estimate = self._candidate_zero_shift_estimate(peaks, observed_positions)
            if estimate is not None:
                estimates.append(estimate)
        if not estimates:
            return 0.0
        estimates.sort(key=lambda item: item["quality"], reverse=True)
        best = estimates[0]
        consensus = [
            item
            for item in estimates
            if abs(float(item["zero"]) - float(best["zero"])) <= 0.12
            and float(item["residual"]) <= max(0.16, float(best["residual"]) + 0.08)
        ]
        if not consensus:
            consensus = [best]
        zeros = np.asarray([item["zero"] for item in consensus], dtype=float)
        weights = np.asarray([item["quality"] for item in consensus], dtype=float)
        center = float(np.average(zeros, weights=weights))
        return float(np.clip(center, -0.5, 0.5))

    def _estimate_global_zero_shift_from_trusted_assignments(
        self,
        candidate_data: list[tuple[FinderCandidateInput, list[HKLPeak]]],
        observed_peaks: list[ObservedPeak],
    ) -> float | None:
        if not candidate_data or len(observed_peaks) < 3:
            return None
        deltas = []
        weights = []
        for observed in observed_peaks:
            possible = []
            for _candidate, peaks in candidate_data:
                nearest = self._nearest_phase_peak(observed.two_theta, peaks, tolerance=0.38)
                if nearest is None:
                    continue
                peak, delta = nearest
                if peak.intensity < 6.0:
                    continue
                possible.append((peak, delta))
            if len(possible) != 1:
                continue
            peak, delta = possible[0]
            deltas.append(float(delta))
            weights.append(max(float(observed.intensity), 1.0) * max(float(peak.intensity), 1.0))
        if len(deltas) < 3:
            return None
        deltas_array = np.asarray(deltas, dtype=float)
        weights_array = np.asarray(weights, dtype=float)
        center = float(np.average(deltas_array, weights=weights_array))
        keep = np.abs(deltas_array - center) <= 0.14
        if np.count_nonzero(keep) >= 3:
            deltas_array = deltas_array[keep]
            weights_array = weights_array[keep]
            center = float(np.average(deltas_array, weights=weights_array))
        residual = float(np.average(np.abs(deltas_array - center), weights=weights_array))
        if len(deltas_array) < 3 or residual > 0.18:
            return None
        return float(np.clip(center, -0.5, 0.5))

    def _candidate_zero_shift_estimate(self, peaks: list[HKLPeak], observed_positions: np.ndarray) -> dict[str, float] | None:
        strong = sorted(
            [peak for peak in peaks if peak.intensity >= 8.0],
            key=lambda peak: peak.intensity,
            reverse=True,
        )[:25]
        if len(strong) < 3:
            return None
        deltas = []
        weights = []
        for peak in strong:
            nearest_index = int(np.argmin(np.abs(observed_positions - peak.two_theta)))
            delta = float(observed_positions[nearest_index] - peak.two_theta)
            if abs(delta) <= 0.4:
                deltas.append(delta)
                weights.append(max(float(peak.intensity), 1.0))
        if len(deltas) < 3:
            return None
        deltas_array = np.asarray(deltas, dtype=float)
        weights_array = np.asarray(weights, dtype=float)
        center = float(np.average(deltas_array, weights=weights_array))
        keep = np.abs(deltas_array - center) <= 0.14
        if np.count_nonzero(keep) >= 3:
            deltas_array = deltas_array[keep]
            weights_array = weights_array[keep]
            center = float(np.average(deltas_array, weights=weights_array))
        residual = float(np.average(np.abs(deltas_array - center), weights=weights_array))
        matched_fraction = len(deltas_array) / max(len(strong), 1)
        if len(deltas_array) < 3 or matched_fraction < 0.18 or residual > 0.22:
            return None
        quality = (len(deltas_array) * matched_fraction * float(np.nanmean(weights_array))) / (residual + 0.03)
        return {
            "zero": float(np.clip(center, -0.5, 0.5)),
            "residual": residual,
            "quality": max(quality, 1e-6),
        }

    def _shift_peaks(self, peaks: list[HKLPeak], zero_shift: float) -> list[HKLPeak]:
        return [
            HKLPeak(
                h=peak.h,
                k=peak.k,
                l=peak.l,
                d=peak.d,
                two_theta=float(peak.two_theta) + zero_shift,
                intensity=peak.intensity,
                multiplicity=peak.multiplicity,
                f2=peak.f2,
                lp=peak.lp,
                raw_intensity=peak.raw_intensity,
            )
            for peak in peaks
        ]

    def _estimate_phase_cell_scale(
        self,
        peaks: list[HKLPeak],
        observed_positions: np.ndarray,
        zero_shift: float,
        wavelength: float,
    ) -> float:
        if len(observed_positions) == 0:
            return 1.0
        strong = sorted(
            [peak for peak in peaks if peak.intensity >= 8.0 and peak.d > 0],
            key=lambda peak: peak.intensity,
            reverse=True,
        )[:30]
        if len(strong) < 4:
            return 1.0
        scales = []
        weights = []
        before_residuals = []
        for peak in strong:
            predicted = float(peak.two_theta) + zero_shift
            nearest_index = int(np.argmin(np.abs(observed_positions - predicted)))
            observed_two_theta = float(observed_positions[nearest_index])
            delta = observed_two_theta - predicted
            if abs(delta) > 0.35:
                continue
            d_observed = self._d_from_two_theta(observed_two_theta - zero_shift, wavelength)
            if d_observed is None:
                continue
            scales.append(d_observed / float(peak.d))
            weights.append(max(float(peak.intensity), 1.0))
            before_residuals.append(abs(delta))
        if len(scales) < 4:
            return 1.0
        scales_array = np.asarray(scales, dtype=float)
        weights_array = np.asarray(weights, dtype=float)
        center = float(np.average(scales_array, weights=weights_array))
        keep = np.abs(scales_array - center) <= 0.004
        if np.count_nonzero(keep) >= 4:
            scales_array = scales_array[keep]
            weights_array = weights_array[keep]
            center = float(np.average(scales_array, weights=weights_array))
        if not 0.97 <= center <= 1.03:
            return 1.0
        after_residuals = []
        for peak in strong:
            shifted = self._two_theta_from_scaled_d(peak.d, center, wavelength)
            if shifted is None:
                continue
            predicted = shifted + zero_shift
            nearest_index = int(np.argmin(np.abs(observed_positions - predicted)))
            delta = float(observed_positions[nearest_index] - predicted)
            if abs(delta) <= 0.35:
                after_residuals.append(abs(delta))
        if len(after_residuals) < 4:
            return 1.0
        before = float(np.nanmedian(before_residuals))
        after = float(np.nanmedian(after_residuals))
        if after > before * 0.9:
            return 1.0
        return float(np.clip(center, 0.97, 1.03))

    def _apply_peak_model(
        self,
        peaks: list[HKLPeak],
        zero_shift: float,
        cell_scale: float,
        wavelength: float,
    ) -> list[HKLPeak]:
        if abs(cell_scale - 1.0) < 1e-7:
            return self._shift_peaks(peaks, zero_shift)
        adjusted = []
        for peak in peaks:
            d_scaled = float(peak.d) * float(cell_scale)
            two_theta = self._two_theta_from_d(d_scaled, wavelength)
            if two_theta is None:
                continue
            adjusted.append(
                HKLPeak(
                    h=peak.h,
                    k=peak.k,
                    l=peak.l,
                    d=d_scaled,
                    two_theta=two_theta + zero_shift,
                    intensity=peak.intensity,
                    multiplicity=peak.multiplicity,
                    f2=peak.f2,
                    lp=peak.lp,
                    raw_intensity=peak.raw_intensity,
                )
            )
        return adjusted

    def _two_theta_from_scaled_d(self, d_spacing: float, cell_scale: float, wavelength: float) -> float | None:
        return self._two_theta_from_d(float(d_spacing) * float(cell_scale), wavelength)

    def _two_theta_from_d(self, d_spacing: float, wavelength: float) -> float | None:
        if d_spacing <= 0:
            return None
        argument = float(wavelength) / (2.0 * float(d_spacing))
        if not 0.0 < argument < 1.0:
            return None
        return float(np.rad2deg(2.0 * np.arcsin(argument)))

    def _d_from_two_theta(self, two_theta: float, wavelength: float) -> float | None:
        theta = np.deg2rad(float(two_theta) / 2.0)
        sine = float(np.sin(theta))
        if sine <= 0:
            return None
        return float(wavelength) / (2.0 * sine)

    def _snap_peaks_to_observed(
        self,
        peaks: list[HKLPeak],
        observed_positions: np.ndarray,
        min_delta: float = 0.08,
        max_delta: float = 0.45,
        intensity_min: float = 4.0,
    ) -> list[HKLPeak]:
        if len(observed_positions) == 0:
            return peaks
        snapped = []
        for peak in peaks:
            two_theta = float(peak.two_theta)
            if peak.intensity >= intensity_min:
                nearest_index = int(np.argmin(np.abs(observed_positions - two_theta)))
                observed_two_theta = float(observed_positions[nearest_index])
                delta = observed_two_theta - two_theta
                if min_delta <= abs(delta) <= max_delta:
                    two_theta = observed_two_theta
            snapped.append(
                HKLPeak(
                    h=peak.h,
                    k=peak.k,
                    l=peak.l,
                    d=peak.d,
                    two_theta=two_theta,
                    intensity=peak.intensity,
                    multiplicity=peak.multiplicity,
                    f2=peak.f2,
                    lp=peak.lp,
                    raw_intensity=peak.raw_intensity,
                )
            )
        return snapped

    def _fit_scales(self, target_y: np.ndarray, profiles: list[np.ndarray]) -> np.ndarray:
        if not profiles:
            return np.array([], dtype=float)
        matrix = np.column_stack(profiles)
        weights = self._fit_weights(target_y)
        try:
            scales, _residual = nnls(matrix * weights[:, None], target_y * weights)
        except Exception:
            try:
                scales, *_rest = np.linalg.lstsq(matrix * weights[:, None], target_y * weights, rcond=None)
            except Exception:
                scales = np.ones(len(profiles), dtype=float)
        scales = np.clip(np.asarray(scales, dtype=float), 0.0, None)
        if not np.any(scales):
            scales = np.ones(len(profiles), dtype=float)
        return scales

    def _fit_weights(self, target_y: np.ndarray) -> np.ndarray:
        y = np.asarray(target_y, dtype=float)
        if len(y) == 0:
            return np.ones_like(y)
        positive = np.clip(y, 0.0, None)
        noise_floor = max(float(np.nanpercentile(positive, 55)), 1.0)
        high_cap = max(float(np.nanpercentile(positive, 96)), noise_floor)
        compressed = np.sqrt(np.clip(positive, noise_floor, high_cap))
        weights = 1.0 / compressed
        peak_indices, _properties = find_peaks(
            positive,
            prominence=max(float(np.nanpercentile(positive, 98)) * 0.025, float(np.nanstd(positive)) * 2.0, 1.0),
            distance=max(3, len(positive) // 1000),
        )
        half_width = max(2, len(positive) // 900)
        for index in peak_indices:
            left = max(0, index - half_width)
            right = min(len(positive), index + half_width + 1)
            weights[left:right] *= 2.5
        return weights / max(float(np.nanmedian(weights)), 1e-9)

    def _count_matches(self, peaks: list[HKLPeak], observed_positions: np.ndarray) -> tuple[int, int]:
        strong = sorted(
            [peak for peak in peaks if peak.intensity >= 5.0],
            key=lambda peak: peak.intensity,
            reverse=True,
        )[:30]
        matched = 0
        for peak in strong:
            if len(observed_positions) and float(np.min(np.abs(observed_positions - peak.two_theta))) <= 0.25:
                matched += 1
        return matched, len(strong)

    def _status(self, score: float, matched: int, total: int) -> str:
        if matched < 2:
            return "weak"
        if score >= 0.35:
            return "good"
        if score >= 0.18:
            return "ok"
        return "weak"
