from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import sqlite3

import numpy as np

from benchmarks.match.dataset import BenchmarkDataset
from benchmarks.match.detection_limits import (
    build_detection_manifest,
    measure_component_observability,
)
from benchmarks.match.evaluate_gain import (
    IndistinguishableGainScenario,
    _evaluate_gain_chunk,
    evaluate_gain_scenario,
)
from benchmarks.match.extract_features import (
    FeatureExtractionConfig,
    extract_match_features_parallel,
)
from benchmarks.match.feature_cache import load_feature_matrix, save_feature_matrix
from benchmarks.match.generate_profiles import generate_profile
from benchmarks.match.metrics import rank_feature_matrix
from benchmarks.match.scenarios import ScenarioConfig, build_scenario_manifest
from benchmarks.match.splits import assign_split_families
from xrd_finder.finder.fingerprint_matching import DEFAULT_MATCH_WEIGHTS
from xrd_finder.finder.gain_policy import DEFAULT_GAIN_POLICY


@dataclass(frozen=True, slots=True)
class ComponentDetectionResult:
    scenario_id: str
    phase_count: int
    phase_id: str
    family_id: str
    nominal_fraction: float
    diffraction_power: float
    nominal_signal_fraction: float
    profile_area_share: float
    visible_lines: int
    max_line_snr: float
    observable: bool
    match_rank: int
    noise: str
    fwhm: float
    overlap: str


@dataclass(frozen=True, slots=True)
class SequentialGainResult:
    scenario_id: str
    phase_count: int
    stage: int
    accepted_phase_ids: str
    target_phase_id: str
    target_family: str
    target_retrieval_rank: int
    target_rank: int
    target_in_shortlist: bool
    target_gain: float
    target_profile_gain: float
    reportable: bool
    elapsed_seconds: float


