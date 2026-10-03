from __future__ import annotations

from dataclasses import dataclass
import argparse
from pathlib import Path
from collections import defaultdict

import numpy as np

from benchmarks.match.extract_features import FeatureMatrix
from benchmarks.match.metrics import RankingMetrics, evaluate_rankings, rank_feature_matrix
from xrd_finder.finder.fingerprint_matching import MatchWeights


@dataclass(frozen=True, slots=True)
class WeightSearchConfig:
    coarse_step: float = 0.025
    refinement_step: float = 0.005
    refinement_radius: float = 0.025


@dataclass(frozen=True, slots=True)
class WeightSelection:
    weights: MatchWeights
    train_metrics: RankingMetrics
    validation_metrics: RankingMetrics
    evaluated_vectors: int


def optimize_weights(matrix: FeatureMatrix, config: WeightSearchConfig = WeightSearchConfig()) -> WeightSelection:
    if any(row.split == "test" for row in matrix.rows):
        raise ValueError("Held-out test rows cannot be supplied to weight optimization.")
    train = matrix.select_splits(("train",))
    validation = matrix.select_splits(("validation",))
    if not train.rows or not validation.rows:
        raise ValueError("Weight optimization requires both train and validation queries.")
    candidates = list(_simplex(config.coarse_step))
    best = _select_best(candidates, validation)
    refined = list(_local_simplex(best, config.refinement_step, config.refinement_radius))
    best = _select_best(refined, validation)
    return WeightSelection(
        weights=best,
        train_metrics=evaluate_rankings(rank_feature_matrix(train, best)),
        validation_metrics=evaluate_rankings(rank_feature_matrix(validation, best)),
        evaluated_vectors=len(candidates) + len(refined),
    )


def _select_best(candidates: list[MatchWeights], matrix: FeatureMatrix) -> MatchWeights:
    if not candidates:
        raise ValueError("At least one weight vector is required.")
    objectives = _vectorized_objectives(candidates, matrix)
    return max(
        zip(objectives, candidates, strict=True),
        key=lambda item: (
            item[0][0],
            item[0][1],
            item[0][2],
            tuple(-value for value in item[1].as_tuple()),
        ),
    )[1]


def _vectorized_objectives(
    candidates: list[MatchWeights],
    matrix: FeatureMatrix,
    *,
    chunk_size: int = 256,
) -> list[tuple[float, float, float]]:
    grouped = defaultdict(list)
    for row in matrix.rows:
        grouped[row.query_id].append(row)
    count = len(grouped)
    if count == 0:
        return [(0.0, 0.0, 0.0) for _candidate in candidates]

    weight_matrix = np.asarray([item.as_tuple() for item in candidates], dtype=float)
    mrr = np.zeros(len(candidates), dtype=float)
    top5 = np.zeros(len(candidates), dtype=float)
    recall10 = np.zeros(len(candidates), dtype=float)
    for start in range(0, len(candidates), max(1, int(chunk_size))):
        stop = min(start + max(1, int(chunk_size)), len(candidates))
        weights = weight_matrix[start:stop]
        local_mrr = np.zeros(stop - start, dtype=float)
        local_top5 = np.zeros(stop - start, dtype=float)
        local_recall10 = np.zeros(stop - start, dtype=float)
        for rows in grouped.values():
            families = sorted({row.candidate_family for row in rows})
            family_index = {family: index for index, family in enumerate(families)}
            order = np.argsort(
                np.asarray([family_index[row.candidate_family] for row in rows], dtype=int),
                kind="stable",
            )
            ordered_groups = np.asarray(
                [family_index[rows[index].candidate_family] for index in order],
                dtype=int,
            )
            starts = np.flatnonzero(np.r_[True, ordered_groups[1:] != ordered_groups[:-1]])
            feature_values = np.asarray(
                [
                    (
                        rows[index].features.observed_coverage,
                        rows[index].features.reference_coverage,
                        rows[index].features.sufficient_lines,
                        rows[index].features.alignment_seed,
                    )
                    for index in order
                ],
                dtype=float,
            )
            caps = np.asarray([_score_cap(rows[index].features) for index in order], dtype=float)
            scores = np.minimum(100.0 * feature_values @ weights.T, caps[:, None])
            family_scores = np.maximum.reduceat(scores, starts, axis=0)
            ranked = np.argsort(-family_scores, axis=0, kind="stable")
            dominant_index = family_index[rows[0].dominant_family]
            dominant_ranks = np.argmax(ranked == dominant_index, axis=0) + 1
            local_mrr += 1.0 / dominant_ranks
            local_top5 += dominant_ranks <= 5
            true_indices = np.asarray(
                [family_index[family] for family in rows[0].true_families if family in family_index],
                dtype=int,
            )
            if len(true_indices):
                top_ten = ranked[:10]
                local_recall10 += np.isin(top_ten, true_indices).sum(axis=0) / len(true_indices)
        mrr[start:stop] = local_mrr / count
        top5[start:stop] = local_top5 / count
        recall10[start:stop] = local_recall10 / count
    return list(zip(mrr.tolist(), top5.tolist(), recall10.tolist(), strict=True))


def _score_cap(features) -> float:
    anchor_fraction = features.observed_matched / max(features.anchor_count, 1)
    if features.observed_matched < 3 or anchor_fraction < 0.22:
        return 28.0
    if features.observed_matched < 4 or anchor_fraction < 0.32:
        return 48.0
    if features.reference_matched < 3:
        return 52.0
    return 100.0


def _simplex(step: float):
    units = round(1.0 / float(step))
    if units <= 0 or abs(units * step - 1.0) > 1.0e-9:
        raise ValueError("Simplex step must divide one exactly.")
    for first in range(units + 1):
        for second in range(units - first + 1):
            for third in range(units - first - second + 1):
                fourth = units - first - second - third
                yield MatchWeights(first / units, second / units, third / units, fourth / units)


def _local_simplex(center: MatchWeights, step: float, radius: float):
    seen = set()
    for weights in _simplex(step):
        if max(abs(value - base) for value, base in zip(weights.as_tuple(), center.as_tuple(), strict=True)) > radius + 1.0e-12:
            continue
        key = tuple(round(value, 12) for value in weights.as_tuple())
        if key not in seen:
            seen.add(key)
            yield weights
    if not seen:
        yield center


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize Match weights from a cached feature matrix.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.parse_args()
    raise SystemExit("Feature extraction must be run before weight optimization.")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WeightSearchConfig", "WeightSelection", "optimize_weights"]
