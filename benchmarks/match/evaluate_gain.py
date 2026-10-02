from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import argparse
import csv
from concurrent.futures import ProcessPoolExecutor
import math
import json
from pathlib import Path
import time
from collections.abc import Mapping, Sequence
from types import SimpleNamespace

import numpy as np
from scipy.optimize import nnls

from benchmarks.match.generate_profiles import (
    ReferenceLine,
    _detect_observed_records,
    _fit_reciprocal_metric,
    benchmark_instrument_fwhm,
    generate_profile,
)
from benchmarks.match.gain_scenarios import GainScenarioConfig, build_gain_scenario_manifest
from benchmarks.match.gain_retrieval import (
    adaptive_gain_shortlist,
    dominant_line_gain_shortlist,
    dual_score_gain_shortlist,
    fused_line_gain_shortlist,
    hybrid_gain_shortlist,
    rare_line_gain_shortlist,
)
from benchmarks.match.joint_gain import (
    build_joint_candidate_pool,
    evaluate_joint_gain,
    prefilter_joint_profile_ids,
    select_informative_residual_peaks,
)
from benchmarks.match.scenarios import ScenarioDefinition
from benchmarks.match.dataset import BenchmarkDataset
from benchmarks.match.scenarios import ScenarioConfig, build_scenario_manifest
from benchmarks.match.splits import assign_split_families
from xrd_finder.finder.fingerprint_matching import fingerprint_match_score
from xrd_finder.finder.cell_parameter_estimator import FastCellParameterEstimator
from xrd_finder.finder.models import ObservedPeak
from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY, GainPolicy, GainStage
from xrd_finder.finder.gain_evidence import phase_signal_to_noise
from xrd_finder.finder.gain_ranking import GainCandidate, GainQuery, rank_gain_candidates
from xrd_finder.finder.joint_phase_search import JointPhaseSearchConfig
from xrd_finder.services.calculated_pattern_service import HKLPeak, pseudo_voigt_values
from xrd_finder.services.gain_shortlist import estimate_matched_profile_fwhm
from xrd_finder.services.phase_pattern_equivalence import (
    compare_phase_patterns,
    phase_patterns_equivalent,
)


def _ranked_family_position(
    ranked_families: Sequence[str],
    target_family: str,
    *,
    candidate_count: int,
) -> int:
    if target_family in ranked_families:
        return ranked_families.index(target_family) + 1
    return max(int(candidate_count), len(ranked_families)) + 1
from xrd_finder.ui.gain_scoring import fit_residual_candidate_scale, profile_residual_gain


@dataclass(frozen=True, slots=True)
class GainScenarioResult:
    query_id: str
    split: str
    scenario_mode: str
    accepted_phase_id: str
    target_phase_id: str
    target_family: str
    target_retrieval_rank: int
    target_rank: int
    dominant_evidence: GainStage
    limited_residual: bool
    candidate_count: int
    shortlist_count: int
    before_fit: float
    residual_share: float
    target_in_shortlist: bool
    global_zero_shift: float
    true_zero_shift: float
    accepted_fwhm: float
    target_fwhm: float
    target_true_fwhm: float
    target_direct_gain: float
    target_overlap_gain: float
    target_direct_matches: int
    target_direct_coverage: float
    target_direct_reliability: float
    target_profile_gain: float
    target_phase_snr: float
    target_gain: float
    top_candidate_id: str
    top_candidate_family: str
    top_direct_matches: int
    top_direct_coverage: float
    top_direct_reliability: float
    top_direct_gain: float
    top_overlap_gain: float
    top_hidden_gain: float
    top_profile_gain: float
    top_phase_snr: float
    match_dominant_rank: int
    accepted_family_correct: bool
    elapsed_seconds: float
    gain_engine: str = "greedy"
    retrieval_seconds: float = 0.0
    profile_seconds: float = 0.0
    search_seconds: float = 0.0
    evaluated_combinations: int = 0
    best_combination: tuple[str, ...] = ()
    ranked_candidate_ids: tuple[str, ...] = ()
    ranked_families: tuple[str, ...] = ()
    suppressed_candidate_count: int = 0
    full_set_recovered: bool = False
    false_positive_families: int = 0
    variant_group: str = ""
    variant_kind: str = ""


class IndistinguishableGainScenario(ValueError):
    """The accepted pattern already represents every synthetic component."""


def _gain_candidate_ids(
    references: Mapping[str, Sequence[ReferenceLine]],
    accepted_phase_id: str | Sequence[str],
    *,
    fwhm: float,
) -> tuple[str, ...]:
    """Exclude cards whose aligned peak pattern duplicates the accepted one."""

    accepted_ids = (
        (accepted_phase_id,)
        if isinstance(accepted_phase_id, str)
        else tuple(accepted_phase_id)
    )
    return tuple(
        sorted(
            phase_id
            for phase_id in references
            if phase_id not in accepted_ids
            and not any(
                phase_patterns_equivalent(
                    references[selected_id],
                    references[phase_id],
                    fwhm=fwhm,
                )
                for selected_id in accepted_ids
            )
        )
    )


