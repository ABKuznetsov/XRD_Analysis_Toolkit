from __future__ import annotations

import json
import gc
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from xrd_finder.services.local_phase_cache import LocalPhaseCache


class LocalPhaseCacheReindexTests(unittest.TestCase):
    def test_cached_peak_calculation_uses_cristma_when_cif_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cif_path = Path(tmp) / "phase.cif"
            cif_path.write_text("data_test\n", encoding="utf-8")
            expected = [SimpleNamespace(two_theta=15.94, intensity=42.4)]

            class FakeAdapter:
                def reference_sticks_from_cif(self, path, **kwargs):
                    self.call = (Path(path), kwargs)
                    return tuple(expected)

                def sticks_from_cif(self, *_args, **_kwargs):
                    raise AssertionError("bulk indexing must not enter the slow fallback path")

            cache = object.__new__(LocalPhaseCache)
            cache._cristma_powder_adapter = FakeAdapter()
            cache._calculated_pattern_service = SimpleNamespace(
                calculate_sticks=lambda *_args, **_kwargs: []
            )

            result = cache._calculate_cached_peaks(SimpleNamespace(wavelength=1.54056), cif_path)

            self.assertEqual(result, expected)
            self.assertEqual(cache._cristma_powder_adapter.call[0], cif_path)
            self.assertTrue(cache._cristma_powder_adapter.call[1]["use_lp"])

    def test_build_index_reindexes_cif_paths_already_recorded_in_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = LocalPhaseCache(root / "cache")
            payload = {
                "schema_version": 1,
                "application": "XRD Phase Finder",
                "library": "phase_library",
                "sources": ["USER"],
                "entries": [{
                    "source": "USER",
                    "entry_id": "nested-entry",
                    "formula": "LiB3O5",
                    "name": "LiB3O5",
                    "cif_text": "data_test\n_cell_length_a 5.0\n",
                }],
            }
            incoming = root / "incoming.json"
            incoming.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(cache.import_phase_library(incoming), 1)
            stored = cache.get("USER", "nested-entry")
            self.assertIsNotNone(stored)
            self.assertTrue(Path(stored.cif_path).is_file())

            indexed = []

            def record_index(cif_path, source, entry_id, fallback=None, **_kwargs):
                indexed.append((Path(cif_path), source, entry_id))
                return True

            with patch.object(cache, "index_cif", side_effect=record_index):
                self.assertEqual(cache.build_index(), 1)

            self.assertEqual(indexed, [(Path(stored.cif_path), "USER", "nested-entry")])
            del stored, cache
            gc.collect()


if __name__ == "__main__":
    unittest.main()
