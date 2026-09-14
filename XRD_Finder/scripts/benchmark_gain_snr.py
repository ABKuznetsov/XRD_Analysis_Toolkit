from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, replace
import json
from pathlib import Path

import numpy as np

from benchmark_match_gain import (
    APP_ROOT,
    DEFAULT_CACHE,
    CaseDefinition,
    SOFTWARE_VERSION,
    _build_cases,
    _component_line_significance,
    _load_candidates,
    _representatives,
    _run_case,
    _synthetic_profile,
    _write_csv,
)


TARGET_SNRS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0)


def _actual_second_line_snr(
    definition: CaseDefinition,
    by_key,
    seed: int,
) -> float:
    x = np.arange(10.0, 80.0001, 0.025)
    _observed, _clean, profiles, effective_sigma = _synthetic_profile(
        definition,
        by_key,
        x,
        np.random.default_rng(seed),
    )
    significance = _component_line_significance(
        x,
        profiles[1],
        profiles[0],
        effective_sigma,
        definition.fwhm,
    )
    return float(significance["second_line_snr"])


def _tune_minor_fraction(
    definition: CaseDefinition,
    by_key,
    *,
    seed: int,
    target_snr: float,
) -> tuple[CaseDefinition, float]:
    fractions = np.unique(
        np.concatenate(
            (
                np.geomspace(0.001, 0.08, 28),
                np.linspace(0.09, 0.45, 28),
            )
        )
    )
    trials = []
    for fraction in fractions:
        trial = replace(
            definition,
            weights=(1.0 - float(fraction), float(fraction)),
        )
        actual_snr = _actual_second_line_snr(trial, by_key, seed)
        log_error = abs(np.log((actual_snr + 0.25) / (target_snr + 0.25)))
        trials.append((log_error, abs(actual_snr - target_snr), trial, actual_snr))
    _error, _absolute_error, best, actual = min(
        trials,
        key=lambda item: (item[0], item[1]),
    )
    return best, float(actual)


def _snr_band(value: float) -> str:
    if value < 2.0:
        return "<2"
    if value < 3.0:
        return "2-3"
    if value < 5.0:
        return "3-5"
    return ">=5"


def _summarize_snr(rows: list[dict[str, object]], false_rows: list[dict[str, object]]) -> dict[str, object]:
    bands = {}
    for label in ("<2", "2-3", "3-5", ">=5"):
        selected = [row for row in rows if row["snr_band"] == label]
        bands[label] = {
            "cases": len(selected),
            "positive_gain": sum(float(row["expected_gain"]) > 0.0 for row in selected),
            "top1": sum(int(row["family_rank"]) == 1 for row in selected),
            "top5": sum(0 < int(row["family_rank"]) <= 5 for row in selected),
            "median_gain": float(np.median([float(row["expected_gain"]) for row in selected]))
            if selected
            else 0.0,
        }
    return {
        "benchmark": "Gain noise-significance stress test",
        "software_version": SOFTWARE_VERSION,
        "profiles": len(rows) + len(false_rows),
        "negative_single_phase_controls": len(false_rows),
        "binary_snr_cases": len(rows),
        "snr_definition": (
            "Peak height of the second-strongest true minor-phase line divided by "
            "the known pointwise Gaussian-plus-counting noise standard deviation."
        ),
        "bands": bands,
        "false_gain_ge_5": sum(float(row["max_false_gain"]) >= 5.0 for row in false_rows),
        "maximum_false_gain": max(
            (float(row["max_false_gain"]) for row in false_rows),
            default=0.0,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate 50 synthetic profiles calibrated by minor-phase line SNR."
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--output",
        type=Path,
        default=APP_ROOT / "benchmark_results" / "gain_snr_v1_2_0",
    )
    parser.add_argument("--seed", type=int, default=1250)
    parser.add_argument(
        "--gain-baseline-mode",
        choices=("current", "sigma-2.5", "sigma-2.0", "sigma-1.5", "low-baseline"),
        default="current",
    )
    args = parser.parse_args()

    output_dir = args.output.resolve()
    (output_dir / "patterns").mkdir(parents=True, exist_ok=True)
    candidates = _load_candidates(args.cache.expanduser().resolve())
    representatives = _representatives(candidates)
    by_key = {candidate.key: candidate for candidate in candidates}
    source_cases = _build_cases(representatives, args.seed)
    source_singles = source_cases[:10]
    source_binaries = source_cases[20:40]

    definitions: list[CaseDefinition] = []
    target_by_case: dict[str, float] = {}
    tuned_snr_by_case: dict[str, float] = {}
    for index, source in enumerate(source_singles, start=1):
        definitions.append(replace(source, case_id=f"N{index:02d}"))
    for index in range(40):
        source = source_binaries[index % len(source_binaries)]
        target_snr = float(TARGET_SNRS[index % len(TARGET_SNRS)])
        case_id = f"Q{index + 1:02d}"
        case_seed = args.seed * 1000 + len(definitions) + 1
        trial = replace(source, case_id=case_id)
        tuned, actual_snr = _tune_minor_fraction(
            trial,
            by_key,
            seed=case_seed,
            target_snr=target_snr,
        )
        definitions.append(tuned)
        target_by_case[case_id] = target_snr
        tuned_snr_by_case[case_id] = actual_snr

    results = []
    gain_details = []
    for index, definition in enumerate(definitions, start=1):
        result, details = _run_case(
            definition,
            candidates,
            by_key,
            output_dir,
            seed=args.seed * 1000 + index,
            gain_baseline_mode=args.gain_baseline_mode,
        )
        results.append(result)
        gain_details.extend(details)
        print(f"[{index:02d}/50] {definition.case_id}", flush=True)

    result_rows = [asdict(result) for result in results]
    _write_csv(output_dir / "cases.csv", [asdict(case) for case in definitions])
    _write_csv(output_dir / "results.csv", result_rows)
    _write_csv(output_dir / "gain_steps.csv", gain_details)

    detail_by_case = {
        str(row["case_id"]): row
        for row in gain_details
        if row["expected_key"]
    }
    snr_rows = []
    false_rows = []
    result_by_case = {row["case_id"]: row for row in result_rows}
    for definition in definitions:
        result = result_by_case[definition.case_id]
        if definition.kind == "single":
            false_rows.append(
                {
                    "case_id": definition.case_id,
                    "max_false_gain": result["max_false_gain"],
                }
            )
            continue
        detail = detail_by_case[definition.case_id]
        actual_snr = float(detail["second_line_snr"])
        snr_rows.append(
            {
                "case_id": definition.case_id,
                "target_snr": target_by_case[definition.case_id],
                "tuned_snr": tuned_snr_by_case[definition.case_id],
                "actual_second_line_snr": actual_snr,
                "snr_band": _snr_band(actual_snr),
                "minor_area_fraction": definition.weights[1],
                "noise_fraction": definition.noise_fraction,
                "stage": detail["stage"],
                "expected_gain": detail["expected_gain"],
                "family_rank": detail["family_rank"],
                "positive_candidates": detail["positive_candidates"],
            }
        )

    _write_csv(output_dir / "snr_cases.csv", snr_rows)
    _write_csv(output_dir / "negative_controls.csv", false_rows)
    summary = _summarize_snr(snr_rows, false_rows)
    summary["gain_baseline_mode"] = args.gain_baseline_mode
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
