from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from benchmarks.match.gain_retrieval import (
    JointGainCandidatePool,
    joint_gain_candidate_pool,
)
from benchmarks.match.generate_profiles import ReferenceLine
from xrd_finder.finder.joint_phase_search import (
    JointPhaseCandidate,
    JointPhaseSearchConfig,
    JointPhaseSearchResult,
    search_phase_combinations,
)


@dataclass(frozen=True, slots=True)
class JointGainEvaluation:
    search_result: JointPhaseSearchResult
    ranked_phase_ids: tuple[str, ...]
    ranked_family_keys: tuple[str, ...]
    active_fit_points: int

    @property
    def evaluated_combinations(self) -> int:
        return self.search_result.evaluated_combinations

    @property
    def search_seconds(self) -> float:
        return self.search_result.elapsed_seconds


def build_joint_candidate_pool(
    references: Mapping[str, Sequence[ReferenceLine]],
    **kwargs,
) -> JointGainCandidatePool:
    return joint_gain_candidate_pool(references, **kwargs)


def build_joint_fit_mask(
    *,
    x: np.ndarray,
    target: np.ndarray,
    references: Mapping[str, Sequence[ReferenceLine]],
    phase_ids: Sequence[str],
    mode: str = "peak-windows",
    window_centers: Sequence[float] | None = None,
    observed_window: float = 0.25,
    baseline_points: int = 240,
) -> np.ndarray:
    """Select common windows around unexplained residual maxima.

    Every candidate and combination is fitted on the same residual-defined
    regions. Sparse baseline controls only anchor the local fit outside peaks.
    ``references`` and ``phase_ids`` remain arguments for adapter compatibility;
    candidate lines deliberately do not choose the evaluation regions.
    """
    x_values = np.asarray(x, dtype=float)
    target_values = np.asarray(target, dtype=float)
    if x_values.ndim != 1 or target_values.shape != x_values.shape:
        raise ValueError("x and target must be one-dimensional and have identical shapes")
    if mode == "full":
        return np.ones(len(x_values), dtype=bool)
    if mode != "peak-windows":
        raise ValueError(f"Unsupported joint profile mode: {mode}")
    if not len(x_values):
        return np.zeros(0, dtype=bool)

    mask = np.zeros(len(x_values), dtype=bool)
    centers = tuple(
        float(value) for value in (() if window_centers is None else window_centers)
    )
    if centers:
        for center in centers:
            if np.isfinite(center):
                mask |= np.abs(x_values - center) <= max(float(observed_window), 0.0)
    elif len(x_values) > 2:
        smoothed = gaussian_filter1d(target_values, sigma=1.0, mode="nearest")
        differences = np.diff(smoothed)
        difference_median = float(np.median(differences)) if len(differences) else 0.0
        noise = (
            1.4826 * float(np.median(np.abs(differences - difference_median)))
            / np.sqrt(2.0)
            if len(differences)
            else 0.0
        )
        signal_span = max(float(np.ptp(smoothed)), 0.0)
        prominence = max(3.0 * noise, 0.005 * signal_span, np.finfo(float).eps)
        peak_indices, _ = find_peaks(smoothed, prominence=prominence)
        for peak_index in peak_indices:
            center = float(x_values[int(peak_index)])
            mask |= np.abs(x_values - center) <= max(float(observed_window), 0.0)

    controls = max(int(baseline_points), 2)
    stride = max(1, int(np.ceil(len(mask) / controls)))
    mask[::stride] = True
    mask[0] = True
    mask[-1] = True
    return mask


