from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from benchmarks.match.extract_features import FeatureMatrix
from benchmarks.match.metrics import QueryRanking, RankingMetrics, evaluate_rankings
from xrd_finder.finder.fingerprint_matching import MatchWeights, apply_match_weights


def rank_tolerance_blend(
    fixed: FeatureMatrix,
    adaptive: FeatureMatrix,
    weights: MatchWeights,
    alpha: float,
) -> tuple[QueryRanking, ...]:
    blend = max(0.0, min(float(alpha), 1.0))
    adaptive_rows = {
        (row.query_id, row.candidate_id): row
        for row in adaptive.rows
    }
    grouped = defaultdict(list)
    for row in fixed.rows:
        other = adaptive_rows.get((row.query_id, row.candidate_id))
        if other is None:
            raise ValueError("Fixed and adaptive matrices do not contain identical candidates.")
        fixed_score = apply_match_weights(row.features, weights)
        adaptive_score = apply_match_weights(other.features, weights)
        grouped[row.query_id].append((row, (1.0 - blend) * fixed_score + blend * adaptive_score))

    rankings = []
    for query_id in sorted(grouped):
        values = grouped[query_id]
        family_scores: dict[str, float] = {}
        for row, score in values:
            family_scores[row.candidate_family] = max(
                score,
                family_scores.get(row.candidate_family, float("-inf")),
            )
        ranked = tuple(
            family
            for family, _score in sorted(family_scores.items(), key=lambda item: (-item[1], item[0]))
        )
        template = values[0][0]
        rank = ranked.index(template.dominant_family) + 1
        rankings.append(
            QueryRanking(
                query_id=query_id,
                ranked_families=ranked,
                dominant_family=template.dominant_family,
                true_families=template.true_families,
                split=template.split,
                stratum=template.stratum,
                dominant_rank=rank,
            )
        )
    return tuple(rankings)


def select_blend_alpha(
    fixed_validation: FeatureMatrix,
    adaptive_validation: FeatureMatrix,
    weights: MatchWeights,
    values: Sequence[float],
) -> tuple[float, RankingMetrics]:
    evaluated = [
        (
            float(alpha),
            evaluate_rankings(
                rank_tolerance_blend(fixed_validation, adaptive_validation, weights, alpha)
            ),
        )
        for alpha in values
    ]
    return max(
        evaluated,
        key=lambda item: (
            item[1].mrr,
            item[1].top5,
            item[1].mixture_recall10,
            -item[0],
        ),
    )


__all__ = ["rank_tolerance_blend", "select_blend_alpha"]
