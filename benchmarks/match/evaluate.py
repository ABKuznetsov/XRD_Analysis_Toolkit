from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import hashlib
from pathlib import Path
from collections.abc import Mapping
from collections import defaultdict
import sqlite3

from benchmarks.match.dataset import BenchmarkDataset
from benchmarks.match.bootstrap import paired_bootstrap
from benchmarks.match.adaptive_weights import optimize_weights_by_stratum
from benchmarks.match.extract_features import (
    FeatureExtractionConfig,
    FeatureMatrix,
    extract_match_features,
    extract_match_features_parallel,
)
from benchmarks.match.feature_cache import load_feature_matrix, save_feature_matrix
from benchmarks.match.metrics import RankingMetrics, evaluate_rankings, rank_feature_matrix
from benchmarks.match.optimize_weights import WeightSearchConfig, optimize_weights
from benchmarks.match.report import (
    summarize_timings,
    write_comparison_csv,
    write_selected_weights,
    write_summary,
    write_timing_csv,
    write_sensitivity_csv,
    write_adaptive_weights_csv,
)
from benchmarks.match.scenarios import ScenarioConfig, build_scenario_manifest
from benchmarks.match.splits import assign_split_families
from xrd_finder.finder.fingerprint_matching import DEFAULT_MATCH_WEIGHTS, MatchWeights


MANUSCRIPT_WEIGHTS = MatchWeights(0.62, 0.25, 0.08, 0.05)
EQUAL_WEIGHTS = MatchWeights(0.25, 0.25, 0.25, 0.25)


def _weight_sets(selected_weights: MatchWeights) -> Mapping[str, MatchWeights]:
    return {
        "manuscript": MANUSCRIPT_WEIGHTS,
        "current": DEFAULT_MATCH_WEIGHTS,
        "equal": EQUAL_WEIGHTS,
        "selected": selected_weights,
    }


def compare_weight_sets(
    test_matrix: FeatureMatrix,
    selected_weights: MatchWeights,
) -> dict[str, RankingMetrics]:
    weights = _weight_sets(selected_weights)
    return {
        label: evaluate_rankings(rank_feature_matrix(test_matrix, vector))
        for label, vector in weights.items()
    }


def compare_weight_sets_by_stratum(
    test_matrix: FeatureMatrix,
    selected_weights: MatchWeights,
) -> dict[tuple[str, str, str], RankingMetrics]:
    result = {}
    for label, weights in _weight_sets(selected_weights).items():
        rankings = rank_feature_matrix(test_matrix, weights)
        for dimension in ("noise", "fwhm", "phases", "overlap"):
            grouped = defaultdict(list)
            for ranking in rankings:
                values = _parse_stratum(ranking.stratum)
                grouped[values.get(dimension, "unknown")].append(ranking)
            for value, items in grouped.items():
                result[(dimension, value, label)] = evaluate_rankings(tuple(items))
    return result


def _parse_stratum(text: str) -> dict[str, str]:
    return {
        key: value
        for item in str(text).split(";")
        if "=" in item
        for key, value in (item.split("=", 1),)
    }


