from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Collection, Sequence

import numpy as np
from scipy.optimize import nnls

from xrd_finder.finder.gain_evidence import phase_signal_to_noise


def _readonly_vector(values: np.ndarray | Sequence[float]) -> np.ndarray:
    array = np.array(values, dtype=float, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True)
class JointPhaseCandidate:
    key: str
    family_key: str
    profile: np.ndarray
    peak_positions: np.ndarray
    peak_amplitudes: np.ndarray
    payload: object | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", str(self.key))
        object.__setattr__(self, "family_key", str(self.family_key))
        object.__setattr__(self, "profile", _readonly_vector(self.profile))
        object.__setattr__(
            self,
            "peak_positions",
            _readonly_vector(self.peak_positions),
        )
        object.__setattr__(
            self,
            "peak_amplitudes",
            _readonly_vector(self.peak_amplitudes),
        )


@dataclass(frozen=True, slots=True)
class JointPhaseSearchConfig:
    beam_width: int = 5
    max_added_phases: int = 3
    derivative_weight: float = 0.10
    complexity_penalty: float = 0.003
    excess_penalty: float = 3.0
    minimum_phase_snr: float = 3.0
    minimum_relative_improvement: float = 0.003
    minimum_reported_gain: float = 3.0


@dataclass(frozen=True, slots=True)
class JointPhaseCombination:
    family_keys: tuple[str, ...]
    card_keys: tuple[str, ...]
    scales: tuple[float, ...]
    score: float
    phase_snrs: tuple[float, ...] = ()
    model: np.ndarray = field(
        default_factory=lambda: _readonly_vector(()),
        repr=False,
        compare=False,
    )
    residual: np.ndarray = field(
        default_factory=lambda: _readonly_vector(()),
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "family_keys", tuple(self.family_keys))
        object.__setattr__(self, "card_keys", tuple(self.card_keys))
        object.__setattr__(self, "scales", tuple(float(value) for value in self.scales))
        object.__setattr__(
            self,
            "phase_snrs",
            tuple(float(value) for value in self.phase_snrs),
        )
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "model", _readonly_vector(self.model))
        object.__setattr__(self, "residual", _readonly_vector(self.residual))


@dataclass(frozen=True, slots=True)
class JointPhaseCandidateGain:
    key: str
    family_key: str
    gain: float
    phase_snr: float
    supporting_family_keys: tuple[str, ...]
    reportable: bool
    rejection_reason: str = ""


@dataclass(frozen=True, slots=True)
class JointPhaseSearchResult:
    baseline: JointPhaseCombination
    combinations: tuple[JointPhaseCombination, ...]
    candidate_gains: tuple[JointPhaseCandidateGain, ...]
    evaluated_combinations: int
    elapsed_seconds: float