def evaluate_gain_scenario(
    references: Mapping[str, Sequence[ReferenceLine]],
    family_by_phase: Mapping[str, str],
    scenario: ScenarioDefinition,
    *,
    shortlist_limit: int = 100,
    policy: GainPolicy = DEFAULT_GAIN_POLICY,
    shortlist_strategy: str = "quick",
    instrument_data: bool = False,
    instrument_model: bool = False,
    accepted_from_match: bool = False,
    accepted_phase_ids: Sequence[str] | None = None,
    gain_engine: str = "greedy",
    joint_config: JointPhaseSearchConfig | None = None,
    joint_profile_mode: str = "full",
) -> GainScenarioResult:
    started = time.perf_counter()
    if gain_engine not in {"greedy", "joint-beam"}:
        raise ValueError(f"Unsupported Gain engine: {gain_engine}")
    if joint_profile_mode not in {"full", "peak-windows"}:
        raise ValueError(f"Unsupported joint profile mode: {joint_profile_mode}")
    if len(scenario.components) < 2:
        raise ValueError("Gain evaluation requires at least two phases.")
    generated = generate_profile(
        references,
        scenario,
        instrument_resolution=instrument_data,
    )
    dominant = max(scenario.components, key=lambda item: item.fraction)
    if accepted_phase_ids:
        component_by_id = {item.phase_id: item for item in scenario.components}
        accepted_components = tuple(component_by_id[item] for item in accepted_phase_ids)
        accepted = accepted_components[0]
        match_dominant_rank = 1
    elif accepted_from_match:
        accepted_phase_id, match_dominant_rank = _select_match_candidate(
            references,
            family_by_phase,
            generated.observed_records,
            dominant.family_id,
        )
        accepted = SimpleNamespace(
            phase_id=accepted_phase_id,
            family_id=family_by_phase[accepted_phase_id],
            fraction=0.0,
        )
        accepted_components = (accepted,)
    else:
        accepted = dominant
        accepted_components = (accepted,)
        match_dominant_rank = 1
    accepted_true_families = set()
    for selected in accepted_components:
        accepted_true_families.update(
            component.family_id
            for component in scenario.components
            if component.family_id == selected.family_id
            or phase_patterns_equivalent(
                references[selected.phase_id],
                references[component.phase_id],
                fwhm=0.18,
            )
        )
    accepted_family_correct = bool(accepted_true_families)
    remaining = sorted(
        (
            item
            for item in scenario.components
            if item.family_id not in accepted_true_families
        ),
        key=lambda item: item.fraction,
        reverse=True,
    )
    if not remaining:
        raise IndistinguishableGainScenario(
            f"{scenario.scenario_id} has no diffraction-distinct component after accepting "
            f"{accepted.phase_id}"
        )
    target_component = remaining[0]
    target = np.clip(generated.y - generated.background, 0.0, None)
    accepted_alignment = fingerprint_match_score(
        references[accepted.phase_id],
        list(generated.observed_records),
        wavelength=1.5406,
        refine_alignment=True,
    )
    accepted_cell = _estimate_candidate_cell(
        references[accepted.phase_id],
        generated.observed_records,
        initial_zero_shift=float(accepted_alignment.zero_shift),
        refine_zero_shift=True,
    )
    global_zero_shift = float(
        accepted_cell.zero_shift_deg if accepted_cell is not None else accepted_alignment.zero_shift
    )
    accepted_profiles = []
    selected_positions_list = []
    accepted_widths = []
    for selected in accepted_components:
        alignment = (
            accepted_alignment
            if selected.phase_id == accepted.phase_id
            else fingerprint_match_score(
                references[selected.phase_id],
                list(generated.observed_records),
                wavelength=1.5406,
                refine_alignment=True,
                fixed_zero_shift=global_zero_shift,
            )
        )
        cell = (
            accepted_cell
            if selected.phase_id == accepted.phase_id
            else _estimate_candidate_cell(
                references[selected.phase_id],
                generated.observed_records,
                initial_zero_shift=global_zero_shift,
                refine_zero_shift=False,
            )
        )
        lines = _aligned_reference_lines(
            references[selected.phase_id],
            cell=None if cell is None else cell.cell,
            position_scale=alignment.position_scale,
            zero_shift=global_zero_shift,
        )
        width = estimate_matched_profile_fwhm(
            lines,
            generated.observed_records,
            default_fwhm=alignment.profile_fwhm,
            tolerance=0.55,
        )
        accepted_widths.append(width)
        accepted_profiles.append(
            _candidate_profile(
                generated.x,
                lines,
                width,
                1.0,
                0.0,
                instrument_floor=instrument_model,
            )
        )
        selected_positions_list.extend(_aligned_positions(lines, 1.0, 0.0))
    accepted_fwhm = float(np.median(accepted_widths))
    accepted_scales = _joint_nonnegative_scales(target, accepted_profiles)
    selected_total = sum(
        (profile * scale for profile, scale in zip(accepted_profiles, accepted_scales, strict=True)),
        np.zeros_like(target),
    )
    residual = np.clip(target - selected_total, 0.0, None)
    residual_records = tuple(
        _detect_observed_records(
            generated.x,
            residual,
            limit=80,
            distance_scale=1.0,
        )
    )
    selected_positions = np.asarray(sorted(selected_positions_list), dtype=float)
    direct_records, overlap_records = _partition_residual_records(
        residual_records,
        selected_positions,
        accepted_fwhm,
    )
    direct_count = len(direct_records)
    overlap_count = len(overlap_records)
    target_area = float(np.trapezoid(target))
    residual_area = float(np.trapezoid(residual))
    residual_share = residual_area / max(target_area, 1.0e-12)
    before_fit = float(np.clip(100.0 * (1.0 - residual_share), 0.0, 100.0))

    retrieval_started = time.perf_counter()
    candidate_ids = _gain_candidate_ids(
        references,
        tuple(item.phase_id for item in accepted_components),
        fwhm=accepted_fwhm,
    )
    quick_records = (
        select_informative_residual_peaks(residual_records, limit=12)
        if gain_engine == "joint-beam" and joint_profile_mode == "peak-windows"
        else residual_records
    )
    quick = {
        candidate_id: fingerprint_match_score(
            references[candidate_id],
            list(quick_records),
            wavelength=1.5406,
            refine_alignment=False,
        )
        for candidate_id in candidate_ids
    }
    retrieval_families = []
    for candidate_id in sorted(candidate_ids, key=lambda key: (-quick[key].score, key)):
        family = family_by_phase[candidate_id]
        if family not in retrieval_families:
            retrieval_families.append(family)
    target_retrieval_rank = (
        retrieval_families.index(target_component.family_id) + 1
        if target_component.family_id in retrieval_families
        else len(retrieval_families) + 1
    )
    if gain_engine == "joint-beam":
        return _evaluate_joint_gain_scenario(
            references=references,
            family_by_phase=family_by_phase,
            scenario=scenario,
            generated=generated,
            accepted=accepted,
            accepted_components=accepted_components,
            accepted_profiles=tuple(accepted_profiles),
            target_component=target_component,
            target=target,
            selected_total=selected_total,
            residual=residual,
            residual_records=residual_records,
            direct_records=direct_records,
            overlap_records=overlap_records,
            quick=quick,
            candidate_ids=candidate_ids,
            global_zero_shift=global_zero_shift,
            accepted_fwhm=accepted_fwhm,
            before_fit=before_fit,
            residual_share=residual_share,
            target_retrieval_rank=target_retrieval_rank,
            shortlist_limit=shortlist_limit,
            policy=policy,
            instrument_model=instrument_model,
            match_dominant_rank=match_dominant_rank,
            accepted_family_correct=accepted_family_correct,
            joint_config=joint_config,
            joint_profile_mode=joint_profile_mode,
            started=started,
        )
    if shortlist_strategy == "adaptive":
        shortlist = adaptive_gain_shortlist(
            {candidate_id: references[candidate_id] for candidate_id in candidate_ids},
            residual_records,
            quick,
            limit=shortlist_limit,
        )
    elif shortlist_strategy == "hybrid":
        shortlist = hybrid_gain_shortlist(
            {candidate_id: references[candidate_id] for candidate_id in candidate_ids},
            residual_records,
            quick,
            limit=shortlist_limit,
        )
    elif shortlist_strategy == "fusion":
        shortlist = fused_line_gain_shortlist(
            {candidate_id: references[candidate_id] for candidate_id in candidate_ids},
            residual_records,
            quick,
            limit=shortlist_limit,
        )
    elif shortlist_strategy == "rare":
        shortlist = rare_line_gain_shortlist(
            {candidate_id: references[candidate_id] for candidate_id in candidate_ids},
            residual_records,
            quick,
            limit=shortlist_limit,
        )
    elif shortlist_strategy == "dominant":
        shortlist = dominant_line_gain_shortlist(
            {candidate_id: references[candidate_id] for candidate_id in candidate_ids},
            residual_records,
            quick,
            limit=shortlist_limit,
        )
    elif shortlist_strategy == "dominant-expand":
        shortlist = dominant_line_gain_shortlist(
            {candidate_id: references[candidate_id] for candidate_id in candidate_ids},
            residual_records,
            quick,
            limit=shortlist_limit,
            extra_limit=max(4, int(round(shortlist_limit * 0.20))),
        )
    elif shortlist_strategy == "match":
        original_match = {
            candidate_id: fingerprint_match_score(
                references[candidate_id],
                list(generated.observed_records),
                wavelength=1.5406,
                refine_alignment=False,
            )
            for candidate_id in candidate_ids
        }
        shortlist = dual_score_gain_shortlist(
            candidate_ids,
            residual_scores=quick,
            original_scores=original_match,
            limit=shortlist_limit,
        )
    elif shortlist_strategy == "quick":
        shortlist = tuple(
            sorted(candidate_ids, key=lambda key: (-quick[key].score, key))[
                : max(1, int(shortlist_limit))
            ]
        )
    else:
        raise ValueError(f"Unsupported Gain shortlist strategy: {shortlist_strategy}")
    retrieval_seconds = time.perf_counter() - retrieval_started
    profile_started = time.perf_counter()
    remaining_fit = max(0.0, 100.0 - before_fit)
    gain_candidates = []
    gain_candidate_by_id = {}
    refined_by_id = {}
    direct_by_id = {}
    for candidate_id in candidate_ids:
        if candidate_id not in shortlist:
            item = GainCandidate(key=candidate_id)
            gain_candidates.append(item)
            gain_candidate_by_id[candidate_id] = item
            continue
        refined = fingerprint_match_score(
            references[candidate_id],
            list(residual_records),
            wavelength=1.5406,
            refine_alignment=True,
            fixed_zero_shift=global_zero_shift,
        )
        refined_by_id[candidate_id] = refined
        direct_refined = fingerprint_match_score(
            references[candidate_id],
            list(direct_records),
            wavelength=1.5406,
            refine_alignment=False,
            fixed_zero_shift=global_zero_shift,
        )
        direct_by_id[candidate_id] = direct_refined
        overlap_refined = fingerprint_match_score(
            references[candidate_id],
            list(overlap_records),
            wavelength=1.5406,
            refine_alignment=False,
            fixed_zero_shift=global_zero_shift,
        )
        hidden_refined = fingerprint_match_score(
            references[candidate_id],
            list(generated.observed_records),
            wavelength=1.5406,
            refine_alignment=False,
            fixed_zero_shift=global_zero_shift,
        )
        direct_gain = remaining_fit * direct_refined.score / 100.0
        overlap_gain = remaining_fit * overlap_refined.score / 100.0
        direct_reliability = min(1.0, direct_refined.features.observed_matched / 3.0) * min(
            1.0,
            direct_refined.features.observed_coverage / 0.35,
        )
        hidden_gain = policy.hidden_gain(
            before_fit=before_fit,
            presence=hidden_refined.score / 100.0,
        )
        candidate_cell = _estimate_candidate_cell(
            references[candidate_id],
            residual_records,
            initial_zero_shift=global_zero_shift,
            refine_zero_shift=False,
        )
        aligned_lines = _aligned_reference_lines(
            references[candidate_id],
            cell=None if candidate_cell is None else candidate_cell.cell,
            position_scale=refined.position_scale,
            zero_shift=global_zero_shift,
        )
        candidate_fwhm = estimate_matched_profile_fwhm(
            aligned_lines,
            residual_records,
            default_fwhm=refined.profile_fwhm,
            tolerance=0.55,
        )
        refined_by_id[candidate_id] = (refined, candidate_fwhm)
        candidate_profile = _candidate_profile(
            generated.x,
            aligned_lines,
            candidate_fwhm,
            1.0,
            0.0,
            instrument_floor=instrument_model,
        )
        scale = fit_residual_candidate_scale(
            target=target,
            selected_total=selected_total,
            profile=candidate_profile,
            weights=np.ones_like(target),
        )
        profile_gain = profile_residual_gain(
            residual_target=residual,
            calculated=candidate_profile * scale,
            weights=np.ones_like(target),
            residual_area=residual_area,
            before_fit=before_fit,
        )
        phase_snr = phase_signal_to_noise(
            x=generated.x,
            residual_after=target - selected_total - candidate_profile * scale,
            candidate_curve=candidate_profile * scale,
            peak_positions=np.asarray([line.two_theta for line in aligned_lines], dtype=float),
            peak_amplitudes=np.asarray([line.intensity for line in aligned_lines], dtype=float),
            fwhm=candidate_fwhm,
        )
        item = GainCandidate(
                key=candidate_id,
                direct_gain=direct_gain,
                overlap_gain=overlap_gain,
                hidden_gain=hidden_gain,
                profile_gain=profile_gain,
                direct_reliability=direct_reliability,
                phase_snr=phase_snr,
            )
        gain_candidates.append(item)
        gain_candidate_by_id[candidate_id] = item
    profile_seconds = time.perf_counter() - profile_started
    ranked = rank_gain_candidates(
        GainQuery(
            before_fit=before_fit,
            direct_count=direct_count,
            overlap_count=overlap_count,
            residual_line_count=len(residual_records),
            selected_phase_count=len(accepted_components),
            residual_share=residual_share,
        ),
        gain_candidates,
        policy,
    )
    ranked_families = []
    for item in ranked:
        family = family_by_phase[item.key]
        if family not in ranked_families:
            ranked_families.append(family)
    target_family = target_component.family_id
    target_rank = (
        ranked_families.index(target_family) + 1
        if target_family in ranked_families
        else len(ranked_families) + 1
    )
    target_result = next(
        (item for item in ranked if item.key == target_component.phase_id),
        None,
    )
    if target_result is None:
        comparisons = [
            compare_phase_patterns(
                references[item.phase_id],
                references[target_component.phase_id],
                fwhm=accepted_fwhm,
            )
            for item in accepted_components
        ]
        if any(item.equivalent for item in comparisons):
            raise IndistinguishableGainScenario(
                f"{scenario.scenario_id} target {target_component.phase_id} is diffraction-equivalent "
                "to an accepted phase at the measured width"
            )
        raise ValueError(
            f"Gain target {target_component.phase_id} in {scenario.scenario_id} was suppressed "
            f"as a duplicate of an accepted phase: {comparisons}"
        )
    target_candidate = gain_candidate_by_id[target_component.phase_id]
    top_result = ranked[0]
    top_candidate = gain_candidate_by_id[top_result.key]
    top_direct = direct_by_id.get(top_result.key)
    return GainScenarioResult(
        query_id=scenario.scenario_id,
        split=scenario.split,
        scenario_mode=scenario.overlap,
        accepted_phase_id=accepted.phase_id,
        target_phase_id=target_component.phase_id,
        target_family=target_family,
        target_retrieval_rank=target_retrieval_rank,
        target_rank=target_rank,
        dominant_evidence=target_result.dominant_evidence,
        limited_residual=target_result.limited_residual,
        candidate_count=len(candidate_ids),
        shortlist_count=len(shortlist),
        before_fit=before_fit,
        residual_share=residual_share,
        target_in_shortlist=target_component.phase_id in shortlist,
        global_zero_shift=global_zero_shift,
        true_zero_shift=float(scenario.zero_shift),
        accepted_fwhm=float(accepted_fwhm),
        target_fwhm=float(
            refined_by_id[target_component.phase_id][1]
            if target_component.phase_id in refined_by_id
            else math.nan
        ),
        target_true_fwhm=float(generated.component_fwhm[target_component.phase_id]),
        target_direct_gain=float(target_candidate.direct_gain),
        target_overlap_gain=float(target_candidate.overlap_gain),
        target_direct_matches=int(
            direct_by_id[target_component.phase_id].features.observed_matched
            if target_component.phase_id in direct_by_id
            else 0
        ),
        target_direct_coverage=float(
            direct_by_id[target_component.phase_id].features.observed_coverage
            if target_component.phase_id in direct_by_id
            else 0.0
        ),
        target_direct_reliability=float(target_candidate.direct_reliability),
        target_profile_gain=float(target_candidate.profile_gain or 0.0),
        target_phase_snr=float(target_candidate.phase_snr or 0.0),
        target_gain=float(target_result.gain),
        top_candidate_id=top_result.key,
        top_candidate_family=family_by_phase[top_result.key],
        top_direct_matches=int(top_direct.features.observed_matched if top_direct is not None else 0),
        top_direct_coverage=float(top_direct.features.observed_coverage if top_direct is not None else 0.0),
        top_direct_reliability=float(top_candidate.direct_reliability),
        top_direct_gain=float(top_candidate.direct_gain),
        top_overlap_gain=float(top_candidate.overlap_gain),
        top_hidden_gain=float(top_candidate.hidden_gain),
        top_profile_gain=float(top_candidate.profile_gain or 0.0),
        top_phase_snr=float(top_candidate.phase_snr or 0.0),
        match_dominant_rank=int(match_dominant_rank),
        accepted_family_correct=bool(accepted_family_correct),
        elapsed_seconds=time.perf_counter() - started,
        gain_engine="greedy",
        retrieval_seconds=float(retrieval_seconds),
        profile_seconds=float(profile_seconds),
        ranked_candidate_ids=tuple(item.key for item in ranked),
        ranked_families=tuple(ranked_families),
    )


