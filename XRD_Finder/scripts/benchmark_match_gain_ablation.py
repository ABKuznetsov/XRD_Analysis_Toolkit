from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from benchmark_match_gain import (
    APP_ROOT,
    CU_KA1_WAVELENGTH,
    DEFAULT_CACHE,
    SOFTWARE_VERSION,
    Candidate,
    _build_cases,
    _component_line_significance,
    _load_candidates,
    _make_harness,
    _rank_gain,
    _rank_match,
    _rank_of_family,
    _representatives,
    _synthetic_profile,
)
from xrd_finder.finder.fingerprint_matching import fingerprint_match_score


MODES = (
    "match_only",
    "residual_match",
    "gain",
    "raw_gain",
)


def _remaining_candidates(
    candidates: list[Candidate],
    selected: list[Candidate],
) -> list[Candidate]:
    selected_keys = {candidate.key for candidate in selected}
    selected_families = {candidate.family for candidate in selected}
    return [
        candidate
        for candidate in candidates
        if candidate.key not in selected_keys
        and candidate.family not in selected_families
    ]


def _filtered_ranking(
    ranking: list[tuple[float, Candidate]],
    selected: list[Candidate],
) -> list[tuple[float, Candidate]]:
    remaining = {candidate.key for candidate in _remaining_candidates(
        [candidate for _score, candidate in ranking],
        selected,
    )}
    return [
        (score, candidate)
        for score, candidate in ranking
        if candidate.key in remaining
    ]


def _rank_residual_match(
    harness,
    candidates: list[Candidate],
    selected: list[Candidate],
    context,
) -> list[tuple[float, Candidate]]:
    x = np.asarray(context.get("x", []), dtype=float)
    residual = np.asarray(context.get("residual_target", []), dtype=float)
    if len(x) < 5 or len(residual) != len(x):
        return []
    records = harness._observed_peak_records(x, residual, limit=80)
    if not records:
        return []
    ranking = [
        (
            fingerprint_match_score(
                candidate.peaks,
                records,
                wavelength=CU_KA1_WAVELENGTH,
            ).score,
            candidate,
        )
        for candidate in _remaining_candidates(candidates, selected)
    ]
    ranking.sort(key=lambda item: (-item[0], item[1].key))
    return ranking


def _rank_raw_gain(
    harness,
    candidates: list[Candidate],
    selected: list[Candidate],
    context,
) -> list[tuple[float, Candidate]]:
    residual = np.asarray(context.get("residual_target", []), dtype=float)
    weights = np.asarray(context.get("weights", []), dtype=float)
    if len(residual) < 5 or len(weights) != len(residual):
        return []
    residual_area = harness._weighted_integral_area(residual, weights)
    if residual_area <= 0.0:
        return []

    ranking: list[tuple[float, Candidate]] = []
    for candidate in _remaining_candidates(candidates, selected):
        candidate_mapping = candidate.mapping()
        peaks = harness._aligned_candidate_gain_peaks(
            candidate_mapping,
            list(candidate.peaks),
            context,
        )
        profile = harness._candidate_gain_profile(
            candidate_mapping,
            peaks,
            context,
        )
        if profile is None:
            ranking.append((0.0, candidate))
            continue
        profile = np.asarray(profile, dtype=float)
        usable = (
            np.isfinite(profile)
            & np.isfinite(residual)
            & np.isfinite(weights)
            & (weights > 0.0)
        )
        weighted_profile = profile * weights
        denominator = float(np.dot(weighted_profile[usable], profile[usable]))
        if denominator <= 1.0e-12:
            ranking.append((0.0, candidate))
            continue
        scale = max(
            0.0,
            float(np.dot(weighted_profile[usable], residual[usable])) / denominator,
        )
        candidate_curve = np.clip(profile * scale, 0.0, None)
        covered = np.minimum(residual, candidate_curve)
        covered_area = harness._weighted_integral_area(covered, weights)
        score = 100.0 * covered_area / max(residual_area, 1.0e-12)
        ranking.append((float(np.clip(score, 0.0, 100.0)), candidate))
    ranking.sort(key=lambda item: (-item[0], item[1].key))
    return ranking


def _rank_modes(
    harness,
    candidates: list[Candidate],
    selected: list[Candidate],
    initial_match: list[tuple[float, Candidate]],
    zero_shift: float,
) -> tuple[dict[str, list[tuple[float, Candidate]]], str]:
    harness.match_candidates = [candidate.mapping() for candidate in selected]
    harness.match_zero_shifts = {
        candidate.key: float(zero_shift)
        for candidate in selected
    }
    context = harness._candidate_gain_context()
    if context is None:
        return {mode: [] for mode in MODES}, ""
    gain_ranking, stage, _evidence = _rank_gain(
        harness,
        candidates,
        selected,
        zero_shift,
    )
    return {
        "match_only": _filtered_ranking(initial_match, selected),
        "residual_match": _rank_residual_match(
            harness,
            candidates,
            selected,
            context,
        ),
        "gain": gain_ranking,
        "raw_gain": _rank_raw_gain(
            harness,
            candidates,
            selected,
            context,
        ),
    }, stage