def search_phase_combinations(
    *,
    x: np.ndarray | Sequence[float],
    target: np.ndarray | Sequence[float],
    weights: np.ndarray | Sequence[float],
    candidates: Sequence[JointPhaseCandidate],
    required_keys: Collection[str] = (),
    config: JointPhaseSearchConfig | None = None,
) -> JointPhaseSearchResult:
    started = perf_counter()
    search_config = config or JointPhaseSearchConfig()
    x_values, target_values, weight_values, normalized = _validate_inputs(
        x=x,
        target=target,
        weights=weights,
        candidates=candidates,
        required_keys=required_keys,
        config=search_config,
    )
    required_key_set = set(str(key) for key in required_keys)
    required = tuple(
        sorted(
            (
                candidate
                for candidate in normalized
                if candidate.key in required_key_set
            ),
            key=lambda candidate: (candidate.family_key, candidate.key),
        )
    )
    baseline = _fit_combination(
        target=target_values,
        weights=weight_values,
        candidates=required,
        required_count=len(required),
        config=search_config,
    )
    accepted_families = {candidate.family_key for candidate in required}
    optional = tuple(
        sorted(
            (
                candidate
                for candidate in normalized
                if candidate.key not in required_key_set
                and candidate.family_key not in accepted_families
            ),
            key=lambda candidate: (candidate.family_key, candidate.key),
        )
    )
    if not np.any(target_values) or not optional or search_config.max_added_phases == 0:
        return JointPhaseSearchResult(
            baseline=baseline,
            combinations=(baseline,),
            candidate_gains=(),
            evaluated_combinations=1,
            elapsed_seconds=float(perf_counter() - started),
        )

    retained_states: list[
        tuple[JointPhaseCombination, tuple[JointPhaseCandidate, ...]]
    ] = [(baseline, required)]
    retained_combinations: list[JointPhaseCombination] = [baseline]
    best_edges: dict[str, JointPhaseCandidateGain] = {}
    evaluated_combinations = 1
    baseline_denominator = max(abs(baseline.score), np.finfo(float).eps)

    for _depth in range(search_config.max_added_phases):
        next_states: dict[
            tuple[str, ...],
            tuple[JointPhaseCombination, tuple[JointPhaseCandidate, ...]],
        ] = {}
        for parent, parent_candidates in retained_states:
            used_families = {candidate.family_key for candidate in parent_candidates}
            current_optional = parent_candidates[len(required):]
            for candidate in optional:
                if candidate.family_key in used_families:
                    continue
                child_optional = tuple(
                    sorted(
                        (*current_optional, candidate),
                        key=lambda item: (item.family_key, item.key),
                    )
                )
                child_candidates = (*required, *child_optional)
                child = _fit_combination(
                    target=target_values,
                    weights=weight_values,
                    candidates=child_candidates,
                    required_count=len(required),
                    config=search_config,
                )
                evaluated_combinations += 1
                candidate_index = child.card_keys.index(candidate.key)
                candidate_curve = child.scales[candidate_index] * candidate.profile
                candidate_snr = _phase_support_snr(
                    x=x_values,
                    residual_after=child.residual,
                    candidate=candidate,
                    candidate_curve=candidate_curve,
                    fwhm=_profile_fwhm(x_values, candidate.profile),
                )
                phase_snrs = list(child.phase_snrs)
                if len(phase_snrs) != len(child_candidates):
                    phase_snrs = [0.0] * len(child_candidates)
                phase_snrs[candidate_index] = candidate_snr
                child = JointPhaseCombination(
                    family_keys=child.family_keys,
                    card_keys=child.card_keys,
                    scales=child.scales,
                    score=child.score,
                    phase_snrs=tuple(phase_snrs),
                    model=child.model,
                    residual=child.residual,
                )

                improvement = parent.score - child.score
                relative_improvement = improvement / max(
                    abs(parent.score),
                    np.finfo(float).eps,
                )
                gain = max(100.0 * improvement / baseline_denominator, 0.0)
                if candidate_snr < search_config.minimum_phase_snr:
                    rejection_reason = "phase_snr_below_threshold"
                elif relative_improvement < search_config.minimum_relative_improvement:
                    rejection_reason = "minimum_improvement"
                elif gain < search_config.minimum_reported_gain:
                    rejection_reason = "gain_below_reporting_threshold"
                else:
                    rejection_reason = ""

                edge = JointPhaseCandidateGain(
                    key=candidate.key,
                    family_key=candidate.family_key,
                    gain=float(gain),
                    phase_snr=float(candidate_snr),
                    supporting_family_keys=tuple(sorted(child.family_keys)),
                    reportable=not rejection_reason,
                    rejection_reason=rejection_reason,
                )
                previous = best_edges.get(candidate.family_key)
                if previous is None or _gain_sort_key(edge) < _gain_sort_key(previous):
                    best_edges[candidate.family_key] = edge

                if rejection_reason in {
                    "phase_snr_below_threshold",
                    "minimum_improvement",
                }:
                    continue
                state_key = tuple(sorted(child.family_keys))
                existing = next_states.get(state_key)
                state = (child, tuple(child_candidates))
                if existing is None or _combination_sort_key(child) < _combination_sort_key(existing[0]):
                    next_states[state_key] = state

        retained_states = sorted(
            next_states.values(),
            key=lambda state: _combination_sort_key(state[0]),
        )[: search_config.beam_width]
        if not retained_states:
            break
        retained_combinations.extend(state[0] for state in retained_states)

    unique_combinations: dict[tuple[str, ...], JointPhaseCombination] = {}
    for combination in retained_combinations:
        key = tuple(sorted(combination.family_keys))
        current = unique_combinations.get(key)
        if current is None or _combination_sort_key(combination) < _combination_sort_key(current):
            unique_combinations[key] = combination
    combinations = tuple(
        sorted(unique_combinations.values(), key=_combination_sort_key)
    )
    candidate_gains = tuple(sorted(best_edges.values(), key=_gain_sort_key))
    return JointPhaseSearchResult(
        baseline=baseline,
        combinations=combinations,
        candidate_gains=candidate_gains,
        evaluated_combinations=evaluated_combinations,
        elapsed_seconds=float(perf_counter() - started),
    )