def _evaluate_joint_gain_scenario(
    *,
    references,
    family_by_phase,
    scenario,
    generated,
    accepted,
    accepted_components,
    accepted_profiles,
    target_component,
    target,
    selected_total,
    residual,
    residual_records,
    direct_records,
    overlap_records,
    quick,
    candidate_ids,
    global_zero_shift,
    accepted_fwhm,
    before_fit,
    residual_share,
    target_retrieval_rank,
    shortlist_limit,
    policy,
    instrument_model,
    match_dominant_rank,
    accepted_family_correct,
    joint_config,
    joint_profile_mode,
    started,
) -> GainScenarioResult:
    retrieval_started = time.perf_counter()
    original_records = (
        select_informative_residual_peaks(generated.observed_records, limit=12)
        if joint_profile_mode == "peak-windows"
        else generated.observed_records
    )
    original_scores = {
        candidate_id: fingerprint_match_score(
            references[candidate_id],
            list(original_records),
            wavelength=1.5406,
            refine_alignment=False,
        )
        for candidate_id in candidate_ids
    }
    rare_ids = rare_line_gain_shortlist(
        {candidate_id: references[candidate_id] for candidate_id in candidate_ids},
        residual_records,
        quick,
        limit=min(12, max(1, len(candidate_ids))),
    )
    pool = build_joint_candidate_pool(
        references,
        original_scores=original_scores,
        residual_scores=quick,
        rare_candidate_ids=rare_ids,
        accepted_phase_ids=tuple(item.phase_id for item in accepted_components),
        original_limit=min(40, max(1, len(candidate_ids))),
        residual_limit=min(40, max(1, len(candidate_ids))),
        rare_limit=min(12, max(1, len(candidate_ids))),
        optional_limit=min(max(1, int(shortlist_limit)), 60),
        target_phase_id=target_component.phase_id,
        fwhm=accepted_fwhm,
    )
    if joint_profile_mode == "peak-windows":
        pool = replace(
            pool,
            optional_ids=prefilter_joint_profile_ids(
                pool,
                residual_scores=quick,
                limit=min(24, max(1, int(shortlist_limit))),
                rescue_count=4,
            ),
        )
    retrieval_seconds = time.perf_counter() - retrieval_started

    profile_started = time.perf_counter()
    profiles: dict[str, np.ndarray] = {}
    joint_references: dict[str, Sequence[ReferenceLine]] = {}
    accepted_profile_by_id = {
        component.phase_id: profile
        for component, profile in zip(
            accepted_components,
            accepted_profiles,
            strict=True,
        )
    }
    for phase_id in pool.required_ids:
        profiles[phase_id] = np.asarray(accepted_profile_by_id[phase_id], dtype=float)
        joint_references[phase_id] = references[phase_id]
    candidate_widths: dict[str, float] = {}
    for candidate_id in pool.optional_ids:
        refined = fingerprint_match_score(
            references[candidate_id],
            list(residual_records),
            wavelength=1.5406,
            refine_alignment=True,
            fixed_zero_shift=global_zero_shift,
        )
        candidate_cell = _estimate_candidate_cell(
            references[candidate_id],
            residual_records,
            initial_zero_shift=global_zero_shift,
            refine_zero_shift=False,
        )
        aligned_lines = _aligned_reference_lines(
            references[candidate_id],
            cell=None if candidate_cell is None else candidate_cell.cell,
            position_scale=refined.position_scale,
            zero_shift=global_zero_shift,
        )
        candidate_fwhm = estimate_matched_profile_fwhm(
            aligned_lines,
            residual_records,
            default_fwhm=refined.profile_fwhm,
            tolerance=0.55,
        )
        candidate_widths[candidate_id] = float(candidate_fwhm)
        profiles[candidate_id] = _candidate_profile(
            generated.x,
            aligned_lines,
            candidate_fwhm,
            1.0,
            0.0,
            instrument_floor=instrument_model,
        )
        joint_references[candidate_id] = aligned_lines
    profile_seconds = time.perf_counter() - profile_started

    residual_window_mode = joint_profile_mode == "peak-windows"
    evaluation_pool = replace(pool, required_ids=()) if residual_window_mode else pool
    evaluation = evaluate_joint_gain(
        x=generated.x,
        target=residual if residual_window_mode else target,
        weights=np.ones_like(target),
        profiles=profiles,
        references=joint_references,
        pool=evaluation_pool,
        config=joint_config,
        profile_mode=joint_profile_mode,
        window_centers=tuple(record.two_theta for record in residual_records),
    )
    target_pattern_family = pool.family_for(target_component.phase_id)
    target_rank = _ranked_family_position(
        evaluation.ranked_family_keys,
        target_pattern_family,
        candidate_count=len(pool.optional_ids),
    )
    gain_by_family = {
        item.family_key: item for item in evaluation.search_result.candidate_gains
    }
    target_gain_result = gain_by_family.get(target_pattern_family)
    top_candidate_id = (
        evaluation.ranked_phase_ids[0] if evaluation.ranked_phase_ids else ""
    )
    top_gain_result = (
        gain_by_family.get(pool.family_for(top_candidate_id))
        if top_candidate_id
        else None
    )
    best = min(
        evaluation.search_result.combinations,
        key=lambda item: (item.score, item.card_keys),
    )
    target_representative = next(
        (
            phase_id
            for phase_id in pool.optional_ids
            if pool.family_for(phase_id) == target_pattern_family
        ),
        None,
    )
    target_direct = (
        fingerprint_match_score(
            joint_references[target_representative],
            list(direct_records),
            wavelength=1.5406,
            refine_alignment=False,
            fixed_zero_shift=0.0,
        )
        if target_representative is not None
        else None
    )
    top_direct = (
        fingerprint_match_score(
            joint_references[top_candidate_id],
            list(direct_records),
            wavelength=1.5406,
            refine_alignment=False,
            fixed_zero_shift=0.0,
        )
        if top_candidate_id
        else None
    )
    stage = policy.select_stage(
        direct_count=len(direct_records),
        overlap_count=len(overlap_records),
    )
    target_gain = float(target_gain_result.gain if target_gain_result is not None else 0.0)
    top_gain = float(top_gain_result.gain if top_gain_result is not None else 0.0)
    true_families = {component.family_id for component in scenario.components}
    best_families = {
        family_by_phase[phase_id]
        for phase_id in best.card_keys
        if phase_id in family_by_phase
    }
    best_families.update(component.family_id for component in accepted_components)
    return GainScenarioResult(
        query_id=scenario.scenario_id,
        split=scenario.split,
        scenario_mode=scenario.overlap,
        accepted_phase_id=accepted.phase_id,
        target_phase_id=target_component.phase_id,
        target_family=target_component.family_id,
        target_retrieval_rank=target_retrieval_rank,
        target_rank=target_rank,
        dominant_evidence=stage,
        limited_residual=len(residual_records) <= 2,
        candidate_count=len(candidate_ids),
        shortlist_count=len(pool.optional_ids),
        before_fit=before_fit,
        residual_share=residual_share,
        target_in_shortlist=target_representative is not None,
        global_zero_shift=global_zero_shift,
        true_zero_shift=float(scenario.zero_shift),
        accepted_fwhm=float(accepted_fwhm),
        target_fwhm=float(
            candidate_widths.get(target_representative, math.nan)
            if target_representative is not None
            else math.nan
        ),
        target_true_fwhm=float(generated.component_fwhm[target_component.phase_id]),
        target_direct_gain=target_gain if stage is GainStage.DIRECT else 0.0,
        target_overlap_gain=target_gain if stage is GainStage.OVERLAP else 0.0,
        target_direct_matches=int(target_direct.features.observed_matched if target_direct else 0),
        target_direct_coverage=float(target_direct.features.observed_coverage if target_direct else 0.0),
        target_direct_reliability=1.0 if target_direct else 0.0,
        target_profile_gain=target_gain,
        target_phase_snr=float(target_gain_result.phase_snr if target_gain_result else 0.0),
        target_gain=target_gain,
        top_candidate_id=top_candidate_id,
        top_candidate_family=(family_by_phase[top_candidate_id] if top_candidate_id else ""),
        top_direct_matches=int(top_direct.features.observed_matched if top_direct else 0),
        top_direct_coverage=float(top_direct.features.observed_coverage if top_direct else 0.0),
        top_direct_reliability=1.0 if top_direct else 0.0,
        top_direct_gain=top_gain if stage is GainStage.DIRECT else 0.0,
        top_overlap_gain=top_gain if stage is GainStage.OVERLAP else 0.0,
        top_hidden_gain=top_gain if stage is GainStage.HIDDEN else 0.0,
        top_profile_gain=top_gain,
        top_phase_snr=float(top_gain_result.phase_snr if top_gain_result else 0.0),
        match_dominant_rank=int(match_dominant_rank),
        accepted_family_correct=bool(accepted_family_correct),
        elapsed_seconds=time.perf_counter() - started,
        gain_engine="joint-beam",
        retrieval_seconds=float(retrieval_seconds),
        profile_seconds=float(profile_seconds),
        search_seconds=float(evaluation.search_seconds),
        evaluated_combinations=int(evaluation.evaluated_combinations),
        best_combination=tuple(best.card_keys),
        ranked_candidate_ids=tuple(evaluation.ranked_phase_ids),
        ranked_families=tuple(evaluation.ranked_family_keys),
        suppressed_candidate_count=sum(
            not item.reportable for item in evaluation.search_result.candidate_gains
        ),
        full_set_recovered=true_families.issubset(best_families),
        false_positive_families=len(best_families - true_families),
    )


