from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Collection, Sequence

import numpy as np


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
    x_values, target_values, weight_values, normalized = _validate_inputs(
        x=x,
        target=target,
        weights=weights,
        candidates=candidates,
        required_keys=required_keys,
        config=config or JointPhaseSearchConfig(),
    )
    required = tuple(
        candidate for candidate in normalized if candidate.key in set(required_keys)
    )
    baseline = _required_baseline(
        target=target_values,
        weights=weight_values,
        required=required,
    )
    if not np.any(target_values) or len(required) == len(normalized):
        return JointPhaseSearchResult(
            baseline=baseline,
            combinations=(baseline,),
            candidate_gains=(),
            evaluated_combinations=1,
            elapsed_seconds=float(perf_counter() - started),
        )
    return JointPhaseSearchResult(
        baseline=baseline,
        combinations=(baseline,),
        candidate_gains=(),
        evaluated_combinations=1,
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
    return x_values, target_values, weight_values, normalized


def _required_baseline(
    *,
    target: np.ndarray,
    weights: np.ndarray,
    required: Sequence[JointPhaseCandidate],
) -> JointPhaseCombination:
    if required:
        matrix = np.column_stack([candidate.profile for candidate in required])
        root_weights = np.sqrt(weights)
        weighted_matrix = matrix * root_weights[:, None]
        weighted_target = target * root_weights
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
    denominator = max(float(np.dot(weights, target * target)), np.finfo(float).eps)
    score = float(np.dot(weights, residual * residual) / denominator)
    if not np.any(target):
        score = 0.0
    return JointPhaseCombination(
        family_keys=tuple(candidate.family_key for candidate in required),
        card_keys=tuple(candidate.key for candidate in required),
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
