from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from benchmarks.match.generate_profiles import ReferenceLine
from benchmarks.match.splits import PhaseDescriptor


@dataclass(slots=True)
class BenchmarkDataset:
    path: Path
    connection: sqlite3.Connection

    @classmethod
    def open(cls, path: Path | str, *, immutable: bool = True) -> "BenchmarkDataset":
        resolved = Path(path).resolve()
        query = f"file:{resolved.as_posix()}?mode=ro"
        if immutable:
            query += "&immutable=1"
        connection = sqlite3.connect(query, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        return cls(path=resolved, connection=connection)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "BenchmarkDataset":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def reference_count(self) -> int:
        return int(self.connection.execute("select count(*) from reference_phases").fetchone()[0])

    def reference_ids(self) -> tuple[str, ...]:
        rows = self.connection.execute("select phase_id from reference_phases order by phase_id").fetchall()
        return tuple(str(row[0]) for row in rows)

    def phase_descriptors(self) -> tuple[PhaseDescriptor, ...]:
        rows = self.connection.execute(
            """
            select p.phase_id, p.family_id, coalesce(c.category, 'inorganic') as category
            from reference_phases as p
            left join phase_categories as c on c.phase_id = p.phase_id
            order by p.phase_id
            """
        ).fetchall()
        return tuple(PhaseDescriptor(str(row[0]), str(row[1]), str(row[2])) for row in rows)

    def reference_library(self) -> dict[str, tuple[ReferenceLine, ...]]:
        rows = self.connection.execute(
            """
            select phase_id, two_theta, intensity, d, h, k, l, multiplicity
            from reference_peaks
            order by phase_id, peak_index
            """
        ).fetchall()
        result: dict[str, list[ReferenceLine]] = {}
        for row in rows:
            result.setdefault(str(row[0]), []).append(
                ReferenceLine(
                    float(row[1]),
                    float(row[2]),
                    None if row[3] is None else float(row[3]),
                    None if row[4] is None else int(row[4]),
                    None if row[5] is None else int(row[5]),
                    None if row[6] is None else int(row[6]),
                    None if row[7] is None else int(row[7]),
                )
            )
        return {phase_id: tuple(lines) for phase_id, lines in result.items()}


__all__ = ["BenchmarkDataset"]