def _validate_inputs(
    *,
    x: np.ndarray | Sequence[float],
    target: np.ndarray | Sequence[float],
    weights: np.ndarray | Sequence[float],
    candidates: Sequence[JointPhaseCandidate],
    required_keys: Collection[str],
    config: JointPhaseSearchConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[JointPhaseCandidate, ...]]:
    x_values = np.asarray(x, dtype=float)
    target_values = np.asarray(target, dtype=float)
    weight_values = np.asarray(weights, dtype=float)
    if x_values.ndim != 1 or target_values.ndim != 1 or weight_values.ndim != 1:
        raise ValueError("x, target and weights must be one-dimensional")
    if target_values.shape != weight_values.shape:
        raise ValueError("target and weights must have identical shapes")
    if x_values.shape != target_values.shape:
        raise ValueError("x and target must have identical shapes")
    if not (
        np.all(np.isfinite(x_values))
        and np.all(np.isfinite(target_values))
        and np.all(np.isfinite(weight_values))
    ):
        raise ValueError("x, target and weights must contain only finite values")
    if np.any(weight_values < 0.0):
        raise ValueError("weights must be nonnegative")

    normalized = tuple(candidates)
    keys = [candidate.key for candidate in normalized]
    if len(keys) != len(set(keys)):
        raise ValueError("candidate keys must be unique")
    for candidate in normalized:
        if candidate.profile.ndim != 1 or candidate.profile.shape != target_values.shape:
            raise ValueError("candidate profile length must match target")
        if not np.all(np.isfinite(candidate.profile)):
            raise ValueError("candidate profiles must contain only finite values")
        if candidate.peak_positions.shape != candidate.peak_amplitudes.shape:
            raise ValueError("candidate peak positions and amplitudes must match")
        if not (
            np.all(np.isfinite(candidate.peak_positions))
            and np.all(np.isfinite(candidate.peak_amplitudes))
        ):
            raise ValueError("candidate peak data must contain only finite values")

    missing = sorted(set(str(key) for key in required_keys) - set(keys))
    if missing:
        raise ValueError(f"required candidate keys are missing: {', '.join(missing)}")
    if config.beam_width <= 0 or config.max_added_phases < 0:
        raise ValueError("beam limits must be positive")
    if (
        config.derivative_weight < 0.0
        or config.complexity_penalty < 0.0
        or config.excess_penalty < 0.0
        or config.minimum_phase_snr < 0.0
        or config.minimum_relative_improvement < 0.0
        or config.minimum_reported_gain < 0.0
    ):
        raise ValueError("search thresholds and score weights must be nonnegative")
    return x_values, target_values, weight_values, normalized