def _positive_rank(
    ranking: list[tuple[float, Candidate]],
    family: str,
    *,
    positive_only: bool,
) -> int:
    return _rank_of_family(
        ranking,
        family,
        positive_only=positive_only,
    )


def _score_for_family(
    ranking: list[tuple[float, Candidate]],
    family: str,
) -> float:
    return max(
        (float(score) for score, candidate in ranking if candidate.family == family),
        default=0.0,
    )


def _top_keys(
    ranking: list[tuple[float, Candidate]],
    limit: int = 5,
) -> str:
    return ";".join(
        f"{candidate.key}:{score:.3f}"
        for score, candidate in ranking[:limit]
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _summarize(
    step_rows: list[dict[str, object]],
    control_rows: list[dict[str, object]],
    *,
    candidate_entries: int,
    candidate_families: int,
) -> dict[str, object]:
    mode_summary: dict[str, dict[str, object]] = {}
    for mode in MODES:
        rows = [row for row in step_rows if row["mode"] == mode]
        controls = [row for row in control_rows if row["mode"] == mode]
        ranks = [int(row["family_rank"]) for row in rows]
        reciprocal_ranks = [1.0 / rank if rank > 0 else 0.0 for rank in ranks]
        summary: dict[str, object] = {
            "expected_steps": len(rows),
            "family_top1": sum(rank == 1 for rank in ranks),
            "family_top5": sum(0 < rank <= 5 for rank in ranks),
            "family_top10": sum(0 < rank <= 10 for rank in ranks),
            "mean_reciprocal_rank": float(np.mean(reciprocal_ranks)),
            "median_expected_score": float(np.median([
                float(row["expected_score"])
                for row in rows
            ])),
        }
        if mode in {"gain", "raw_gain"}:
            summary.update({
                "positive_expected_score": sum(
                    float(row["expected_score"]) > 0.0
                    for row in rows
                ),
                "single_phase_false_score_ge_5": sum(
                    float(row["max_false_score"]) >= 5.0
                    for row in controls
                    if row["kind"] == "single"
                ),
                "single_phase_controls": sum(
                    row["kind"] == "single"
                    for row in controls
                ),
                "all_true_selected_false_score_ge_5": sum(
                    float(row["max_false_score"]) >= 5.0
                    for row in controls
                ),
                "median_max_false_score": float(np.median([
                    float(row["max_false_score"])
                    for row in controls
                ])),
            })
        mode_summary[mode] = summary
    return {
        "benchmark": "XRD Phase Finder Match/Gain ranking ablation",
        "software_version": SOFTWARE_VERSION,
        "cases": 50,
        "expected_minor_phase_steps": len(step_rows) // len(MODES),
        "candidate_entries": candidate_entries,
        "candidate_families": candidate_families,
        "modes": mode_summary,
        "definitions": {
            "match_only": (
                "Original full-pattern Match ranking after already selected "
                "entries and formula families are excluded."
            ),
            "residual_match": (
                "Match recalculated from peaks detected in the positive residual "
                "after the selected true phases are jointly fitted."
            ),
            "gain": (
                "Production conditional Gain including profile support, BIC, "
                "independent-line gate and unsupported-line penalties."
            ),
            "raw_gain": (
                "Residual profile coverage after an unconstrained one-candidate "
                "least-squares scale; no evidence gate, BIC or unsupported-line penalty."
            ),
        },
        "scope": (
            "Closed-world synthetic benchmark using the same 50 cases, random seed "
            "and COD-derived candidate pool in every mode. The true previously "
            "selected phases are supplied at each conditional step."
        ),
    }


def _summary_markdown(summary: dict[str, object]) -> str:
    lines = [
        "# Match/Gain ranking ablation",
        "",
        f"- Cases: {summary['cases']}",
        f"- Expected minor-phase steps: {summary['expected_minor_phase_steps']}",
        f"- Candidate pool: {summary['candidate_entries']} entries, "
        f"{summary['candidate_families']} formula families",
        "",
        "| Mode | Top-1 | Top-5 | Top-10 | MRR | Positive | "
        "Single-phase false >=5% |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        values = summary["modes"][mode]
        expected = values["expected_steps"]
        positive = values.get("positive_expected_score", "n/a")
        false_count = values.get("single_phase_false_score_ge_5", "n/a")
        false_total = values.get("single_phase_controls", "")
        false_text = (
            f"{false_count}/{false_total}"
            if false_count != "n/a"
            else "n/a"
        )
        lines.append(
            f"| {mode} | {values['family_top1']}/{expected} | "
            f"{values['family_top5']}/{expected} | "
            f"{values['family_top10']}/{expected} | "
            f"{values['mean_reciprocal_rank']:.3f} | "
            f"{positive if positive == 'n/a' else f'{positive}/{expected}'} | "
            f"{false_text} |"
        )
    lines.extend([
        "",
        str(summary["scope"]),
        "",
        "False-addition rates are reported only for Gain scores because Match "
        "rankings do not define a directly comparable automatic acceptance threshold.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Match, residual Match, Gain and raw Gain on 50 cases."
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--output",
        type=Path,
        default=APP_ROOT / "benchmark_results" / "match_gain_ablation_current",
    )
    parser.add_argument("--seed", type=int, default=1200)
    args = parser.parse_args()

    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = _load_candidates(args.cache.expanduser().resolve())
    representatives = _representatives(candidates)
    cases = _build_cases(representatives, args.seed)
    by_key = {candidate.key: candidate for candidate in candidates}
    peak_map = {candidate.key: candidate.peaks for candidate in candidates}

    step_rows: list[dict[str, object]] = []
    control_rows: list[dict[str, object]] = []
    for case_index, definition in enumerate(cases, start=1):
        rng = np.random.default_rng(args.seed * 1000 + case_index)
        x = np.arange(10.0, 80.0001, 0.025)
        observed, _clean, component_profiles, effective_sigma = _synthetic_profile(
            definition,
            by_key,
            x,
            rng,
        )
        harness = _make_harness(
            peak_map,
            x,
            observed,
            definition.case_id,
            definition.fwhm,
            "current",
        )
        observed_records = harness._observed_peak_records(x, observed, limit=80)
        initial_match = _rank_match(candidates, observed_records)
        true_candidates = [by_key[key] for key in definition.components]
        selected = [true_candidates[0]]

        for expected_index, expected in enumerate(true_candidates[1:], start=1):
            rankings, stage = _rank_modes(
                harness,
                candidates,
                selected,
                initial_match,
                definition.zero_shift,
            )
            significance = _component_line_significance(
                x,
                component_profiles[expected_index],
                np.sum(component_profiles[:expected_index], axis=0),
                effective_sigma,
                definition.fwhm,
            )
            for mode, ranking in rankings.items():
                positive_only = mode in {"gain", "raw_gain"}
                step_rows.append({
                    "case_id": definition.case_id,
                    "kind": definition.kind,
                    "step": expected_index,
                    "stage": stage,
                    "mode": mode,
                    "selected_keys": ";".join(
                        candidate.key
                        for candidate in selected
                    ),
                    "expected_key": expected.key,
                    "expected_family": expected.family,
                    "expected_score": round(
                        _score_for_family(ranking, expected.family),
                        6,
                    ),
                    "family_rank": _positive_rank(
                        ranking,
                        expected.family,
                        positive_only=positive_only,
                    ),
                    "top5": _top_keys(
                        [
                            item
                            for item in ranking
                            if not positive_only or item[0] > 0.0
                        ]
                    ),
                    **{
                        key: round(value, 6) if isinstance(value, float) else value
                        for key, value in significance.items()
                    },
                })
            selected.append(expected)

        final_rankings, final_stage = _rank_modes(
            harness,
            candidates,
            selected,
            initial_match,
            definition.zero_shift,
        )
        for mode, ranking in final_rankings.items():
            control_rows.append({
                "case_id": definition.case_id,
                "kind": definition.kind,
                "stage": final_stage,
                "mode": mode,
                "selected_keys": ";".join(
                    candidate.key
                    for candidate in selected
                ),
                "max_false_score": round(
                    max((float(score) for score, _candidate in ranking), default=0.0),
                    6,
                ),
                "top5": _top_keys(ranking),
            })
        print(
            f"[{case_index:02d}/{len(cases)}] {definition.case_id}",
            flush=True,
        )

    summary = _summarize(
        step_rows,
        control_rows,
        candidate_entries=len(candidates),
        candidate_families=len({candidate.family for candidate in candidates}),
    )
    _write_csv(output_dir / "ablation_steps.csv", step_rows)
    _write_csv(output_dir / "negative_controls.csv", control_rows)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    readme = _summary_markdown(summary)
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    print()
    print(readme)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
