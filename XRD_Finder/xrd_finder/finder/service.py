from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy.optimize import nnls
from scipy.signal import find_peaks

from xrd_finder.finder.assignment_builder import AssignmentBuilder, nearest_index as nearest_peak_index, nearest_phase_peak
from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.models import (
    FinderCandidateInput,
    FinderCandidateResult,
    FinderInput,
    FinderResult,
    ObservedPeak,
)
from xrd_finder.finder.matching import XrdMatchingOptions, XrdSearchMatchResult, search_match_result
from xrd_finder.finder.observed_pattern_processor import ObservedPatternData, ObservedPatternProcessor
from xrd_finder.finder.profile_calculator import CachedProfileCalculator, array_fingerprint
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    CalculatedPatternService,
    HKLPeak,
    radiation_lines_from_wavelength,
)


@dataclass(frozen=True, slots=True)
class FinderHeuristics:
    trusted_peak_tolerance: float = 0.38
    zero_outlier_tolerance: float = 0.14
    zero_consensus_tolerance: float = 0.12
    trusted_zero_max_residual: float = 0.18
    zero_consensus_min_residual: float = 0.16
    zero_consensus_residual_margin: float = 0.08
    zero_min_matched_fraction: float = 0.18
    zero_max_residual: float = 0.22
    trusted_peak_intensity_min: float = 6.0
    strong_peak_intensity_min: float = 8.0
    zero_candidate_peak_tolerance: float = 0.4
    cell_scale_peak_tolerance: float = 0.35
    cell_scale_min: float = 0.97
    cell_scale_max: float = 1.03
    match_tolerance: float = 0.25
    match_peak_intensity_min: float = 5.0
    good_score: float = 0.35
    ok_score: float = 0.18
    snap_min_delta: float = 0.08
    snap_max_delta: float = 0.45
    snap_intensity_min: float = 4.0