def run_gain_benchmark(
    dataset_path: Path,
    output_dir: Path,
    *,
    workers: int = 1,
    shortlist_limit: int = 100,
    scenario_set: str = "factorial-test",
    splits: Sequence[str] | None = None,
    policy: GainPolicy = DEFAULT_GAIN_POLICY,
    shortlist_strategy: str = "quick",
    instrument_data: bool = False,
    instrument_model: bool = False,
    accepted_from_match: bool = False,
    gain_engine: str = "greedy",
    joint_config: JointPhaseSearchConfig | None = None,
    joint_profile_mode: str = "full",
) -> Path:
    with BenchmarkDataset.open(dataset_path) as dataset:
        phases = dataset.phase_descriptors()
        references = dataset.reference_library()
    assignments = assign_split_families(phases, seed=5036)
    if scenario_set == "targeted":
        scenarios = build_gain_scenario_manifest(
            phases,
            assignments,
            references,
            GainScenarioConfig(seed=5036),
        )
    elif scenario_set == "factorial-test":
        scenarios = tuple(
            item
            for item in build_scenario_manifest(phases, assignments, ScenarioConfig(seed=5036))
            if item.split == "test" and len(item.components) >= 2
        )
    else:
        raise ValueError(f"Unsupported Gain scenario set: {scenario_set}")
    if splits:
        allowed_splits = {str(value) for value in splits}
        scenarios = tuple(item for item in scenarios if item.split in allowed_splits)
    families = {phase.phase_id: phase.family_id for phase in phases}
    worker_count = max(1, min(int(workers), len(scenarios)))
    if worker_count == 1:
        results = _evaluate_gain_chunk(
            (
                references,
                families,
                scenarios,
                shortlist_limit,
                policy,
                shortlist_strategy,
                instrument_data,
                instrument_model,
                accepted_from_match,
                gain_engine,
                joint_config,
                joint_profile_mode,
            )
        )
    else:
        chunk_size = int(math.ceil(len(scenarios) / worker_count))
        arguments = [
            (
                references,
                families,
                scenarios[start : start + chunk_size],
                shortlist_limit,
                policy,
                shortlist_strategy,
                instrument_data,
                instrument_model,
                accepted_from_match,
                gain_engine,
                joint_config,
                joint_profile_mode,
            )
            for start in range(0, len(scenarios), chunk_size)
        ]
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            chunks = list(executor.map(_evaluate_gain_chunk, arguments))
        results = tuple(item for chunk in chunks for item in chunk)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "gain_results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(asdict(results[0])))
        writer.writeheader()
        for result in results:
            writer.writerow(_gain_csv_row(result))
    summary_path = output_dir / "gain_summary.md"
    summary_path.write_text(_gain_summary(results), encoding="utf-8")
    return summary_path


