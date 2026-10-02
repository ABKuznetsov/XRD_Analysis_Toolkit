from __future__ import annotations

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import statistics
from typing import Sequence

from benchmarks.match.dataset import BenchmarkDataset
from benchmarks.match.evaluate_gain import evaluate_gain_scenario
from benchmarks.match.gain_scenarios import build_joint_gain_stress_manifest
from benchmarks.match.splits import assign_split_families
from xrd_finder.finder.joint_phase_search import JointPhaseSearchConfig


def joint_gain_parameter_grid() -> tuple[JointPhaseSearchConfig, ...]:
    return tuple(
        JointPhaseSearchConfig(
            derivative_weight=derivative,
            complexity_penalty=complexity,
            excess_penalty=excess,
        )
        for derivative in (0.0, 0.05, 0.10, 0.20)
        for complexity in (0.0, 0.001, 0.003, 0.01)
        for excess in (1.0, 2.0, 3.0, 5.0)
    )


@dataclass(frozen=True, slots=True)
class JointGainSensitivityRow:
    split: str
    case_id: str
    variant_group: str
    variant_kind: str
    config: JointPhaseSearchConfig
    target_rank: int
    ranked_families: tuple[str, ...]
    full_set_recovered: bool
    false_positive_families: int
    search_seconds: float
    suppressed_candidate_count: int


@dataclass(frozen=True, slots=True)
class JointGainStabilityMetrics:
    order_top5_retention: float
    card_variant_rank_delta: float
    top5_jaccard: float
    suppressed_candidate_count: int


def select_validation_config(
    rows: Sequence[JointGainSensitivityRow],
) -> JointPhaseSearchConfig:
    validation = tuple(row for row in rows if row.split == "validation")
    if not validation:
        raise ValueError("At least one validation sensitivity row is required.")
    configs = tuple(dict.fromkeys(row.config for row in validation))

    def selection_key(config: JointPhaseSearchConfig):
        group = tuple(row for row in validation if row.config == config)
        return (
            sum(row.full_set_recovered for row in group) / len(group),
            sum(row.target_rank <= 5 for row in group) / len(group),
            -sum(row.false_positive_families for row in group) / len(group),
            -statistics.median(row.search_seconds for row in group),
            -abs(config.derivative_weight - 0.10),
            -abs(config.complexity_penalty - 0.003),
            -abs(config.excess_penalty - 3.0),
        )

    return max(configs, key=selection_key)


def calculate_stability_metrics(
    rows: Sequence[JointGainSensitivityRow],
) -> JointGainStabilityMetrics:
    grouped: dict[tuple[str, str], list[JointGainSensitivityRow]] = {}
    for row in rows:
        if row.variant_group:
            grouped.setdefault((row.variant_kind, row.variant_group), []).append(row)
    order_pairs = [group for (kind, _), group in grouped.items() if kind == "accepted-order" and len(group) >= 2]
    card_pairs = [group for (kind, _), group in grouped.items() if kind == "card-variant" and len(group) >= 2]
    order_retention = (
        sum(all(item.target_rank <= 5 for item in pair[:2]) for pair in order_pairs)
        / len(order_pairs)
        if order_pairs
        else 0.0
    )
    card_delta = (
        max(abs(pair[0].target_rank - pair[1].target_rank) for pair in card_pairs)
        if card_pairs
        else 0.0
    )
    jaccards = []
    for pair in (*order_pairs, *card_pairs):
        first = set(pair[0].ranked_families[:5])
        second = set(pair[1].ranked_families[:5])
        union = first | second
        jaccards.append(len(first & second) / len(union) if union else 1.0)
    return JointGainStabilityMetrics(
        order_top5_retention=float(order_retention),
        card_variant_rank_delta=float(card_delta),
        top5_jaccard=float(min(jaccards) if jaccards else 0.0),
        suppressed_candidate_count=sum(row.suppressed_candidate_count for row in rows),
    )


