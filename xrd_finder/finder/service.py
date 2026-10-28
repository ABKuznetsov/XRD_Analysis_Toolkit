from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import math
from scipy.optimize import nnls
from scipy.signal import find_peaks

from xrd_finder.finder.assignment_builder import AssignmentBuilder, nearest_index as nearest_peak_index, nearest_phase_peak
from xrd_finder.finder.cell_parameter_estimator import CellParameterEstimate, FastCellParameterEstimator
from xrd_finder.finder.context import CalculationContext
from xrd_finder.finder.fingerprint_matching import fingerprint_match_score
from xrd_finder.finder.quantification import fit_accepted_phases, mass_fractions
from xrd_finder.finder.models import (
    FinderCandidateInput,
    FinderCandidateFailure,
    FinderCandidateResult,
    FinderInput,
    FinderResult,
    ObservedPeak,
)
from xrd_finder.finder.matching import XrdMatchingOptions, XrdSearchMatchResult, search_match_result
from xrd_finder.finder.observed_pattern_processor import ObservedPatternData, ObservedPatternProcessor
from xrd_finder.finder.profile_calculator import CachedProfileCalculator, array_fingerprint
from xrd_finder.finder.profile_width_estimator import estimate_phase_fwhm_from_signal
from xrd_finder.finder.profile_backend import instrument_fwhm_at, profile_reference_angle
from xrd_finder.services.calculated_pattern_service import (
    CU_KA1_WAVELENGTH,
    CalculatedPatternService,
    HKLPeak,
    expand_atoms_by_symmetry,
    radiation_lines_from_wavelength,
)
from xrd_finder.services.element_masses import atomic_weight
from xrd_finder.services.peak_cell_alignment import apply_peak_cell, estimate_peak_cell_alignment, improve_peak_cell_estimate


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
    cell_parameter_peak_tolerance: float = 0.55


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
        cell_parameter_estimator: FastCellParameterEstimator | None = None,
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
        self.cell_parameter_estimator = cell_parameter_estimator or FastCellParameterEstimator()
        self.observed_processor = ObservedPatternProcessor()
        self._observed_cache: OrderedDict[tuple[object, ...], ObservedPatternData] = OrderedDict()
        self._observed_cache_limit = max(0, int(observed_cache_limit))
        self._observed_hits = 0
        self._observed_misses = 0

    def run(self, finder_input: FinderInput) -> FinderResult:
        observed = self._prepare_observed_cached(finder_input)
        x_grid = observed.x_grid
        wavelength = finder_input.wavelength or CU_KA1_WAVELENGTH
        primary_wavelength = radiation_lines_from_wavelength(
            wavelength,
            include_kalpha2=finder_input.include_kalpha2,
        )[0][0]
        if finder_input.instrument_profile is not None:
            primary_wavelength = finder_input.instrument_profile.radiation.components[0].wavelength_angstrom

        candidate_data = []
        candidate_failures = []
        two_theta_min = finder_input.two_theta_min or float(np.nanmin(x_grid))
        two_theta_max = finder_input.two_theta_max or float(np.nanmax(x_grid))
        context = CalculationContext(
            wavelength=float(wavelength),
            primary_wavelength=float(primary_wavelength),
            fwhm=float(observed.fwhm),
            two_theta_min=float(two_theta_min),
            two_theta_max=float(two_theta_max),
            x_grid_fingerprint=array_fingerprint(x_grid),
            include_kalpha2=bool(finder_input.include_kalpha2),
            instrument_profile_key=(
                ""
                if finder_input.instrument_profile is None
                else finder_input.instrument_profile.calculation_key()
            ),
        )
        for candidate in finder_input.candidates:
            try:
                if candidate.structure is not None and not candidate.cif_path:
                    structure = candidate.structure
                    line_data = None
                    peaks = self.calculated_pattern_service.calculate_sticks(
                        structure,
                        two_theta_min=context.two_theta_min,
                        two_theta_max=context.two_theta_max,
                        wavelength=context.primary_wavelength,
                        use_lp=True,
                    )
                elif candidate.reference_lines is not None:
                    structure = None
                    line_data = None
                    peaks = self.profile_calculator.peaks_from_reference_lines(
                        candidate.reference_lines,
                        context,
                        instrument_profile=finder_input.instrument_profile,
                    )
                else:
                    structure, line_data = self.profile_calculator.line_calculator.candidate_structure_and_lines(
                        candidate.cif_path,
                        context=context,
                        use_lp=True,
                        instrument_profile=finder_input.instrument_profile,
                    )
                    peaks = list(line_data.peaks)
            except Exception as exc:
                candidate_failures.append(FinderCandidateFailure(
                    self._candidate_key(candidate), candidate.entry_id, candidate.source,
                    candidate.cif_path, 'reference_lines', type(exc).__name__, str(exc)))
                continue
            candidate_data.append((candidate, structure, peaks, line_data))

        alignment_data = [
            (candidate, peaks)
            for candidate, _structure, peaks, _line_data in candidate_data
        ]
        # Adding an impurity candidate must not move the instrument alignment
        # already established by the primary phase.
        primary_alignment_data = alignment_data[:1]
        global_zero = self.estimate_zero_shift(
            primary_alignment_data[0][1] if primary_alignment_data else [],
            observed.peaks,
            wavelength=context.primary_wavelength,
        )
        if not finder_input.refine_scan_zero:
            trusted_zero = self._estimate_global_zero_shift_from_trusted_assignments(
                primary_alignment_data, observed.peaks)
            if trusted_zero is not None:
                global_zero = float(trusted_zero)
        prepared_profiles = []
        for candidate_index, (candidate, structure, peaks, line_data) in enumerate(candidate_data):
            cell_estimate = None
            if structure is None and candidate.reference_lines is not None:
                # The accepted-phase fast path has indexed d spacings but no CIF
                # object. Estimate its metric without recalculating intensities.
                alignment = estimate_peak_cell_alignment(
                    self._shift_peaks(peaks, global_zero),
                    observed.peaks,
                    wavelength=context.primary_wavelength,
                    zero_shift=global_zero,
                    initial_cell=candidate.initial_cell,
                    refine_scan_zero=candidate_index == 0 and finder_input.refine_scan_zero,
                )
                cell_estimate = alignment.estimate
                if cell_estimate is not None:
                    if candidate_index == 0 and finder_input.refine_scan_zero:
                        global_zero = float(cell_estimate.zero_shift_deg)
                    peaks = self._shift_peaks(list(alignment.peaks), -global_zero)
            if self._has_indexed_cell(structure, peaks):
                cell_estimate = self.cell_parameter_estimator.estimate(
                    initial_cell=structure.cell,
                    calculated_peaks=peaks,
                    observed_peaks=observed.peaks,
                    wavelength=context.primary_wavelength,
                    zero_shift_deg=global_zero,
                    tolerance_deg=self.heuristics.cell_parameter_peak_tolerance,
                    refine_zero_shift=candidate_index == 0 and finder_input.refine_scan_zero,
                )
                cell_estimate = improve_peak_cell_estimate(peaks, observed.peaks,
                    baseline_estimate=cell_estimate, initial_cell=structure.cell,
                    wavelength=context.primary_wavelength, zero_shift=global_zero,
                    refine_scan_zero=candidate_index == 0 and finder_input.refine_scan_zero)
                if cell_estimate is not None:
                    try:
                        if candidate.cif_path:
                            structure, line_data = self.profile_calculator.line_calculator.candidate_structure_and_lines(
                                candidate.cif_path,
                                context=context,
                                use_lp=True,
                                instrument_profile=finder_input.instrument_profile,
                                cell_override=cell_estimate.cell,
                            )
                            peaks = list(line_data.peaks)
                        else:
                            positioned = apply_peak_cell(peaks, cell_estimate.cell,
                                wavelength=context.primary_wavelength, zero_shift=0.0)
                            if positioned is None:
                                raise ValueError("Invalid estimated peak metric")
                            peaks = list(positioned)
                        if candidate_index == 0 and finder_input.refine_scan_zero:
                            global_zero = float(cell_estimate.zero_shift_deg)
                    except Exception:
                        cell_estimate = None
            # Indexed CIF phases keep their crystallographic metric. Applying one
            # scalar to every d-spacing makes distinct anisotropic cells converge
            # to the same apparent pattern. Their independent a/b/c/angles are
            # estimated below from matched hkl values instead.
            cell_scale = (
                1.0
                if candidate.reference_lines is not None or self._has_indexed_cell(structure, peaks)
                else self._estimate_phase_cell_scale(
                    peaks,
                    observed.peak_positions,
                    global_zero,
                    context.primary_wavelength,
                )
            )
            phase_context = context.with_alignment(global_zero, cell_scale)
            reference_peaks = self._apply_peak_model(peaks, phase_context)
            indexed_geometry = any((peak.h, peak.k, peak.l) != (0, 0, 0) for peak in reference_peaks)
            adjusted = (
                self._snap_peaks_to_observed(reference_peaks, observed.peak_positions)
                # An indexed phase must retain one coherent lattice even when
                # its cell estimate is rejected. Independent peak snapping can
                # otherwise impersonate reflections of another phase.
                if finder_input.snap_peak_positions and cell_estimate is None and not indexed_geometry
                else reference_peaks
            )
            # Load accepted physical line sets before optimizing their shape,
            # so the trial and final profiles share geometry, spectrum and LP.
            if line_data is None and candidate.quantification_cif_path:
                try:
                    physical_structure, physical_lines = self.profile_calculator.line_calculator.candidate_structure_and_lines(
                        candidate.quantification_cif_path, context=context, use_lp=True,
                        instrument_profile=finder_input.instrument_profile,
                        cell_override=(cell_estimate.cell if cell_estimate is not None else
                                       getattr(structure, "cell", None)),
                    )
                    if structure is not None and (
                        structure.atoms != physical_structure.atoms or structure.symops != physical_structure.symops
                    ):
                        raise ValueError("Modified atomic sites require a new physical structure calculation")
                    structure, line_data = physical_structure, physical_lines
                    reference_peaks = self._apply_peak_model(list(line_data.peaks), phase_context)
                    adjusted = reference_peaks
                except (OSError, ValueError, RuntimeError):
                    line_data = None
            prepared_profiles.append(
                (
                    candidate,
                    structure,
                    reference_peaks,
                    adjusted,
                    phase_context,
                    cell_scale,
                    line_data,
                    cell_estimate,
                )
            )

        # Estimate shape from the first accepted phase and keep its model stable
        # as further accepted phases are added. This is not candidate searching.
        primary_peak_sets = (
            [prepared_profiles[0][3]]
            if prepared_profiles
            else []
        )
        fitted_fwhm, fitted_eta = self._optimized_profile_parameters(
            observed.target_y,
            primary_peak_sets,
            x_grid,
            prepared_profiles[0][4] if prepared_profiles else context,
            finder_input.instrument_profile,
            prepared_profiles[0][6] if prepared_profiles else None,
        )
        if finder_input.instrument_profile is not None:
            fitted_eta = (0.0 if finder_input.instrument_profile.resolution.model == 'constant_fwhm' else None)
        profiles = []
        for (
            candidate,
            structure,
            reference_peaks,
            adjusted,
            phase_context,
            cell_scale,
            line_data,
            cell_estimate,
        ) in prepared_profiles:
            phase_fwhm = self._estimate_phase_fwhm_from_signal(
                adjusted,
                observed.x_grid,
                observed.target_y,
                base_fwhm=fitted_fwhm,
            )
            phase_eta = fitted_eta
            if finder_input.instrument_profile is not None:
                angle = profile_reference_angle(adjusted, finder_input.instrument_profile)
                phase_fwhm = max(phase_fwhm, instrument_fwhm_at(finder_input.instrument_profile, angle))
            profiles.append(
                (
                    candidate,
                    # Only a CrIStMa line set supplies the validated physical
                    # convention. Legacy structure-object profiles can still
                    # be drawn, but their scales are not comparable for Quant.
                    structure if line_data is not None and line_data.cristma_lines is not None else None,
                    reference_peaks,
                    adjusted,
                    None,  # The physical fit does not consume display profiles.
                    cell_scale,
                    phase_fwhm,
                    phase_eta,
                    cell_estimate,
                )
            )

        quantification_errors = []
        if candidate_failures:
            quantification_errors.append('Selected CIF candidates failed: ' + '; '.join(
                f'{Path(failure.cif_path).name or failure.candidate_key}: {failure.message}'
                for failure in candidate_failures))
        elif not finder_input.quantification_complete:
            quantification_errors.append('Not all selected structures are available for quantitative analysis')
        physical_fit = fit_accepted_phases(
            profiles,x_grid,observed.target_y,context.with_alignment(global_zero,1.0),
            finder_input.instrument_profile,self.profile_calculator,
            refine_sample_broadening=finder_input.refine_sample_broadening,
            observed_peaks=observed.peaks,
            diagnostics=quantification_errors,
        ) if (finder_input.quantification_complete and len(profiles) == len(finder_input.candidates)) else None
        if physical_fit is not None:
            quantity_fractions = physical_fit.fractions
            # Preserve the public peak-normalized scale convention, while using
            # exactly the physical columns and coefficients that produced Quant.
            maxima = np.max(physical_fit.profiles, axis=0)
            scales = physical_fit.scales * maxima / 100.0
            physical_profiles = []
            for index, item in enumerate(profiles):
                # Cached cards can outlive a changed CIF. Peak geometry and hkl
                # must come from the same native lines as the physical column.
                peaks = self._apply_peak_model(
                    list(physical_fit.peaks[index]), context.with_alignment(global_zero, item[5])
                )
                profile = physical_fit.profiles[:, index] * (100.0 / maxima[index])
                physical_profiles.append((*item[:2], peaks, peaks, profile, *item[5:]))
            profiles = physical_profiles
        else:
            display_profiles = []
            for item, prepared in zip(profiles, prepared_profiles):
                (
                    candidate, _structure, _reference, adjusted, _display,
                    _scale, phase_fwhm, phase_eta, cell_estimate,
                ) = item
                phase_context, line_data = prepared[4], prepared[6]
                fitted_context = replace(phase_context, fwhm=phase_fwhm, profile_eta=float(phase_eta or 0.0))
                absolute_peaks = [
                    replace(
                        peak,
                        intensity=(
                            float(getattr(peak, "raw_intensity", 0.0) or 0.0)
                            if float(getattr(peak, "raw_intensity", 0.0) or 0.0) > 0.0
                            else float(getattr(peak, "intensity", 0.0) or 0.0)
                        ),
                    )
                    for peak in adjusted
                ]
                if (
                    line_data is not None
                    and finder_input.instrument_profile is not None
                    and (cell_estimate is not None or not finder_input.snap_peak_positions)
                ):
                    profile = self.profile_calculator.profile_from_lines(
                        line_data,
                        x_grid,
                        fitted_context,
                        instrument_profile=finder_input.instrument_profile,
                    )
                else:
                    if candidate.reference_lines is not None:
                        support = self.profile_calculator.peaks_from_reference_lines(
                            candidate.reference_lines, fitted_context,
                            instrument_profile=finder_input.instrument_profile,
                            include_boundary_wings=True)
                        support = self._apply_peak_model(support,fitted_context)
                        existing = {(p.h,p.k,p.l,round(p.d,8)) for p in absolute_peaks}
                        absolute_peaks.extend(replace(p,intensity=float(p.raw_intensity or p.intensity))
                            for p in support if (p.h,p.k,p.l,round(p.d,8)) not in existing)
                    profile = self.profile_calculator.profile_from_peaks(
                        absolute_peaks,
                        x_grid,
                        context=fitted_context,
                        source_fingerprint=(
                            None
                            if candidate.reference_lines is None
                            else candidate.reference_lines.fingerprint
                        ),
                        instrument_profile=finder_input.instrument_profile,
                    )
                display_profiles.append((*item[:4], profile, *item[5:]))
            profiles = display_profiles
            quantity_fractions = np.full(len(profiles), np.nan)
            scales = self._fit_incremental_scales(observed.target_y, [item[4] for item in profiles])
        calculated_total = np.zeros_like(x_grid)
        results = []
        assignment_phase_sets = []
        phase_fwhm_values = []
        for (
            candidate,
            _structure,
            reference_peaks,
            peaks,
            profile,
            cell_scale,
            phase_fwhm,
            phase_eta,
            cell_estimate,
        ), scale, quantity_fraction in zip(profiles, scales, quantity_fractions):
            scaled_profile = profile * float(scale)
            calculated_total += scaled_profile
            if float(scale) > 0.0:
                phase_fwhm_values.append(float(phase_fwhm))
            match_result = self._match_result(peaks, observed.peak_positions)
            candidate_result = FinderCandidateResult(
                candidate_key=self._candidate_key(candidate),
                entry_id=candidate.entry_id,
                name=candidate.name,
                formula=candidate.formula,
                source=candidate.source,
                scale=float(scale),
                quantity_percent=(float(quantity_fraction * 100.0) if np.isfinite(quantity_fraction) else None),
                score=match_result.score,
                matched_peaks=match_result.matched_peaks,
                total_peaks=match_result.total_peaks,
                mean_delta_two_theta=match_result.mean_delta_two_theta,
                status=match_result.status,
                cell_scale=float(cell_scale),
                estimated_cell=self._cell_payload(cell_estimate),
                cell_fit_peaks=(0 if cell_estimate is None else int(cell_estimate.matched_peaks)),
                cell_fit_initial_rms_deg=(
                    0.0 if cell_estimate is None else float(cell_estimate.initial_rms_deg)
                ),
                cell_fit_rms_deg=(
                    0.0 if cell_estimate is None else float(cell_estimate.fitted_rms_deg)
                ),
                fwhm=float(phase_fwhm),
                profile_eta=None if phase_eta is None else float(phase_eta),
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
                sample_broadening=(
                    physical_fit.sample_broadening[len(results)]
                    if physical_fit is not None and finder_input.refine_sample_broadening
                    else ({"status": "unavailable_physical_profile", "profile_model": "legacy_width_floor"}
                          if finder_input.refine_sample_broadening else {})
                ),
                mass_profile=(
                    (physical_fit.profiles[:, len(results)] / physical_fit.mass_factors[len(results)]).tolist()
                    if physical_fit is not None and physical_fit.mass_factors else []
                ),
            )
            results.append(candidate_result)
            if float(scale) > 0.0:
                assignment_phase_sets.append((candidate_result, peaks))

        assigned_peaks = self.assignment_builder.assign_observed_peaks(
            observed.peaks,
            assignment_phase_sets,
            tolerance=max(0.20, min(0.55, (float(np.nanmedian(phase_fwhm_values)) if phase_fwhm_values else fitted_fwhm) * 2.7)),
        )

        return FinderResult(
            pattern_x=x_grid.tolist(),
            pattern_y=observed.observed_y.tolist(),
            background=observed.background.tolist(),
            calculated_total=(calculated_total + observed.background).tolist(),
            global_zero_shift=float(global_zero),
            fwhm=float(np.nanmedian(phase_fwhm_values)) if phase_fwhm_values else float(fitted_fwhm),
            profile_eta=None if fitted_eta is None else float(fitted_eta),
            candidates=results,
            observed_peaks=assigned_peaks,
            sample_broadening_requested=finder_input.refine_sample_broadening,
            quantification_error='; '.join(quantification_errors),
            candidate_failures=candidate_failures,
        )

    @staticmethod
    def _cell_payload(estimate: CellParameterEstimate | None) -> dict[str, float]:
        if estimate is None:
            return {}
        cell = estimate.cell
        return {
            name: float(getattr(cell, name))
            for name in ("a", "b", "c", "alpha", "beta", "gamma", "volume")
            if getattr(cell, name) is not None
        }

    @staticmethod
    def _unit_cell_molar_mass(structure) -> float | None:
        """Return the molar mass of all occupied atoms in one unit cell."""

        if structure is None:
            return None
        if getattr(structure, "metadata", {}).get("quantification_symmetry_unresolved"):
            return None
        atoms = getattr(structure, "atoms", None) or []
        if not atoms or any(any(getattr(atom, name, None) is None for name in ("x", "y", "z")) for atom in atoms):
            return None
        total = 0.0
        for atom in expand_atoms_by_symmetry(structure):
            try:
                weight = atomic_weight(str(atom.element))
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return None
            occupancy = float(atom.occupancy)
            if not math.isfinite(weight) or weight <= 0 or not math.isfinite(occupancy) or occupancy < 0:
                return None
            total += occupancy * weight
        return total if math.isfinite(total) and total > 0 else None

    @staticmethod
    def _unit_cell_volume(structure) -> float | None:
        """Compute volume from the current metric, never a stale CIF volume."""
        cell = getattr(structure, "cell", None)
        try:
            a, b, c = (float(getattr(cell, name)) for name in ("a", "b", "c"))
            angles = [float(getattr(cell, name)) for name in ("alpha", "beta", "gamma")]
            if min(a, b, c) <= 0 or any(not 0 < angle < 180 for angle in angles):
                return None
            ca, cb, cg = np.cos(np.radians(angles))
            determinant = 1 + 2*ca*cb*cg - ca*ca - cb*cb - cg*cg
            volume = a*b*c*math.sqrt(max(0., float(determinant)))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        return volume if math.isfinite(volume) and volume > 0 else None

    @staticmethod
    def _mass_fractions(scales, cell_masses, cell_volumes) -> np.ndarray:
        return mass_fractions(scales,cell_masses,cell_volumes)

    @staticmethod
    def _has_indexed_cell(structure, peaks: list[HKLPeak]) -> bool:
        cell = getattr(structure, "cell", None)
        if cell is None:
            return False
        if any(getattr(cell, name, None) is None for name in ("a", "b", "c", "alpha", "beta", "gamma")):
            return False
        return any(
            (int(getattr(peak, "h", 0)), int(getattr(peak, "k", 0)), int(getattr(peak, "l", 0))) != (0, 0, 0)
            for peak in peaks
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
            array_fingerprint(x),
            array_fingerprint(y),
        )

    def _candidate_key(self, candidate: FinderCandidateInput) -> str:
        if candidate.entry_id:
            source = str(candidate.source or "UNKNOWN").upper()
            entry_id = str(candidate.entry_id)
            if entry_id.upper().startswith(f"{source}:"):
                return entry_id
            return f"{source}:{entry_id}"
        if candidate.source and candidate.formula:
            return f"{candidate.source}:{candidate.formula}"
        return candidate.cif_path

    def _estimate_global_zero_shift(
        self,
        candidate_data: list[tuple[FinderCandidateInput | None, list[HKLPeak]]],
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

    def estimate_zero_shift(
        self,
        peaks: list[HKLPeak],
        observed_peaks: list[ObservedPeak],
        *,
        wavelength: float,
    ) -> float:
        """Compare local alignment with the independently searched Match seed.

        Match supplies a starting offset, not permission to alter the cell or
        force a fit. The offset must still explain distinct strong lines under
        the existing zero-residual and coverage criteria.
        """
        if not peaks or len(observed_peaks) < 3:
            return 0.0
        alignment_data = [(None, peaks)]
        positions = np.sort(np.asarray([peak.two_theta for peak in observed_peaks], dtype=float))
        local_zero = self._estimate_global_zero_shift_from_trusted_assignments(alignment_data, observed_peaks)
        if local_zero is None and self._candidate_zero_shift_estimate(peaks, positions) is not None:
            local_zero = self._estimate_global_zero_shift(alignment_data, positions)
        fallback_zero = local_zero if local_zero is not None else 0.0

        records = [(peak.two_theta, peak.intensity) for peak in observed_peaks]
        match = fingerprint_match_score(
            peaks,
            records,
            wavelength=wavelength,
            line_tolerance_two_theta=self.heuristics.cell_parameter_peak_tolerance,
        )
        if local_zero is not None:
            if abs(match.zero_shift - local_zero) <= self.heuristics.zero_outlier_tolerance:
                return local_zero
            local_match = fingerprint_match_score(
                peaks, records, wavelength=wavelength,
                line_tolerance_two_theta=self.heuristics.cell_parameter_peak_tolerance,
                fixed_zero_shift=local_zero,
            )
            if match.score <= local_match.score:
                return local_zero
        if match.features.observed_matched < 3 or match.features.reference_matched < 3:
            return fallback_zero
        residual_estimate = self._candidate_zero_shift_estimate(peaks, positions - match.zero_shift)
        if residual_estimate is None:
            return fallback_zero
        zero = float(match.zero_shift + residual_estimate['zero'])
        strong = sorted(
            [peak for peak in peaks if peak.intensity >= self.heuristics.strong_peak_intensity_min],
            key=lambda peak: peak.intensity,
            reverse=True,
        )[:25]
        used = set()
        for peak in strong:
            index = nearest_peak_index(positions, float(peak.two_theta) + zero)
            if abs(float(positions[index]) - peak.two_theta - zero) <= self.heuristics.zero_outlier_tolerance:
                used.add(index)
        if len(used) < 3 or len(used) / max(len(strong), 1) < self.heuristics.zero_min_matched_fraction:
            return fallback_zero
        return zero

    def _estimate_global_zero_shift_from_trusted_assignments(
        self,
        candidate_data: list[tuple[FinderCandidateInput | None, list[HKLPeak]]],
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
        weighted = matrix * weights[:, None]
        norms = np.linalg.norm(weighted, axis=0)
        active = norms > 0
        scales = np.zeros(len(profiles), dtype=float)
        if np.any(active):
            fitted, _residual = nnls(weighted[:, active] / norms[active], target_y * weights)
            scales[active] = fitted / norms[active]
        return scales

    def _fit_incremental_scales(self, target_y: np.ndarray, profiles: list[np.ndarray]) -> np.ndarray:
        """Jointly refit every selected phase after a phase is added.

        Fixing the first phase before fitting the rest makes it absorb shared
        reflections and can force a real later phase to zero. Weighted NNLS
        lets earlier scales decrease when a newly selected phase explains both
        shared and previously uncovered reflections. Exact duplicate columns
        retain selection-order priority in scipy's NNLS solution.
        """
        if not profiles:
            return np.array([], dtype=float)
        target = np.asarray(target_y, dtype=float)
        clean_profiles = [
            np.clip(np.asarray(profile, dtype=float), 0.0, None)
            for profile in profiles
        ]
        return self._fit_scales(target, clean_profiles)

    def _optimized_profile_parameters(
        self,
        target_y: np.ndarray,
        peak_sets: list[list[HKLPeak]],
        x_grid: np.ndarray,
        context: CalculationContext,
        instrument_profile=None,
        primary_line_data=None,
    ) -> tuple[float, float | None]:
        minimum_width = .04
        if instrument_profile is not None:
            reference_peaks = (primary_line_data.peaks if primary_line_data is not None
                               else (peak_sets[0] if peak_sets else []))
            angle = profile_reference_angle(reference_peaks, instrument_profile,
                context.cell_scale if primary_line_data is not None else 1.0)
            minimum_width = max(minimum_width, instrument_fwhm_at(instrument_profile, angle))
        base = max(float(context.fwhm), minimum_width)
        fixed_eta = (0.0 if instrument_profile is None or instrument_profile.resolution.model == 'constant_fwhm' else None)
        if not peak_sets:
            return base, float(context.profile_eta) if instrument_profile is None else fixed_eta
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
        candidates = np.unique(np.maximum(candidates, minimum_width))
        eta_candidates = (0.0, 0.25, 0.5, 0.7) if instrument_profile is None else (0.0,)
        weights = self._fit_weights(target_y)
        best_fwhm = base
        best_eta = float(context.profile_eta)
        best_score = float("inf")
        for fwhm in candidates:
            for eta in eta_candidates:
                trial_context = replace(context, fwhm=float(fwhm), profile_eta=float(eta))
                profiles = []
                for index, peaks in enumerate(peak_sets):
                    if not peaks:
                        continue
                    if index == 0 and primary_line_data is not None and instrument_profile is not None:
                        profile = self.profile_calculator.profile_from_lines(primary_line_data, x_grid,
                            trial_context, instrument_profile=instrument_profile, normalize=False)
                    else:
                        profile = self.profile_calculator.profile_from_peaks(peaks, x_grid,
                            context=trial_context, instrument_profile=instrument_profile)
                    profiles.append(profile)
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
        return max(minimum_width, float(np.clip(best_fwhm, 0.04, 0.45))), (
            float(np.clip(best_eta, 0.0, 0.85)) if instrument_profile is None else fixed_eta)

    def _estimate_phase_fwhm_from_observed_peaks(
        self,
        peaks: list[HKLPeak],
        observed_peaks: list[ObservedPeak],
        *,
        base_fwhm: float,
    ) -> float:
        if not peaks or not observed_peaks:
            return float(np.clip(base_fwhm, 0.04, 0.80))
        observed_positions = np.asarray([peak.two_theta for peak in observed_peaks], dtype=float)
        if not len(observed_positions):
            return float(np.clip(base_fwhm, 0.04, 0.80))
        tolerance = max(0.18, min(0.65, float(base_fwhm) * 2.8))
        widths = []
        strong = sorted(
            (peak for peak in peaks if float(getattr(peak, "intensity", 0.0) or 0.0) >= 4.0),
            key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0),
            reverse=True,
        )[:36]
        for peak in strong:
            position = float(peak.two_theta)
            index = int(np.argmin(np.abs(observed_positions - position)))
            delta = abs(float(observed_positions[index]) - position)
            if delta > tolerance:
                continue
            observed_peak = observed_peaks[index]
            width = float(getattr(observed_peak, "fwhm", base_fwhm) or base_fwhm)
            if not np.isfinite(width):
                continue
            weight = max(float(getattr(peak, "intensity", 1.0) or 1.0), 1.0)
            repeats = max(1, min(6, int(round(weight / 18.0))))
            widths.extend([width] * repeats)
        if len(widths) < 2:
            return float(np.clip(base_fwhm, 0.04, 0.80))
        return float(np.clip(np.nanmedian(np.asarray(widths, dtype=float)), 0.04, 0.80))

    def _estimate_phase_fwhm_from_signal(
        self,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        target_y: np.ndarray,
        *,
        base_fwhm: float,
    ) -> float:
        return estimate_phase_fwhm_from_signal(
            peaks,
            x_grid,
            target_y,
            base_fwhm=base_fwhm,
        )

    def _local_signal_fwhm(
        self,
        x: np.ndarray,
        y: np.ndarray,
        center: float,
        *,
        search_radius: float,
        window_radius: float,
    ) -> float | None:
        search_mask = (x >= center - search_radius) & (x <= center + search_radius)
        if int(np.count_nonzero(search_mask)) < 3:
            return None
        search_indices = np.flatnonzero(search_mask)
        peak_index = int(search_indices[int(np.nanargmax(y[search_indices]))])
        if abs(float(x[peak_index]) - float(center)) > search_radius:
            return None
        window_mask = (x >= float(x[peak_index]) - window_radius) & (x <= float(x[peak_index]) + window_radius)
        window_indices = np.flatnonzero(window_mask)
        if len(window_indices) < 5:
            return None
        local_y = y[window_indices]
        edge_count = max(2, min(8, len(local_y) // 5))
        edge_values = np.concatenate([local_y[:edge_count], local_y[-edge_count:]])
        baseline = float(np.nanpercentile(edge_values, 35))
        height = float(y[peak_index]) - baseline
        if height <= max(float(np.nanpercentile(y, 95)) * 0.015, 1.0):
            return None
        half = baseline + 0.5 * height
        left = peak_index
        while left > 0 and y[left] > half and x[left] >= x[peak_index] - window_radius:
            left -= 1
        right = peak_index
        while right < len(y) - 1 and y[right] > half and x[right] <= x[peak_index] + window_radius:
            right += 1
        if left == peak_index or right == peak_index:
            return None
        left_x = self._interpolated_crossing_x(x, y, left, left + 1, half)
        right_x = self._interpolated_crossing_x(x, y, right, right - 1, half)
        width = abs(float(right_x) - float(left_x))
        if not np.isfinite(width):
            return None
        return float(np.clip(width, 0.04, 0.90))

    @staticmethod
    def _interpolated_crossing_x(x: np.ndarray, y: np.ndarray, index_a: int, index_b: int, level: float) -> float:
        xa = float(x[index_a])
        xb = float(x[index_b])
        ya = float(y[index_a])
        yb = float(y[index_b])
        denominator = yb - ya
        if abs(denominator) < 1.0e-12:
            return xa
        fraction = (float(level) - ya) / denominator
        return xa + float(np.clip(fraction, 0.0, 1.0)) * (xb - xa)

    def _optimized_phase_profile_parameters(
        self,
        target_y: np.ndarray,
        peaks: list[HKLPeak],
        x_grid: np.ndarray,
        context: CalculationContext,
        instrument_profile=None,
    ) -> tuple[float, float | None]:
        if instrument_profile is not None:
            return self._optimized_profile_parameters(target_y, [peaks], x_grid, context, instrument_profile)
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