def run_detection_benchmark(
    dataset_path: Path,
    output_dir: Path,
    *,
    workers: int = 4,
    shortlist_limit: int = 24,
    gain_strategy: str = "quick",
) -> Path:
    with BenchmarkDataset.open(dataset_path) as dataset:
        phases = dataset.phase_descriptors()
        references = dataset.reference_library()
    assignments = assign_split_families(phases, seed=5036)
    base = tuple(
        item
        for item in build_scenario_manifest(phases, assignments, ScenarioConfig(seed=5036))
        if item.split == "test"
    )
    scenarios = build_detection_manifest(base)
    scenario_by_id = {item.scenario_id: item for item in scenarios}
    families = {phase.phase_id: phase.family_id for phase in phases}
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_key = hashlib.sha256(
        f"detection-v1:{_sha256(dataset_path)}:{scenarios!r}".encode("utf-8")
    ).hexdigest()
    cache_path = output_dir / "feature_matrix.sqlite"
    try:
        matrix = load_feature_matrix(cache_path, expected_cache_key=cache_key)
        print(f"Loaded {len(matrix.query_ids())} cached detection patterns", flush=True)
    except (OSError, ValueError, sqlite3.DatabaseError):
        cache_path.unlink(missing_ok=True)
        matrix = extract_match_features_parallel(
            references,
            families,
            scenarios,
            workers=workers,
            config=FeatureExtractionConfig(),
        )
        save_feature_matrix(cache_path, matrix, cache_key=cache_key)

    rankings = {
        item.query_id: item
        for item in rank_feature_matrix(matrix, DEFAULT_MATCH_WEIGHTS)
    }
    component_rows = []
    for index, scenario in enumerate(scenarios, start=1):
        generated = generate_profile(references, scenario)
        ranking = rankings[scenario.scenario_id]
        for component in scenario.components:
            visibility = measure_component_observability(generated, component.phase_id)
            rank = (
                ranking.ranked_families.index(component.family_id) + 1
                if component.family_id in ranking.ranked_families
                else len(ranking.ranked_families) + 1
            )
            component_rows.append(
                ComponentDetectionResult(
                    scenario_id=scenario.scenario_id,
                    phase_count=len(scenario.components),
                    phase_id=component.phase_id,
                    family_id=component.family_id,
                    nominal_fraction=visibility.nominal_fraction,
                    diffraction_power=visibility.diffraction_power,
                    nominal_signal_fraction=visibility.nominal_signal_fraction,
                    profile_area_share=visibility.profile_area_share,
                    visible_lines=visibility.visible_lines,
                    max_line_snr=visibility.max_line_snr,
                    observable=visibility.observable,
                    match_rank=rank,
                    noise=scenario.noise,
                    fwhm=scenario.fwhm,
                    overlap=scenario.overlap,
                )
            )
        if index % 25 == 0 or index == len(scenarios):
            print(f"Visibility {index}/{len(scenarios)}", flush=True)

    _write_dataclass_csv(output_dir / "component_results.csv", component_rows)
    profile_summary = _profile_summary(component_rows, rankings, scenario_by_id, matrix.timings)
    _write_rows(output_dir / "profile_summary.csv", profile_summary)
    signal_summary = _component_group_summary(component_rows, "nominal_signal_fraction")
    _write_rows(output_dir / "signal_limit_summary.csv", signal_summary)
    _write_rows(output_dir / "noise_summary.csv", _component_group_summary(component_rows, "noise"))
    _write_rows(output_dir / "fwhm_summary.csv", _component_group_summary(component_rows, "fwhm"))
    _write_rows(output_dir / "power_summary.csv", _component_group_summary(component_rows, "diffraction_power"))

    gain_scenarios = tuple(item for item in scenarios if len(item.components) > 1)
    gain_results = _run_gain(
        references,
        families,
        gain_scenarios,
        workers=workers,
        shortlist_limit=shortlist_limit,
        shortlist_strategy=gain_strategy,
    )
    if gain_results:
        _write_dataclass_csv(output_dir / "gain_results.csv", gain_results)
    component_by_key = {(item.scenario_id, item.phase_id): item for item in component_rows}
    gain_summary = _gain_group_summary(gain_results, component_by_key, scenario_by_id)
    _write_rows(output_dir / "gain_summary.csv", gain_summary)
    gain_signal_summary = _gain_signal_summary(gain_results, component_by_key)
    _write_rows(output_dir / "gain_signal_summary.csv", gain_signal_summary)
    sequential_results = _run_sequential_gain(
        references,
        families,
        gain_scenarios,
        workers=workers,
        shortlist_limit=shortlist_limit,
        shortlist_strategy=gain_strategy,
    )
    _write_dataclass_csv(output_dir / "sequential_gain_results.csv", sequential_results)
    sequential_summary = _sequential_gain_summary(
        sequential_results,
        component_by_key,
        profile_summary,
    )
    _write_rows(output_dir / "sequential_gain_summary.csv", sequential_summary)
    report = _write_report(
        output_dir / "detection_limits.md",
        component_rows,
        profile_summary,
        signal_summary,
        gain_summary,
        gain_signal_summary,
        sequential_summary,
        matrix.timings,
    )
    return report


def _run_gain(references, families, scenarios, *, workers, shortlist_limit, shortlist_strategy):
    if not scenarios:
        return ()
    chunk_size = int(math.ceil(len(scenarios) / max(1, int(workers))))
    arguments = [
        (
            references,
            families,
            scenarios[start:start + chunk_size],
            shortlist_limit,
            DEFAULT_GAIN_POLICY,
            shortlist_strategy,
            False,
            False,
            False,
        )
        for start in range(0, len(scenarios), chunk_size)
    ]
    with ProcessPoolExecutor(max_workers=max(1, int(workers))) as executor:
        chunks = list(executor.map(_evaluate_gain_chunk, arguments))
    return tuple(item for chunk in chunks for item in chunk)


def build_sequential_gain_requests(scenarios):
    requests = []
    for scenario in scenarios:
        ordered = tuple(sorted(scenario.components, key=lambda item: item.fraction, reverse=True))
        for stage in range(1, len(ordered)):
            requests.append((scenario, tuple(item.phase_id for item in ordered[:stage]), stage))
    return tuple(requests)