def _evaluate_gain_chunk(arguments):
    (
        references,
        families,
        scenarios,
        shortlist_limit,
        policy,
        shortlist_strategy,
        instrument_data,
        instrument_model,
        accepted_from_match,
        gain_engine,
        joint_config,
        joint_profile_mode,
    ) = arguments
    results = []
    for scenario in scenarios:
        try:
            results.append(
                evaluate_gain_scenario(
                    references,
                    families,
                    scenario,
                    shortlist_limit=shortlist_limit,
                    policy=policy,
                    shortlist_strategy=shortlist_strategy,
                    instrument_data=instrument_data,
                    instrument_model=instrument_model,
                    accepted_from_match=accepted_from_match,
                    gain_engine=gain_engine,
                    joint_config=joint_config,
                    joint_profile_mode=joint_profile_mode,
                )
            )
        except IndistinguishableGainScenario:
            continue
    return tuple(results)


def _gain_csv_row(result: GainScenarioResult) -> dict[str, object]:
    row = asdict(result)
    row["dominant_evidence"] = str(result.dominant_evidence)
    for key in ("best_combination", "ranked_candidate_ids", "ranked_families"):
        row[key] = json.dumps(list(row[key]), ensure_ascii=False, separators=(",", ":"))
    return row


def _gain_summary(results: Sequence[GainScenarioResult]) -> str:
    zero_errors = [abs(item.global_zero_shift - item.true_zero_shift) for item in results]
    width_errors = [
        abs(item.target_fwhm - item.target_true_fwhm)
        for item in results
        if math.isfinite(item.target_fwhm)
    ]
    ranks_all = np.asarray([item.target_rank for item in results], dtype=float)
    retrieval = [item.retrieval_seconds for item in results]
    profile = [item.profile_seconds for item in results]
    search = [item.search_seconds for item in results]
    combinations = [item.evaluated_combinations for item in results]
    order_stability, card_stability = _gain_variant_stability(results)
    lines = [
        "# Gain benchmark summary",
        "",
        "The accepted phase is supplied by the configured oracle or by a complete Match pass; Gain ranks the strongest remaining true phase.",
        "",
        "Every candidate is scored once from direct, overlap and hidden evidence; direct evidence has the greatest weight and hidden evidence the least.",
        "One or two residual lines may retrieve a candidate, but the resulting Gain is capped and unsupported strong candidate lines are penalized.",
        "One global zero shift is fitted from the accepted phase. Each phase then receives an independent indexed reciprocal-metric refinement and an independently estimated FWHM.",
        f"Match-selected accepted phase correct-family rate: {np.mean([item.accepted_family_correct for item in results]):.4f}.",
        f"Dominant-phase Match Top-1/Top-5/Top-10: {np.mean([item.match_dominant_rank <= 1 for item in results]):.4f} / {np.mean([item.match_dominant_rank <= 5 for item in results]):.4f} / {np.mean([item.match_dominant_rank <= 10 for item in results]):.4f}.",
        "",
        f"Global zero-shift median absolute error: {np.median(zero_errors):.4f} deg.",
        f"Candidate FWHM median absolute error: {np.median(width_errors):.4f} deg ({len(width_errors)}/{len(results)} targets estimated)." if width_errors else "Candidate FWHM could not be estimated.",
        "",
        f"Retrieval median/p95: {np.median(retrieval):.4f} / {_p95(retrieval):.4f} s.",
        f"Profile build median/p95: {np.median(profile):.4f} / {_p95(profile):.4f} s.",
        f"Beam search median/p95: {np.median(search):.4f} / {_p95(search):.4f} s.",
        f"Evaluated combinations median/p95: {np.median(combinations):.1f} / {_p95(combinations):.1f}.",
        f"Pool recall: {np.mean([item.target_in_shortlist for item in results]):.4f}.",
        f"Top-1/Top-5/Top-10: {np.mean(ranks_all <= 1):.4f} / {np.mean(ranks_all <= 5):.4f} / {np.mean(ranks_all <= 10):.4f}.",
        f"Full-set recovery: {np.mean([item.full_set_recovered for item in results]):.4f}.",
        f"False-positive families per query: {np.mean([item.false_positive_families for item in results]):.4f}.",
        f"Order stability (paired Top-5 retention): {order_stability}.",
        f"Card-variant stability (median absolute rank delta): {card_stability}.",
        "",
        "| Evidence group | Queries | MRR | Top-1 | Top-5 | Top-10 | Shortlist recall | Median time (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    groups = [("all", tuple(results))]
    groups.extend(
        (
            f"dominant:{stage}",
            tuple(item for item in results if item.dominant_evidence == stage),
        )
        for stage in GainStage
    )
    groups.append(("limited-residual", tuple(item for item in results if item.limited_residual)))
    groups.extend(
        (f"mode:{mode}", tuple(item for item in results if item.scenario_mode == mode))
        for mode in sorted({item.scenario_mode for item in results})
    )
    for label, group in groups:
        if not group:
            continue
        ranks = np.asarray([item.target_rank for item in group], dtype=float)
        lines.append(
            f"| {label} | {len(group)} | {np.mean(1.0 / ranks):.4f} | "
            f"{np.mean(ranks <= 1):.4f} | {np.mean(ranks <= 5):.4f} | "
            f"{np.mean(ranks <= 10):.4f} | {np.mean([item.target_in_shortlist for item in group]):.4f} | "
            f"{np.median([item.elapsed_seconds for item in group]):.3f} |"
        )
    return "\n".join(lines) + "\n"


def _p95(values: Sequence[float | int]) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), 95))


