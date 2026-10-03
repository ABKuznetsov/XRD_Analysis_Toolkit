from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
from pathlib import Path
import sqlite3

from benchmarks.match.dataset import BenchmarkDataset
from benchmarks.match.bootstrap import paired_bootstrap
from benchmarks.match.extract_features import FeatureExtractionConfig, extract_match_features_parallel
from benchmarks.match.feature_cache import load_feature_matrix, save_feature_matrix
from benchmarks.match.metrics import evaluate_rankings, rank_feature_matrix
from benchmarks.match.scenarios import ScenarioConfig, build_scenario_manifest
from benchmarks.match.splits import assign_split_families
from xrd_finder.finder.fingerprint_matching import DEFAULT_MATCH_WEIGHTS


@dataclass(frozen=True, slots=True)
class ParameterSetting:
    dimension: str
    value: str
    distance_scale: float = 1.0
    max_observed_lines: int = 48
    max_reference_lines: int = 64
    line_tolerance: float = 0.55


def default_parameter_settings() -> tuple[ParameterSetting, ...]:
    settings = []
    settings.extend(
        ParameterSetting("peak_distance", f"{0.11 * scale:.3f}", distance_scale=scale)
        for scale in (0.5, 1.0, 1.5, 2.0)
    )
    settings.extend(
        ParameterSetting("observed_lines", str(value), max_observed_lines=value)
        for value in (10, 20, 32, 48)
    )
    settings.extend(
        ParameterSetting("reference_lines", str(value), max_reference_lines=value)
        for value in (16, 32, 48, 64)
    )
    settings.extend(
        ParameterSetting("position_tolerance", f"{value:.2f}", line_tolerance=value)
        for value in (0.25, 0.40, 0.55, 0.75)
    )
    return tuple(settings)


def run_parameter_sensitivity(
    dataset_path: Path,
    output_dir: Path,
    *,
    workers: int = 1,
) -> Path:
    with BenchmarkDataset.open(dataset_path) as dataset:
        phases = dataset.phase_descriptors()
        references = dataset.reference_library()
    assignments = assign_split_families(phases, seed=5036)
    all_scenarios = build_scenario_manifest(phases, assignments, ScenarioConfig(seed=5036))
    validation = tuple(item for item in all_scenarios if item.split == "validation")
    scenarios = _balanced_sample(validation)
    family_by_phase = {phase.phase_id: phase.family_id for phase in phases}
    dataset_hash = _sha256(dataset_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for setting in default_parameter_settings():
        cache_key = hashlib.sha256(
            f"{dataset_hash}:parameter-v1:{setting!r}:{scenarios!r}".encode("utf-8")
        ).hexdigest()
        cache_path = output_dir / f"{setting.dimension}-{setting.value}.sqlite"
        try:
            matrix = load_feature_matrix(cache_path, expected_cache_key=cache_key)
        except (OSError, ValueError, sqlite3.Error):
            print(f"Evaluating {setting.dimension}={setting.value}", flush=True)
            matrix = extract_match_features_parallel(
                references,
                family_by_phase,
                scenarios,
                workers=workers,
                max_reference_lines=setting.max_reference_lines,
                max_observed_lines=setting.max_observed_lines,
                line_tolerance_two_theta=setting.line_tolerance,
                config=FeatureExtractionConfig(detector_distance_scale=setting.distance_scale),
            )
            save_feature_matrix(cache_path, matrix, cache_key=cache_key)
        metrics = evaluate_rankings(rank_feature_matrix(matrix, DEFAULT_MATCH_WEIGHTS))
        rows.append(
            {
                **asdict(setting),
                "prominent_peak_distance_deg": 0.11 * setting.distance_scale,
                "height_peak_distance_deg": 0.045 * setting.distance_scale,
                **asdict(metrics),
            }
        )
    output = output_dir / "parameter_sensitivity.csv"
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    selected = _select_validation_settings(rows)
    baseline = ParameterSetting("combined", "baseline")
    combined = ParameterSetting(
        "combined",
        "validation-selected",
        distance_scale=selected["peak_distance"].distance_scale,
        max_observed_lines=selected["observed_lines"].max_observed_lines,
        max_reference_lines=selected["reference_lines"].max_reference_lines,
        line_tolerance=selected["position_tolerance"].line_tolerance,
    )
    test_scenarios = tuple(item for item in all_scenarios if item.split == "test")
    confirmation = []
    confirmation_rankings = []
    for setting in (baseline, combined):
        matrix = _load_or_extract(
            output_dir / f"test-{setting.value}.sqlite",
            dataset_hash,
            setting,
            test_scenarios,
            references,
            family_by_phase,
            workers,
        )
        rankings = rank_feature_matrix(matrix, DEFAULT_MATCH_WEIGHTS)
        confirmation_rankings.append(rankings)
        metrics = evaluate_rankings(rankings)
        confirmation.append({**asdict(setting), **asdict(metrics)})
    confirmation_path = output_dir / "selected_parameter_test.csv"
    with confirmation_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(confirmation[0]))
        writer.writeheader()
        writer.writerows(confirmation)
    intervals_path = output_dir / "selected_parameter_bootstrap.csv"
    metric_vectors = {
        "mrr": lambda item: 1.0 / item.dominant_rank,
        "top1": lambda item: float(item.dominant_rank <= 1),
        "top5": lambda item: float(item.dominant_rank <= 5),
        "top10": lambda item: float(item.dominant_rank <= 10),
        "mixture_recall10": lambda item: len(set(item.true_families).intersection(item.ranked_families[:10])) / max(len(set(item.true_families)), 1),
    }
    interval_rows = []
    for metric, value_for in metric_vectors.items():
        interval = paired_bootstrap(
            tuple(value_for(item) for item in confirmation_rankings[0]),
            tuple(value_for(item) for item in confirmation_rankings[1]),
        )
        interval_rows.append({"metric": metric, **asdict(interval)})
    with intervals_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(interval_rows[0]))
        writer.writeheader()
        writer.writerows(interval_rows)
    return output


