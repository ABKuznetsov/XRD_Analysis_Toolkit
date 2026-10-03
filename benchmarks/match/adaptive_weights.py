from __future__ import annotations

from dataclasses import dataclass

from benchmarks.match.extract_features import FeatureMatrix
from benchmarks.match.metrics import RankingMetrics, evaluate_rankings, rank_feature_matrix
from benchmarks.match.optimize_weights import WeightSearchConfig, optimize_weights
from xrd_finder.finder.fingerprint_matching import MatchWeights


@dataclass(frozen=True, slots=True)
class StratumWeightResult:
    dimension: str
    value: str
    weights: MatchWeights
    train_queries: int
    validation_queries: int
    test_metrics: RankingMetrics


def optimize_weights_by_stratum(
    matrix: FeatureMatrix,
    *,
    dimensions: tuple[str, ...] = ("fwhm", "noise", "phases"),
    config: WeightSearchConfig = WeightSearchConfig(0.05, 0.01, 0.05),
) -> tuple[StratumWeightResult, ...]:
    results = []
    for dimension in dimensions:
        values = sorted(
            {
                _parse_stratum(row.stratum).get(dimension, "unknown")
                for row in matrix.rows
            }
        )
        for value in values:
            subset = FeatureMatrix(
                tuple(
                    row
                    for row in matrix.rows
                    if _parse_stratum(row.stratum).get(dimension, "unknown") == value
                )
            )
            fit = subset.select_splits(("train", "validation"))
            if not fit.select_splits(("train",)).rows or not fit.select_splits(("validation",)).rows:
                continue
            selection = optimize_weights(fit, config)
            test = subset.select_splits(("test",))
            metrics = evaluate_rankings(rank_feature_matrix(test, selection.weights))
            results.append(
                StratumWeightResult(
                    dimension=dimension,
                    value=value,
                    weights=selection.weights,
                    train_queries=len(fit.select_splits(("train",)).query_ids()),
                    validation_queries=len(fit.select_splits(("validation",)).query_ids()),
                    test_metrics=metrics,
                )
            )
    return tuple(results)


def _parse_stratum(text: str) -> dict[str, str]:
    return {
        key: value
        for item in str(text).split(";")
        if "=" in item
        for key, value in (item.split("=", 1),)
    }


__all__ = ["StratumWeightResult", "optimize_weights_by_stratum"]
