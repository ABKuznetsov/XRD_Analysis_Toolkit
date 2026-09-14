from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from xrd_finder.instrument.models import InstrumentProfile
from xrd_finder.services.diffraction_backend_comparison import compare_cif_backends


def _default_cifs() -> list[Path]:
    candidates = [APP_ROOT / "Entry_96-100-0018.cif"]
    cache = APP_ROOT / "data" / "cod_cache" / "cif"
    candidates.extend(cache / name for name in ("1010437.cif", "1100067.cif"))
    return [path for path in candidates if path.is_file()]


def _markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Diffraction backend comparison",
        "",
        "Legacy Finder and CrIStMa are compared without changing Match/Gain heuristics.",
        "Line agreement uses the strongest legacy reflections and a 0.15 deg tolerance.",
        "",
        "| CIF | Legacy lines | CrIStMa lines | Strong lines matched | Median delta (deg) | Profile corr. | Legacy (s) | CrIStMa (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {name} | {legacy_line_count} | {cristma_line_count} | {matched:.0%} | "
            "{median:.4f} | {correlation:.3f} | {legacy_seconds:.3f} | {cristma_seconds:.3f} |".format(
                name=Path(str(row["cif_path"])).name,
                legacy_line_count=row["legacy_line_count"],
                cristma_line_count=row["cristma_line_count"],
                matched=float(row["strong_line_match_fraction"]),
                median=float(row["median_position_delta_deg"]),
                correlation=float(row["profile_correlation"]),
                legacy_seconds=float(row["legacy_seconds"]),
                cristma_seconds=float(row["cristma_seconds"]),
            )
        )
    lines.extend(
        [
            "",
            "Profile correlation is diagnostic only: the engines use different scattering and correction models.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Finder legacy and CrIStMa powder calculations on CIF files."
    )
    parser.add_argument("cif", nargs="*", type=Path, help="CIF files to compare")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=APP_ROOT / "benchmark_results" / "diffraction_backend_current",
    )
    args = parser.parse_args()

    cif_paths = args.cif or _default_cifs()
    if not cif_paths:
        parser.error("No CIF files were supplied and no default fixtures were found")

    profile = InstrumentProfile.default_cu_kalpha()
    rows = [
        compare_cif_backends(path, instrument_profile=profile).to_dict()
        for path in cif_paths
    ]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "README.md").write_text(_markdown(rows), encoding="utf-8")
    print(_markdown(rows), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