def _select_validation_settings(rows):
    baseline = {
        "peak_distance": 0.110,
        "observed_lines": 48.0,
        "reference_lines": 64.0,
        "position_tolerance": 0.55,
    }
    selected = {}
    for dimension, base in baseline.items():
        candidates = [row for row in rows if row["dimension"] == dimension]
        best = max(
            candidates,
            key=lambda row: (
                row["mrr"],
                row["top5"],
                row["mixture_recall10"],
                -abs(float(row["value"]) - base),
            ),
        )
        selected[dimension] = ParameterSetting(
            dimension=dimension,
            value=str(best["value"]),
            distance_scale=float(best["distance_scale"]),
            max_observed_lines=int(best["max_observed_lines"]),
            max_reference_lines=int(best["max_reference_lines"]),
            line_tolerance=float(best["line_tolerance"]),
        )
    return selected


def _load_or_extract(
    cache_path,
    dataset_hash,
    setting,
    scenarios,
    references,
    family_by_phase,
    workers,
):
    cache_key = hashlib.sha256(
        f"{dataset_hash}:parameter-test-v1:{setting!r}:{scenarios!r}".encode("utf-8")
    ).hexdigest()
    try:
        return load_feature_matrix(cache_path, expected_cache_key=cache_key)
    except (OSError, ValueError, sqlite3.Error):
        print(f"Confirming {setting.value} on held-out test", flush=True)
        matrix = extract_match_features_parallel(
            references,
            family_by_phase,
            scenarios,
            workers=workers,
            max_reference_lines=setting.max_reference_lines,
            max_observed_lines=setting.max_observed_lines,
            line_tolerance_two_theta=setting.line_tolerance,
            config=FeatureExtractionConfig(detector_distance_scale=setting.distance_scale),
        )
        save_feature_matrix(cache_path, matrix, cache_key=cache_key)
        return matrix


def _balanced_sample(scenarios):
    grouped = {}
    for scenario in scenarios:
        grouped.setdefault((scenario.fwhm, scenario.noise), []).append(scenario)
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
    parser = argparse.ArgumentParser(description="Run Match parameter sensitivity analysis.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/match-parameter-sensitivity"))
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    output = run_parameter_sensitivity(args.dataset, args.output, workers=args.workers)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ParameterSetting", "default_parameter_settings", "run_parameter_sensitivity"]