def run_joint_gain_sensitivity(
    dataset_path: Path,
    output_dir: Path,
    *,
    workers: int = 1,
) -> Path:
    with BenchmarkDataset.open(dataset_path) as dataset:
        phases = dataset.phase_descriptors()
        references = dataset.reference_library()
    assignments = assign_split_families(phases, seed=5036)
    cases = build_joint_gain_stress_manifest(phases, assignments, references, seed=5036)
    family_by_phase = {phase.phase_id: phase.family_id for phase in phases}
    validation_cases = tuple(case for case in cases if case.scenario.split == "validation")
    tasks = tuple(
        (case, config)
        for config in joint_gain_parameter_grid()
        for case in validation_cases
    )
    worker_count = max(1, min(int(workers), len(tasks))) if tasks else 1
    if worker_count == 1:
        rows = _evaluate_sensitivity_chunk((references, family_by_phase, tasks))
    else:
        chunk_size = int(math.ceil(len(tasks) / worker_count))
        arguments = tuple(
            (references, family_by_phase, tasks[start : start + chunk_size])
            for start in range(0, len(tasks), chunk_size)
        )
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            chunks = tuple(executor.map(_evaluate_sensitivity_chunk, arguments))
        rows = tuple(row for chunk in chunks for row in chunk)
    selected = select_validation_config(rows)
    test_rows = tuple(
        _evaluate_case(case, selected, references, family_by_phase)
        for case in cases
        if case.scenario.split == "test"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_rows(output_dir / "joint_gain_validation.csv", rows)
    _write_rows(output_dir / "joint_gain_test.csv", test_rows)
    selected_path = output_dir / "joint_gain_selected_config.json"
    selected_path.write_text(
        json.dumps(asdict(selected), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    stability = calculate_stability_metrics(test_rows)
    (output_dir / "joint_gain_stability.json").write_text(
        json.dumps(asdict(stability), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return selected_path


def _evaluate_case(case, config, references, family_by_phase):
    result = evaluate_gain_scenario(
        references,
        family_by_phase,
        case.scenario,
        accepted_phase_ids=case.accepted_phase_ids,
        gain_engine="joint-beam",
        shortlist_limit=60,
        joint_config=config,
    )
    ranked_families = tuple(result.ranked_families)
    true_families = {component.family_id for component in case.scenario.components}
    best_families = {
        family_by_phase[phase_id]
        for phase_id in result.best_combination
        if phase_id in family_by_phase
    }
    return JointGainSensitivityRow(
        split=case.scenario.split,
        case_id=case.case_id,
        variant_group=case.variant_group,
        variant_kind=case.variant_kind,
        config=config,
        target_rank=result.target_rank,
        ranked_families=ranked_families,
        full_set_recovered=true_families.issubset(best_families),
        false_positive_families=len(best_families - true_families),
        search_seconds=result.search_seconds,
        suppressed_candidate_count=result.suppressed_candidate_count,
    )


def _evaluate_sensitivity_chunk(arguments):
    references, family_by_phase, tasks = arguments
    return tuple(
        _evaluate_case(case, config, references, family_by_phase)
        for case, config in tasks
    )


def _write_rows(path: Path, rows: Sequence[JointGainSensitivityRow]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    serialized = []
    for row in rows:
        item = asdict(row)
        config = item.pop("config")
        item.update({f"config_{key}": value for key, value in config.items()})
        item["ranked_families"] = "|".join(row.ranked_families)
        serialized.append(item)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(serialized[0]))
        writer.writeheader()
        writer.writerows(serialized)


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune joint Gain on validation stress cases.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/gain-joint-sensitivity"))
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    output = run_joint_gain_sensitivity(args.dataset, args.output, workers=args.workers)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "JointGainSensitivityRow",
    "JointGainStabilityMetrics",
    "calculate_stability_metrics",
    "joint_gain_parameter_grid",
    "run_joint_gain_sensitivity",
    "select_validation_config",
]
