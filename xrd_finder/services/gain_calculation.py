from __future__ import annotations
from xrd_finder.ui.gain_peak_search_actions import build_window_peak_gain_context, score_window_peak_gain_row, clear_gain_column
from xrd_finder.services.gain_peak_search import gain_peak_retrieval_records
from xrd_finder.services.gain_retrieval_union import GainRetrievalConfig, build_production_gain_retrieval_pool
from xrd_finder.services.gain_shortlist import GAIN_PROFILE_CANDIDATE_LIMIT
from xrd_finder.services.calculated_pattern_service import radiation_lines_from_wavelength
from dataclasses import replace
from xrd_finder.services.peak_cell_alignment import apply_peak_cell

import math
import sqlite3
from concurrent.futures import CancelledError
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import nnls
from scipy.signal import find_peaks
import numpy as np

from xrd_finder.finder.context import CalculationContext
from xrd_finder.core.structure import CellParameters
from xrd_finder.finder.joint_profile_fit import evaluate_mass_profiles
from xrd_finder.finder.quantification import _cif_metadata, unit_cell_volume
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.finder.profile_backend import FinderPeakProfileBackend
from xrd_finder.finder.gain_evidence import phase_signal_to_noise
from xrd_finder.finder.residual_peak_refinement import refine_residual_peak, refine_residual_peaks
from xrd_finder.finder.profile_calculator import array_fingerprint
from xrd_finder.finder.phase_width_model import fit_phase_width_model, match_clean_phase_records, width_difference_corroboration
from xrd_finder.services.calculated_pattern_service import HKLPeak, PROFILE_WINDOW_FACTOR
from xrd_finder.services.preprocessing_service import estimate_background
from xrd_finder.services.local_phase_cache import LocalPhaseSearchError
from xrd_finder.services.runtime_diagnostics import traced_operation
from xrd_finder.services.phase_pattern_equivalence import compare_phase_patterns
from xrd_finder.services.gain_shortlist import common_zero_shift, estimate_matched_profile_fwhm, residual_peak_is_explained, select_profile_candidate_indices, summarize_combined_residual_evidence
from xrd_finder.ui.peak_matching import ObservedLineRecord, observed_peak_records, instrument_fwhm_at, radiation_satellites_at
from xrd_finder.ui.gain_scoring import DEFAULT_GAIN_POLICY, GainStage, build_gain_indexed_evidence, fit_residual_candidate_scale, profile_residual_gain
from xrd_finder.services.gain_peak_width import estimate_profile_fwhm
from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.gain_lines import GainLineMixin
from xrd_finder.services.gain_cell_alignment import refine_gain_cell
from xrd_finder.services.candidate_rows import CandidateRowFormatter, normalize_candidate_row
from xrd_finder.services.cod_online_service import formula_elements

GAIN_PEAK_FIT_CACHE_LIMIT = 4096


def _gain_scan_peaks(peaks, context):
    x = np.asarray(context.get('x', []), dtype=float)
    finite_x = x[np.isfinite(x)]
    if not finite_x.size:
        return list(peaks)
    low, high = float(finite_x.min()), float(finite_x.max())
    return [peak for peak in peaks if low <= float(peak.two_theta) <= high]


class GainJobCancelled(Exception):
    """Cooperative stop between Gain stages; never a scientific fallback."""


@dataclass(frozen=True)
class GainObservedPeakCache:
    key: tuple
    refined_peaks: dict = field(default_factory=dict)


@dataclass
class GainJobInput:
    observed: np.ndarray | None
    instrument_profile: InstrumentProfile
    candidates: list[dict[str, str]]
    rows: list[list[str]]
    finder_observed: np.ndarray | None = None
    background: np.ndarray | None = None
    scoring_source: str = "Auto"
    background_removed: bool = False
    preprocess_auto: bool = False
    wavelength: float = 1.54056
    include_kalpha2: bool = True
    zero_shifts: dict = field(default_factory=dict)
    cell_scales: dict = field(default_factory=dict)
    profile_fwhm: float = 0.0
    profile_eta: float = 0.0
    hidden_matches: dict = field(default_factory=dict)
    cache_root: str = ""
    pdf2_root: str = ""
    embedded_paths: dict = field(default_factory=dict)
    project_phases: list = field(default_factory=list)
    project_structures: list = field(default_factory=list)
    linked_phase_ids: list = field(default_factory=list)
    local_sources: list[str] = field(default_factory=list)
    excluded_elements: list[str] = field(default_factory=list)
    required_elements: list[str] = field(default_factory=list)
    optional_elements: list[str] = field(default_factory=list)
    restrict_to_selected_elements: bool = False
    allow_inorganic: bool = True
    allow_organic: bool = True
    context_key: tuple = ()
    accepted_fit_x: np.ndarray | None = None
    accepted_fit_target: np.ndarray | None = None
    accepted_fit_profiles: np.ndarray | None = None
    accepted_fit_broadening: list[dict] = field(default_factory=list)
    accepted_fit_mass_profiles: np.ndarray | None = None
    accepted_fit_peak_positions: np.ndarray | None = None
    gain_overlap_locked: bool = False
    observed_cache_scope: tuple = ()
    observed_peak_cache: GainObservedPeakCache | None = None

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = deepcopy(getattr(self, name))
            if isinstance(value, np.ndarray):
                value.setflags(write=False)
            setattr(self, name, value)
        snapshot = (self.accepted_fit_x, self.accepted_fit_target, self.accepted_fit_profiles)
        if any(value is not None for value in snapshot):
            if any(value is None for value in snapshot):
                raise ValueError("Accepted profile snapshot must be complete")
            x, target, profiles = snapshot
            if (x.ndim != 1 or len(x) < 2 or target.shape != x.shape
                    or profiles.shape != (len(self.candidates), len(x))
                    or not all(np.all(np.isfinite(value)) for value in snapshot)
                    or np.any(np.diff(x) <= 0) or np.any(profiles < 0)):
                raise ValueError("Accepted profile snapshot does not match the phase set")
        mass_profiles = self.accepted_fit_mass_profiles
        if mass_profiles is not None:
            if (self.accepted_fit_profiles is None or mass_profiles.shape != self.accepted_fit_profiles.shape
                    or not np.all(np.isfinite(mass_profiles)) or np.any(mass_profiles < 0.)):
                raise ValueError('Physical mass profiles must match the accepted phase snapshot')
        positions = self.accepted_fit_peak_positions
        if positions is not None and (mass_profiles is None or positions.ndim != 1
                                       or not np.all(np.isfinite(positions))):
            raise ValueError('Physical reflection positions require a valid mass profile snapshot')

    def material_class_allowed(self, formula):
        organic = {"C", "H"}.issubset(formula_elements(formula))
        return self.allow_organic if organic else self.allow_inorganic


@dataclass
class GainJobResult:
    rows: list[list[str]]
    status: str = ""
    debug: str = ""
    hidden_matches: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    cancelled: bool = False
    indexed_evidence: dict = field(default_factory=dict)
    observed_peak_cache: GainObservedPeakCache | None = None