def run_benchmark(
    dataset_path: Path,
    output_dir: Path,
    *,
    smoke: bool = False,
    workers: int = 1,
    adaptive_tolerance: bool = False,
) -> Path:
    with BenchmarkDataset.open(dataset_path) as dataset:
        phases = dataset.phase_descriptors()
        references = dataset.reference_library()
    assignments = assign_split_families(phases, seed=5036)
    scenarios = build_scenario_manifest(phases, assignments, ScenarioConfig(seed=5036))
    if smoke:
        scenarios = tuple(scenario for index, scenario in enumerate(scenarios) if index % 2 == 0)
    family_by_phase = {phase.phase_id: phase.family_id for phase in phases}
    digest = _sha256(dataset_path)
    cache_key = hashlib.sha256(
        f"{digest}:extract-v4-production-peaks:adaptive={adaptive_tolerance}:{scenarios!r}".encode("utf-8")
    ).hexdigest()
    extraction_config = FeatureExtractionConfig(
        adaptive_line_tolerance=bool(adaptive_tolerance),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    feature_cache = output_dir / "feature_matrix.sqlite"
    if feature_cache.exists():
        try:
            matrix = load_feature_matrix(feature_cache, expected_cache_key=cache_key)
            print(f"Loaded {len(matrix.query_ids())} cached query matrices from {feature_cache}")
        except (OSError, ValueError):
            matrix = _extract_and_cache(
                feature_cache, cache_key, references, family_by_phase, scenarios,
                workers=workers, config=extraction_config,
            )
    else:
        matrix = _extract_and_cache(
            feature_cache, cache_key, references, family_by_phase, scenarios,
            workers=workers, config=extraction_config,
        )
    timing_matrix = matrix
    if workers > 1:
        runtime_scenarios = _runtime_sample(scenarios)
        runtime_key = hashlib.sha256(
            f"{cache_key}:single-process-runtime-v1:{runtime_scenarios!r}".encode("utf-8")
        ).hexdigest()
        runtime_cache = output_dir / "runtime_feature_matrix.sqlite"
        try:
            timing_matrix = load_feature_matrix(runtime_cache, expected_cache_key=runtime_key)
        except (OSError, ValueError, sqlite3.Error):
            timing_matrix = _extract_and_cache(
                runtime_cache,
                runtime_key,
                references,
                family_by_phase,
                runtime_scenarios,
                workers=1,
                config=extraction_config,
            )
    fit_matrix = matrix.select_splits(("train", "validation"))
    config = (
        WeightSearchConfig(coarse_step=0.10, refinement_step=0.02, refinement_radius=0.10)
        if smoke
        else WeightSearchConfig()
    )
    selection = optimize_weights(fit_matrix, config)
    test_matrix = matrix.select_splits(("test",))
    comparison = compare_weight_sets(test_matrix, selection.weights)
    write_selected_weights(
        output_dir / "selected_weights.json",
        digest,
        selection.weights,
        selection.train_metrics,
        selection.validation_metrics,
    )
    write_comparison_csv(output_dir / "comparison.csv", comparison)
    _write_weight_bootstrap(output_dir / "weight_bootstrap.csv", test_matrix, selection.weights)
    write_sensitivity_csv(
        output_dir / "sensitivity.csv",
        compare_weight_sets_by_stratum(test_matrix, selection.weights),
    )
    write_adaptive_weights_csv(
        output_dir / "adaptive_weights.csv",
        optimize_weights_by_stratum(matrix),
    )
    write_timing_csv(output_dir / "query_timings.csv", timing_matrix.timings)
    return write_summary(
        output_dir / "summary.md",
        digest,
        selection.weights,
        comparison,
        summarize_timings(timing_matrix.timings, workload_query_count=len(scenarios)),
    )


def _write_weight_bootstrap(path: Path, matrix: FeatureMatrix, selected: MatchWeights) -> None:
    current = rank_feature_matrix(matrix, DEFAULT_MATCH_WEIGHTS)
    proposed = rank_feature_matrix(matrix, selected)
    value_functions = {
        "mrr": lambda item: 1.0 / item.dominant_rank,
        "top1": lambda item: float(item.dominant_rank <= 1),
        "top5": lambda item: float(item.dominant_rank <= 5),
        "top10": lambda item: float(item.dominant_rank <= 10),
        "mixture_recall10": lambda item: len(
            set(item.true_families).intersection(item.ranked_families[:10])
        ) / max(len(set(item.true_families)), 1),
    }
    rows = []
    for metric, value_for in value_functions.items():
        interval = paired_bootstrap(
            tuple(value_for(item) for item in current),
            tuple(value_for(item) for item in proposed),
        )
        rows.append({"metric": metric, **asdict(interval)})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _extract_and_cache(
    feature_cache,
    cache_key,
    references,
    family_by_phase,
    scenarios,
    *,
    workers,
    config,
):
    def show_progress(done, total, timing):
        print(
            f"Pattern {done}/{total}: {timing.total_seconds:.2f} s "
            f"({timing.candidate_count} candidates, {timing.refined_count} refined)",
            flush=True,
        )

    if workers > 1:
        print(f"Extracting {len(scenarios)} patterns with {workers} workers", flush=True)
        matrix = extract_match_features_parallel(
            references,
            family_by_phase,
            scenarios,
            workers=workers,
            config=config,
        )
        print(f"Extracted {len(scenarios)} patterns", flush=True)
    else:
        matrix = extract_match_features(
            references,
            family_by_phase,
            scenarios,
            progress=show_progress,
            config=config,
        )
    save_feature_matrix(feature_cache, matrix, cache_key=cache_key)
    return matrix


def _runtime_sample(scenarios):
    grouped = defaultdict(list)
    for scenario in scenarios:
        grouped[(scenario.fwhm, scenario.noise)].append(scenario)
    return tuple(
        grouped[key][index % len(grouped[key])]
        for index, key in enumerate(sorted(grouped))
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Match benchmark.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/match-benchmark"))
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--adaptive-tolerance", action="store_true")
    args = parser.parse_args()
    summary = run_benchmark(
        args.dataset,
        args.output,
        smoke=args.smoke,
        workers=args.workers,
        adaptive_tolerance=args.adaptive_tolerance,
    )
    print(f"Wrote {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["compare_weight_sets", "compare_weight_sets_by_stratum", "run_benchmark"]