class FinderService:
    """Standalone phase-finder core.

    This class intentionally knows nothing about project trees, Qt widgets, or
    ecosystem workflows. GUI apps and future command-line/packaged tools should
    translate their state into FinderInput and render FinderResult.
    """

    def __init__(
        self,
        calculated_pattern_service: CalculatedPatternService | None = None,
        sticks_cache_limit: int = 256,
        profile_cache_limit: int = 256,
        profile_cache_max_bytes: int = 128 * 1024 * 1024,
        observed_cache_limit: int = 64,
        heuristics: FinderHeuristics | None = None,
    ) -> None:
        self.calculated_pattern_service = calculated_pattern_service or CalculatedPatternService()
        self.heuristics = heuristics or FinderHeuristics()
        self.profile_calculator = CachedProfileCalculator(
            self.calculated_pattern_service,
            sticks_cache_limit=sticks_cache_limit,
            profile_cache_limit=profile_cache_limit,
            profile_cache_max_bytes=profile_cache_max_bytes,
        )
        self.assignment_builder = AssignmentBuilder()
        self.observed_processor = ObservedPatternProcessor()
        self._observed_cache: OrderedDict[tuple[object, ...], ObservedPatternData] = OrderedDict()
        self._observed_cache_limit = max(0, int(observed_cache_limit))
        self._observed_hits = 0
        self._observed_misses = 0

    def run(self, finder_input: FinderInput) -> FinderResult:
        observed = self._prepare_observed_cached(finder_input)
        x_grid = observed.x_grid
        wavelength = finder_input.wavelength or CU_KA1_WAVELENGTH
        primary_wavelength = radiation_lines_from_wavelength(wavelength)[0][0]

        candidate_data = []
        two_theta_min = finder_input.two_theta_min or float(np.nanmin(x_grid))
        two_theta_max = finder_input.two_theta_max or float(np.nanmax(x_grid))
        context = CalculationContext(
            wavelength=float(wavelength),
            primary_wavelength=float(primary_wavelength),
            fwhm=float(observed.fwhm),
            two_theta_min=float(two_theta_min),
            two_theta_max=float(two_theta_max),
            x_grid_fingerprint=array_fingerprint(x_grid),
        )
        for candidate in finder_input.candidates:
            try:
                if candidate.structure is not None:
                    peaks = self.calculated_pattern_service.calculate_sticks(
                        candidate.structure,
                        two_theta_min=context.two_theta_min,
                        two_theta_max=context.two_theta_max,
                        wavelength=context.primary_wavelength,
                        use_lp=True,
                    )
                else:
                    peaks = self.profile_calculator.candidate_sticks(
                        candidate.cif_path,
                        context=context,
                        use_lp=True,
                    )
            except Exception:
                continue
            candidate_data.append((candidate, peaks))

        trusted_zero = self._estimate_global_zero_shift_from_trusted_assignments(candidate_data, observed.peaks)
        global_zero = (
            trusted_zero
            if trusted_zero is not None
            else self._estimate_global_zero_shift(candidate_data, observed.peak_positions)
        )
        prepared_profiles = []
        for candidate, peaks in candidate_data:
            cell_scale = self._estimate_phase_cell_scale(peaks, observed.peak_positions, global_zero, context.primary_wavelength)
            phase_context = context.with_alignment(global_zero, cell_scale)
            reference_peaks = self._apply_peak_model(peaks, phase_context)
            adjusted = (
                self._snap_peaks_to_observed(reference_peaks, observed.peak_positions)
                if finder_input.snap_peak_positions
                else reference_peaks
            )
            prepared_profiles.append((candidate, reference_peaks, adjusted, phase_context, cell_scale))

        fitted_fwhm, fitted_eta = self._optimized_profile_parameters(
            observed.target_y,
            [peaks for _candidate, _reference_peaks, peaks, _phase_context, _cell_scale in prepared_profiles],
            x_grid,
            context,
        )
        profiles = []
        for candidate, reference_peaks, adjusted, phase_context, cell_scale in prepared_profiles:
            phase_fwhm, phase_eta = self._optimized_phase_profile_parameters(
                observed.target_y,
                adjusted,
                x_grid,
                replace(context, fwhm=fitted_fwhm, profile_eta=fitted_eta),
            )
            fitted_context = replace(phase_context, fwhm=phase_fwhm, profile_eta=phase_eta)
            profile = self.profile_calculator.profile_from_peaks(
                adjusted,
                x_grid,
                context=fitted_context,
            )
            profiles.append((candidate, reference_peaks, adjusted, profile, cell_scale, phase_fwhm, phase_eta))

        scales = self._fit_scales(observed.target_y, [profile for _candidate, _reference_peaks, _peaks, profile, _cell_scale, _phase_fwhm, _phase_eta in profiles])
        total_scale = float(np.sum(scales)) if len(scales) else 0.0
        calculated_total = np.zeros_like(x_grid)
        results = []
        assignment_phase_sets = []
        phase_fwhm_values = []
        for (candidate, reference_peaks, peaks, profile, cell_scale, phase_fwhm, phase_eta), scale in zip(profiles, scales):
            scaled_profile = profile * float(scale)
            calculated_total += scaled_profile
            if float(scale) > 1e-9:
                phase_fwhm_values.append(float(phase_fwhm))
            match_result = self._match_result(peaks, observed.peak_positions)
            candidate_result = FinderCandidateResult(
                candidate_key=self._candidate_key(candidate),
                entry_id=candidate.entry_id,
                name=candidate.name,
                formula=candidate.formula,
                source=candidate.source,
                scale=float(scale),
                quantity_percent=float(scale / total_scale * 100.0) if total_scale else 0.0,
                score=match_result.score,
                matched_peaks=match_result.matched_peaks,
                total_peaks=match_result.total_peaks,
                mean_delta_two_theta=match_result.mean_delta_two_theta,
                status=match_result.status,
                cell_scale=float(cell_scale),
                fwhm=float(phase_fwhm),
                profile_eta=float(phase_eta),
                two_theta=x_grid.tolist(),
                profile=scaled_profile.tolist(),
                peak_two_theta=[float(peak.two_theta) for peak in peaks],
                peak_reference_two_theta=[float(peak.two_theta) for peak in reference_peaks],
                peak_intensity=[float(peak.intensity) for peak in peaks],
                peak_h=[int(getattr(peak, "h", 0)) for peak in peaks],
                peak_k=[int(getattr(peak, "k", 0)) for peak in peaks],
                peak_l=[int(getattr(peak, "l", 0)) for peak in peaks],
                matched_reference_two_theta=[float(match.reference_two_theta) for match in match_result.matches],
                matched_observed_two_theta=[float(match.observed_two_theta) for match in match_result.matches],
                matched_delta_two_theta=[float(match.delta_two_theta) for match in match_result.matches],
            )
            results.append(candidate_result)
            if float(scale) > 1e-9:
                assignment_phase_sets.append((candidate_result, peaks))

        assigned_peaks = self.assignment_builder.assign_observed_peaks(
            observed.peaks,
            assignment_phase_sets,
            tolerance=max(0.08, min(0.22, (float(np.nanmedian(phase_fwhm_values)) if phase_fwhm_values else fitted_fwhm) * 1.15)),
        )

        return FinderResult(
            pattern_x=x_grid.tolist(),
            pattern_y=observed.observed_y.tolist(),
            background=observed.background.tolist(),
            calculated_total=(calculated_total + observed.background).tolist(),
            global_zero_shift=float(global_zero),
            fwhm=float(np.nanmedian(phase_fwhm_values)) if phase_fwhm_values else float(fitted_fwhm),
            profile_eta=float(fitted_eta),
            candidates=results,
            observed_peaks=assigned_peaks,
        )

    def cache_info(self) -> dict[str, int]:
        info = self.profile_calculator.cache_info()
        info.update({
            "observed": len(self._observed_cache),
            "observed_hits": int(self._observed_hits),
            "observed_misses": int(self._observed_misses),
        })
        return info

    def clear_observed_cache(self) -> None:
        self._observed_cache.clear()
        self._observed_hits = 0
        self._observed_misses = 0

    def _prepare_observed_cached(self, finder_input: FinderInput) -> ObservedPatternData:
        cache_key = self._observed_cache_key(finder_input)
        cached = self._observed_cache.get(cache_key)
        if cached is not None:
            self._observed_hits += 1
            self._observed_cache.move_to_end(cache_key)
            return cached
        self._observed_misses += 1
        observed = self.observed_processor.prepare(finder_input)
        if self._observed_cache_limit > 0:
            self._observed_cache[cache_key] = observed
            while len(self._observed_cache) > self._observed_cache_limit:
                self._observed_cache.popitem(last=False)
        return observed

    def _observed_cache_key(self, finder_input: FinderInput) -> tuple[object, ...]:
        if finder_input.observed_x is not None and finder_input.observed_y is not None:
            x = np.asarray(finder_input.observed_x, dtype=float)
            y = np.asarray(finder_input.observed_y, dtype=float)
            source_key = ("arrays", array_fingerprint(x), array_fingerprint(y))
        else:
            path = Path(finder_input.pattern_path)
            try:
                stat = path.stat()
                source_key = ("file", str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))
            except OSError:
                source_key = ("file", str(path))
        return (
            source_key,
            bool(finder_input.subtract_background),
            self._array_pair_signature(finder_input.background_x, finder_input.background_y),
            int(finder_input.smoothing_window),
            None if finder_input.fwhm is None else round(float(finder_input.fwhm), 6),
        )

    def _array_pair_signature(self, x_values, y_values) -> tuple[object, ...] | None:
        if x_values is None or y_values is None:
            return None
        try:
            x = np.asarray(x_values, dtype=float)
            y = np.asarray(y_values, dtype=float)
        except Exception:
            return None
        if len(x) != len(y) or len(x) == 0:
            return None
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.any(finite):
            return None
        x = x[finite]
        y = y[finite]
        return (
            int(len(x)),
            round(float(x[0]), 6),
            round(float(x[-1]), 6),
            round(float(np.nanmin(y)), 6),
            round(float(np.nanmax(y)), 6),
            round(float(np.nanmean(y)), 6),
        )

    def _candidate_key(self, candidate: FinderCandidateInput) -> str:
        if candidate.entry_id:
            return f"{candidate.source or 'UNKNOWN'}:{candidate.entry_id}"
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
            if abs(float(item["zero"]) - float(best["zero"])) <= self.heuristics.zero_consensus_tolerance
            and float(item["residual"]) <= max(
                self.heuristics.zero_consensus_min_residual,
                float(best["residual"]) + self.heuristics.zero_consensus_residual_margin,
            )
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
                nearest = nearest_phase_peak(observed.two_theta, peaks, tolerance=self.heuristics.trusted_peak_tolerance)
                if nearest is None:
                    continue
                peak, delta = nearest
                if peak.intensity < self.heuristics.trusted_peak_intensity_min:
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
        keep = np.abs(deltas_array - center) <= self.heuristics.zero_outlier_tolerance
        if np.count_nonzero(keep) >= 3:
            deltas_array = deltas_array[keep]
            weights_array = weights_array[keep]
            center = float(np.average(deltas_array, weights=weights_array))
        residual = float(np.average(np.abs(deltas_array - center), weights=weights_array))
        if len(deltas_array) < 3 or residual > self.heuristics.trusted_zero_max_residual:
            return None
        return float(np.clip(center, -0.5, 0.5))

    def _candidate_zero_shift_estimate(self, peaks: list[HKLPeak], observed_positions: np.ndarray) -> dict[str, float] | None:
        strong = sorted(
            [peak for peak in peaks if peak.intensity >= self.heuristics.strong_peak_intensity_min],
            key=lambda peak: peak.intensity,
            reverse=True,
        )[:25]
        if len(strong) < 3:
            return None
        deltas = []
        weights = []
        for peak in strong:
            index = nearest_peak_index(observed_positions, float(peak.two_theta))
            delta = float(observed_positions[index] - peak.two_theta)
            if abs(delta) <= self.heuristics.zero_candidate_peak_tolerance:
                deltas.append(delta)
                weights.append(max(float(peak.intensity), 1.0))
        if len(deltas) < 3:
            return None
        deltas_array = np.asarray(deltas, dtype=float)
        weights_array = np.asarray(weights, dtype=float)
        center = float(np.average(deltas_array, weights=weights_array))
        keep = np.abs(deltas_array - center) <= self.heuristics.zero_outlier_tolerance
        if np.count_nonzero(keep) >= 3:
            deltas_array = deltas_array[keep]
            weights_array = weights_array[keep]
            center = float(np.average(deltas_array, weights=weights_array))
        residual = float(np.average(np.abs(deltas_array - center), weights=weights_array))
        matched_fraction = len(deltas_array) / max(len(strong), 1)
        if (
            len(deltas_array) < 3
            or matched_fraction < self.heuristics.zero_min_matched_fraction
            or residual > self.heuristics.zero_max_residual
        ):
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
            [peak for peak in peaks if peak.intensity >= self.heuristics.strong_peak_intensity_min and peak.d > 0],
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
            index = nearest_peak_index(observed_positions, predicted)
            observed_two_theta = float(observed_positions[index])
            delta = observed_two_theta - predicted
            if abs(delta) > self.heuristics.cell_scale_peak_tolerance:
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
        if not self.heuristics.cell_scale_min <= center <= self.heuristics.cell_scale_max:
            return 1.0
        after_residuals = []
        for peak in strong:
            shifted = self._two_theta_from_scaled_d(peak.d, center, wavelength)
            if shifted is None:
                continue
            predicted = shifted + zero_shift
            index = nearest_peak_index(observed_positions, predicted)
            delta = float(observed_positions[index] - predicted)
            if abs(delta) <= self.heuristics.cell_scale_peak_tolerance:
                after_residuals.append(abs(delta))
        if len(after_residuals) < 4:
            return 1.0
        before = float(np.nanmedian(before_residuals))
        after = float(np.nanmedian(after_residuals))
        if after > before * 0.9:
            return 1.0
        return float(np.clip(center, self.heuristics.cell_scale_min, self.heuristics.cell_scale_max))

    def _apply_peak_model(
        self,
        peaks: list[HKLPeak],
        context: CalculationContext,
    ) -> list[HKLPeak]:
        zero_shift = context.global_zero_shift
        cell_scale = context.cell_scale
        if abs(cell_scale - 1.0) < 1e-7:
            return self._shift_peaks(peaks, zero_shift)
        adjusted = []
        for peak in peaks:
            d_scaled = float(peak.d) * float(cell_scale)
            two_theta = self._two_theta_from_d(d_scaled, context.primary_wavelength)
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
    ) -> list[HKLPeak]:
        if len(observed_positions) == 0:
            return peaks
        snapped = []
        for peak in peaks:
            two_theta = float(peak.two_theta)
            if peak.intensity >= self.heuristics.snap_intensity_min:
                index = nearest_peak_index(observed_positions, two_theta)
                observed_two_theta = float(observed_positions[index])
                delta = observed_two_theta - two_theta
                if self.heuristics.snap_min_delta <= abs(delta) <= self.heuristics.snap_max_delta:
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

    def _optimized_profile_parameters(
        self,
        target_y: np.ndarray,
        peak_sets: list[list[HKLPeak]],
        x_grid: np.ndarray,
        context: CalculationContext,
    ) -> tuple[float, float]:
        base = float(context.fwhm)
        if not peak_sets:
            return base, float(context.profile_eta)
        candidates = np.unique(
            np.clip(
                np.concatenate([
                    np.linspace(max(0.045, base * 0.55), min(0.40, base * 1.45), 7),
                    np.asarray([0.06, 0.085, 0.12, 0.17, 0.24], dtype=float),
                ]),
                0.04,
                0.45,
            )
        )
        eta_candidates = (0.0, 0.25, 0.5, 0.7)
        weights = self._fit_weights(target_y)
        best_fwhm = base
        best_eta = float(context.profile_eta)
        best_score = float("inf")
        for fwhm in candidates:
            for eta in eta_candidates:
                trial_context = replace(context, fwhm=float(fwhm), profile_eta=float(eta))
                profiles = [
                    self.profile_calculator.profile_from_peaks(peaks, x_grid, context=trial_context)
                    for peaks in peak_sets
                    if peaks
                ]
                if not profiles:
                    continue
                scales = self._fit_scales(target_y, profiles)
                calculated = np.zeros_like(target_y, dtype=float)
                for profile, scale in zip(profiles, scales):
                    calculated += profile * float(scale)
                residual = (np.asarray(target_y, dtype=float) - calculated) * weights
                score = float(np.nanmean(residual * residual))
                if score < best_score:
                    best_score = score
                    best_fwhm = float(fwhm)
                    best_eta = float(eta)
        return float(np.clip(best_fwhm, 0.04, 0.45)), float(np.clip(best_eta, 0.0, 0.85))

    def _optimized_phase_profile_parameters(
        self,
        target_y: np.ndarray,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
    ) -> tuple[float, float]:
        base_fwhm = float(context.fwhm)
        base_eta = float(context.profile_eta)
        if not peaks:
            return base_fwhm, base_eta
        candidates = np.unique(
            np.clip(
                np.asarray([base_fwhm * 0.55, base_fwhm * 0.75, base_fwhm, base_fwhm * 1.35, base_fwhm * 1.75], dtype=float),
                0.04,
                0.50,
            )
        )
        eta_candidates = tuple(np.unique(np.clip(np.asarray([base_eta, 0.0, 0.35, 0.65], dtype=float), 0.0, 0.85)))
        weights = self._fit_weights(target_y)
        best_fwhm = base_fwhm
        best_eta = base_eta
        best_score = float("inf")
        for fwhm in candidates:
            for eta in eta_candidates:
                trial_context = replace(context, fwhm=float(fwhm), profile_eta=float(eta))
                profile = self.profile_calculator.profile_from_peaks(peaks, x_grid, context=trial_context)
                scale = self._fit_scales(target_y, [profile])
                if not len(scale):
                    continue
                calculated = profile * float(scale[0])
                residual = (np.asarray(target_y, dtype=float) - calculated) * weights
                score = float(np.nanmean(residual * residual))
                if score < best_score:
                    best_score = score
                    best_fwhm = float(fwhm)
                    best_eta = float(eta)
        return float(np.clip(best_fwhm, 0.04, 0.50)), float(np.clip(best_eta, 0.0, 0.85))

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

    def _match_result(self, peaks: list[HKLPeak], observed_positions: np.ndarray) -> XrdSearchMatchResult:
        return search_match_result(
            peaks,
            observed_positions,
            XrdMatchingOptions(
                tolerance_two_theta=self.heuristics.match_tolerance,
                intensity_min=self.heuristics.match_peak_intensity_min,
                max_reference_peaks=30,
                good_score=self.heuristics.good_score,
                ok_score=self.heuristics.ok_score,
                min_matched_peaks=2,
            ),
        )