def _run_sequential_gain(references, families, scenarios, *, workers, shortlist_limit, shortlist_strategy):
    requests = build_sequential_gain_requests(scenarios)
    if not requests:
        return ()
    chunk_size = int(math.ceil(len(requests) / max(1, int(workers))))
    arguments = [
        (references, families, requests[start:start + chunk_size], shortlist_limit, shortlist_strategy)
        for start in range(0, len(requests), chunk_size)
    ]
    with ProcessPoolExecutor(max_workers=max(1, int(workers))) as executor:
        chunks = list(executor.map(_evaluate_sequential_gain_chunk, arguments))
    return tuple(item for chunk in chunks for item in chunk)


def _evaluate_sequential_gain_chunk(arguments):
    references, families, requests, shortlist_limit, shortlist_strategy = arguments
    rows = []
    for scenario, accepted_ids, stage in requests:
        try:
            result = evaluate_gain_scenario(
                references,
                families,
                scenario,
                shortlist_limit=shortlist_limit,
                shortlist_strategy=shortlist_strategy,
                accepted_phase_ids=accepted_ids,
            )
        except IndistinguishableGainScenario:
            continue
        shown = DEFAULT_GAIN_POLICY.reportable_gain(
            result.target_gain,
            dominant_evidence=result.dominant_evidence,
            profile_gain=result.target_profile_gain,
            profile_evaluated=True,
        )
        rows.append(SequentialGainResult(
            scenario_id=scenario.scenario_id,
            phase_count=len(scenario.components),
            stage=stage,
            accepted_phase_ids=";".join(accepted_ids),
            target_phase_id=result.target_phase_id,
            target_family=result.target_family,
            target_retrieval_rank=result.target_retrieval_rank,
            target_rank=result.target_rank,
            target_in_shortlist=result.target_in_shortlist,
            target_gain=result.target_gain,
            target_profile_gain=result.target_profile_gain,
            reportable=shown > 0.0,
            elapsed_seconds=result.elapsed_seconds,
        ))
    return tuple(rows)


def _profile_summary(component_rows, rankings, scenarios, timings):
    grouped = defaultdict(list)
    for row in component_rows:
        grouped[row.phase_count].append(row)
    timing_by_id = {item.query_id: item.total_seconds for item in timings}
    rows = []
    for phase_count, components in sorted(grouped.items()):
        scenario_ids = sorted({item.scenario_id for item in components})
        observable = [item for item in components if item.observable]
        full_visible = 0
        full_nominal = 0
        dominant_top1 = 0
        dominant_top5 = 0
        dominant_top10 = 0
        for scenario_id in scenario_ids:
            scenario = scenarios[scenario_id]
            ranking = rankings[scenario_id]
            local = [item for item in components if item.scenario_id == scenario_id]
            visible_families = {item.family_id for item in local if item.observable}
            nominal_families = {item.family_id for item in local}
            ranked10 = set(ranking.ranked_families[:10])
            full_visible += int(visible_families.issubset(ranked10))
            full_nominal += int(nominal_families.issubset(ranked10))
            dominant_component = max(scenario.components, key=lambda item: item.fraction)
            dominant = dominant_component.family_id
            dominant_rank = next(
                item.match_rank
                for item in local
                if item.phase_id == dominant_component.phase_id
            )
            dominant_top1 += int(dominant_rank <= 1)
            dominant_top5 += int(dominant_rank <= 5)
            dominant_top10 += int(dominant_rank <= 10)
        rows.append(
            {
                "phase_count": phase_count,
                "patterns": len(scenario_ids),
                "components": len(components),
                "observable_components": len(observable),
                "observable_fraction": _ratio(len(observable), len(components)),
                "observable_match_top5": _ratio(sum(item.match_rank <= 5 for item in observable), len(observable)),
                "observable_match_top10": _ratio(sum(item.match_rank <= 10 for item in observable), len(observable)),
                "full_visible_recovery_top10": _ratio(full_visible, len(scenario_ids)),
                "full_nominal_recovery_top10": _ratio(full_nominal, len(scenario_ids)),
                "dominant_top1": _ratio(dominant_top1, len(scenario_ids)),
                "dominant_top5": _ratio(dominant_top5, len(scenario_ids)),
                "dominant_top10": _ratio(dominant_top10, len(scenario_ids)),
                "median_seconds": float(np.median([timing_by_id[item] for item in scenario_ids])),
            }
        )
    return rows