def prefilter_joint_profile_ids(
    pool: JointGainCandidatePool,
    *,
    residual_scores: Mapping[str, object],
    limit: int = 12,
    rescue_count: int = 2,
) -> tuple[str, ...]:
    """Choose cards worth an expensive profile build.

    Most slots follow the residual-line score. A small number preserve the
    fused retrieval order so a rare-line or original-pattern candidate can
    still reach the joint fit.
    """
    maximum = max(0, min(int(limit), len(pool.optional_ids)))
    if maximum == 0:
        return ()
    rescue = max(0, min(int(rescue_count), maximum))
    primary_count = maximum - rescue

    def score(phase_id: str) -> float:
        value = residual_scores.get(phase_id, 0.0)
        raw = getattr(value, "score", value)
        try:
            number = float(raw)
        except (TypeError, ValueError):
            return 0.0
        return number if np.isfinite(number) else 0.0

    ranked = tuple(
        sorted(pool.optional_ids, key=lambda phase_id: (-score(phase_id), phase_id))
    )
    selected = list(ranked[:primary_count])
    for phase_id in pool.optional_ids:
        if phase_id not in selected:
            selected.append(phase_id)
        if len(selected) >= maximum:
            break
    return tuple(selected)


def select_informative_residual_peaks(
    peaks: Sequence[object],
    *,
    limit: int = 12,
) -> tuple[object, ...]:
    """Return the strongest residual maxima in stable angular order."""
    maximum = max(0, min(int(limit), len(peaks)))
    if maximum == 0:
        return ()

    def intensity(peak: object) -> float:
        try:
            value = float(getattr(peak, "intensity"))
        except (AttributeError, TypeError, ValueError):
            return 0.0
        return value if np.isfinite(value) else 0.0

    def position(peak: object) -> float:
        try:
            value = float(getattr(peak, "two_theta"))
        except (AttributeError, TypeError, ValueError):
            return 0.0
        return value if np.isfinite(value) else 0.0

    strongest = sorted(peaks, key=lambda peak: (-intensity(peak), position(peak)))[:maximum]
    return tuple(sorted(strongest, key=position))


def evaluate_joint_gain(
    *,
    x: np.ndarray,
    target: np.ndarray,
    weights: np.ndarray,
    profiles: Mapping[str, np.ndarray],
    references: Mapping[str, Sequence[ReferenceLine]],
    pool: JointGainCandidatePool,
    config: JointPhaseSearchConfig | None = None,
    profile_mode: str = "full",
    window_centers: Sequence[float] | None = None,
) -> JointGainEvaluation:
    family_by_phase = dict(pool.family_assignments)
    ordered_ids = (*pool.required_ids, *pool.optional_ids)
    candidates = tuple(
        JointPhaseCandidate(
            key=phase_id,
            family_key=family_by_phase[phase_id],
            profile=np.asarray(profiles[phase_id], dtype=float),
            peak_positions=np.asarray(
                [line.two_theta for line in references[phase_id]],
                dtype=float,
            ),
            peak_amplitudes=np.asarray(
                [line.intensity for line in references[phase_id]],
                dtype=float,
            ),
            payload=phase_id,
        )
        for phase_id in ordered_ids
    )
    fit_mask = build_joint_fit_mask(
        x=np.asarray(x, dtype=float),
        target=np.asarray(target, dtype=float),
        references=references,
        phase_ids=ordered_ids,
        mode=profile_mode,
        window_centers=window_centers,
    )
    result = search_phase_combinations(
        x=np.asarray(x, dtype=float),
        target=np.asarray(target, dtype=float),
        weights=np.asarray(weights, dtype=float) * fit_mask,
        candidates=candidates,
        required_keys=pool.required_ids,
        config=config,
    )
    reportable = tuple(gain for gain in result.candidate_gains if gain.reportable)
    return JointGainEvaluation(
        search_result=result,
        ranked_phase_ids=tuple(gain.key for gain in reportable),
        ranked_family_keys=tuple(gain.family_key for gain in reportable),
        active_fit_points=int(np.count_nonzero(fit_mask)),
    )


__all__ = [
    "JointGainEvaluation",
    "build_joint_candidate_pool",
    "build_joint_fit_mask",
    "evaluate_joint_gain",
    "prefilter_joint_profile_ids",
    "select_informative_residual_peaks",
]
