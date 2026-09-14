from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION, CachedPhaseEntry, LocalPhaseCache
from xrd_finder.ui.candidate_line_provider import CandidateLineProvider, LineSetStatus


class CandidateLineProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache = LocalPhaseCache(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _seed(self, entry_id: str, *, version: int) -> None:
        peaks = [
            {
                "d": 3.0,
                "two_theta": 30.0,
                "intensity": 100.0,
                "raw_intensity": 120.0,
                "h": 1,
                "k": 1,
                "l": 0,
                "multiplicity": 8,
            },
            {
                "d": 2.0,
                "two_theta": 45.0,
                "intensity": 25.0,
                "raw_intensity": 40.0,
                "h": 2,
                "k": 0,
                "l": 0,
                "multiplicity": 4,
            },
        ]
        with self.cache._connect() as connection:
            self.cache._upsert(
                connection,
                CachedPhaseEntry(
                    source="COD",
                    entry_id=entry_id,
                    formula="Ca O",
                    name="test",
                    peaks_json=json.dumps(peaks),
                    derived_version=version,
                ),
                keep_cif=False,
            )

    def test_current_sql_peak_rows_are_returned_in_index_order(self) -> None:
        self._seed("current", version=DERIVED_CACHE_VERSION)

        records = self.cache.peak_records("COD", "current")

        self.assertEqual([record["peak_index"] for record in records], [0, 1])
        self.assertEqual(records[0]["norm_intensity"], 1.0)
        self.assertEqual(records[0]["raw_intensity"], 120.0)
        self.assertEqual(records[0]["multiplicity"], 8)

    def test_provider_distinguishes_ready_obsolete_and_unsupported_rows(self) -> None:
        self._seed("current", version=DERIVED_CACHE_VERSION)
        self._seed("old", version=DERIVED_CACHE_VERSION - 1)
        provider = CandidateLineProvider(self.cache)

        ready = provider.resolve({"Source": "COD", "Entry": "current"})
        obsolete = provider.resolve({"Source": "COD", "Entry": "old"})
        unsupported = provider.resolve({"Source": "PDF2", "Entry": "00-001"})

        self.assertEqual(ready.status, LineSetStatus.READY)
        self.assertIsNotNone(ready.line_set)
        self.assertEqual(len(ready.line_set.lines), 2)
        self.assertFalse(ready.needs_index)
        self.assertEqual(obsolete.status, LineSetStatus.OBSOLETE)
        self.assertTrue(obsolete.needs_index)
        self.assertEqual(unsupported.status, LineSetStatus.UNSUPPORTED)
        self.assertFalse(unsupported.needs_index)


if __name__ == "__main__":
    unittest.main()