def _component_group_summary(component_rows, field):
    grouped = defaultdict(list)
    for row in component_rows:
        value = getattr(row, field)
        if isinstance(value, float):
            value = round(value, 6)
        grouped[value].append(row)
    result = []
    for value, items in sorted(grouped.items(), key=lambda item: str(item[0])):
        observable = [item for item in items if item.observable]
        result.append(
            {
                field: value,
                "components": len(items),
                "observable_components": len(observable),
                "observable_fraction": _ratio(len(observable), len(items)),
                "observable_match_top5": _ratio(sum(item.match_rank <= 5 for item in observable), len(observable)),
                "observable_match_top10": _ratio(sum(item.match_rank <= 10 for item in observable), len(observable)),
                "median_visible_lines": float(np.median([item.visible_lines for item in items])),
                "median_max_snr": float(np.median([item.max_line_snr for item in items])),
                "median_profile_area_share": float(np.median([item.profile_area_share for item in items])),
            }
        )
    return result


def _gain_group_summary(gain_results, component_by_key, scenarios):
    grouped = defaultdict(list)
    for result in gain_results:
        component = component_by_key.get((result.query_id, result.target_phase_id))
        if component is not None:
            grouped[component.phase_count].append((result, component))
    rows = []
    for phase_count, pairs in sorted(grouped.items()):
        observable = [(result, component) for result, component in pairs if component.observable]
        reportable = [
            DEFAULT_GAIN_POLICY.reportable_gain(
                result.target_gain,
                dominant_evidence=result.dominant_evidence,
                profile_gain=result.target_profile_gain,
                profile_evaluated=True,
            )
            for result, _component in observable
        ]
        first_cycle_top10 = 0
        for result, component in observable:
            scenario = scenarios[result.query_id]
            dominant = max(scenario.components, key=lambda item: item.fraction)
            dominant_row = component_by_key[(result.query_id, dominant.phase_id)]
            first_cycle_top10 += int(dominant_row.match_rank <= 10 and result.target_rank <= 10)
        rows.append(
            {
                "phase_count": phase_count,
                "patterns_evaluated": len(pairs),
                "observable_targets": len(observable),
                "gain_top1": _ratio(sum(result.target_rank <= 1 for result, _ in observable), len(observable)),
                "gain_top5": _ratio(sum(result.target_rank <= 5 for result, _ in observable), len(observable)),
                "gain_top10": _ratio(sum(result.target_rank <= 10 for result, _ in observable), len(observable)),
                "retrieval_top24": _ratio(sum(result.target_retrieval_rank <= 24 for result, _ in observable), len(observable)),
                "conditional_gain_top1": _ratio(sum(result.target_rank <= 1 for result, _ in observable if result.target_in_shortlist), sum(result.target_in_shortlist for result, _ in observable)),
                "conditional_gain_top5": _ratio(sum(result.target_rank <= 5 for result, _ in observable if result.target_in_shortlist), sum(result.target_in_shortlist for result, _ in observable)),
                "conditional_gain_top10": _ratio(sum(result.target_rank <= 10 for result, _ in observable if result.target_in_shortlist), sum(result.target_in_shortlist for result, _ in observable)),
                "first_cycle_top10": _ratio(first_cycle_top10, len(observable)),
                "target_in_shortlist": _ratio(sum(result.target_in_shortlist for result, _ in observable), len(observable)),
                "reportable_target_gain": _ratio(sum(value > 0 for value in reportable), len(observable)),
                "median_seconds": float(np.median([result.elapsed_seconds for result, _ in pairs])),
            }
        )
    return rows