def _gain_variant_stability(results: Sequence[GainScenarioResult]) -> tuple[str, str]:
    groups: dict[tuple[str, str], list[GainScenarioResult]] = {}
    for result in results:
        if result.variant_group and result.variant_kind:
            groups.setdefault((result.variant_kind, result.variant_group), []).append(result)
    order = [items for (kind, _), items in groups.items() if kind == "accepted-order" and len(items) >= 2]
    cards = [items for (kind, _), items in groups.items() if kind == "card-variant" and len(items) >= 2]
    order_value = (
        f"{np.mean([all(item.target_rank <= 5 for item in pair[:2]) for pair in order]):.4f}"
        if order
        else "n/a"
    )
    card_value = (
        f"{np.median([abs(pair[0].target_rank - pair[1].target_rank) for pair in cards]):.3f}"
        if cards
        else "n/a"
    )
    return order_value, card_value


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic Gain benchmark.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/gain-benchmark"))
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--shortlist", type=int, default=100)
    parser.add_argument(
        "--scenario-set",
        choices=("factorial-test", "targeted"),
        default="factorial-test",
    )
    parser.add_argument(
        "--splits",
        nargs="+",
        choices=("train", "validation", "test"),
    )
    parser.add_argument("--minimum-profile-support", type=float, default=0.35)
    parser.add_argument("--sparse-profile-weight", type=float, default=0.0)
    parser.add_argument("--phase-snr-minimum-support", type=float, default=0.50)
    parser.add_argument(
        "--shortlist-strategy",
        choices=("quick", "adaptive", "hybrid", "rare", "dominant", "dominant-expand", "match"),
        default="quick",
    )
    parser.add_argument("--instrument-data", action="store_true")
    parser.add_argument("--instrument-model", action="store_true")
    parser.add_argument("--accepted-from-match", action="store_true")
    parser.add_argument(
        "--gain-engine",
        choices=("greedy", "joint-beam"),
        default="greedy",
    )
    parser.add_argument("--beam-width", type=int, default=5)
    parser.add_argument("--max-added-phases", type=int, default=3)
    parser.add_argument("--derivative-weight", type=float, default=0.10)
    parser.add_argument("--complexity-penalty", type=float, default=0.003)
    parser.add_argument("--excess-penalty", type=float, default=3.0)
    parser.add_argument("--minimum-phase-snr", type=float, default=3.0)
    parser.add_argument("--minimum-relative-improvement", type=float, default=0.003)
    parser.add_argument(
        "--joint-profile-mode",
        choices=("peak-windows", "full"),
        default="peak-windows",
        help="Fit informative peak windows or the complete profile.",
    )
    args = parser.parse_args()
    output = run_gain_benchmark(
        args.dataset,
        args.output,
        workers=args.workers,
        shortlist_limit=args.shortlist,
        scenario_set=args.scenario_set,
        splits=args.splits,
        policy=replace(
            DEFAULT_GAIN_POLICY,
            minimum_profile_support=args.minimum_profile_support,
            sparse_profile_weight=args.sparse_profile_weight,
            minimum_phase_snr_support=args.phase_snr_minimum_support,
        ),
        shortlist_strategy=args.shortlist_strategy,
        instrument_data=args.instrument_data,
        instrument_model=args.instrument_model,
        accepted_from_match=args.accepted_from_match,
        gain_engine=args.gain_engine,
        joint_config=JointPhaseSearchConfig(
            beam_width=args.beam_width,
            max_added_phases=args.max_added_phases,
            derivative_weight=args.derivative_weight,
            complexity_penalty=args.complexity_penalty,
            excess_penalty=args.excess_penalty,
            minimum_phase_snr=args.minimum_phase_snr,
            minimum_relative_improvement=args.minimum_relative_improvement,
        ),
        joint_profile_mode=args.joint_profile_mode,
    )
    print(f"Wrote {output}")
    return 0


