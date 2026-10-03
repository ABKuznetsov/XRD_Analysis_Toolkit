from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication

from xrd_finder.services.candidate_preparation_queue import (
    CandidatePreparationStage,
    CandidatePreparedNotice,
)
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION
from xrd_finder.ui.candidate_batch_updates import CandidateBatchUpdateController
from xrd_finder.ui.candidate_structure_actions import PhaseFinderCandidateStructureActionsMixin


class _ReadyCache:
    def __init__(self, cif_path: Path) -> None:
        self._path = cif_path
        self.index_calls = 0
        self.user_calls = 0

    def cif_path(self, _source: str, _entry_id: str) -> Path:
        return self._path

    def get(self, _source: str, _entry_id: str):
        return SimpleNamespace(derived_version=DERIVED_CACHE_VERSION)

    def peak_records(self, _source: str, _entry_id: str) -> list[object]:
        return [object()]

    def index_cif(self, *_args, **_kwargs) -> None:
        self.index_calls += 1

    def add_user_cif(self, *_args, **_kwargs) -> None:
        self.user_calls += 1


class _StaleCache(_ReadyCache):
    def get(self, _source: str, _entry_id: str):
        return SimpleNamespace(derived_version=0)

    def peak_records(self, _source: str, _entry_id: str) -> list[object]:
        return []


class _StructureHost(PhaseFinderCandidateStructureActionsMixin):
    def __init__(self, cache: _ReadyCache, *, busy: bool = False) -> None:
        self.local_phase_cache = cache
        self._busy = busy

    def _candidate_embedded_cif_path(self, _candidate):
        return None

    def _candidate_preparation_is_busy(self) -> bool:
        return self._busy


class CandidateUiResponsivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def test_preview_does_not_reindex_or_copy_a_ready_cached_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            cif_path = Path(directory) / "ready.cif"
            cif_path.write_text("data_ready\n", encoding="utf-8")
            cache = _ReadyCache(cif_path)
            host = _StructureHost(cache)

            host._integrate_ready_candidate_cif(
                {"Source": "COD", "Entry": "123"},
                refresh_rows=False,
            )

            self.assertEqual(cache.index_calls, 0)
            self.assertEqual(cache.user_calls, 0)

    def test_ready_rows_are_flushed_in_small_batches(self):
        batches: list[list[list[str]]] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda source, entry_id: [source, entry_id],
            rows_ready=batches.append,
            interval_ms=1000,
            max_batch_rows=3,
        )
        self.addCleanup(controller.stop)
        controller.start_session(7)
        for index in range(8):
            controller.accept_notice(
                CandidatePreparedNotice(
                    source="COD",
                    entry_id=str(index),
                    stage=CandidatePreparationStage.READY,
                    session_tokens=(7,),
                )
            )

        self.assertEqual(controller.flush_now(), 3)
        self.assertEqual(len(batches[0]), 3)
        self.assertEqual(len(controller._pending), 5)
        self.assertTrue(controller._timer.isActive())

    def test_selecting_a_candidate_being_prepared_does_not_index_it_again(self):
        with tempfile.TemporaryDirectory() as directory:
            cif_path = Path(directory) / "loading.cif"
            cif_path.write_text("data_loading\n", encoding="utf-8")
            cache = _StaleCache(cif_path)
            host = _StructureHost(cache, busy=True)
            ready_calls: list[object] = []

            host._with_candidate_cif_ready(
                {"Source": "COD", "Entry": "456"},
                "Preview structure",
                ready_calls.append,
            )

            self.assertEqual(cache.index_calls, 0)
            self.assertEqual(ready_calls, [])


if __name__ == "__main__":
    unittest.main()