def _gain_signal_summary(gain_results, component_by_key):
    grouped = defaultdict(list)
    for result in gain_results:
        component = component_by_key.get((result.query_id, result.target_phase_id))
        if component is not None and component.observable:
            grouped[round(component.nominal_signal_fraction, 6)].append(result)
    rows = []
    for signal, items in sorted(grouped.items()):
        reportable = [
            DEFAULT_GAIN_POLICY.reportable_gain(
                item.target_gain,
                dominant_evidence=item.dominant_evidence,
                profile_gain=item.target_profile_gain,
                profile_evaluated=True,
            )
            for item in items
        ]
        rows.append({
            "nominal_signal_fraction": signal,
            "observable_targets": len(items),
            "gain_top1": _ratio(sum(item.target_rank <= 1 for item in items), len(items)),
            "gain_top5": _ratio(sum(item.target_rank <= 5 for item in items), len(items)),
            "gain_top10": _ratio(sum(item.target_rank <= 10 for item in items), len(items)),
            "retrieval_top24": _ratio(sum(item.target_retrieval_rank <= 24 for item in items), len(items)),
            "conditional_gain_top10": _ratio(sum(item.target_rank <= 10 for item in items if item.target_in_shortlist), sum(item.target_in_shortlist for item in items)),
            "target_in_shortlist": _ratio(sum(item.target_in_shortlist for item in items), len(items)),
            "reportable_target_gain": _ratio(sum(value > 0 for value in reportable), len(items)),
        })
    return rows


def _sequential_gain_summary(results, component_by_key, profile_summary):
    grouped = defaultdict(list)
    for item in results:
        component = component_by_key.get((item.scenario_id, item.target_phase_id))
        if component is not None and component.observable:
            grouped[(item.phase_count, item.stage)].append(item)
    rows = []
    for (phase_count, stage), items in sorted(grouped.items()):
        retrieved = [item for item in items if item.target_in_shortlist]
        rows.append({
            "phase_count": phase_count,
            "gain_stage": stage,
            "accepted_phases": stage,
            "observable_targets": len(items),
            "retrieval_top24": _ratio(len(retrieved), len(items)),
            "gain_top1": _ratio(sum(item.target_rank <= 1 for item in items), len(items)),
            "gain_top5": _ratio(sum(item.target_rank <= 5 for item in items), len(items)),
            "gain_top10": _ratio(sum(item.target_rank <= 10 for item in items), len(items)),
            "conditional_gain_top10": _ratio(sum(item.target_rank <= 10 for item in retrieved), len(retrieved)),
            "reportable": _ratio(sum(item.reportable for item in items), len(items)),
            "median_seconds": float(np.median([item.elapsed_seconds for item in items])),
        })
    return rows


