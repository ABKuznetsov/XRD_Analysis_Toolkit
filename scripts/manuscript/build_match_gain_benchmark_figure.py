from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "XRD_Finder" / "benchmark_results" / "match_gain_v1_2_0"
OUTPUT = ROOT / "manuscript_assets" / "phase_finder"


def _rows(name: str) -> list[dict[str, str]]:
    with (RESULTS / name).open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _pattern(case_id: str) -> tuple[np.ndarray, np.ndarray]:
    data = np.genfromtxt(
        RESULTS / "patterns" / f"{case_id}.csv",
        delimiter=",",
        names=True,
    )
    return np.asarray(data["2theta_deg"]), np.asarray(data["observed_corrected"])


def _percent(value: int, total: int) -> str:
    return f"{100.0 * value / max(total, 1):.0f}%"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = _rows("results.csv")
    gain_steps = [row for row in _rows("gain_steps.csv") if row["expected_key"]]

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 13,
            "axes.titlesize": 15,
            "axes.labelsize": 13,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "legend.fontsize": 11,
            "axes.linewidth": 0.9,
        }
    )
    figure, axes = plt.subplots(2, 2, figsize=(12.2, 8.4), constrained_layout=True)

    profile_axis = axes[0, 0]
    for offset, case_id, label, color in [
        (2.2, "S07", "single phase", "#1f4e79"),
        (1.1, "B04", "binary mixture", "#2b7a4b"),
        (0.0, "T04", "ternary mixture", "#b64a3c"),
    ]:
        x, y = _pattern(case_id)
        scale = max(float(np.nanpercentile(y, 99.8)), 1.0)
        profile_axis.plot(x, y / scale + offset, color=color, linewidth=0.8, label=label)
    profile_axis.set_title("(a) Representative synthetic profiles", loc="left", fontweight="bold")
    profile_axis.set_xlabel(r"$2\theta$ (deg)")
    profile_axis.set_ylabel("normalized intensity + offset")
    profile_axis.set_xlim(10, 80)
    profile_axis.set_yticks([])
    profile_axis.legend(frameon=False, loc="upper right")

    match_axis = axes[0, 1]
    total = len(results)
    match_values = [
        sum(int(row["dominant_exact_rank"]) == 1 for row in results),
        sum(0 < int(row["dominant_exact_rank"]) <= 5 for row in results),
        sum(int(row["dominant_family_rank"]) == 1 for row in results),
        sum(0 < int(row["dominant_family_rank"]) <= 5 for row in results),
    ]
    labels = ["entry\ntop-1", "entry\ntop-5", "family\ntop-1", "family\ntop-5"]
    bars = match_axis.bar(
        np.arange(4),
        np.asarray(match_values) / total * 100.0,
        color=["#718096", "#4a637d", "#4a9a72", "#24744f"],
        width=0.68,
    )
    match_axis.set_title("(b) Dominant-phase Match", loc="left", fontweight="bold")
    match_axis.set_ylabel("successful cases (%)")
    match_axis.set_xticks(np.arange(4), labels)
    match_axis.set_ylim(0, 108)
    match_axis.spines[["top", "right"]].set_visible(False)
    for bar, value in zip(bars, match_values, strict=True):
        match_axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{value}/{total}",
            ha="center",
            va="bottom",
            fontsize=12,
        )

    gain_axis = axes[1, 0]
    stages = ["direct", "overlap", "all"]
    totals = [
        sum(row["stage"] == "direct" for row in gain_steps),
        sum(row["stage"] == "overlap" for row in gain_steps),
        len(gain_steps),
    ]
    top1 = [
        sum(row["stage"] == "direct" and int(row["family_rank"]) == 1 for row in gain_steps),
        sum(row["stage"] == "overlap" and int(row["family_rank"]) == 1 for row in gain_steps),
        sum(int(row["family_rank"]) == 1 for row in gain_steps),
    ]
    top5 = [
        sum(row["stage"] == "direct" and 0 < int(row["family_rank"]) <= 5 for row in gain_steps),
        sum(row["stage"] == "overlap" and 0 < int(row["family_rank"]) <= 5 for row in gain_steps),
        sum(0 < int(row["family_rank"]) <= 5 for row in gain_steps),
    ]
    positions = np.arange(3)
    width = 0.34
    gain_axis.bar(
        positions - width / 2,
        [100.0 * value / max(total_value, 1) for value, total_value in zip(top1, totals, strict=True)],
        width,
        label="top-1",
        color="#58789b",
    )
    gain_axis.bar(
        positions + width / 2,
        [100.0 * value / max(total_value, 1) for value, total_value in zip(top5, totals, strict=True)],
        width,
        label="top-5",
        color="#38a169",
    )
    gain_axis.set_title("(c) Conditional Gain recovery", loc="left", fontweight="bold")
    gain_axis.set_ylabel("expected residual phases (%)")
    gain_axis.set_xticks(positions, ["direct\n(n=10)", "overlap\n(n=28)", "all stages\n(n=40)"])
    gain_axis.set_ylim(0, 108)
    gain_axis.spines[["top", "right"]].set_visible(False)
    gain_axis.legend(frameon=False, loc="upper left")
    for index, (top1_value, top5_value, total_value) in enumerate(
        zip(top1, top5, totals, strict=True)
    ):
        gain_axis.text(
            index - width / 2,
            100.0 * top1_value / max(total_value, 1) + 2,
            f"{top1_value}/{total_value}",
            ha="center",
            fontsize=11,
        )
        gain_axis.text(
            index + width / 2,
            100.0 * top5_value / max(total_value, 1) + 2,
            f"{top5_value}/{total_value}",
            ha="center",
            fontsize=11,
        )

    false_axis = axes[1, 1]
    singles = [float(row["max_false_gain"]) for row in results if row["kind"] == "single"]
    all_cases = [float(row["max_false_gain"]) for row in results]
    false_axis.boxplot(
        [singles, all_cases],
        tick_labels=["single phase\n(n=20)", "all true phases\nselected (n=50)"],
        widths=0.48,
        patch_artist=True,
        boxprops={"facecolor": "#d9e3ed", "edgecolor": "#4a637d"},
        medianprops={"color": "#b64a3c", "linewidth": 1.6},
        whiskerprops={"color": "#4a637d"},
        capprops={"color": "#4a637d"},
        flierprops={"marker": "o", "markersize": 4, "markerfacecolor": "#b64a3c"},
    )
    false_axis.axhline(5.0, color="#b64a3c", linestyle="--", linewidth=1.2, label="5% threshold")
    false_axis.set_title("(d) Residual false Gain", loc="left", fontweight="bold")
    false_axis.set_ylabel("maximum unselected-family Gain (%)")
    false_axis.set_ylim(-0.2, 5.8)
    false_axis.spines[["top", "right"]].set_visible(False)
    false_axis.legend(frameon=False, loc="upper left")
    false_axis.text(
        1.5,
        0.35,
        f"0/{len(singles)} single-phase cases reached 5%",
        ha="center",
        fontsize=12,
    )

    figure.suptitle(
        "Version 1.2.0 closed-world synthetic Match/Gain benchmark",
        fontsize=17,
        fontweight="bold",
    )
    figure.savefig(OUTPUT / "fig7_benchmark.png", dpi=300, facecolor="white")
    figure.savefig(OUTPUT / "fig7_benchmark.svg", facecolor="white")
    plt.close(figure)


if __name__ == "__main__":
    main()
