from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from benchmarks.match.scenarios import ScenarioConfig, build_scenario_manifest
from benchmarks.match.splits import PhaseDescriptor, assign_split_families


@dataclass(frozen=True, slots=True)
class BuildConfig:
    source_index: Path
    output: Path
    max_bytes: int = 20 * 1024 * 1024
    max_reference_lines: int = 64
    smoke: bool = False


@dataclass(frozen=True, slots=True)
class DatasetBuildResult:
    path: Path
    sha256: str
    reference_phases: int
    reference_peaks: int
    size_bytes: int


def build_dataset(config: BuildConfig) -> DatasetBuildResult:
    source_path = Path(config.source_index).resolve()
    output = Path(config.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    temporary.unlink(missing_ok=True)
    output.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = sqlite3.connect(temporary)
    target.execute("pragma foreign_keys = on")
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    target.executescript(schema)
    phase_count = 0
    peak_count = 0
    signatures: set[tuple[tuple[float, float], ...]] = set()
    descriptors = []
    try:
        phase_sql = """
            select source, entry_id, formula, name, spacegroup
            from phases as p
            where source = 'COD'
              and exists(
                  select 1 from phase_peaks as pp
                  where pp.source = p.source and pp.entry_id = p.entry_id
              )
            order by entry_id
        """
        if config.smoke:
            phase_sql += " limit 64"
        rows = source.execute(phase_sql).fetchall()
        for row in rows:
            peaks = source.execute(
                """
                select peak_index, two_theta, d,
                       coalesce(
                           intensity,
                           case when norm_intensity <= 1.5 then norm_intensity * 100.0 else norm_intensity end,
                           raw_intensity,
                           0
                       ) as intensity,
                       h, k, l, multiplicity
                from phase_peaks
                where source = 'COD' and entry_id = ?
                  and two_theta between 5 and 120
                  and coalesce(
                      intensity,
                      case when norm_intensity <= 1.5 then norm_intensity * 100.0 else norm_intensity end,
                      raw_intensity,
                      0
                  ) >= 1
                order by coalesce(
                    intensity,
                    case when norm_intensity <= 1.5 then norm_intensity * 100.0 else norm_intensity end,
                    raw_intensity,
                    0
                ) desc
                limit ?
                """,
                (row["entry_id"], max(3, int(config.max_reference_lines))),
            ).fetchall()
            if len(peaks) < 3:
                continue
            signature = tuple(
                sorted((round(float(peak["two_theta"]), 4), round(float(peak["intensity"]), 3)) for peak in peaks)
            )
            if signature in signatures:
                continue
            signatures.add(signature)
            phase_id = f"COD:{row['entry_id']}"
            formula = str(row["formula"] or "")
            formula_key = _formula_key(formula)
            family_id = f"{formula_key}:{hashlib.sha1(repr(signature).encode('utf-8')).hexdigest()[:12]}"
            target.execute(
                "insert into reference_phases values(?, 'COD', ?, ?, ?, ?, ?, ?)",
                (
                    phase_id,
                    str(row["entry_id"]),
                    formula,
                    formula_key,
                    str(row["name"] or ""),
                    str(row["spacegroup"] or ""),
                    family_id,
                ),
            )
            category = "organic" if "C" in _elements(formula) and "H" in _elements(formula) else "inorganic"
            target.execute(
                "insert into phase_categories values(?, ?, ?)",
                (phase_id, category, "contains C and H" if category == "organic" else "default"),
            )
            descriptors.append(PhaseDescriptor(phase_id, family_id, category))
            for new_index, peak in enumerate(sorted(peaks, key=lambda item: float(item["two_theta"]))):
                target.execute(
                    "insert into reference_peaks values(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        phase_id,
                        new_index,
                        float(peak["two_theta"]),
                        float(peak["d"]) if peak["d"] is not None else None,
                        float(peak["intensity"]),
                        peak["h"],
                        peak["k"],
                        peak["l"],
                        peak["multiplicity"],
                    ),
                )
                peak_count += 1
            phase_count += 1
        assignments = assign_split_families(descriptors, seed=5036)
        for family_id, split in sorted({(item.family_id, item.split) for item in assignments}):
            target.execute("insert into split_assignments values(?, ?)", (family_id, split))
        scenarios = build_scenario_manifest(descriptors, assignments, ScenarioConfig(seed=5036))
        for scenario in scenarios:
            target.execute(
                "insert into scenario_definitions values(?, ?, ?, ?)",
                (
                    scenario.scenario_id,
                    scenario.split,
                    scenario.seed,
                    json.dumps(asdict(scenario), sort_keys=True, separators=(",", ":")),
                ),
            )
            for component_order, component in enumerate(scenario.components):
                target.execute(
                    "insert into scenario_components values(?, ?, ?, ?)",
                    (
                        scenario.scenario_id,
                        component.phase_id,
                        component.fraction,
                        component_order,
                    ),
                )
        target.execute("insert into dataset_meta values('schema_version', '1')")
        target.execute("insert into dataset_meta values('source', 'COD peak index')")
        target.execute("insert into dataset_meta values('scenario_seed', '5036')")
        target.commit()
        integrity = target.execute("pragma integrity_check").fetchone()[0]
        violations = target.execute("pragma foreign_key_check").fetchall()
        if integrity != "ok" or violations:
            raise ValueError(f"Invalid benchmark database: integrity={integrity}, foreign_keys={len(violations)}")
    except Exception:
        target.close()
        source.close()
        temporary.unlink(missing_ok=True)
        raise
    target.close()
    source.close()
    size = temporary.stat().st_size
    if size > int(config.max_bytes):
        temporary.unlink(missing_ok=True)
        raise ValueError(f"Benchmark database is {size} bytes; limit is {config.max_bytes} bytes.")
    temporary.replace(output)
    return DatasetBuildResult(output, _sha256(output), phase_count, peak_count, size)


def _elements(formula: str) -> set[str]:
    return set(re.findall(r"[A-Z][a-z]?", formula))


def _formula_key(formula: str) -> str:
    return "".join(sorted(re.sub(r"\s+", "", formula).upper()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the compact Match/Gain benchmark database.")
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = build_dataset(BuildConfig(args.source_index, args.output, smoke=args.smoke))
    print(
        f"Built {result.path}: {result.reference_phases} phases, "
        f"{result.reference_peaks} peaks, {result.size_bytes} bytes, sha256={result.sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
