from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

from benchmarks.match.extract_features import FeatureMatrix
from xrd_finder.finder.fingerprint_matching import MatchWeights, apply_match_weights


@dataclass(frozen=True, slots=True)
class QueryRanking:
    query_id: str
    ranked_families: tuple[str, ...]
    dominant_family: str
    true_families: tuple[str, ...]
    split: str
    stratum: str
    dominant_rank: int


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    query_count: int
    mrr: float
    top1: float
    top5: float
    top10: float
    mixture_recall5: float
    mixture_recall10: float


def rank_feature_matrix(matrix: FeatureMatrix, weights: MatchWeights) -> tuple[QueryRanking, ...]:
    grouped = defaultdict(list)
    for row in matrix.rows:
        grouped[row.query_id].append(row)
    rankings = []
    for query_id in sorted(grouped):
        rows = grouped[query_id]
        family_scores: dict[str, float] = {}
        for row in rows:
            score = apply_match_weights(row.features, weights)
            family_scores[row.candidate_family] = max(score, family_scores.get(row.candidate_family, float("-inf")))
        ranked = tuple(family for family, _score in sorted(family_scores.items(), key=lambda item: (-item[1], item[0])))
        dominant = rows[0].dominant_family
        dominant_rank = ranked.index(dominant) + 1 if dominant in ranked else len(ranked) + 1
        rankings.append(
            QueryRanking(
                query_id=query_id,
                ranked_families=ranked,
                dominant_family=dominant,
                true_families=rows[0].true_families,
                split=rows[0].split,
                stratum=rows[0].stratum,
                dominant_rank=dominant_rank,
            )
        )
    return tuple(rankings)


def evaluate_rankings(rankings: tuple[QueryRanking, ...]) -> RankingMetrics:
    count = len(rankings)
    if not count:
        return RankingMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ranks = [item.dominant_rank for item in rankings]
    recall5 = []
    recall10 = []
    for item in rankings:
        true = set(item.true_families)
        recall5.append(len(true.intersection(item.ranked_families[:5])) / max(len(true), 1))
        recall10.append(len(true.intersection(item.ranked_families[:10])) / max(len(true), 1))
    return RankingMetrics(
        query_count=count,
        mrr=sum(1.0 / rank for rank in ranks) / count,
        top1=sum(rank <= 1 for rank in ranks) / count,
        top5=sum(rank <= 5 for rank in ranks) / count,
        top10=sum(rank <= 10 for rank in ranks) / count,
        mixture_recall5=sum(recall5) / count,
        mixture_recall10=sum(recall10) / count,
    )


__all__ = ["QueryRanking", "RankingMetrics", "evaluate_rankings", "rank_feature_matrix"]