def _nonnegative_scale(target: np.ndarray, profile: np.ndarray) -> float:
    denominator = float(np.dot(profile, profile))
    if denominator <= 1.0e-12:
        return 0.0
    return max(0.0, float(np.dot(target, profile)) / denominator)


def _joint_nonnegative_scales(target, profiles) -> np.ndarray:
    target_values = np.clip(np.asarray(target, dtype=float), 0.0, None)
    if not profiles:
        return np.asarray([], dtype=float)
    matrix = np.column_stack(
        [np.clip(np.asarray(profile, dtype=float), 0.0, None) for profile in profiles]
    )
    if matrix.shape[0] != len(target_values):
        raise ValueError("Every selected profile must use the target grid.")
    scales, _residual = nnls(matrix, target_values)
    return np.asarray(scales, dtype=float)


def _aligned_positions(
    lines: Sequence[ReferenceLine],
    position_scale: float,
    zero_shift: float,
) -> np.ndarray:
    return np.asarray(
        sorted(
            45.0 + (float(line.two_theta) - 45.0) * float(position_scale) + float(zero_shift)
            for line in lines
            if float(line.intensity) >= 3.0
        ),
        dtype=float,
    )


def _partition_residual_records(records, selected_positions: np.ndarray, fwhm: float):
    direct = []
    overlap = []
    tolerance = max(0.28, min(0.85, float(fwhm) * 1.7))
    for record in records[:24]:
        position = float(getattr(record, "two_theta", 0.0) or 0.0)
        delta = float(np.min(np.abs(selected_positions - position))) if len(selected_positions) else math.inf
        if delta <= tolerance:
            overlap.append(record)
        else:
            direct.append(record)
    return tuple(direct), tuple(overlap)


