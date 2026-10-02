from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

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


def evaluate_joint_gain(
    *,
    x: np.ndarray,
    target: np.ndarray,
    weights: np.ndarray,
    profiles: Mapping[str, np.ndarray],
    references: Mapping[str, Sequence[ReferenceLine]],
    pool: JointGainCandidatePool,
    config: JointPhaseSearchConfig | None = None,
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
    result = search_phase_combinations(
        x=np.asarray(x, dtype=float),
        target=np.asarray(target, dtype=float),
        weights=np.asarray(weights, dtype=float),
        candidates=candidates,
        required_keys=pool.required_ids,
        config=config,
    )
    reportable = tuple(gain for gain in result.candidate_gains if gain.reportable)
    return JointGainEvaluation(
        search_result=result,
        ranked_phase_ids=tuple(gain.key for gain in reportable),
        ranked_family_keys=tuple(gain.family_key for gain in reportable),
    )


__all__ = [
    "JointGainEvaluation",
    "build_joint_candidate_pool",
    "evaluate_joint_gain",
]
