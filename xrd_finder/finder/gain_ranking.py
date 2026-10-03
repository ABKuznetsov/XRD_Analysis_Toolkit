from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence

from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY, GainPolicy, GainStage


@dataclass(frozen=True, slots=True)
class GainQuery:
    before_fit: float
    direct_count: int
    overlap_count: int
    residual_line_count: int | None = None
    selected_phase_count: int = 1
    residual_share: float = 1.0


@dataclass(frozen=True, slots=True)
class GainCandidate:
    key: str
    direct_gain: float = 0.0
    overlap_gain: float = 0.0
    hidden_gain: float = 0.0
    profile_gain: float | None = None
    direct_reliability: float = 1.0
    phase_snr: float | None = None


@dataclass(frozen=True, slots=True)
class GainRankingResult:
    key: str
    gain: float
    dominant_evidence: GainStage
    limited_residual: bool


def rank_gain_candidates(
    query: GainQuery,
    candidates: Sequence[GainCandidate],
    policy: GainPolicy = DEFAULT_GAIN_POLICY,
) -> list[GainRankingResult]:
    residual_line_count = (
        int(query.residual_line_count)
        if query.residual_line_count is not None
        else int(query.direct_count) + int(query.overlap_count)
    )
    exhausted = policy.residual_is_exhausted(
        selected_phase_count=int(query.selected_phase_count),
        before_fit=float(query.before_fit),
        residual_share=float(query.residual_share),
    )
    results = []
    for candidate in candidates:
        overlap_dominance_weight = (
            policy.winner_overlap_weight
            if policy.evidence_combination in {"winner_corroboration", "winner_reliable_direct"}
            else policy.overlap_evidence_weight
        )
        weighted_evidence = (
            (max(float(candidate.direct_gain), 0.0), GainStage.DIRECT),
            (
                overlap_dominance_weight * max(float(candidate.overlap_gain), 0.0),
                GainStage.OVERLAP,
            ),
            (
                policy.hidden_evidence_weight * max(float(candidate.hidden_gain), 0.0),
                GainStage.HIDDEN,
            ),
        )
        dominant_evidence = max(weighted_evidence, key=lambda item: item[0])[1]
        if exhausted:
            gain = 0.0
        else:
            gain = policy.combine_evidence(
                direct_gain=candidate.direct_gain,
                overlap_gain=candidate.overlap_gain,
                hidden_gain=candidate.hidden_gain,
                profile_gain=candidate.profile_gain,
                remaining_fit=max(0.0, 100.0 - float(query.before_fit)),
                residual_line_count=residual_line_count,
                direct_reliability=candidate.direct_reliability,
                phase_snr=candidate.phase_snr,
            )
        results.append(
            GainRankingResult(
                candidate.key,
                float(gain),
                dominant_evidence,
                residual_line_count <= 2,
            )
        )
    return sorted(results, key=lambda result: (-result.gain, result.key))


__all__ = [
    "GainCandidate",
    "GainQuery",
    "GainRankingResult",
    "rank_gain_candidates",
]