def _candidate_profile(
    x: np.ndarray,
    lines: Sequence[ReferenceLine],
    fwhm: float,
    position_scale: float,
    zero_shift: float,
    *,
    instrument_floor: bool = False,
) -> np.ndarray:
    profile = np.zeros_like(x, dtype=float)
    maximum = max((float(line.intensity) for line in lines), default=1.0)
    for line in lines:
        center = 45.0 + (float(line.two_theta) - 45.0) * float(position_scale) + float(zero_shift)
        line_fwhm = max(float(fwhm), benchmark_instrument_fwhm(center)) if instrument_floor else float(fwhm)
        profile += max(float(line.intensity), 0.0) / max(maximum, 1.0e-12) * pseudo_voigt_values(
            x,
            center,
            line_fwhm,
            0.35,
        )
    return profile


def _select_match_candidate(
    references: Mapping[str, Sequence[ReferenceLine]],
    family_by_phase: Mapping[str, str],
    observed_records: Sequence[object],
    dominant_family: str,
) -> tuple[str, int]:
    """Run the all-database Match pass and return its first candidate."""

    candidate_ids = tuple(sorted(references))
    quick = {
        candidate_id: fingerprint_match_score(
            references[candidate_id],
            list(observed_records),
            wavelength=1.5406,
            refine_alignment=False,
        )
        for candidate_id in candidate_ids
    }
    refine_ids = sorted(
        candidate_ids,
        key=lambda candidate_id: (-quick[candidate_id].score, candidate_id),
    )[:96]
    refined = dict(quick)
    for candidate_id in refine_ids:
        refined[candidate_id] = fingerprint_match_score(
            references[candidate_id],
            list(observed_records),
            wavelength=1.5406,
            refine_alignment=True,
        )
    ordered = sorted(
        candidate_ids,
        key=lambda candidate_id: (-refined[candidate_id].score, candidate_id),
    )
    ranked_families = []
    for candidate_id in ordered:
        family = family_by_phase[candidate_id]
        if family not in ranked_families:
            ranked_families.append(family)
    dominant_rank = (
        ranked_families.index(dominant_family) + 1
        if dominant_family in ranked_families
        else len(ranked_families) + 1
    )
    return ordered[0], dominant_rank


def _estimate_candidate_cell(
    lines: Sequence[ReferenceLine],
    observed_records: Sequence[object],
    *,
    initial_zero_shift: float,
    refine_zero_shift: bool,
):
    metric = _fit_reciprocal_metric(lines)
    if metric is None:
        return None
    initial_cell = FastCellParameterEstimator._cell_from_reciprocal_metric(metric)
    if initial_cell is None:
        return None
    peaks = _hkl_peaks(lines)
    observed = []
    for record in observed_records:
        try:
            observed.append(
                ObservedPeak(
                    two_theta=float(getattr(record, "two_theta")),
                    intensity=float(
                        getattr(record, "area", 0.0)
                        or getattr(record, "height", 0.0)
                        or getattr(record, "intensity", 0.0)
                    ),
                    fwhm=float(getattr(record, "fwhm", 0.18) or 0.18),
                )
            )
        except (TypeError, ValueError):
            continue
    return FastCellParameterEstimator().estimate(
        initial_cell=initial_cell,
        calculated_peaks=peaks,
        observed_peaks=observed,
        wavelength=1.5406,
        zero_shift_deg=float(initial_zero_shift),
        tolerance_deg=0.65,
        refine_zero_shift=bool(refine_zero_shift),
    )


def _hkl_peaks(lines: Sequence[ReferenceLine]) -> list[HKLPeak]:
    result = []
    for line in lines:
        if line.d is None or line.h is None or line.k is None or line.l is None:
            continue
        result.append(
            HKLPeak(
                h=int(line.h),
                k=int(line.k),
                l=int(line.l),
                d=float(line.d),
                two_theta=float(line.two_theta),
                intensity=float(line.intensity),
                multiplicity=int(line.multiplicity or 1),
            )
        )
    return result


def _aligned_reference_lines(
    lines: Sequence[ReferenceLine],
    *,
    cell,
    position_scale: float,
    zero_shift: float,
) -> tuple[object, ...]:
    metric = _reciprocal_metric_from_cell(cell) if cell is not None else None
    result = []
    for line in lines:
        position = 45.0 + (float(line.two_theta) - 45.0) * float(position_scale) + float(zero_shift)
        if metric is not None and line.h is not None and line.k is not None and line.l is not None:
            vector = np.asarray([line.h, line.k, line.l], dtype=float)
            reciprocal_square = float(vector @ metric @ vector)
            if reciprocal_square > 0.0:
                argument = 1.5406 * math.sqrt(reciprocal_square) / 2.0
                if 0.0 < argument < 1.0:
                    position = math.degrees(2.0 * math.asin(argument)) + float(zero_shift)
        result.append(
            SimpleNamespace(
                two_theta=position,
                intensity=float(line.intensity),
                d=line.d,
                h=line.h,
                k=line.k,
                l=line.l,
                multiplicity=line.multiplicity,
            )
        )
    return tuple(result)


def _reciprocal_metric_from_cell(cell) -> np.ndarray | None:
    try:
        a, b, c = float(cell.a), float(cell.b), float(cell.c)
        alpha, beta, gamma = (math.radians(float(value)) for value in (cell.alpha, cell.beta, cell.gamma))
        direct = np.asarray(
            [
                [a * a, a * b * math.cos(gamma), a * c * math.cos(beta)],
                [a * b * math.cos(gamma), b * b, b * c * math.cos(alpha)],
                [a * c * math.cos(beta), b * c * math.cos(alpha), c * c],
            ],
            dtype=float,
        )
        return np.linalg.inv(direct)
    except (TypeError, ValueError, np.linalg.LinAlgError):
        return None


__all__ = ["GainScenarioResult", "evaluate_gain_scenario", "run_gain_benchmark"]


if __name__ == "__main__":
    raise SystemExit(main())