def _combination_sort_key(
    combination: JointPhaseCombination,
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    return (
        float(combination.score),
        tuple(sorted(combination.family_keys)),
        tuple(combination.card_keys),
    )


def _gain_sort_key(
    gain: JointPhaseCandidateGain,
) -> tuple[float, str, str]:
    return (-float(gain.gain), gain.family_key, gain.key)


def _profile_fwhm(x: np.ndarray, profile: np.ndarray) -> float:
    if len(x) < 2 or len(profile) != len(x):
        return 0.05
    finite = np.isfinite(x) & np.isfinite(profile)
    if np.count_nonzero(finite) < 2:
        return 0.05
    index = int(np.nanargmax(np.where(finite, profile, -np.inf)))
    maximum = float(profile[index])
    spacing = float(np.nanmedian(np.diff(x[finite])))
    fallback = max(abs(spacing), 0.05)
    if maximum <= 0.0:
        return fallback
    threshold = maximum * 0.5
    left = index
    while left > 0 and profile[left - 1] >= threshold:
        left -= 1
    right = index
    while right + 1 < len(profile) and profile[right + 1] >= threshold:
        right += 1
    if right == left:
        return fallback
    return max(float(abs(x[right] - x[left])), fallback)


def _phase_support_snr(
    *,
    x: np.ndarray,
    residual_after: np.ndarray,
    candidate: JointPhaseCandidate,
    candidate_curve: np.ndarray,
    fwhm: float,
) -> float:
    base_snr = phase_signal_to_noise(
        x=x,
        residual_after=residual_after,
        candidate_curve=candidate_curve,
        peak_positions=candidate.peak_positions,
        peak_amplitudes=candidate.peak_amplitudes,
        fwhm=fwhm,
    )
    if not len(x):
        return 0.0
    x_min = float(np.min(x))
    x_max = float(np.max(x))
    usable_lines = sum(
        1
        for position, amplitude in zip(
            candidate.peak_positions,
            candidate.peak_amplitudes,
            strict=False,
        )
        if np.isfinite(position)
        and np.isfinite(amplitude)
        and x_min <= float(position) <= x_max
        and float(amplitude) > 0.0
    )
    repeatability = np.sqrt(min(usable_lines, 3) / 3.0)
    return float(base_snr * repeatability)


def _fit_combination(
    *,
    target: np.ndarray,
    weights: np.ndarray,
    candidates: Sequence[JointPhaseCandidate],
    required_count: int,
    config: JointPhaseSearchConfig,
) -> JointPhaseCombination:
    if candidates:
        matrix = np.column_stack([candidate.profile for candidate in candidates])
        root_weights = np.sqrt(weights)
        weighted_matrix = matrix * root_weights[:, None]
        weighted_target = target * root_weights
        try:
            scales = nnls(weighted_matrix, weighted_target)[0]
        except (RuntimeError, ValueError, np.linalg.LinAlgError):
            scales = np.clip(
                np.linalg.lstsq(weighted_matrix, weighted_target, rcond=None)[0],
                0.0,
                None,
            )
        model = matrix @ scales
    else:
        scales = np.zeros(0, dtype=float)
        model = np.zeros_like(target)
    residual = target - model
    under = np.maximum(residual, 0.0)
    over = np.maximum(-residual, 0.0)
    denominator = max(float(np.dot(weights, target * target)), np.finfo(float).eps)
    profile_error = float(
        np.sum(weights * (under * under + config.excess_penalty * over * over))
        / denominator
    )
    target_gradient = np.diff(target)
    model_gradient = np.diff(model)
    derivative_denominator = max(
        float(np.sum(np.abs(target_gradient))),
        np.finfo(float).eps,
    )
    derivative_error = float(
        np.sum(np.abs(target_gradient - model_gradient)) / derivative_denominator
    )
    optional_phase_count = max(len(candidates) - int(required_count), 0)
    score = (
        profile_error
        + config.derivative_weight * derivative_error
        + config.complexity_penalty * optional_phase_count
    )
    return JointPhaseCombination(
        family_keys=tuple(candidate.family_key for candidate in candidates),
        card_keys=tuple(candidate.key for candidate in candidates),
        scales=tuple(float(value) for value in scales),
        score=score,
        model=model,
        residual=residual,
    )


__all__ = [
    "JointPhaseCandidate",
    "JointPhaseCandidateGain",
    "JointPhaseCombination",
    "JointPhaseSearchConfig",
    "JointPhaseSearchResult",
    "search_phase_combinations",
]