class GainCalculationMixin:
    """Shared numerical Gain implementation; inputs and UI hooks live in adapters."""

    def _gain_check_cancelled(self) -> None:
        pass

    def _gain_accepted_profile_snapshot(self):
        return None

    def _gain_mass_profile_snapshot(self):
        return None

    def _gain_accepted_peak_positions(self):
        return None

    def _gain_peak_refiner(self):
        return None

    def _prepare_observed_peak_reuse(self, x, target):
        pass

    def _gain_stage_for_context(self, context) -> str:
        if "peak_search" in context:
            direct, shared = gain_peak_retrieval_records(context["peak_search"])
            return str(DEFAULT_GAIN_POLICY.select_stage(
                direct_count=len(direct), overlap_count=len(shared)))
        if self._gain_overlap_locked:
            overlap_count = len(self._gain_stage_records(context, GainStage.OVERLAP, limit=24))
            if overlap_count >= DEFAULT_GAIN_POLICY.minimum_stage_records:
                return str(GainStage.OVERLAP)
            return str(GainStage.HIDDEN)
        return str(
            DEFAULT_GAIN_POLICY.select_stage(
                direct_count=len(self._gain_stage_records(context, GainStage.DIRECT, limit=24)),
                overlap_count=len(self._gain_stage_records(context, GainStage.OVERLAP, limit=24)),
            )
        )

    def _gain_process_events(self) -> None:
        pass

    def _gain_stage_progress(self, text: str) -> None:
        pass

    def _gain_set_status(self, text: str) -> None:
        self._gain_status_text = text

    def _estimate_profile_fwhm(self, x, corrected_y) -> float:
        return estimate_profile_fwhm(x, corrected_y)

    def _fit_weights(self, corrected_y: np.ndarray) -> np.ndarray:
        y = np.asarray(corrected_y, dtype=float)
        if len(y) == 0:
            return np.ones_like(y)
        scale = max(float(np.nanpercentile(y, 98)), 1.0)
        weights = 0.15 + np.clip(y / scale, 0.0, 1.0) ** 0.7
        peak_indices, _properties = find_peaks(
            y,
            prominence=max(scale * 0.015, float(np.nanstd(y)) * 2.0, 1.0),
            distance=max(3, len(y) // 1000),
        )
        half_width = max(2, len(y) // 900)
        for index in peak_indices:
            left = max(0, index - half_width)
            right = min(len(y), index + half_width + 1)
            weights[left:right] *= 3.0
        return weights

    def _observed_peak_records(
        self,
        x,
        corrected_y,
        limit: int = 24,
        *,
        sigma_threshold: float = 3.0,
        residual: bool = False,
    ) -> list[ObservedLineRecord]:
        instrument_profile = None
        try:
            getter = getattr(self, '_gain_instrument_profile', None)
            instrument_profile = (getter() if getter is not None else
                                  self._instrument_profile_for_pattern(self._active_pattern()))
        except Exception:
            instrument_profile = None
        return observed_peak_records(
            x,
            corrected_y,
            limit=limit,
            instrument_profile=instrument_profile,
            sigma_threshold=sigma_threshold,
            refine_peak=getattr(self, "_gain_peak_refiner", lambda: None)(),
            residual=residual,
            global_zero_shift=common_zero_shift(getattr(self, 'match_zero_shifts', {}).values()),
        )

    def _corrected_profile_fit_quality(self, observed_corrected: np.ndarray, calculated_corrected: np.ndarray) -> float:
        observed_corrected = np.clip(np.asarray(observed_corrected, dtype=float), 0.0, None)
        calculated_corrected = np.clip(np.asarray(calculated_corrected, dtype=float), 0.0, None)
        if len(observed_corrected) == 0 or float(np.nanmax(observed_corrected)) <= 0:
            return 0.0
        if len(calculated_corrected) != len(observed_corrected):
            return 0.0
        weights = self._fit_weights(observed_corrected)
        residual = observed_corrected - calculated_corrected
        numerator = float(np.nansum(weights * residual * residual))
        denominator = float(np.nansum(weights * observed_corrected * observed_corrected))
        if denominator <= 0:
            return 0.0
        return float(np.clip(100.0 * (1.0 - numerator / denominator), 0.0, 100.0))

    def _trim_candidate_gain_profile_cache(self, limit: int = 512) -> None:
        while len(self._candidate_gain_profile_cache) > limit:
            self._candidate_gain_profile_cache.pop(next(iter(self._candidate_gain_profile_cache)), None)


    @traced_operation("gain.rank")
    def _rank_candidate_rows_by_peak_probability(
        self,
        rows: list[list[str]],
        force: bool = False,
        progress=None,
        gain_context=None,
    ) -> list[list[str]]:
        if not force and not self._rank_by_peak_probability_enabled():
            return rows
        if not any(len(row) > 1 and str(row[0]).strip() and str(row[1]).strip() for row in rows):
            return rows
        if self.match_candidates and gain_context is not None and "peak_search" in gain_context:
            # The measured Gain context is authoritative here; Match records
            # are used only when ranking before any phase has been accepted.
            observed_records = list(gain_context["peak_search"].records)
        else:
            probability_data = self._probability_observed_data()
            if probability_data is None:
                return clear_gain_column(rows) if self.match_candidates else rows
            _observed_x, _corrected, observed_records = probability_data
        if not observed_records:
            return clear_gain_column(rows) if self.match_candidates else rows
        gain_records = observed_records
        if gain_context is None and self.match_candidates:
            gain_context = self._candidate_gain_context()
        if self.match_candidates and gain_context is None:
            return clear_gain_column(rows)
        if gain_context is not None and "peak_search" in gain_context:
            gain_records = list(gain_context["peak_search"].records)
        elif gain_context is not None:
            residual_share = float(gain_context.get("residual_share", 0.0) or 0.0)
            before_fit = float(gain_context.get("before_fit", 0.0) or 0.0)
            remaining_fit = max(0.0, 100.0 - before_fit)
            if DEFAULT_GAIN_POLICY.residual_is_exhausted(
                selected_phase_count=len(self.match_candidates),
                before_fit=before_fit,
                residual_share=residual_share,
            ):
                self._last_gain_debug = (
                    f"Gain: fit {before_fit:.1f}%, remaining {remaining_fit:.1f}%; "
                    "adding more phases is likely overfitting"
                )
                gain_records = []
            else:
                try:
                    gain_records = self._gain_observed_records(gain_context, limit=80)
                except Exception:
                    gain_records = []
        if gain_context is not None and gain_records:
            if "peak_search" not in gain_context and len(self.match_candidates) >= 5:
                low_angle_gain_count = 0
                for record in gain_records:
                    position = self._record_position_value(record)
                    if 5.0 <= position <= 60.0:
                        low_angle_gain_count += 1
                    if low_angle_gain_count >= 3:
                        break
                if low_angle_gain_count < 3:
                    self._last_gain_debug = (
                        f"Gain: residual exhausted ({low_angle_gain_count} uncovered peaks below 60 deg); "
                        "adding more phases is likely overfitting"
                    )
                    gain_records = []

        if force and not self.match_candidates:
            # Peak-index preselection already bounds this list. Every row in
            # that shortlist must participate in the initial Match ranking.
            rank_limit = len(rows)
        elif force:
            # Gain rows already passed the indexed peak preselection. Do not
            # discard a valid residual phase merely because it was appended
            # below an arbitrary ranking cutoff.
            rank_limit = len(rows)
        else:
            rank_limit = 120
        rows_to_rank = rows[:rank_limit]
        tail_rows = rows[rank_limit:]
        scored_rows = []
        selected_keys = {self._candidate_key(candidate) for candidate in (self.match_candidates or [])}
        has_selected_phases = bool(self.match_candidates)
        precomputed_gains: dict[int, float] = {}
        if has_selected_phases and gain_context is not None:
            gain_context["gain_stage"] = "combined"
            preliminary_gains: dict[int, float] = {}
            for row_index, row in enumerate(rows_to_rank):
                self._gain_check_cancelled()
                if progress is not None and row_index % 25 == 0:
                    try:
                        progress(row_index, len(rows_to_rank))
                    except Exception:
                        pass
                candidate = {
                    "Source": row[0] if len(row) > 0 else "",
                    "Entry": row[1] if len(row) > 1 else "",
                    "Formula": row[2] if len(row) > 2 else "",
                    "Phase": row[3] if len(row) > 3 else "",
                }
                if self._candidate_key(candidate) in selected_keys:
                    continue
                preliminary_gains[row_index] = self._candidate_row_preliminary_gain(row, gain_context)
            overlap_records = self._gain_stage_records(
                gain_context,
                GainStage.OVERLAP,
                limit=80,
            )
            residual_summary = summarize_combined_residual_evidence(
                gain_records,
                overlap_records,
                expected_fwhm=float(gain_context.get("fwhm", 0.18) or 0.18),
            )
            gain_records = list(residual_summary.significant_records)
            if residual_summary.kind == "none":
                self._last_gain_debug = "Gain: no significant unexplained peaks"
            else:
                profile_indices = self._gain_multichannel_profile_indices(
                    rows_to_rank,
                    preliminary_gains,
                    gain_records,
                    overlap_records,
                    gain_context,
                )
                if not profile_indices:
                    profile_indices = select_profile_candidate_indices(
                        preliminary_gains,
                    )
                for row_index in profile_indices:
                    precomputed_gains[row_index] = self._candidate_row_integral_gain(
                        rows_to_rank[row_index], gain_context
                    )
            self._active_gain_stage = ""
        for index, row in enumerate(rows_to_rank):
            self._gain_check_cancelled()
            if progress is not None and not precomputed_gains and (index == 0 or index % 25 == 0):
                try:
                    progress(index, len(rows_to_rank))
                except Exception:
                    pass
            elif progress is None and index > 0 and index % 50 == 0:
                self._gain_process_events()
            scored_row = list(row)
            row_candidate = {
                "Source": scored_row[0] if len(scored_row) > 0 else "",
                "Entry": scored_row[1] if len(scored_row) > 1 else "",
                "Formula": scored_row[2] if len(scored_row) > 2 else "",
                "Phase": scored_row[3] if len(scored_row) > 3 else "",
            }
            row_key = self._candidate_key(row_candidate)
            existing_match_text = scored_row[5] if len(scored_row) > 5 else ""
            hidden_matches = getattr(self, "_candidate_hidden_match_by_key", None)
            if hidden_matches is None:
                hidden_matches = {}
                self._candidate_hidden_match_by_key = hidden_matches
            if existing_match_text:
                hidden_matches[row_key] = existing_match_text
            elif has_selected_phases:
                existing_match_text = hidden_matches.get(row_key, "")
            scored_row[5] = ""
            scored_row[6] = ""
            if has_selected_phases:
                probability = self._percent_text_value(existing_match_text)
            else:
                probability = self._candidate_row_peak_probability_from_records(
                    scored_row,
                    observed_records,
                    allow_cif_fallback=False,
                )
            if probability > 0 and not has_selected_phases:
                scored_row[5] = f"{probability:.0f}%"
            gain = 0.0
            displayed_gain = 0.0
            if has_selected_phases:
                gain = precomputed_gains.get(index, 0.0)
                profile_evaluated, profile_gain = gain_context.get(
                    "_gain_profile_support_by_key", {}
                ).get(row_key, (False, None))
                displayed_gain = DEFAULT_GAIN_POLICY.reportable_gain(
                    gain,
                    dominant_evidence=gain_context.get(
                        "_gain_dominant_evidence_by_key", {}
                    ).get(row_key),
                    profile_gain=profile_gain,
                    profile_evaluated=profile_evaluated,
                )
            if displayed_gain > 0:
                scored_row[6] = (
                    f"{displayed_gain:.1f}%" if displayed_gain < 10.0 else f"{displayed_gain:.0f}%"
                )
            if has_selected_phases and gain_context is not None and "peak_search" in gain_context:
                # Retained overlap hypotheses should be reviewable even with
                # blank Gain. Values below the display threshold belong to the
                # same blank group; rank them by retrieval evidence instead of
                # letting hidden raw Gain displace stronger shared hypotheses.
                gain = displayed_gain
                probability = 0.0
                if gain <= 0.0 and index in precomputed_gains:
                    evidence = gain_context.get("_gain_peak_candidate_scores", {}).get(row_key)
                    if evidence is not None:
                        probability = float(evidence.retrieval_score)
            scored_rows.append([gain, probability, index, scored_row])
        if progress is not None:
            try:
                progress(len(rows_to_rank), len(rows_to_rank))
            except Exception:
                pass

        match_nonzero = sum(1 for _gain, probability, _index, _row in scored_rows if probability > 0.0)
        gain_nonzero = sum(1 for _gain, _probability, _index, row in scored_rows if row[6])
        gain_text = ""
        if self.match_candidates:
            residual_share = float(gain_context.get("residual_share", 0.0) or 0.0) if gain_context is not None else 0.0
            before_fit = float(gain_context.get("before_fit", 0.0) or 0.0) if gain_context is not None else 0.0
            remaining_fit = max(0.0, 100.0 - before_fit)
            if gain_context is not None and "peak_search" in gain_context:
                search = gain_context["peak_search"]
                gain_text = (f"Gain: {len(search.direct_records)} independent peaks, "
                             f"{len(search.overlap_records)} shared peaks, candidates {gain_nonzero}/{len(scored_rows)}")
            elif gain_context is not None:
                if (before_fit >= 98.0 or residual_share < 0.025 or remaining_fit < 1.5) and gain_nonzero == 0:
                    gain_text = f"Gain: fit {before_fit:.1f}%, remaining {remaining_fit:.1f}%"
                else:
                    gain_text = (
                        f"Gain: fit {before_fit:.1f}%, "
                        f"remaining {remaining_fit:.1f}%, candidates {gain_nonzero}/{len(scored_rows)}"
                    )
            if not gain_text and gain_nonzero == 0:
                gain_text = getattr(self, "_last_gain_debug", "") or "Gain: no new phase signal"
        suffix = gain_text or f"FP: match {match_nonzero}/{len(scored_rows)}, gain {gain_nonzero}/{len(scored_rows)}"
        self._gain_set_status(f"{self._scoring_source_status_text()} | {suffix}")
        if not any(gain > 0 or probability > 0 for gain, probability, _index, _row in scored_rows):
            return [row for _gain, _probability, _index, row in scored_rows] + tail_rows
        scored_rows.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [row for _gain, _probability, _index, row in scored_rows] + tail_rows

    def _percent_text_value(self, text: object) -> float:
        try:
            value = str(text).strip().replace("%", "").replace(",", ".")
            return float(value) if value else 0.0
        except Exception:
            return 0.0

    def _gain_observed_records(self, context, limit: int = 80) -> list[ObservedLineRecord]:
        if "peak_search" in context:
            direct, _shared = gain_peak_retrieval_records(context["peak_search"])
            return list(direct[:limit])
        x = np.asarray(context["x"], dtype=float)
        residual_target = np.asarray(context["residual_target"], dtype=float)
        signed_residual = np.asarray(context.get("difference_curve", []), dtype=float)
        detection_signal = signed_residual if signed_residual.shape == x.shape else residual_target
        residual_records = self._observed_peak_records(x, detection_signal, limit=limit * 2, residual=True)
        selected_total = np.asarray(context.get("selected_total", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        records = list(residual_records)
        if not records:
            return []
        if len(selected_total) != len(x) or len(target) != len(x):
            return self._refine_gain_records_on_signed_residual(context, records[:limit])
        selected_peak_positions = np.asarray(context.get("selected_peak_positions", []), dtype=float)
        selected_peak_positions = selected_peak_positions[np.isfinite(selected_peak_positions)]
        selected_peak_positions.sort()
        stick_tolerance = max(0.32, min(0.72, float(context.get("fwhm", 0.18) or 0.18) * 3.0))
        explained_peak_indices, _properties = find_peaks(
            np.clip(selected_total, 0.0, None),
            prominence=max(float(np.nanpercentile(np.clip(selected_total, 0.0, None), 98)) * 0.015, 1.0),
            distance=max(3, len(selected_total) // 1600),
        )
        if len(explained_peak_indices) == 0 and not len(selected_peak_positions):
            return self._refine_gain_records_on_signed_residual(context, records[:limit])
        explained_positions = x[explained_peak_indices]
        explained_strength = selected_total[explained_peak_indices]
        strength_floor = max(float(np.nanpercentile(explained_strength, 55)), 1.0) if len(explained_strength) else 1.0
        keep_records: list[ObservedLineRecord] = []
        seen_positions: set[int] = set()
        tolerance = max(0.34, min(0.85, float(context.get("fwhm", 0.18) or 0.18) * 2.7))
        residual_positive = residual_target[np.isfinite(residual_target) & (residual_target > 0.0)]
        residual_height_floor = (
            max(
                float(np.nanpercentile(residual_positive, 72)) * 0.28,
                float(np.nanpercentile(residual_positive, 93)) * 0.045,
                1.0,
            )
            if len(residual_positive)
            else 1.0
        )
        for record in records:
            position = self._record_position_value(record)
            line_fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), float(context.get("fwhm", 0.18) or 0.18))
            line_stick_tolerance = max(0.24, min(0.95, line_fwhm * 1.45))
            line_profile_tolerance = max(0.28, min(1.05, line_fwhm * 1.70))
            if len(selected_peak_positions):
                stick_index = int(np.searchsorted(selected_peak_positions, float(position)))
                stick_deltas = []
                if stick_index < len(selected_peak_positions):
                    stick_deltas.append(abs(float(selected_peak_positions[stick_index]) - float(position)))
                if stick_index > 0:
                    stick_deltas.append(abs(float(selected_peak_positions[stick_index - 1]) - float(position)))
                if stick_deltas and min(stick_deltas) <= max(stick_tolerance, line_stick_tolerance):
                    continue
            covered_by_profile = False
            if len(explained_positions):
                index = int(np.argmin(np.abs(explained_positions - float(position))))
                delta = abs(float(explained_positions[index]) - float(position))
                covered_by_profile = delta <= max(tolerance, line_profile_tolerance) and float(explained_strength[index]) >= strength_floor
            if covered_by_profile:
                target_index = int(np.argmin(np.abs(x - float(position))))
                target_height = max(float(target[target_index]), 1.0)
                residual_height = max(float(residual_target[target_index]), 0.0)
                if residual_height <= max(target_height * 0.45, residual_height_floor):
                    continue
            else:
                target_index = int(np.argmin(np.abs(x - float(position))))
                residual_height = max(float(residual_target[target_index]), 0.0)
                if residual_height <= residual_height_floor:
                    continue
            position_key = int(round(float(position) * 1000.0))
            if position_key in seen_positions:
                continue
            seen_positions.add(position_key)
            keep_records.append(record)
            if len(keep_records) >= limit:
                break
        return self._refine_gain_records_on_signed_residual(context, keep_records)

    def _gain_stage_records(self, context, stage: str, limit: int = 80) -> list[ObservedLineRecord]:
        cache = context.setdefault("_gain_stage_records_cache", {})
        cache_key = (str(stage), int(limit))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        records = self._compute_gain_stage_records(context, stage, limit=limit)
        cache[cache_key] = records
        return records

    def _compute_gain_stage_records(self, context, stage: str, limit: int = 80) -> list[ObservedLineRecord]:
        if "peak_search" in context:
            search = context["peak_search"]
            direct, shared = gain_peak_retrieval_records(search)
            records = direct if str(stage) == "direct" else shared if str(stage) == "overlap" else search.records
            return list(sorted(records, key=lambda r: (-r.area, r.two_theta))[:limit])
        if stage == "direct":
            return self._gain_observed_records(context, limit=limit)

        x = np.asarray(context.get("x", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        residual_target = np.asarray(context.get("residual_target", []), dtype=float)
        if len(x) == 0 or len(target) != len(x) or len(residual_target) != len(x):
            return []
        if stage == "hidden":
            return self._observed_peak_records(x, target, limit=limit)

        selected_positions = np.asarray(context.get("selected_peak_positions", []), dtype=float)
        selected_positions = selected_positions[np.isfinite(selected_positions)]
        selected_positions.sort()
        if not len(selected_positions):
            return []
        # Overlap seeds are already restricted to accepted-phase regions and
        # must pass a model-deficit check below.  A 2-sigma seed gate retains
        # weak shoulders without weakening the 3-sigma direct-line gate.
        records = self._observed_peak_records(
            x,
            target,
            limit=limit * 3,
            sigma_threshold=2.0,
        )
        overlap_records: list[ObservedLineRecord] = []
        base_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        selected_total = np.asarray(context.get("selected_total", []), dtype=float)
        if len(selected_total) != len(x):
            return []
        target_positive = target[np.isfinite(target) & (target > 0.0)]
        residual_positive = residual_target[np.isfinite(residual_target) & (residual_target > 0.0)]
        if not len(target_positive) or not len(residual_positive):
            return []
        deficit_floor = max(
            float(np.nanpercentile(residual_positive, 65)) * 0.20,
            float(np.nanpercentile(target_positive, 80)) * 0.025,
            1.0,
        )
        for record in records:
            position = self._record_position_value(record)
            index = int(np.searchsorted(selected_positions, position))
            neighbours = []
            if index < len(selected_positions):
                neighbours.append(abs(float(selected_positions[index]) - position))
            if index > 0:
                neighbours.append(abs(float(selected_positions[index - 1]) - position))
            local_tolerance = max(
                0.28,
                min(
                    0.85,
                    max(float(getattr(record, "fwhm", 0.0) or 0.0), base_fwhm) * 1.7,
                ),
            )
            if not neighbours or min(neighbours) > local_tolerance:
                continue
            record_fwhm = max(
                float(getattr(record, "fwhm", 0.0) or 0.0),
                base_fwhm,
            )
            # Measure the deficit at the residual maximum belonging to this
            # observed line.  Independent maxima over the full overlap window
            # can compare two different peaks: a nearby strong accepted peak
            # then hides a weaker but locally severe underfit reflection.
            measurement_half_width = max(
                0.055,
                min(local_tolerance * 0.55, record_fwhm * 0.65),
            )
            left = int(np.searchsorted(x, position - measurement_half_width, side="left"))
            right = int(np.searchsorted(x, position + measurement_half_width, side="right"))
            if right <= left:
                continue
            local_residual = np.asarray(residual_target[left:right], dtype=float)
            if not np.any(np.isfinite(local_residual)):
                continue
            peak_index = left + int(np.nanargmax(local_residual))
            observed_height = float(target[peak_index])
            calculated_height = float(selected_total[peak_index])
            residual_height = float(residual_target[peak_index])
            deficit_height = max(observed_height - calculated_height, residual_height, 0.0)
            deficit_fraction = deficit_height / max(observed_height, 1.0e-12)
            if residual_peak_is_explained(
                observed_height=observed_height,
                calculated_height=calculated_height,
                residual_height=residual_height,
                noise_floor=deficit_floor,
                overlaps_accepted_phase=True,
                minimum_deficit_fraction=0.12,
            ):
                continue
            overlap_records.append(
                replace(
                    record,
                    two_theta=float(position),
                    area=max(float(getattr(record, "area", 0.0) or 0.0) * deficit_fraction, deficit_height),
                    fwhm=float(getattr(record, "fwhm", base_fwhm) or base_fwhm),
                    height=deficit_height,
                    prominence=record.prominence * deficit_fraction,
                    area_positive=record.area_positive * deficit_fraction,
                    area_signed=record.area_signed * deficit_fraction,
                    # Keep measured shape information, but scale significance
                    # down to the residual amplitude at the same noise level.
                    local_snr=record.local_snr * min(deficit_fraction, 1.0),
                    area_snr=record.area_snr * min(deficit_fraction, 1.0),
                    curvature=record.curvature * min(deficit_fraction, 1.0),
                    delta_chi2=record.delta_chi2 * min(deficit_fraction, 1.0)**2,
                    confidence=record.confidence * min(deficit_fraction, 1.0),
                    overlap_flag=True,
                )
            )
            if len(overlap_records) >= limit:
                break
        overlap_records.sort(key=lambda item: float(item.area), reverse=True)
        return self._refine_gain_records_on_signed_residual(context, overlap_records)[:limit]

    def _refine_gain_records_on_signed_residual(
        self,
        context,
        seeds: list[ObservedLineRecord],
    ) -> list[ObservedLineRecord]:
        if not seeds:
            return []
        x = np.asarray(context.get("x", []), dtype=float)
        signed_residual = np.asarray(context.get("difference_curve", []), dtype=float)
        if len(x) < 9 or len(signed_residual) != len(x):
            return list(seeds)
        instrument_profile = context.get("instrument_profile")
        expected_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.04)
        return self._refine_records_on_signed_signal(
            x,
            signed_residual,
            seeds,
            instrument_profile=instrument_profile,
            expected_fwhm=expected_fwhm,
            residual=True,
        )

    def _refine_records_on_signed_signal(
        self,
        x: np.ndarray,
        signed_signal: np.ndarray,
        seeds: list[ObservedLineRecord],
        *,
        instrument_profile,
        expected_fwhm: float,
        residual: bool = False,
    ) -> list[ObservedLineRecord]:
        fit_seeds = list(seeds[:48])
        refined = refine_residual_peaks(
            x,
            signed_signal,
            fit_seeds,
            expected_fwhm=expected_fwhm,
            instrument_fwhm_at=lambda position: instrument_fwhm_at(instrument_profile, position),
            satellite_components_at=lambda position: radiation_satellites_at(instrument_profile, position),
            refine_peak=getattr(self, "_gain_peak_refiner", lambda: None)(),
            constrain_center=residual,
            enforce_instrument_floor=residual,
        )
        records: list[ObservedLineRecord] = []
        seen_positions: set[int] = set()
        for seed, fitted in zip(fit_seeds, refined, strict=False):
            if fitted is None or fitted.fit_quality < 0.20 or fitted.height <= 0.0:
                record = seed
            else:
                record = ObservedLineRecord(
                    two_theta=fitted.two_theta,
                    area=fitted.area,
                    fwhm=fitted.fwhm_observed,
                    height=fitted.height,
                    prominence=fitted.prominence,
                    area_positive=float(
                        getattr(seed, "area_positive", fitted.area) or fitted.area
                    ),
                    area_signed=float(
                        getattr(seed, "area_signed", fitted.area) or fitted.area
                    ),
                    area_snr=float(getattr(seed, "area_snr", 0.0) or 0.0),
                    curvature=float(getattr(seed, "curvature", 0.0) or 0.0),
                    fwhm_observed=fitted.fwhm_observed,
                    fwhm_sample=fitted.fwhm_sample,
                    instrument_limited=fitted.instrument_limited,
                    fit_quality=fitted.fit_quality,
                    asymmetry=fitted.asymmetry,
                    broadening_scale=float(
                        getattr(seed, "broadening_scale", 1.0) or 1.0
                    ),
                    profile_match=max(
                        float(getattr(seed, "profile_match", 0.0) or 0.0),
                        float(fitted.fit_quality),
                    ),
                    local_snr=float(getattr(seed, "local_snr", 0.0) or 0.0),
                    confidence=max(
                        float(getattr(seed, "confidence", 0.0) or 0.0),
                        float(fitted.fit_quality),
                    ),
                    overlap_flag=bool(getattr(seed, "overlap_flag", False)),
                    delta_chi2=float(getattr(seed, "delta_chi2", 0.0) or 0.0),
                    width_persistence=int(
                        getattr(seed, "width_persistence", 0) or 0
                    ),
                    evidence_class=str(
                        getattr(seed, "evidence_class", "") or ""
                    ),
                )
            position_key = int(round(float(record.two_theta) * 1000.0))
            if position_key in seen_positions:
                continue
            seen_positions.add(position_key)
            records.append(record)
        for seed in seeds[len(fit_seeds) :]:
            position_key = int(round(float(seed.two_theta) * 1000.0))
            if position_key not in seen_positions:
                seen_positions.add(position_key)
                records.append(seed)
        records.sort(key=lambda item: float(item.height), reverse=True)
        return records

    def _gain_sql_candidate_rows(self, *, stage: str = "direct", context=None) -> list[list[str]]:
        if context is None:
            context = self._candidate_gain_context()
        if context is None:
            return []
        context["gain_stage"] = stage
        before_fit = float(context.get("before_fit", 0.0) or 0.0)
        remaining_fit = max(0.0, 100.0 - before_fit)
        residual_share = float(context.get("residual_share", 0.0) or 0.0)
        if "peak_search" not in context and DEFAULT_GAIN_POLICY.residual_is_exhausted(
            selected_phase_count=len(self.match_candidates),
            before_fit=before_fit,
            residual_share=residual_share,
        ):
            self._last_gain_debug = (
                f"Gain: fit {before_fit:.1f}%, remaining {remaining_fit:.1f}%; "
                "adding more phases is likely overfitting"
            )
            return []
        if stage == "combined":
            stage_records = [
                *self._gain_stage_records(context, GainStage.DIRECT, limit=80),
                *self._gain_stage_records(context, GainStage.OVERLAP, limit=80),
            ]
            if len(stage_records) < 2:
                stage_records = self._gain_stage_records(context, GainStage.HIDDEN, limit=80)
        else:
            stage_records = self._gain_stage_records(context, stage, limit=80)
        ranked_records = sorted(
            stage_records,
            key=lambda item: max(float(getattr(item, "area", 0.0) or 0.0), 0.0),
            reverse=True,
        )
        base_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        reliable_records = [
            record
            for record in ranked_records
            if max(float(getattr(record, "fwhm", 0.0) or 0.0), 0.0)
            >= max(0.055, base_fwhm * 0.40)
            and max(float(getattr(record, "fwhm", 0.0) or 0.0), 0.0)
            <= min(0.90, base_fwhm * 4.0)
        ]
        ordered_records = reliable_records + [
            record for record in ranked_records if record not in reliable_records
        ]
        positions = []
        scan_range = context["peak_search"].two_theta_range if "peak_search" in context else None
        for record in ordered_records:
            position = self._record_position_value(record)
            in_range = scan_range[0] <= position <= scan_range[1] if scan_range is not None else 5.0 <= position <= 60.0
            if in_range and all(
                abs(position - existing) > max(0.10, base_fwhm * 0.60)
                for existing in positions
            ):
                positions.append(position)
            if len(positions) >= (10 if stage == "hidden" else 12):
                break
        if not positions:
            return []
        options = self._gain_search_options()
        sources = options.local_sources
        excluded = options.excluded_elements
        # The worker owns cancellation; synchronous callers retain the short
        # interactive SQL budget instead of starting an unbounded UI query.
        cancelled = getattr(self, "_cancelled", None)
        worker_query = callable(cancelled)
        try:
            geometric_entries = (
                self.local_phase_cache.search_by_geometric_fingerprint(
                    positions,
                    excluded_elements=excluded,
                    sources=sources,
                    limit=160,
                    summary_only=True,
                    cancelled=cancelled if worker_query else None,
                    progress=getattr(self, '_progress', None),
                )
                if len(positions) >= 3
                else []
            )
            # An independent line-hit query protects the shortlist when one
            # noisy or incompletely subtracted residual peak corrupts the
            # four-line geometric fingerprint.
            line_entries = self.local_phase_cache.search_by_peaks(
                positions[:6],
                excluded_elements=excluded,
                sources=sources,
                wavelength=self._active_wavelength(),
                tolerance_two_theta=max(
                    0.28,
                    min(0.58, base_fwhm * 2.2),
                ),
                limit=80,
                summary_only=True,
                strict=worker_query,
                cancelled=cancelled if worker_query else None,
            )
            entries = [*geometric_entries, *line_entries]
        except CancelledError as error:
            raise GainJobCancelled() from error
        except LocalPhaseSearchError:
            raise
        except sqlite3.Error as error:
            raise LocalPhaseSearchError(error) from error
        except Exception:
            return []
        rows = self.candidate_search_service.dedupe_candidate_rows(
            self.candidate_search_service.cache_rows(entries)
        )
        if options is not None:
            rows = self.candidate_search_service.filter_candidate_rows_by_excluded_elements(rows, options)
        return rows

    def _candidate_gain_context(self):
        return build_window_peak_gain_context(self)

    def _candidate_row_integral_gain(self, row: list[str], context) -> float:
        if context is None:
            return 0.0
        if "peak_search" in context:
            return score_window_peak_gain_row(self, row, context)
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        peaks = self._candidate_aligned_gain_peaks_cached(candidate, context)
        if not peaks:
            return 0.0
        if self._candidate_duplicates_selected_phase(candidate, peaks, context):
            return 0.0
        evidence = self._candidate_combined_gain_evidence(row, candidate, peaks, context)
        if max(evidence[0], evidence[1], evidence[2]) <= 0.0:
            return 0.0
        peaks, candidate_profile, profile_gain, phase_snr = (
            self._candidate_profile_with_cell_refinement(candidate, peaks, context)
        )
        if self._candidate_duplicates_selected_phase(candidate, peaks, context):
            return 0.0
        evidence = self._candidate_combined_gain_evidence(row, candidate, peaks, context)
        context.setdefault("_gain_profile_support_by_key", {})[
            self._candidate_key(candidate)
        ] = (candidate_profile is not None, profile_gain)
        joint_gain = self._candidate_joint_mass_gain(candidate, peaks, candidate_profile, context)
        if joint_gain is not None:
            return joint_gain
        return DEFAULT_GAIN_POLICY.combine_evidence(
            direct_gain=evidence[0],
            overlap_gain=evidence[1],
            hidden_gain=evidence[2],
            profile_gain=profile_gain,
            remaining_fit=max(0.0, 100.0 - float(context.get("before_fit", 0.0) or 0.0)),
            residual_line_count=evidence[3],
            direct_reliability=evidence[4],
            phase_snr=phase_snr,
        )

    def _candidate_joint_mass_gain(self, candidate, peaks, profile, context):
        key = self._candidate_key(candidate)
        diagnostics = context.setdefault('_gain_joint_by_key', {})
        if key in diagnostics:
            return diagnostics[key].get('gain_percent')
        if context.get('selected_mass_profiles') is None:
            diagnostics[key] = dict(model='legacy', reason='Accepted native mass profiles unavailable')
            return None
        self._gain_check_cancelled()
        try:
            mass_profile, positions, width = self._candidate_mass_profile(candidate, peaks, profile, context)
            result = evaluate_mass_profiles(x=context['x'], target=context['target'],
                accepted_profiles=context['selected_mass_profiles'], candidate_profile=mass_profile,
                weights=1./np.maximum(np.abs(context['target']), 1.), peak_positions=positions,
                selected_peak_positions=context['selected_peak_positions'], fwhm=width)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError, np.linalg.LinAlgError) as error:
            if isinstance(error, GainJobCancelled):
                raise
            diagnostics[key] = dict(model='legacy', reason=str(error))
            return None
        diagnostics[key] = dict(model='experimental_joint', mass_percent=result.mass_percent,
            gain_percent=result.gain_percent, target_reduction_percent=result.joint.target_reduction_percent,
            **asdict(result.evidence))
        context.setdefault('_gain_profile_support_by_key', {})[key] = (True, result.gain_percent)
        return result.gain_percent

    def _candidate_mass_profile(self, candidate, peaks, profile, context):
        path = self._candidate_local_cif_path(candidate)
        if path is None:
            raise ValueError('No local structural CIF for physical joint fit')
        path = Path(path).resolve()
        stat = path.stat()
        mass, volume = _cif_metadata(str(path), stat.st_mtime_ns, stat.st_size)
        override = self._gain_structure_override(candidate)
        cell = override.cell if override is not None else None
        if override is not None:
            _, source = create_phase_from_cif(path)
            if any(getattr(override, name) != getattr(source, name) for name in
                   ('atoms', 'symops', 'space_group', 'space_group_number')):
                raise ValueError('Active structure differs from the native CIF model')
        proposal = context.get('_gain_cell_refinement_by_key', {}).get(self._candidate_key(candidate), {})
        if proposal.get('kept'):
            cell = CellParameters(**proposal['cell'])
        width = context.get('_gain_profile_widths', {}).get(id(profile), context['fwhm'])
        x = np.asarray(context['x'], dtype=float)
        instrument = context['instrument_profile']
        if instrument is None:
            raise ValueError('Physical joint fit requires the active instrument model')
        wavelength, doublet = self._gain_radiation()
        zero = common_zero_shift(self.match_zero_shifts.values())
        calculation = CalculationContext(wavelength, instrument.radiation.components[0].wavelength_angstrom,
            width, float(x[0]), float(x[-1]), array_fingerprint(x), include_kalpha2=doublet,
            global_zero_shift=zero, profile_eta=float(context.get('eta', 0.)))
        calculator = self.finder_service.profile_calculator
        _, lines = calculator.line_calculator.candidate_structure_and_lines(
            str(path), calculation, use_lp=True, instrument_profile=instrument, cell_override=cell)
        native = calculator.profile_from_lines(lines, x, calculation,
            instrument_profile=instrument, normalize=False)
        if cell is not None:
            volume = unit_cell_volume(cell)
        return native/(mass*volume), np.asarray([p.two_theta+zero for p in lines.peaks]), float(width)

    def _candidate_reportable_gain(self, candidate, gain, context):
        key = self._candidate_key(candidate)
        joint = context.get('_gain_joint_by_key', {}).get(key, {}) if context is not None else {}
        if joint.get('model') == 'experimental_joint':
            return float(joint['gain_percent'])
        evaluated, profile_gain = (context or {}).get('_gain_profile_support_by_key', {}).get(key, (False, None))
        return DEFAULT_GAIN_POLICY.reportable_gain(gain,
            dominant_evidence=(context or {}).get('_gain_dominant_evidence_by_key', {}).get(key),
            profile_gain=profile_gain, profile_evaluated=evaluated)

    def _candidate_profile_with_cell_refinement(self, candidate, peaks, context):
        """Evaluate a shortlisted cell at fixed scan zero; retain only better support."""
        key = self._candidate_key(candidate)
        cache = context.setdefault('_gain_cell_profile_cache', {})
        if key in cache:
            return cache[key]
        self._gain_check_cancelled()
        profile = self._candidate_gain_profile(candidate, peaks, context)
        gain, snr = (self._candidate_gain_value_for_profile(profile, peaks, context)
                     if profile is not None else (None, None))
        cache[key] = (peaks, profile, gain, snr)
        if profile is None or key in {self._candidate_key(item) for item in self.match_candidates}:
            return cache[key]
        if not peaks or any((peak.h, peak.k, peak.l) == (0, 0, 0) for peak in peaks):
            return cache[key]
        try:
            path = self._candidate_local_cif_path(candidate)
            if path is None:
                return cache[key]
            _phase, structure = create_phase_from_cif(path)
            records = [*self._gain_stage_records(context, GainStage.DIRECT, limit=90),
                       *self._gain_stage_records(context, GainStage.OVERLAP, limit=90)]
            raw = context.get('_gain_raw_peaks_cache', {}).get(key)
            if raw is None:
                raw = self._candidate_peaks_for_gain(candidate)
            wavelength, _doublet = self._gain_radiation()
            alignment = refine_gain_cell(
                initial_cell=structure.cell, peaks=raw, records=records, wavelength=wavelength,
                zero_shift_deg=common_zero_shift(self.match_zero_shifts.values()))
            self._gain_check_cancelled()
            if alignment is None:
                return cache[key]
            refined_peaks = _gain_scan_peaks(alignment.peaks, context)
            refined_profile = self._candidate_gain_profile(candidate, refined_peaks, context)
            if refined_profile is None:
                return cache[key]
            refined_gain, refined_snr = self._candidate_gain_value_for_profile(refined_profile, refined_peaks, context)
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError, np.linalg.LinAlgError):
            return cache[key]
        kept = refined_gain > max(float(gain or 0.0), 0.0)
        provenance = asdict(alignment.estimate)
        provenance.update(kept=kept, profile_gain_before=gain, profile_gain_after=refined_gain)
        context.setdefault('_gain_cell_refinement_by_key', {})[key] = provenance
        if not kept:
            return cache[key]
        context.setdefault('_gain_cell_aligned_peaks', {})[key] = refined_peaks
        context.setdefault('_gain_aligned_peaks_cache', {})[key] = refined_peaks
        # Scores computed for the catalogue cell cannot support a different metric.
        for name in ('_gain_combined_evidence_cache', '_gain_dominant_evidence_by_key',
                     '_gain_selected_pattern_duplicate_cache'):
            context.get(name, {}).pop(key, None)
        for name in ('_gain_line_score_cache', '_gain_combined_line_score_cache'):
            scores = context.get(name, {})
            for score_key in list(scores):
                if score_key[1] == key:
                    del scores[score_key]
        cache[key] = (refined_peaks, refined_profile, refined_gain, refined_snr)
        return cache[key]

    def _candidate_row_preliminary_gain(self, row: list[str], context) -> float:
        """Cheap residual-line score used before full candidate profiles."""

        if context is None:
            return 0.0
        if "peak_search" in context:
            return score_window_peak_gain_row(self, row, context, preliminary=True)
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        peaks = self._candidate_aligned_gain_peaks_cached(candidate, context)
        if not peaks:
            return 0.0
        if self._candidate_duplicates_selected_phase(candidate, peaks, context):
            return 0.0
        evidence = self._candidate_combined_gain_evidence(row, candidate, peaks, context)
        return DEFAULT_GAIN_POLICY.combine_evidence(
            direct_gain=evidence[0],
            overlap_gain=evidence[1],
            hidden_gain=evidence[2],
            profile_gain=None,
            remaining_fit=max(0.0, 100.0 - float(context.get("before_fit", 0.0) or 0.0)),
            residual_line_count=evidence[3],
            direct_reliability=evidence[4],
        )

    def _candidate_combined_gain_evidence(
        self,
        row: list[str],
        candidate: dict[str, str],
        peaks: list[HKLPeak],
        context,
    ) -> tuple[float, float, float, int, float]:
        cache = context.setdefault("_gain_combined_evidence_cache", {})
        candidate_key = self._candidate_key(candidate)
        if candidate_key in cache:
            return cache[candidate_key]
        direct_gain = self._candidate_preliminary_line_gain(
            candidate, peaks, context, str(GainStage.DIRECT)
        )
        overlap_gain = self._candidate_preliminary_line_gain(
            candidate, peaks, context, str(GainStage.OVERLAP)
        )
        hidden_records = self._gain_stage_records(context, GainStage.HIDDEN, limit=120)
        presence = self._candidate_gain_presence_factor(
            row,
            hidden_records,
            hidden_records,
            peaks=[peak for peak in peaks
                   if float(context['x'][0]) <= peak.two_theta <= float(context['x'][-1])],
        )
        hidden_gain = DEFAULT_GAIN_POLICY.hidden_gain(
            before_fit=float(context.get("before_fit", 0.0) or 0.0),
            presence=presence,
        )
        residual_line_count = self._gain_distinct_residual_line_count(context)
        direct_reliability = self._candidate_direct_evidence_reliability(peaks, context)
        evidence = (
            float(direct_gain),
            float(overlap_gain),
            float(hidden_gain),
            int(residual_line_count),
            float(direct_reliability),
        )
        cache[candidate_key] = evidence
        dominant = max(
            (
                (float(direct_gain), GainStage.DIRECT),
                (
                    DEFAULT_GAIN_POLICY.winner_overlap_weight * float(overlap_gain),
                    GainStage.OVERLAP,
                ),
                (DEFAULT_GAIN_POLICY.hidden_evidence_weight * float(hidden_gain), GainStage.HIDDEN),
            ),
            key=lambda item: item[0],
        )[1]
        context.setdefault("_gain_dominant_evidence_by_key", {})[candidate_key] = dominant
        return evidence

    def _candidate_direct_evidence_reliability(self, peaks: list[HKLPeak], context) -> float:
        records = self._gain_stage_records(context, GainStage.DIRECT, limit=90)
        if not peaks or not records:
            return 0.0
        base_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        tolerance = max(0.26, min(0.72, base_fwhm * 2.4))
        positions = sorted(
            float(getattr(peak, "two_theta", 0.0) or 0.0)
            for peak in peaks
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
        )
        available = set(range(len(positions)))
        matched_count = 0
        matched_area = 0.0
        total_area = sum(max(float(getattr(record, "area", 0.0) or 0.0), 0.0) for record in records)
        for record in records:
            record_position = self._record_position_value(record)
            best = min(
                available,
                key=lambda index: abs(positions[index] - record_position),
                default=None,
            )
            if best is None or abs(positions[best] - record_position) > tolerance:
                continue
            available.remove(best)
            matched_count += 1
            matched_area += max(float(getattr(record, "area", 0.0) or 0.0), 0.0)
        count_reliability = min(1.0, matched_count / 3.0)
        coverage_reliability = min(1.0, matched_area / max(total_area * 0.35, 1.0e-12))
        return float(count_reliability * coverage_reliability)

    def _gain_distinct_residual_line_count(self, context) -> int:
        cached = context.get("_gain_distinct_residual_line_count")
        if cached is not None:
            return int(cached)
        records = [
            *self._gain_stage_records(context, GainStage.DIRECT, limit=90),
            *self._gain_stage_records(context, GainStage.OVERLAP, limit=90),
        ]
        positions = sorted(self._record_position_value(record) for record in records)
        tolerance = max(0.10, min(0.30, float(context.get("fwhm", 0.18) or 0.18) * 0.75))
        distinct: list[float] = []
        for position in positions:
            if not distinct or abs(float(position) - distinct[-1]) > tolerance:
                distinct.append(float(position))
        context["_gain_distinct_residual_line_count"] = len(distinct)
        return len(distinct)

    def _candidate_preliminary_line_gain(
        self,
        candidate: dict[str, str],
        peaks: list[HKLPeak],
        context,
        stage: str,
    ) -> float:
        combined_cache = context.setdefault("_gain_combined_line_score_cache", {})
        candidate_key = self._candidate_key(candidate)
        combined_key = (str(stage), candidate_key)
        if combined_key in combined_cache:
            return float(combined_cache[combined_key])

        line_cache = context.setdefault("_gain_line_score_cache", {})

        def score_stage(stage_name: str) -> float:
            line_key = (stage_name, candidate_key)
            if line_key in line_cache:
                return float(line_cache[line_key])
            previous_stage = str(context.get("gain_stage", "direct") or "direct")
            context["gain_stage"] = stage_name
            try:
                value = float(self._candidate_residual_line_gain(peaks, context))
            finally:
                context["gain_stage"] = previous_stage
            line_cache[line_key] = value
            return value

        value = score_stage(str(stage))
        combined_cache[combined_key] = float(value)
        return float(value)

    def _candidate_aligned_gain_peaks_cached(
        self,
        candidate: dict[str, str],
        context,
    ) -> list[HKLPeak]:
        """Load and align candidate sticks once during one Gain ranking pass."""

        cache = context.setdefault("_gain_aligned_peaks_cache", {})
        key = self._candidate_key(candidate)
        if key in cache:
            return cache[key]
        peaks = self._candidate_peaks_for_gain(candidate)
        context.setdefault("_gain_raw_peaks_cache", {})[key] = tuple(peaks)
        if peaks:
            peaks = self._aligned_candidate_gain_peaks(candidate, peaks, context)
            peaks = _gain_scan_peaks(peaks, context)
        cache[key] = peaks
        return peaks

    def _candidate_duplicates_selected_phase(
        self,
        candidate: dict[str, str],
        peaks: list[HKLPeak],
        context,
    ) -> bool:
        """Return whether a Gain row is another card for an accepted pattern.

        Entry identifiers, names and formulas are intentionally ignored.  The
        comparison uses the aligned strong reflections in both directions, so
        sharing a few peaks is insufficient to hide a genuine additional phase.
        """

        cache = context.setdefault("_gain_selected_pattern_duplicate_cache", {})
        key = self._candidate_key(candidate)
        if key in cache:
            return bool(cache[key])
        fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        duplicate = False
        best_comparison = None
        raw_peaks = context.get("_gain_raw_peaks_cache", {}).get(key, ())
        comparisons = []
        if raw_peaks:
            comparisons.extend(
                (selected_pattern, raw_peaks)
                for selected_pattern in context.get("selected_phase_patterns_raw", ())
            )
        comparisons.extend(
            (selected_pattern, peaks)
            for selected_pattern in context.get("selected_phase_patterns", ())
        )
        for selected_pattern, candidate_pattern in comparisons:
            comparison = compare_phase_patterns(
                _gain_scan_peaks(selected_pattern, context),
                _gain_scan_peaks(candidate_pattern, context),
                fwhm=fwhm,
            )
            if best_comparison is None or min(
                comparison.reference_coverage,
                comparison.candidate_coverage,
            ) > min(
                best_comparison.reference_coverage,
                best_comparison.candidate_coverage,
            ):
                best_comparison = comparison
            if comparison.equivalent:
                duplicate = True
                break
        cache[key] = duplicate
        if duplicate and best_comparison is not None:
            diagnostics = context.setdefault("_gain_suppressed_duplicate_patterns", {})
            diagnostics[key] = best_comparison
        return duplicate

    def _candidate_gain_value_for_profile(
        self,
        candidate_profile: np.ndarray,
        peaks: list[HKLPeak],
        context,
    ) -> tuple[float, float]:
        residual_target = np.asarray(context["residual_target"], dtype=float)
        target = np.asarray(context["target"], dtype=float)
        selected_total = np.asarray(context["selected_total"], dtype=float)
        weights = np.asarray(context.get("target_weights", context["weights"]), dtype=float)
        candidate_scale = self._fit_residual_candidate_scale(
            target,
            selected_total,
            candidate_profile,
            weights,
        )
        if candidate_scale <= 1.0e-8:
            return 0.0, 0.0
        calculated = candidate_profile * candidate_scale
        profile_gain = profile_residual_gain(
            residual_target=residual_target,
            calculated=calculated,
            weights=weights,
            residual_area=float(context["residual_area"]),
            before_fit=float(context.get("before_fit", 0.0) or 0.0),
        )
        phase_snr = phase_signal_to_noise(
            x=np.asarray(context["x"], dtype=float),
            residual_after=target - selected_total - calculated,
            candidate_curve=calculated,
            peak_positions=np.asarray(
                [float(getattr(peak, "two_theta", 0.0) or 0.0) for peak in peaks],
                dtype=float,
            ),
            peak_amplitudes=np.asarray(
                [float(getattr(peak, "intensity", 0.0) or 0.0) for peak in peaks],
                dtype=float,
            ),
            fwhm=max(float(context.get("fwhm", 0.18) or 0.18), 0.05),
        )
        return float(profile_gain), float(phase_snr)

    def _aligned_candidate_gain_peaks(
        self,
        candidate: dict[str, str],
        peaks: list[HKLPeak],
        context,
    ) -> list[HKLPeak]:
        key = self._candidate_key(candidate)
        refined = context.get('_gain_cell_aligned_peaks', {}).get(key)
        if refined is not None:
            return list(refined)
        if key in self.match_zero_shifts or key in self.match_cell_scales:
            return self._adjusted_gain_peaks(candidate, peaks)
        # Zero displacement belongs to the experimental scan, therefore every
        # phase must use the same value.  Do not fit an independent constant
        # offset for each shortlisted candidate.  Indexed cell refinement may
        # still move individual reflections through the reciprocal metric.
        zero_shift = common_zero_shift(self.match_zero_shifts.values())
        if abs(zero_shift) < 1.0e-8:
            return peaks
        return [
            HKLPeak(
                h=int(getattr(peak, "h", 0) or 0),
                k=int(getattr(peak, "k", 0) or 0),
                l=int(getattr(peak, "l", 0) or 0),
                d=float(getattr(peak, "d", 0.0) or 0.0),
                two_theta=float(getattr(peak, "two_theta", 0.0) or 0.0) + zero_shift,
                intensity=float(getattr(peak, "intensity", 0.0) or 0.0),
                multiplicity=int(getattr(peak, "multiplicity", 1) or 1),
                f2=float(getattr(peak, "f2", 0.0) or 0.0),
                lp=float(getattr(peak, "lp", 1.0) or 1.0),
                raw_intensity=float(getattr(peak, "raw_intensity", 0.0) or 0.0),
            )
            for peak in peaks
        ]

    def _candidate_gain_intensity_factor(self, pairs: list[tuple[HKLPeak, object]]) -> float:
        if len(pairs) < 3:
            return 0.0
        ratios = []
        weights = []
        for peak, record in pairs:
            theoretical = max(float(getattr(peak, "intensity", 0.0) or 0.0), 1.0e-6)
            experimental = getattr(record, "area", None)
            if experimental is None:
                try:
                    experimental = record[1]
                except Exception:
                    continue
            experimental = max(float(experimental or 0.0), 1.0e-6)
            ratios.append(math.log(experimental / theoretical))
            weights.append(math.sqrt(theoretical))
        if len(ratios) < 3:
            return 0.0
        values = np.asarray(ratios, dtype=float)
        line_weights = np.asarray(weights, dtype=float)
        center = float(np.median(values))
        deviations = np.abs(values - center)
        order = np.argsort(deviations)
        # One or two systematic texture-enhanced directions should not reject
        # an otherwise coherent phase.
        keep_count = max(3, len(order) - min(2, max(0, len(order) // 5)))
        keep = order[:keep_count]
        mean_deviation = float(np.average(deviations[keep], weights=line_weights[keep]))
        coherent_fraction = keep_count / max(len(values), 1)
        return float(np.clip(math.exp(-mean_deviation / 0.95) * coherent_fraction, 0.05, 1.0))

    def _gain_line_signal_floors(self, context) -> tuple[float, float] | None:
        # Each ranking context owns fixed target/residual arrays across its stages.
        key = "_gain_line_signal_floors"
        if key not in context:
            target = np.asarray(context.get("target", []), dtype=float)
            residual = np.asarray(context.get("residual_target", []), dtype=float)
            target_positive = target[np.isfinite(target) & (target > 0.0)]
            residual_positive = residual[np.isfinite(residual) & (residual > 0.0)]
            if not len(target_positive) or not len(residual_positive):
                context[key] = None
            else:
                context[key] = (
                    max(
                        float(np.nanpercentile(target_positive, 70)) * 0.22,
                        float(np.nanpercentile(target_positive, 92)) * 0.035,
                        1.0,
                    ),
                    max(
                        float(np.nanpercentile(residual_positive, 70)) * 0.30,
                        float(np.nanpercentile(residual_positive, 92)) * 0.045,
                        1.0,
                    ),
                )
        return context[key]

    def _candidate_residual_line_gain(self, peaks: list[HKLPeak], context) -> float:
        if not peaks or context is None:
            return 0.0
        x = np.asarray(context.get("x", []), dtype=float)
        target = np.asarray(context.get("target", []), dtype=float)
        residual_target = np.asarray(context.get("residual_target", []), dtype=float)
        if len(x) == 0 or len(target) != len(x) or len(residual_target) != len(x):
            return 0.0
        stage = str(context.get("gain_stage", "direct") or "direct")
        residual_records = self._gain_stage_records(context, stage, limit=90)
        target_records = self._gain_context_observed_peak_records(context, "target", limit=140)
        if not residual_records or not target_records:
            return 0.0
        residual_records = sorted(
            residual_records,
            key=lambda record: max(float(getattr(record, "area", 0.0) or 0.0), 0.0),
            reverse=True,
        )
        strong = [
            peak
            for peak in sorted(peaks, key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0), reverse=True)
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
            and float(x[0]) <= float(getattr(peak, "two_theta", 0.0) or 0.0) <= float(x[-1])
        ][:42]
        if len(strong) < 3:
            return 0.0
        # One or two remaining experimental lines are useful for retrieval, but
        # they are weak evidence.  Treat this as a property of the residual,
        # rather than of the candidate's calculated intensity distribution.
        limited_residual = self._gain_distinct_residual_line_count(context) <= 2

        base_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        tolerance = max(0.26, min(0.72, base_fwhm * 2.4))
        candidate_positions = np.asarray([float(getattr(peak, "two_theta", 0.0) or 0.0) for peak in strong], dtype=float)
        candidate_weights = np.asarray(
            [
                max(float(getattr(peak, "intensity", 0.0) or 0.0) / 100.0, 0.025) ** 0.55 / math.sqrt(index + 1.0)
                for index, peak in enumerate(strong)
            ],
            dtype=float,
        )
        candidate_ranks = np.arange(len(strong), dtype=int)
        order = np.argsort(candidate_positions)
        candidate_positions = candidate_positions[order]
        candidate_weights = candidate_weights[order]
        candidate_ranks = candidate_ranks[order]

        useful_area = 0.0
        matched_residual_count = 0
        matched_major_residual_count = 0
        matched_candidate_indices: set[int] = set()
        matched_residual_pairs: list[tuple[HKLPeak, ObservedLineRecord]] = []
        matched_top_count = 0
        residual_area = sum(max(float(getattr(record, "area", 0.0) or 0.0), 0.0) for record in residual_records)
        major_residual_limit = min(14, len(residual_records))
        for residual_index, record in enumerate(residual_records):
            position = self._record_position_value(record)
            area = max(float(getattr(record, "area", 0.0) or 0.0), 0.0)
            if area <= 0.0:
                continue
            best_delta = 999.0
            best_index = -1
            for candidate_index, candidate_position in enumerate(candidate_positions):
                if candidate_index in matched_candidate_indices:
                    continue
                delta = abs(float(candidate_position) - float(position))
                if delta < best_delta:
                    best_delta = delta
                    best_index = candidate_index
            line_fwhm = max(float(getattr(record, "fwhm", 0.0) or 0.0), base_fwhm)
            local_tolerance = max(tolerance, min(0.95, line_fwhm * 1.7))
            if best_index < 0 or best_delta > local_tolerance:
                continue
            position_quality = max(0.0, 1.0 - best_delta / max(local_tolerance, 1.0e-6))
            useful_area += area * (0.35 + 0.65 * position_quality)
            matched_residual_count += 1
            if residual_index < major_residual_limit:
                matched_major_residual_count += 1
            if int(candidate_ranks[best_index]) < 12:
                matched_top_count += 1
            matched_candidate_indices.add(best_index)
            matched_residual_pairs.append((strong[int(candidate_ranks[best_index])], record))

        minimum_matches = 1 if limited_residual else 2
        if useful_area <= 0.0 or matched_residual_count < minimum_matches:
            return 0.0
        major_fraction = matched_major_residual_count / max(major_residual_limit, 1)
        residual_coverage = useful_area / max(residual_area, 1.0e-12)

        target_positions = self._record_positions(target_records)
        selected_total = np.asarray(context.get("selected_total", []), dtype=float)
        selected_positions = np.asarray(context.get("selected_peak_positions", []), dtype=float)
        selected_positions = selected_positions[np.isfinite(selected_positions)]
        selected_positions.sort()
        signal_floors = self._gain_line_signal_floors(context)
        if signal_floors is None:
            return 0.0
        target_floor, residual_floor = signal_floors

        def local_max(values: np.ndarray, center: float, half_width: float) -> float:
            if len(values) != len(x):
                return 0.0
            left = int(np.searchsorted(x, center - half_width, side="left"))
            right = int(np.searchsorted(x, center + half_width, side="right"))
            if right <= left:
                return 0.0
            return float(np.nanmax(values[left:right]))

        absent_weight = 0.0
        repeated_weight = 0.0
        matched_weight = 0.0
        observed_only_weight = 0.0
        anchor_weight = 0.0
        matched_anchor_weight = 0.0
        absent_top_count = 0
        checked_top_count = 0
        local_signal_width = max(0.20, min(0.80, tolerance * 1.25))
        for index, (position, weight) in enumerate(zip(candidate_positions, candidate_weights, strict=False)):
            rank = int(candidate_ranks[index])
            if rank < 12:
                checked_top_count += 1
                anchor_weight += float(weight)
            if index in matched_candidate_indices:
                matched_weight += float(weight)
                if rank < 12:
                    matched_anchor_weight += float(weight)
                continue
            target_peak = local_max(target, float(position), local_signal_width)
            residual_peak = local_max(residual_target, float(position), local_signal_width)
            selected_peak = local_max(selected_total, float(position), local_signal_width) if len(selected_total) == len(x) else 0.0
            has_observed_signal = target_peak >= target_floor or residual_peak >= residual_floor
            if len(selected_positions) and self._nearest_selected_line_delta(selected_positions, float(position)) <= tolerance:
                if stage == "overlap":
                    observed_only_weight += float(weight) * 0.15
                else:
                    repeated_weight += float(weight) * 0.80
            elif selected_peak >= max(target_floor, target_peak * 0.35):
                if stage == "overlap":
                    observed_only_weight += float(weight) * 0.15
                else:
                    repeated_weight += float(weight) * 0.65
            elif has_observed_signal or self._nearest_selected_line_delta(target_positions, float(position)) <= tolerance:
                observed_only_weight += float(weight) * 0.50
            else:
                penalty = (
                    (4.2 if rank < 10 else 1.8)
                    if limited_residual
                    else (3.25 if rank < 10 else 1.35)
                )
                absent_weight += float(weight) * penalty
                if rank < 12:
                    absent_top_count += 1

        absent_multiplier = 4.2 if limited_residual else 3.4
        support = matched_weight / max(
            matched_weight
            + absent_multiplier * absent_weight
            + 1.6 * repeated_weight
            + observed_only_weight,
            1.0e-12,
        )
        anchor_support = matched_anchor_weight / max(anchor_weight, 1.0e-12)
        if limited_residual and len(matched_residual_pairs) < 3:
            intensity_factor = 0.55 if len(matched_residual_pairs) == 1 else 0.70
        else:
            intensity_factor = self._candidate_gain_intensity_factor(matched_residual_pairs)
        if limited_residual:
            insufficient_anchor_support = matched_top_count < 1 and anchor_support < 0.10
        else:
            insufficient_anchor_support = matched_top_count < 2 and anchor_support < 0.20
        if insufficient_anchor_support:
            return 0.0
        if (
            checked_top_count
            and absent_top_count >= max(3, int(math.ceil(checked_top_count * 0.34)))
        ):
            if absent_weight > matched_weight * 1.15:
                return 0.0
        minimum_major_fraction = 0.055 if limited_residual else 0.18
        minimum_residual_coverage = 0.018 if limited_residual else 0.035
        minimum_support = 0.08 if limited_residual else 0.22
        minimum_anchor_support = 0.08 if limited_residual else 0.16
        if (
            major_fraction < minimum_major_fraction
            or residual_coverage < minimum_residual_coverage
            or support < minimum_support
            or anchor_support < minimum_anchor_support
            or intensity_factor < 0.10
        ):
            return 0.0
        before_fit = float(context.get("before_fit", 0.0) or 0.0)
        remaining_fit = max(0.0, 100.0 - before_fit)
        line_gain = (
            remaining_fit
            * min(1.0, residual_coverage)
            * min(1.0, major_fraction / 0.38)
            * min(1.0, support / 0.48)
            * min(1.0, anchor_support / 0.42)
            * (0.45 + 0.55 * intensity_factor)
        )
        if stage == "overlap":
            width_corroboration = self._candidate_overlap_width_corroboration(
                matched_residual_pairs,
                context,
            )
            line_gain *= 1.0 + 0.08 * width_corroboration
        return float(np.clip(line_gain, 0.0, remaining_fit))

    def _candidate_overlap_width_corroboration(
        self,
        matched_pairs: list[tuple[HKLPeak, ObservedLineRecord]],
        context,
    ) -> float:
        models = list(context.get("selected_width_models", []))
        if not matched_pairs or not models:
            return 0.0
        tolerance = max(0.22, min(0.70, float(context.get("fwhm", 0.18) or 0.18) * 2.2))
        values = []
        for _peak, record in matched_pairs:
            sample_width = getattr(record, "fwhm_sample", None)
            if sample_width is None or bool(getattr(record, "instrument_limited", False)):
                continue
            fit_quality = float(getattr(record, "fit_quality", 0.0) or 0.0)
            asymmetry = float(getattr(record, "asymmetry", 0.0) or 0.0)
            if fit_quality > 0.0 and fit_quality < 0.35:
                continue
            if asymmetry > 0.45:
                continue
            position = float(getattr(record, "two_theta", 0.0) or 0.0)
            nearest = None
            for item in models:
                positions = np.asarray(item.get("positions", []), dtype=float)
                if not len(positions):
                    continue
                delta = float(np.nanmin(np.abs(positions - position)))
                if delta <= tolerance and (nearest is None or delta < nearest[0]):
                    nearest = (delta, item["model"])
            if nearest is None:
                continue
            model = nearest[1]
            expected = model.predict_sample_fwhm(position)
            corroboration = width_difference_corroboration(
                float(sample_width),
                expected,
                float(model.robust_spread),
            )
            reliability = (fit_quality if fit_quality > 0.0 else 0.55) * (1.0 - asymmetry)
            values.append(corroboration * float(np.clip(reliability, 0.0, 1.0)))
        if not values:
            return 0.0
        return float(np.clip(np.mean(values), 0.0, 1.0))

    def _gain_residual_target(self, difference_curve: np.ndarray, x: np.ndarray, fwhm: float) -> np.ndarray:
        values = np.asarray(difference_curve, dtype=float)
        if len(values) == 0:
            return values
        raw_positive = np.clip(values, 0.0, None)
        step = float(np.nanmedian(np.diff(np.asarray(x, dtype=float)))) if len(x) > 1 else 0.03
        sigma = max(1.0, min(14.0, float(fwhm) / max(abs(step), 1.0e-6) / 4.0))
        smooth = gaussian_filter1d(values, sigma=sigma, mode="nearest")
        positive = np.clip(smooth, 0.0, None)
        if float(np.nanmax(positive)) <= 0:
            return raw_positive
        floor = max(float(np.nanpercentile(positive, 35)) * 0.25, self._gain_noise_floor(positive) * 0.05)
        residual = np.clip(positive - floor, 0.0, None)
        if float(np.nanmax(residual)) <= 0 or self._weighted_integral_area(residual, np.ones_like(residual)) <= 0:
            return positive
        return residual

    def _fit_residual_candidate_scale(
        self,
        target: np.ndarray,
        selected_total: np.ndarray,
        profile: np.ndarray,
        weights: np.ndarray,
    ) -> float:
        return fit_residual_candidate_scale(
            target=target,
            selected_total=selected_total,
            profile=profile,
            weights=weights,
        )

    def _adjusted_gain_peaks(self, candidate: dict[str, str], peaks: list[HKLPeak]) -> list[HKLPeak]:
        if not peaks:
            return []
        key = self._candidate_key(candidate)
        zero_shift = float(self.match_zero_shifts.get(key, 0.0) or 0.0)
        cell_scale = float(self.match_cell_scales.get(key, 1.0) or 1.0)
        estimated_cell = candidate.get("_EstimatedCell")
        if not estimated_cell and abs(zero_shift) < 1.0e-8 and abs(cell_scale - 1.0) < 1.0e-8:
            return peaks
        wavelength = float(self._active_wavelength())
        if estimated_cell and hasattr(self, "_legacy_radiation_for_pattern"):
            radiation_wavelength, include_kalpha2 = (self._gain_radiation() if hasattr(self, "_gain_radiation")
                else self._legacy_radiation_for_pattern(self._active_pattern()))
            wavelength = radiation_lines_from_wavelength(radiation_wavelength, include_kalpha2=include_kalpha2)[0][0]
        adjusted: list[HKLPeak] = []
        for peak in peaks:
            try:
                d_value = float(getattr(peak, "d", 0.0) or 0.0)
                if d_value > 0.0 and abs(cell_scale - 1.0) >= 1.0e-8:
                    two_theta = self._two_theta_from_d_spacing(d_value * cell_scale, wavelength)
                    if two_theta is None:
                        continue
                else:
                    two_theta = float(getattr(peak, "two_theta", 0.0) or 0.0)
                adjusted.append(
                    HKLPeak(
                        h=int(getattr(peak, "h", 0) or 0),
                        k=int(getattr(peak, "k", 0) or 0),
                        l=int(getattr(peak, "l", 0) or 0),
                        d=d_value * cell_scale if d_value > 0.0 else d_value,
                        two_theta=float(two_theta) + zero_shift,
                        intensity=float(getattr(peak, "intensity", 0.0) or 0.0),
                        multiplicity=int(getattr(peak, "multiplicity", 1) or 1),
                        f2=float(getattr(peak, "f2", 0.0) or 0.0),
                        lp=float(getattr(peak, "lp", 1.0) or 1.0),
                        raw_intensity=float(getattr(peak, "raw_intensity", 0.0) or 0.0),
                    )
                )
            except Exception:
                continue
        if isinstance(estimated_cell, dict):
            try:
                cell = CellParameters(**{
                    name: float(estimated_cell[name])
                    for name in ("a", "b", "c", "alpha", "beta", "gamma")
                })
                cell_peaks = apply_peak_cell(adjusted, cell, wavelength=wavelength, zero_shift=zero_shift)
                if cell_peaks is not None:
                    return list(cell_peaks)
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        return adjusted

    def _two_theta_from_d_spacing(self, d_spacing: float, wavelength: float) -> float | None:
        d_spacing = float(d_spacing)
        if d_spacing <= 0.0:
            return None
        argument = float(wavelength) / (2.0 * d_spacing)
        if not 0.0 < argument < 1.0:
            return None
        return float(np.rad2deg(2.0 * np.arcsin(argument)))

    def _candidate_gain_presence_factor(
        self,
        row: list[str],
        observed_records: list[tuple[float, float]],
        gain_records: list[tuple[float, float]],
        *,
        peaks: list[HKLPeak] | None = None,
    ) -> float:
        candidate = {
            "Source": row[0] if len(row) > 0 else "",
            "Entry": row[1] if len(row) > 1 else "",
            "Formula": row[2] if len(row) > 2 else "",
            "Phase": row[3] if len(row) > 3 else "",
        }
        if peaks is None:
            peaks = self._candidate_peaks_for_gain(candidate)
        if not peaks or not observed_records or not gain_records:
            return 0.0
        strong = [
            peak
            for peak in sorted(peaks, key=lambda peak: float(getattr(peak, "intensity", 0.0) or 0.0), reverse=True)[:36]
            if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
        ]
        if len(strong) < 3:
            return 0.0
        observed_positions = self._record_positions(observed_records)
        gain_positions = self._record_positions(gain_records)
        full_coverage, full_count = self._weighted_candidate_line_coverage(strong, observed_positions, tolerance=0.42)
        gain_coverage, gain_count = self._weighted_candidate_line_coverage(strong[:24], gain_positions, tolerance=0.48)
        required_count = 5 if len(strong) >= 12 else 4 if len(strong) >= 8 else 3
        if full_count < required_count or gain_count < required_count:
            return 0.0
        if full_coverage < 0.18 or gain_coverage < 0.22:
            return 0.0
        return float(np.clip((0.25 + 0.75 * full_coverage) * (gain_coverage / 0.48) ** 1.15, 0.0, 1.0))

    def _record_position_value(self, record) -> float:
        value = getattr(record, "two_theta", None)
        if value is not None:
            return float(value)
        return float(record[0])

    def _record_positions(self, records: list[ObservedLineRecord]) -> np.ndarray:
        positions = np.asarray([self._record_position_value(record) for record in records], dtype=float)
        positions = positions[np.isfinite(positions)]
        positions.sort()
        return positions

    def _weighted_candidate_line_coverage(
        self,
        peaks: list[HKLPeak],
        positions: np.ndarray,
        *,
        tolerance: float,
    ) -> tuple[float, int]:
        if len(positions) == 0 or not peaks:
            return 0.0, 0
        total_weight = 0.0
        covered_weight = 0.0
        covered_count = 0
        for index, peak in enumerate(peaks):
            position = float(getattr(peak, "two_theta", 0.0) or 0.0)
            intensity = max(float(getattr(peak, "intensity", 0.0) or 0.0), 0.0)
            weight = math.sqrt(intensity) / math.sqrt(index + 1.0)
            total_weight += weight
            if self._nearest_selected_line_delta(positions, position) <= float(tolerance):
                covered_weight += weight
                covered_count += 1
        return covered_weight / max(total_weight, 1.0e-12), covered_count

    def _nearest_selected_line_delta(self, selected_positions: np.ndarray, position: float) -> float:
        if len(selected_positions) == 0:
            return 999.0
        index = int(np.searchsorted(selected_positions, float(position)))
        deltas = []
        if index < len(selected_positions):
            deltas.append(abs(float(selected_positions[index]) - float(position)))
        if index > 0:
            deltas.append(abs(float(selected_positions[index - 1]) - float(position)))
        return min(deltas) if deltas else 999.0

    def _candidate_gain_profile(self, candidate: dict[str, str], peaks: list[HKLPeak], context) -> np.ndarray | None:
        combined_records = [
            *self._gain_stage_records(context, GainStage.DIRECT, limit=90),
            *self._gain_stage_records(context, GainStage.OVERLAP, limit=90),
        ]
        residual_records = []
        seen_positions: set[int] = set()
        for record in sorted(
            combined_records,
            key=lambda item: float(getattr(item, "fit_quality", 0.0) or 0.0),
            reverse=True,
        ):
            key = int(round(float(record.two_theta) * 100.0))
            if key not in seen_positions:
                seen_positions.add(key)
                residual_records.append(record)
        if not residual_records:
            residual_records = self._gain_context_observed_peak_records(
                context,
                "residual_target",
                limit=120,
            )
        default_fwhm = max(float(context.get("fwhm", 0.18) or 0.18), 0.05)
        candidate_fwhm = estimate_matched_profile_fwhm(
            peaks,
            residual_records,
            default_fwhm=default_fwhm,
            tolerance=max(0.28, min(0.72, default_fwhm * 2.5)),
        )
        profile_peaks = self._gain_profile_window_peaks(peaks, context, candidate_fwhm)
        peak_signature = array_fingerprint(np.asarray(
            [(getattr(peak, 'd', 0.0), peak.two_theta, peak.intensity)
             for peak in profile_peaks], dtype=float).ravel())
        key = (
            context.get("key"),
            self._candidate_source(candidate),
            candidate.get("Entry", ""),
            peak_signature,
            round(float(candidate_fwhm), 5),
            round(float(context.get("eta", 0.0)), 4),
            len(context.get("x", [])),
        )
        cached = self._candidate_gain_profile_cache.get(key)
        if cached is not None:
            context.setdefault('_gain_profile_widths', {})[id(cached)] = candidate_fwhm
            return cached
        profile = self._profile_from_gain_peaks(
            profile_peaks,
            context["x"],
            candidate_fwhm,
            context.get("eta", 0.0),
        )
        if profile is not None:
            context.setdefault('_gain_profile_widths', {})[id(profile)] = candidate_fwhm
            self._candidate_gain_profile_cache[key] = profile
            self._trim_candidate_gain_profile_cache()
        return profile

    def _gain_profile_window_peaks(self, peaks, context, fwhm):
        """Skip distant reflections, retaining profile tails and radiation satellites."""
        x = np.asarray(context['x'], dtype=float)
        if len(x) == 0:
            return []
        instrument = context.get('instrument_profile') or self._gain_instrument_profile()
        components = instrument.radiation.components
        if instrument.radiation.mode != 'kalpha_doublet':
            components = components[:1]
        result = []
        for peak in peaks:
            centers = [float(peak.two_theta)]
            d = float(getattr(peak, 'd', 0.0))
            if d > 0.0 and components:
                primary = self._two_theta_from_d_spacing(d, components[0].wavelength_angstrom)
                if primary is not None:
                    shift = float(peak.two_theta) - primary
                    centers = [angle + shift for component in components
                               if (angle := self._two_theta_from_d_spacing(d, component.wavelength_angstrom)) is not None]
            for center in centers:
                half_window = PROFILE_WINDOW_FACTOR * max(float(fwhm), instrument_fwhm_at(instrument, center))
                if center + half_window >= x[0] and center - half_window <= x[-1]:
                    result.append(peak)
                    break
        return result

    def _profile_from_gain_peaks(self, peaks: list[HKLPeak], x: np.ndarray, fwhm: float, eta: float = 0.0) -> np.ndarray | None:
        try:
            instrument_profile = self._gain_instrument_profile()
            wavelength, include_kalpha2 = self._gain_radiation()
            x_values = np.asarray(x, dtype=float)
            if len(x_values) == 0:
                return None
            calculation_context = CalculationContext(
                wavelength=float(wavelength),
                primary_wavelength=float(wavelength),
                fwhm=max(float(fwhm), 0.01),
                two_theta_min=float(x_values[0]),
                two_theta_max=float(x_values[-1]),
                x_grid_fingerprint=(
                    len(x_values),
                    float(x_values[0]),
                    float(x_values[-1]),
                    0,
                ),
                include_kalpha2=bool(include_kalpha2),
                instrument_profile_key=instrument_profile.calculation_key(),
                profile_eta=float(eta),
            )
            profile = FinderPeakProfileBackend().calculate_with_instrument(
                peaks,
                x_values,
                calculation_context,
                instrument_profile,
            )
        except Exception:
            return None
        profile = np.asarray(profile, dtype=float)
        if len(profile) != len(x) or float(np.nanmax(profile)) <= 0:
            return None
        return profile

    def _gain_noise_floor(self, corrected: np.ndarray) -> float:
        y = np.asarray(corrected, dtype=float)
        finite = y[np.isfinite(y)]
        if not len(finite):
            return 0.0
        median = float(np.nanmedian(finite))
        mad = float(np.nanmedian(np.abs(finite - median)))
        robust_sigma = 1.4826 * mad
        return max(median + 2.7 * robust_sigma, float(np.nanpercentile(finite, 20)))

    def _gain_residual_signal_factor(
        self, target: np.ndarray, residual_target: np.ndarray, x: np.ndarray,
        *, signed_residual: np.ndarray | None = None,
    ) -> float:
        target_records = self._observed_peak_records(x, target, limit=80)
        detection_signal = residual_target
        if signed_residual is not None and np.asarray(signed_residual).shape == np.asarray(x).shape:
            detection_signal = signed_residual
        residual_records = self._observed_peak_records(x, detection_signal, limit=80, residual=True)
        if not target_records or not residual_records:
            return 0.0
        target_area = sum(max(float(record.area), 0.0) for record in target_records)
        residual_area = sum(max(float(record.area), 0.0) for record in residual_records)
        if target_area <= 0.0:
            return 0.0
        strongest_residual = max(max(float(record.area), 0.0) for record in residual_records)
        strongest_fraction = strongest_residual / target_area
        residual_fraction = residual_area / target_area
        if strongest_fraction < 0.025 and residual_fraction < 0.10:
            return 0.0
        signal = max(strongest_fraction / 0.08, residual_fraction / 0.30)
        return float(np.clip(signal ** 0.85, 0.0, 1.0))

    def _fit_nonnegative_scales(self, target: np.ndarray, profiles: list[np.ndarray], weights: np.ndarray) -> list[float]:
        target_values = np.clip(np.asarray(target, dtype=float), 0.0, None)
        result = [0.0] * len(profiles)
        usable: list[np.ndarray] = []
        usable_indices: list[int] = []
        for index, profile in enumerate(profiles):
            values = np.asarray(profile, dtype=float)
            if len(values) != len(target_values) or not np.any(np.isfinite(values)):
                continue
            values = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
            if float(np.max(values)) <= 0.0:
                continue
            usable.append(values)
            usable_indices.append(index)
        if not usable:
            return result
        fit_weights = np.clip(np.asarray(weights, dtype=float), 0.0, None)
        sqrt_weights = np.sqrt(fit_weights)
        design = np.column_stack(usable)
        try:
            scales, _residual = nnls(
                design * sqrt_weights[:, None],
                target_values * sqrt_weights,
            )
        except Exception:
            scales = np.clip(
                np.linalg.lstsq(
                    design * sqrt_weights[:, None],
                    target_values * sqrt_weights,
                    rcond=None,
                )[0],
                0.0,
                None,
            )
        for index, scale in zip(usable_indices, scales, strict=False):
            result[index] = max(0.0, float(scale))
        return result

    def _weighted_gain_error(
        self,
        target: np.ndarray,
        calculated: np.ndarray,
        weights: np.ndarray,
        excess_penalty: float = 3.0,
    ) -> float:
        residual = np.asarray(calculated, dtype=float) - np.asarray(target, dtype=float)
        asymmetric = np.where(residual > 0.0, residual * float(excess_penalty), -residual)
        weighted = asymmetric * np.clip(np.asarray(weights, dtype=float), 0.0, None)
        return float(np.trapezoid(weighted, dx=1.0))

    def _scaled_profile_sum(self, profiles: list[np.ndarray], scales: list[float], target: np.ndarray) -> np.ndarray:
        if not profiles or not scales:
            return np.zeros_like(target, dtype=float)
        total = np.zeros_like(target, dtype=float)
        for profile, scale in zip(profiles, scales, strict=False):
            total += np.asarray(profile, dtype=float) * float(scale)
        return total

    def _weighted_integral_area(self, target: np.ndarray, weights: np.ndarray) -> float:
        weighted = np.asarray(target, dtype=float) * np.clip(np.asarray(weights, dtype=float), 0.0, None)
        return float(np.trapezoid(weighted, dx=1.0))

    def _estimate_background(self, x, y, degree: int = 10, method: str = "auto") -> np.ndarray:
        return estimate_background(x, y, degree=degree, method=method)

    def _gain_context_observed_peak_records(
        self,
        context,
        signal: str,
        *,
        limit: int,
    ) -> list[ObservedLineRecord]:
        cache = context.setdefault("_gain_observed_peak_records_cache", {})
        cache_key = (str(signal), int(limit))
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        x = np.asarray(context.get("x", []), dtype=float)
        y = np.asarray(context.get(signal, []), dtype=float)
        residual_signal = signal in {"residual_target", "difference_curve"}
        if residual_signal:
            signed = np.asarray(context.get("difference_curve", []), dtype=float)
            if signed.shape == x.shape:
                y = signed
        if len(x) == 0 or len(y) != len(x):
            records: list[ObservedLineRecord] = []
        else:
            records = self._observed_peak_records(x, y, limit=limit, residual=residual_signal)
        cache[cache_key] = records
        return records

    def _gain_multichannel_profile_indices(
        self,
        rows: list[list[str]],
        preliminary_gains: dict[int, float],
        residual_records: list[ObservedLineRecord],
        overlap_records: list[ObservedLineRecord],
        context,
    ) -> list[int]:
        """Protect the Quick prefix and use spare verification slots for rescue."""

        references: dict[str, tuple[HKLPeak, ...]] = {}
        primary_scores: dict[str, float] = {}
        aligned_cache = context.get("_gain_aligned_peaks_cache", {})
        duplicate_cache = context.get("_gain_selected_pattern_duplicate_cache", {})
        for row_index, row in enumerate(rows):
            candidate = {
                "Source": row[0] if len(row) > 0 else "",
                "Entry": row[1] if len(row) > 1 else "",
                "Formula": row[2] if len(row) > 2 else "",
                "Phase": row[3] if len(row) > 3 else "",
            }
            candidate_key = self._candidate_key(candidate)
            if bool(duplicate_cache.get(candidate_key, False)):
                continue
            peaks = tuple(aligned_cache.get(candidate_key, ()))
            if not peaks:
                continue
            phase_id = str(row_index)
            references[phase_id] = peaks
            score = float(preliminary_gains.get(row_index, 0.0) or 0.0)
            if score > 0.0:
                primary_scores[phase_id] = score
        if not references:
            return []

        candidate_count = len(references)
        channel_limits = (
            ("strong", min(40, candidate_count)),
            ("rare", min(16, candidate_count)),
        )
        zero_shift = common_zero_shift(self.match_zero_shifts.values())
        if "peak_search" in context:
            # Only the six rescue slots use the peak-center check. Preserve
            # primary scores and the conservative evidence for displayed Gain.
            residual_records, overlap_records = gain_peak_retrieval_records(context["peak_search"])
        pool = build_production_gain_retrieval_pool(
            references,
            primary_scores,
            residual_records,
            overlap_records,
            config=GainRetrievalConfig(
                channel_limits=channel_limits,
                union_limit=min(56, candidate_count),
                profile_limit=min(GAIN_PROFILE_CANDIDATE_LIMIT, candidate_count),
                primary_reserve=min(18, candidate_count),
            ),
            wavelength=self._active_wavelength(),
            zero_shift=zero_shift,
        )
        context["_gain_retrieval_pool"] = pool
        selected = [
            int(phase_id)
            for phase_id in pool.optional_ids
            if str(phase_id).isdigit() and int(phase_id) < len(rows)
        ]
        if len(selected) < min(GAIN_PROFILE_CANDIDATE_LIMIT, candidate_count):
            for row_index in select_profile_candidate_indices(preliminary_gains):
                if row_index not in selected:
                    selected.append(row_index)
                if len(selected) >= GAIN_PROFILE_CANDIDATE_LIMIT:
                    break
        return selected[:GAIN_PROFILE_CANDIDATE_LIMIT]

    def _candidate_profile_gain_context(self):
        selected_candidates = list(self.match_candidates or [])
        accepted_fit = self._gain_accepted_profile_snapshot()
        observed, finder_background, finder_observed, background_removed = self._gain_observation()
        if accepted_fit is None and (observed is None or not len(observed)):
            self._last_gain_debug = "Gain: no observed data"
            return None
        try:
            self._gain_check_cancelled()
            if accepted_fit is not None:
                x, target, accepted_profiles = accepted_fit
                corrected = target
                noise_floor = 0.
            else:
                if finder_background is not None and finder_observed is not None and len(finder_observed):
                    x = np.asarray(finder_observed[:, 0], dtype=float)
                    y = np.asarray(finder_observed[:, 1], dtype=float)
                    background_x = np.asarray(finder_background[:, 0], dtype=float)
                    background_y = np.asarray(finder_background[:, 1], dtype=float)
                    background = np.interp(x, background_x, background_y, left=float(background_y[0]), right=float(background_y[-1]))
                    corrected = np.clip(y - background, 0.0, None)
                else:
                    x = np.asarray(observed[:, 0], dtype=float)
                    y = np.asarray(observed[:, 1], dtype=float)
                if finder_background is None and (
                    getattr(self, "_scoring_source", "Auto") == "Auto"
                    or background_removed
                ):
                    corrected = np.clip(y, 0.0, None)
                elif finder_background is None:
                    background = self._estimate_background(x, y)
                    corrected = np.clip(y - background, 0.0, None)
                if len(corrected) == 0 or float(np.nanmax(corrected)) <= 0:
                    self._last_gain_debug = "Gain: corrected profile is empty"
                    return None
                noise_floor = self._gain_noise_floor(corrected)
                target = np.clip(corrected - noise_floor, 0.0, None)
            if float(np.nanmax(target)) <= 0:
                self._last_gain_debug = f"Gain: target empty, noise floor {noise_floor:.4g}"
                return None
            self._prepare_observed_peak_reuse(x, target)
            fwhm = float(getattr(self, "_last_match_profile_fwhm", 0.0) or self._estimate_profile_fwhm(x, corrected))
            eta = float(getattr(self, "_last_match_profile_eta", 0.0) or 0.0)
            try:
                instrument_profile = self._gain_instrument_profile()
            except Exception:
                instrument_profile = None
            weights = self._fit_weights(target)
            selected_profiles = []
            selected_peak_positions = []
            selected_phase_patterns_raw = []
            selected_phase_patterns = []
            selected_width_models = []
            self._gain_stage_progress("Detecting observed peaks...")
            target_peak_records = self._observed_peak_records(x, target, limit=160)
            self._gain_stage_progress("Refining observed peaks...")
            target_peak_records = self._refine_records_on_signed_signal(
                x,
                target,
                target_peak_records,
                instrument_profile=instrument_profile,
                expected_fwhm=max(fwhm, 0.04),
            )
            for phase_index, candidate in enumerate(selected_candidates):
                self._gain_check_cancelled()
                self._gain_stage_progress("Building accepted phase profiles...")
                raw_peaks = self._candidate_peaks_for_gain(candidate)
                if raw_peaks:
                    selected_phase_patterns_raw.append(tuple(raw_peaks))
                peaks = self._adjusted_gain_peaks(candidate, raw_peaks)
                if peaks:
                    selected_phase_patterns.append(tuple(peaks))
                phase_fwhm = estimate_matched_profile_fwhm(
                    peaks,
                    target_peak_records,
                    default_fwhm=fwhm,
                    tolerance=max(0.28, min(0.72, fwhm * 2.5)),
                )
                phase_width_records = match_clean_phase_records(
                    peaks,
                    target_peak_records,
                    tolerance=max(0.18, min(0.48, fwhm * 1.8)),
                )
                phase_width_model = fit_phase_width_model(phase_width_records)
                if phase_width_model is not None:
                    selected_width_models.append(
                        {
                            "model": phase_width_model,
                            "positions": np.asarray(
                                [
                                    float(getattr(peak, "two_theta", 0.0) or 0.0)
                                    for peak in peaks
                                    if float(getattr(peak, "intensity", 0.0) or 0.0) >= 3.0
                                ],
                                dtype=float,
                            ),
                        }
                    )
                profile = (accepted_profiles[phase_index] if accepted_fit is not None else
                           self._profile_from_gain_peaks(peaks, x, phase_fwhm, eta) if peaks else None)
                if profile is not None:
                    selected_profiles.append(profile)
                    selected_peak_positions.extend(
                        float(getattr(peak, "two_theta", 0.0))
                        for peak in peaks
                        if float(getattr(peak, "intensity", 0.0) or 0.0) >= 1.0
                    )
            if selected_candidates and not selected_profiles:
                self._last_gain_debug = "Gain: no selected phase profiles"
                return None
            if accepted_fit is not None:
                selected_total = np.sum(accepted_profiles, axis=0)
            else:
                selected_scales = self._fit_nonnegative_scales(target, selected_profiles, weights)
                selected_total = self._scaled_profile_sum(selected_profiles, selected_scales, target)
            difference_curve = target - selected_total
            self._gain_stage_progress("Extracting unexplained peak signal...")
            residual_target = self._gain_residual_target(difference_curve, x, fwhm)
            residual_weights = self._fit_weights(residual_target) if float(np.nanmax(residual_target)) > 0 else weights
            before_error = self._weighted_gain_error(residual_target, np.zeros_like(residual_target), residual_weights)
            residual_area = self._weighted_integral_area(residual_target, residual_weights)
            target_area = self._weighted_integral_area(target, weights)
            residual_share = residual_area / max(target_area, 1.0e-12)
            before_fit = self._corrected_profile_fit_quality(target, selected_total)
            self._gain_stage_progress("Checking residual peak significance...")
            residual_signal = self._gain_residual_signal_factor(target, residual_target, x)
            if residual_signal <= 0.0:
                residual_max = float(np.nanmax(residual_target)) if len(residual_target) else 0.0
                self._last_gain_debug = f"Gain: residual below background, max {residual_max:.4g}"
                return None
            if residual_area <= 0:
                residual_max = float(np.nanmax(residual_target)) if len(residual_target) else 0.0
                self._last_gain_debug = f"Gain: residual empty, max {residual_max:.4g}"
                return None
            physical_positions = self._gain_accepted_peak_positions()
            return {
                "key": self._gain_context_key(),
                "x": x,
                "target": target,
                "weights": residual_weights,
                "target_weights": weights,
                "fwhm": fwhm,
                "eta": eta,
                "instrument_profile": instrument_profile,
                "selected_profiles": selected_profiles,
                "selected_mass_profiles": self._gain_mass_profile_snapshot(),
                "selected_phase_patterns_raw": selected_phase_patterns_raw,
                "selected_phase_patterns": selected_phase_patterns,
                "selected_width_models": selected_width_models,
                "selected_total": selected_total,
                "selected_peak_positions": (np.asarray(selected_peak_positions, dtype=float)
                                            if physical_positions is None else physical_positions),
                "difference_curve": difference_curve,
                "residual_target": residual_target,
                "before_error": before_error,
                "before_fit": before_fit,
                "residual_area": residual_area,
                "target_area": target_area,
                "residual_share": residual_share,
                "residual_signal": residual_signal,
            }
        except GainJobCancelled:
            raise
        except Exception:
            import traceback
            self._last_gain_debug = "Gain: context exception"
            print("Gain context exception:", traceback.format_exc(), flush=True)
            return None


class GainComputation(GainLineMixin, GainCalculationMixin):
    """A calculation context made solely from owned data, never a window."""

    def __init__(self, inputs: GainJobInput, cancelled: Callable[[], bool], progress=None):
        from xrd_finder.finder.service import FinderService
        from xrd_finder.services.local_phase_cache import LocalPhaseCache
        from xrd_finder.services.calculated_pattern_service import CalculatedPatternService
        from xrd_finder.services.match_pdf2_service import MatchPdf2Service
        from xrd_finder.ui.candidate_line_provider import CandidateLineProvider

        self._cancelled = cancelled
        self._progress = progress
        if (inputs.accepted_fit_x is None and inputs.preprocess_auto
                and inputs.observed is not None and len(inputs.observed)):
            from dataclasses import replace
            from xrd_finder.services.preprocessing_service import auto_preprocess_for_scoring
            if cancelled():
                raise GainJobCancelled()
            self._gain_stage_progress("Preparing scoring signal and background...")
            prepared = auto_preprocess_for_scoring(inputs.observed[:, 0], inputs.observed[:, 1])
            inputs = replace(inputs, observed=np.column_stack((prepared.x, prepared.corrected_y)),
                             finder_observed=np.column_stack((prepared.x, prepared.y)), preprocess_auto=False)
        self.inputs = inputs
        self._cancelled = cancelled
        self.match_candidates = deepcopy(inputs.candidates)
        self.match_zero_shifts = dict(inputs.zero_shifts)
        self.match_cell_scales = dict(inputs.cell_scales)
        self._last_match_profile_fwhm = inputs.profile_fwhm
        self._last_match_profile_eta = inputs.profile_eta
        self._scoring_source = inputs.scoring_source
        self._candidate_gain_auto_enabled = True
        self._gain_overlap_locked = inputs.gain_overlap_locked
        self._candidate_hidden_match_by_key = dict(inputs.hidden_matches)
        self._candidate_gain_profile_cache = {}
        self._candidate_peak_cache = {}
        self._residual_peak_fit_cache = {}
        self._observed_reuse_key = None
        self._observed_signal_key = None
        self._candidate_json_peak_cache = {}
        self._observed_probability_cache = None
        self._last_gain_debug = ""
        self._gain_status_text = ""
        self._structures = deepcopy(inputs.project_structures)
        self.local_phase_cache = LocalPhaseCache.read_only(inputs.cache_root) if inputs.cache_root else None
        self.candidate_search_service = CandidateRowFormatter(self.local_phase_cache)
        self.candidate_line_provider = CandidateLineProvider(self.local_phase_cache) if self.local_phase_cache else None
        self.finder_service = FinderService()
        self.calculated_pattern_service = CalculatedPatternService()
        self.match_pdf2 = MatchPdf2Service(inputs.pdf2_root, initialize_index=False) if inputs.pdf2_root else None

    def _candidate_peaks_for_gain(self, candidate):
        # A job owns immutable scientific inputs. Reuse converted native lines
        # across context construction, scoring and acceptance-evidence export.
        cache = getattr(self, '_resolved_gain_lines', None)
        if cache is None:
            cache = self._resolved_gain_lines = {}
        key = self._candidate_key(candidate)
        if key not in cache:
            cache[key] = super()._candidate_peaks_for_gain(candidate)
        return cache[key]

    def _gain_check_cancelled(self):
        if self._cancelled():
            raise GainJobCancelled()

    def _gain_peak_refiner(self):
        return self._cached_refine_residual_peak

    def _prepare_observed_peak_reuse(self, x, target):
        def signature(values):
            if values is None:
                return None
            array = np.asarray(values, dtype=float)
            return array.shape, array_fingerprint(array.ravel())

        inputs = self.inputs
        signal = (array_fingerprint(x), array_fingerprint(target))
        key = (inputs.observed_cache_scope, signature(inputs.observed),
               signature(inputs.finder_observed), signature(inputs.background),
               inputs.instrument_profile.calculation_key(), float(inputs.wavelength),
               bool(inputs.include_kalpha2), inputs.scoring_source,
               bool(inputs.background_removed), bool(inputs.preprocess_auto), signal)
        self._observed_reuse_key = key
        self._observed_signal_key = signal
        snapshot = inputs.observed_peak_cache
        if snapshot is not None and snapshot.key == key:
            entries = [(k, v) for k, v in snapshot.refined_peaks.items() if k[:2] == signal]
            self._residual_peak_fit_cache.update(entries[-GAIN_PEAK_FIT_CACHE_LIMIT:])

    def _export_observed_peak_reuse(self):
        if self._observed_reuse_key is None:
            return None
        # Never carry a previous accepted-phase residual into another job.
        entries = {k: v for k, v in self._residual_peak_fit_cache.items()
                   if k[:2] == self._observed_signal_key}
        return GainObservedPeakCache(self._observed_reuse_key, entries)

    def _cached_refine_residual_peak(self, x, signal, seed, *, expected_fwhm,
                                    instrument_fwhm=0., satellite_offsets_weights=(),
                                    constrain_center=True, enforce_instrument_floor=True):
        self._gain_check_cancelled()
        key = (array_fingerprint(x), array_fingerprint(signal), float(seed),
               float(expected_fwhm), float(instrument_fwhm), tuple(satellite_offsets_weights),
               bool(constrain_center), bool(enforce_instrument_floor))
        cache = self._residual_peak_fit_cache
        if key in cache:
            return cache[key]
        result = refine_residual_peak(
            x, signal, seed, expected_fwhm=expected_fwhm, instrument_fwhm=instrument_fwhm,
            satellite_offsets_weights=satellite_offsets_weights,
            constrain_center=constrain_center, enforce_instrument_floor=enforce_instrument_floor)
        if len(cache) >= GAIN_PEAK_FIT_CACHE_LIMIT:
            cache.pop(next(iter(cache)))
        cache[key] = result
        return result

    def _gain_stage_progress(self, text):
        self._gain_check_cancelled()
        if self._progress:
            self._progress(text, 0, 0)

    def _candidate_source(self, candidate):
        return candidate.get("Source", "") or candidate.get("Qual.", "")

    def _candidate_key(self, candidate):
        return f"{self._candidate_source(candidate)}:{candidate.get('Entry', '')}"

    def _gain_instrument_profile(self):
        return self.inputs.instrument_profile

    def _gain_radiation(self):
        return self.inputs.wavelength, self.inputs.include_kalpha2

    def _active_wavelength(self):
        return self.inputs.wavelength

    def _gain_observation(self):
        return self.inputs.observed, self.inputs.background, self.inputs.finder_observed, self.inputs.background_removed

    def _gain_accepted_profile_snapshot(self):
        if self.inputs.accepted_fit_x is None:
            return None
        return self.inputs.accepted_fit_x, self.inputs.accepted_fit_target, self.inputs.accepted_fit_profiles

    def _gain_mass_profile_snapshot(self):
        return self.inputs.accepted_fit_mass_profiles

    def _gain_accepted_peak_positions(self):
        return self.inputs.accepted_fit_peak_positions

    def _gain_context_key(self):
        return self.inputs.context_key

    def _gain_search_options(self):
        return self.inputs

    def _rank_by_peak_probability_enabled(self):
        return True

    def _scoring_source_status_text(self):
        return f"Score: {self._scoring_source}"

    def _gain_line_locations(self):
        return self.inputs.embedded_paths, self.inputs.project_phases

    def _gain_structure_override(self, candidate):
        phases = [phase for phase in self.inputs.project_phases if phase.id in self.inputs.linked_phase_ids]
        if not phases:
            return None
        phase = next((phase for phase in phases if self._candidate_source(candidate) == "USER"
                      and phase.id == candidate.get("Entry")), None)
        path = self._candidate_local_cif_path(candidate)
        if phase is None and path is not None:
            phase = next((phase for phase in reversed(phases) if phase.source_path
                          and str(Path(phase.source_path).resolve()).lower() == str(path.resolve()).lower()), None)
        if phase is None:
            name = candidate.get("_DisplayName") or candidate.get("Phase") or candidate.get("Candidate phase", "")
            phase = next((phase for phase in reversed(phases)
                          if (str(phase.name or "").casefold(), str(phase.formula or "").casefold())
                          == (name.casefold(), candidate.get("Formula", "").casefold())), None)
        if phase is None:
            return None
        return next((structure for structure in self._structures if structure.id == phase.structure_id), None) or next(
            (structure for structure in self._structures if structure.phase_id == phase.id), None)

    def _probability_observed_data(self):
        if self._observed_probability_cache is not None:
            return self._observed_probability_cache
        data = (np.column_stack((self.inputs.accepted_fit_x, self.inputs.accepted_fit_target))
                if self.inputs.accepted_fit_x is not None else self.inputs.observed)
        if data is None or not len(data):
            return None
        if self.inputs.accepted_fit_x is not None or self.inputs.scoring_source == "Auto" or self.inputs.background_removed:
            corrected = np.asarray(data[:, 1], dtype=float)
        else:
            corrected = np.asarray(data[:, 1], dtype=float) - self._estimate_background(data[:, 0], data[:, 1])
        records = self._observed_peak_records(data[:, 0], corrected, limit=80)
        self._observed_probability_cache = (np.asarray(data[:, 0], dtype=float), corrected, records)
        return self._observed_probability_cache


def run_gain_job(inputs: GainJobInput, *, progress=None, cancelled=lambda: False, references_prepared=False) -> GainJobResult:
    try:
        if inputs.cache_root and not references_prepared:
            from xrd_finder.services.reference_preparation import prepare_gain_references
            prepare_gain_references(inputs, progress=progress, cancelled=cancelled)
        calculation = GainComputation(inputs, cancelled, progress=progress)
        calculation._gain_check_cancelled()
        if progress:
            progress("Preparing Gain residual...", 0, 0)
        context = calculation._candidate_gain_context()
        calculation._gain_check_cancelled()
        if context is None:
            debug = calculation._last_gain_debug
            if debug in {"Gain: context exception", "Gain: no selected phase profiles"}:
                raise RuntimeError(debug)
            rows = [normalize_candidate_row(list(row)) for row in inputs.rows[:120]]
            for row in rows:
                row[6] = ""
            return GainJobResult(
                calculation.candidate_search_service.dedupe_candidate_rows(rows),
                f"{calculation._scoring_source_status_text()} | {debug}", debug,
                calculation._candidate_hidden_match_by_key,
                observed_peak_cache=calculation._export_observed_peak_reuse(),
            )
        rows = []
        if context is not None and inputs.cache_root:
            calculation._gain_stage_progress("Searching local residual candidates...")
            rows.extend(calculation._gain_sql_candidate_rows(stage="combined", context=context))
        rows.extend(deepcopy(inputs.rows[:120]))
        for row in rows:
            row[:] = normalize_candidate_row(row)
            row[6] = ""
        rows = calculation.candidate_search_service.dedupe_candidate_rows(rows)
        calculation._gain_check_cancelled()

        def report(value, maximum):
            if progress:
                progress("Updating Gain...", value, maximum)

        ranked = calculation._rank_candidate_rows_by_peak_probability(
            rows, force=True, progress=report, gain_context=context)
        calculation._gain_check_cancelled()
        indexed_evidence = {}
        scored_rows = [row for row in ranked if str(row[6]).strip()]
        if scored_rows:
            calculation._gain_stage_progress("Saving phase acceptance matches...")
            # Preserve the stage chosen by the previous fresh-context acceptance
            # path, rather than changing cell refinement to a different Gain stage.
            stage = GainStage(calculation._gain_stage_for_context(context))
            records = calculation._gain_stage_records(context, str(stage), limit=90)
            for row in scored_rows:
                calculation._gain_check_cancelled()
                candidate = dict(zip(("Source", "Entry", "Formula", "Phase"), row))
                peaks = calculation._candidate_peaks_for_gain(candidate)
                peaks = calculation._aligned_candidate_gain_peaks(candidate, peaks, context)
                peaks = _gain_scan_peaks(peaks, context)
                indexed_evidence[calculation._candidate_key(candidate)] = build_gain_indexed_evidence(
                    peaks=peaks, records=records, stage=stage, base_fwhm=context["fwhm"])
        return GainJobResult(
            ranked, calculation._gain_status_text, calculation._last_gain_debug,
            calculation._candidate_hidden_match_by_key,
            {name: (context or {}).get(name, {}) for name in (
                "_gain_combined_evidence_cache", "_gain_profile_support_by_key",
                "_gain_dominant_evidence_by_key", "_gain_suppressed_duplicate_patterns",
                "_gain_cell_refinement_by_key", "_gain_joint_by_key",
                "_gain_peak_candidate_scores")},
            indexed_evidence=indexed_evidence,
            observed_peak_cache=calculation._export_observed_peak_reuse(),
        )
    except (GainJobCancelled, CancelledError):
        return GainJobResult([], cancelled=True)