def _write_report(path, component_rows, profile_summary, signal_summary, gain_summary, gain_signal_summary, sequential_summary, timings):
    lines = [
        "# Phase-detection limits benchmark",
        "",
        "Synthetic profiles vary phase count, noise, FWHM and relative diffraction power.",
        "A component is observable when at least two detected peaks contribute >=3 sigma and >=10%",
        "of the local crystalline profile, or one peak contributes >=5 sigma and >=20%.",
        "Match searches all 1,058 reference phases. Gain is the first step after the dominant phase",
        "has been accepted by the operator. The relative diffraction-power sweep represents the",
        "effect of different I/Ic values; the compact benchmark database has no reliable I/Ic field.",
        "",
        "## Results by phase count",
        "",
        "| Phases | Patterns | Observable components | Dominant Match Top-1 | Top-5 | Top-10 | Median s |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in profile_summary:
        lines.append(
            f"| {row['phase_count']} | {row['patterns']} | {row['observable_components']}/{row['components']} "
            f"| {_pct(row['dominant_top1'])} | {_pct(row['dominant_top5'])} "
            f"| {_pct(row['dominant_top10'])} | {row['median_seconds']:.3f} |"
        )
    lines.extend([
        "",
        "## First Gain step by phase count",
        "",
        "| Phases | Observable next phases | Retrieval @24 | Gain Top-1 | Top-5 | Top-10 | Conditional Top-10 | First-cycle Top-10 | Reportable Gain | Median s |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in gain_summary:
        lines.append(
            f"| {row['phase_count']} | {row['observable_targets']} "
            f"| {_pct(row['retrieval_top24'])} | {_pct(row['gain_top1'])} | {_pct(row['gain_top5'])} | {_pct(row['gain_top10'])} "
            f"| {_pct(row['conditional_gain_top10'])} "
            f"| {_pct(row['first_cycle_top10'])} "
            f"| {_pct(row['reportable_target_gain'])} "
            f"| {row['median_seconds']:.3f} |"
        )
    lines.extend([
        "",
        "## Sequential Gain after joint refitting",
        "",
        "Each row assumes the preceding true phases have been accepted, rebuilds all accepted profiles, and jointly refits their non-negative scales before the next Gain search.",
        "",
        "| Phases | Gain step | Observable targets | Retrieval @24 | Gain Top-1 | Top-5 | Top-10 | Conditional Top-10 | Reportable | Median s |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in sequential_summary:
        lines.append(
            f"| {row['phase_count']} | {row['gain_stage']} | {row['observable_targets']} "
            f"| {_pct(row['retrieval_top24'])} | {_pct(row['gain_top1'])} | {_pct(row['gain_top5'])} "
            f"| {_pct(row['gain_top10'])} | {_pct(row['conditional_gain_top10'])} "
            f"| {_pct(row['reportable'])} | {row['median_seconds']:.3f} |"
        )
    lines.extend([
        "",
        "## Gain detection curve by mass fraction x relative I/Ic",
        "",
        "| Fraction x I/Ic | Observable targets | Retrieval @24 | Gain Top-1 | Top-5 | Top-10 | Conditional Top-10 | Reportable Gain |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in gain_signal_summary:
        lines.append(
            f"| {float(row['nominal_signal_fraction']):.3f} | {row['observable_targets']} "
            f"| {_pct(row['retrieval_top24'])} | {_pct(row['gain_top1'])} | {_pct(row['gain_top5'])} | {_pct(row['gain_top10'])} "
            f"| {_pct(row['conditional_gain_top10'])} | {_pct(row['reportable_target_gain'])} |"
        )
    lines.extend([
        "",
        "## Detection curve by mass fraction x relative I/Ic",
        "",
        "| Fraction x I/Ic | Components | Observable | Match Top-10 among observable | Median visible lines | Median max SNR | Median profile-area share |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in signal_summary:
        lines.append(
            f"| {float(row['nominal_signal_fraction']):.3f} | {row['components']} "
            f"| {row['observable_components']} ({_pct(row['observable_fraction'])}) "
            f"| {_pct(row['observable_match_top10'])} | {row['median_visible_lines']:.1f} "
            f"| {row['median_max_snr']:.1f} | {_pct(row['median_profile_area_share'])} |"
        )
    lines.extend([
        "",
        f"Median all-candidate Match time: {float(np.median([item.total_seconds for item in timings])):.3f} s per pattern.",
        "",
        "Nominal mass fraction is not treated as observable ground truth. Components below the",
        "peak-visibility rule are reported separately and excluded from detection recall.",
        "Sequential rows use oracle acceptance of the correct preceding phase so each later Gain",
        "step measures retrieval and ranking independently of an earlier operator choice.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_dataclass_csv(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(asdict(rows[0])))
        writer.writeheader()
        for item in rows:
            writer.writerow(asdict(item))


def _write_rows(path, rows):
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _ratio(numerator, denominator):
    return float(numerator) / max(int(denominator), 1)


def _pct(value):
    return f"{100.0 * float(value):.1f}%"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure Match/Gain phase-detection limits.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/detection-limits"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--shortlist", type=int, default=24)
    parser.add_argument(
        "--gain-strategy",
        choices=("quick", "adaptive", "rare", "fusion", "hybrid", "dominant", "dominant-expand", "match"),
        default="quick",
    )
    args = parser.parse_args()
    report = run_detection_benchmark(
        args.dataset,
        args.output,
        workers=args.workers,
        shortlist_limit=args.shortlist,
        gain_strategy=args.gain_strategy,
    )
    print(f"Wrote {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
