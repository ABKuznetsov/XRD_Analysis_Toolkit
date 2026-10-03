from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import csv
import json
from pathlib import Path
from collections.abc import Mapping

from benchmarks.match.metrics import RankingMetrics
from benchmarks.match.extract_features import QueryTiming
from benchmarks.match.adaptive_weights import StratumWeightResult
from xrd_finder.finder.fingerprint_matching import MatchWeights


@dataclass(frozen=True, slots=True)
class TimingSummary:
    query_count: int
    workload_query_count: int
    median_candidate_count: int
    median_refined_count: int
    total_pattern_seconds: float
    mean_total_seconds: float
    median_total_seconds: float
    p95_total_seconds: float
    median_retrieval_seconds: float
    median_quick_seconds: float
    median_refine_seconds: float
    median_quick_ms_per_candidate: float
    median_refine_ms_per_candidate: float
    estimated_workload_seconds: float


def summarize_timings(
    timings: tuple[QueryTiming, ...],
    *,
    workload_query_count: int | None = None,
) -> TimingSummary:
    workload_count = len(timings) if workload_query_count is None else int(workload_query_count)
    if not timings:
        return TimingSummary(0, workload_count, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ordered_total = sorted(item.total_seconds for item in timings)
    median_total = _percentile(ordered_total, 0.50)
    quick_ms_per_candidate = sorted(
        1000.0 * item.quick_seconds / max(1, item.candidate_count) for item in timings
    )
    refine_ms_per_candidate = sorted(
        1000.0 * item.refine_seconds / max(1, item.refined_count) for item in timings
    )
    return TimingSummary(
        query_count=len(timings),
        workload_query_count=workload_count,
        median_candidate_count=round(_percentile(sorted(item.candidate_count for item in timings), 0.50)),
        median_refined_count=round(_percentile(sorted(item.refined_count for item in timings), 0.50)),
        total_pattern_seconds=sum(ordered_total),
        mean_total_seconds=sum(ordered_total) / len(ordered_total),
        median_total_seconds=median_total,
        p95_total_seconds=_percentile(ordered_total, 0.95),
        median_retrieval_seconds=_percentile(sorted(item.retrieval_seconds for item in timings), 0.50),
        median_quick_seconds=_percentile(sorted(item.quick_seconds for item in timings), 0.50),
        median_refine_seconds=_percentile(sorted(item.refine_seconds for item in timings), 0.50),
        median_quick_ms_per_candidate=_percentile(quick_ms_per_candidate, 0.50),
        median_refine_ms_per_candidate=_percentile(refine_ms_per_candidate, 0.50),
        estimated_workload_seconds=median_total * workload_count,
    )


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    position = max(0.0, min(1.0, float(fraction))) * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return float(values[lower] * (1.0 - weight) + values[upper] * weight)


def write_summary(
    path: Path | str,
    dataset_hash: str,
    selected_weights: MatchWeights,
    comparison: Mapping[str, RankingMetrics],
    timing_summary: TimingSummary | None = None,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    weights_text = "/".join(f"{value:.3f}" for value in selected_weights.as_tuple())
    lines = [
        "# Match benchmark summary",
        "",
        f"Dataset SHA-256: `{dataset_hash}`",
        "",
        f"Selected weights (observed/reference/lines/seed): `{weights_text}`",
        "",
        "| Weights | Queries | MRR | Top-1 | Top-5 | Top-10 | Recall@10 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for label, metrics in comparison.items():
        lines.append(
            f"| {label} | {metrics.query_count} | {metrics.mrr:.4f} | {metrics.top1:.4f} | "
            f"{metrics.top5:.4f} | {metrics.top10:.4f} | {metrics.mixture_recall10:.4f} |"
        )
    if timing_summary is not None:
        lines.extend(
            [
                "",
                "## Single-pattern runtime",
                "",
                f"Measured over {timing_summary.query_count} synthetic patterns; each pattern was searched against all {timing_summary.median_candidate_count} candidates.",
                "",
                f"- Total sequential time: {timing_summary.total_pattern_seconds:.3f} s",
                f"- Mean per pattern: {timing_summary.mean_total_seconds:.3f} s",
                f"- Median total: {timing_summary.median_total_seconds:.3f} s",
                f"- 95th percentile total: {timing_summary.p95_total_seconds:.3f} s",
                f"- Median fingerprint retrieval: {timing_summary.median_retrieval_seconds:.3f} s",
                f"- Median quick all-candidate ranking: {timing_summary.median_quick_seconds:.3f} s ({timing_summary.median_quick_ms_per_candidate:.3f} ms/candidate)",
                f"- Median shortlist refinement: {timing_summary.median_refine_seconds:.3f} s for {timing_summary.median_refined_count} candidates ({timing_summary.median_refine_ms_per_candidate:.3f} ms/refined candidate)",
                "",
                "## Full benchmark runtime",
                "",
                f"The complete benchmark contains {timing_summary.workload_query_count} patterns. At the measured single-process median, processing every pattern against the full database is estimated to take {timing_summary.estimated_workload_seconds:.1f} s ({timing_summary.estimated_workload_seconds / 60.0:.2f} min).",
            ]
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def write_selected_weights(
    path: Path | str,
    dataset_hash: str,
    weights: MatchWeights,
    train_metrics: RankingMetrics,
    validation_metrics: RankingMetrics,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset_sha256": dataset_hash,
        "weights": dict(zip(("observed_coverage", "reference_coverage", "sufficient_lines", "alignment_seed"), weights.as_tuple(), strict=True)),
        "train": asdict(train_metrics),
        "validation": asdict(validation_metrics),
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def write_comparison_csv(path: Path | str, comparison: Mapping[str, RankingMetrics]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("label",) + tuple(RankingMetrics.__dataclass_fields__))
        writer.writeheader()
        for label, metrics in comparison.items():
            writer.writerow({"label": label, **asdict(metrics)})
    return output


def write_timing_csv(path: Path | str, timings: tuple[QueryTiming, ...]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(QueryTiming.__dataclass_fields__))
        writer.writeheader()
        for item in timings:
            writer.writerow(asdict(item))
    return output


def write_sensitivity_csv(
    path: Path | str,
    values: Mapping[tuple[str, str, str], RankingMetrics],
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = ("dimension", "value", "weights") + tuple(RankingMetrics.__dataclass_fields__)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for (dimension, value, weights), metrics in sorted(values.items()):
            writer.writerow(
                {"dimension": dimension, "value": value, "weights": weights, **asdict(metrics)}
            )
    return output


def write_adaptive_weights_csv(
    path: Path | str,
    values: tuple[StratumWeightResult, ...],
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "dimension", "value", "observed_coverage", "reference_coverage",
        "sufficient_lines", "alignment_seed", "train_queries", "validation_queries",
    ) + tuple(f"test_{name}" for name in RankingMetrics.__dataclass_fields__)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in values:
            weights = item.weights.as_tuple()
            writer.writerow(
                {
                    "dimension": item.dimension,
                    "value": item.value,
                    "observed_coverage": weights[0],
                    "reference_coverage": weights[1],
                    "sufficient_lines": weights[2],
                    "alignment_seed": weights[3],
                    "train_queries": item.train_queries,
                    "validation_queries": item.validation_queries,
                    **{f"test_{key}": value for key, value in asdict(item.test_metrics).items()},
                }
            )
    return output


__all__ = [
    "TimingSummary",
    "summarize_timings",
    "write_comparison_csv",
    "write_adaptive_weights_csv",
    "write_selected_weights",
    "write_sensitivity_csv",
    "write_summary",
    "write_timing_csv",
]
