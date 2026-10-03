from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from benchmarks.match.build_dataset import BuildConfig, build_dataset
from benchmarks.match.dataset import BenchmarkDataset


def _source_cache(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        create table phases(
            source text, entry_id text, formula text, name text, spacegroup text,
            updated_at real, peaks_json text
        );
        create table phase_peaks(
            source text, entry_id text, peak_index integer, two_theta real, d real,
            intensity real, norm_intensity real, top_rank integer, raw_intensity real,
            h integer, k integer, l integer, multiplicity integer
        );
        """
    )
    for source, entry_id in (("COD", "100"), ("USER", "private"), ("MP", "mp-1")):
        connection.execute(
            "insert into phases values(?, ?, ?, ?, ?, 1, ?)",
            (source, entry_id, "Si O2", "Quartz", "P 31 2 1", "[]"),
        )
        for index, (angle, intensity) in enumerate(((20.0, 100.0), (26.6, 80.0), (50.1, 30.0))):
            connection.execute(
                "insert into phase_peaks values(?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 0, 2)",
                (source, entry_id, index, angle, 1.0, intensity, intensity / 100.0, index + 1, intensity),
            )
    connection.commit()
    connection.close()


class DatasetTests(unittest.TestCase):
    def test_smoke_limit_counts_only_peak_indexed_cod_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "index.sqlite"
            output = root / "benchmark.sqlite"
            _source_cache(source)
            connection = sqlite3.connect(source)
            for index in range(70):
                connection.execute(
                    "insert into phases values('COD', ?, 'C', 'empty', 'P 1', 2, '')",
                    (f"000{index:03d}",),
                )
            connection.commit()
            connection.close()

            result = build_dataset(BuildConfig(source_index=source, output=output, smoke=True))

            self.assertEqual(result.reference_phases, 1)

    def test_builds_cod_only_database_and_opens_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "index.sqlite"
            output = root / "benchmark.sqlite"
            _source_cache(source)

            result = build_dataset(BuildConfig(source_index=source, output=output, max_bytes=2_000_000))

            self.assertEqual(result.reference_phases, 1)
            with BenchmarkDataset.open(output) as dataset:
                self.assertEqual(dataset.reference_count(), 1)
                self.assertEqual(dataset.reference_ids(), ("COD:100",))
                self.assertEqual(dataset.phase_descriptors()[0].phase_id, "COD:100")
                self.assertEqual(len(dataset.reference_library()["COD:100"]), 3)
                self.assertEqual(dataset.connection.execute("select count(*) from split_assignments").fetchone()[0], 1)
                self.assertGreater(dataset.connection.execute("select count(*) from scenario_definitions").fetchone()[0], 0)
                with self.assertRaises(sqlite3.OperationalError):
                    dataset.connection.execute("delete from reference_phases")

    def test_rejects_output_above_configured_size(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "index.sqlite"
            _source_cache(source)

            with self.assertRaises(ValueError):
                build_dataset(BuildConfig(source_index=source, output=root / "too-large.sqlite", max_bytes=1))


if __name__ == "__main__":
    unittest.main()
