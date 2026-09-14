from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from xrd_finder.services.candidate_preparation_queue import (
    CandidatePreparationProgress,
    CandidatePreparationStage,
    CandidatePreparedNotice,
)
from xrd_finder.ui.candidate_batch_updates import CandidateBatchUpdateController


def _notice(
    token: int,
    entry_id: str,
    stage: CandidatePreparationStage = CandidatePreparationStage.READY,
) -> CandidatePreparedNotice:
    return CandidatePreparedNotice(
        session_tokens=(token,),
        source="COD",
        entry_id=entry_id,
        stage=stage,
    )


class CandidateBatchUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_ready_notices_are_deduplicated_and_flushed_as_one_batch(self) -> None:
        batches: list[list[list[str]]] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda source, entry: [source, entry, "Al2 O3", "Corundum"],
            rows_ready=batches.append,
            interval_ms=60_000,
        )
        controller.start_session(7)

        self.assertTrue(controller.accept_notice(_notice(7, "100")))
        self.assertTrue(controller.accept_notice(_notice(7, "100")))
        self.assertTrue(controller.accept_notice(_notice(7, "200")))

        self.assertEqual(controller.flush_now(), 2)
        self.assertEqual([[row[1] for row in batch] for batch in batches], [["100", "200"]])
        controller.stop()

    def test_stale_session_never_updates_visible_rows(self) -> None:
        batches: list[list[list[str]]] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda source, entry: [source, entry],
            rows_ready=batches.append,
            interval_ms=60_000,
        )
        controller.start_session(8)

        self.assertFalse(controller.accept_notice(_notice(7, "100")))
        self.assertEqual(controller.flush_now(), 0)
        self.assertEqual(batches, [])
        controller.stop()

    def test_new_session_discards_unflushed_rows_from_previous_search(self) -> None:
        batches: list[list[list[str]]] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda source, entry: [source, entry],
            rows_ready=batches.append,
            interval_ms=60_000,
        )
        controller.start_session(1)
        controller.accept_notice(_notice(1, "old"))

        controller.start_session(2)
        controller.accept_notice(_notice(2, "new"))

        self.assertEqual(controller.flush_now(), 1)
        self.assertEqual(batches, [[['COD', 'new']]])
        controller.stop()

    def test_failed_notice_is_reported_but_not_loaded(self) -> None:
        statuses: list[str] = []
        loads: list[str] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda _source, entry: loads.append(entry) or [entry],
            rows_ready=lambda _rows: None,
            status_callback=statuses.append,
            interval_ms=60_000,
        )
        controller.start_session(3)

        self.assertTrue(
            controller.accept_notice(
                _notice(3, "broken", CandidatePreparationStage.FAILED)
            )
        )
        self.assertEqual(controller.flush_now(), 0)
        self.assertEqual(loads, [])
        self.assertIn("failed 1", statuses[-1].lower())
        controller.stop()

    def test_status_combines_visible_rows_and_background_stages(self) -> None:
        statuses: list[str] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda source, entry: [source, entry],
            rows_ready=lambda _rows: None,
            status_callback=statuses.append,
            interval_ms=60_000,
        )
        controller.start_session(4)
        controller.set_local_rows(18)
        controller.accept_progress(
            CandidatePreparationProgress(
                queued=7,
                downloading=1,
                indexing=2,
                ready=5,
                failed=1,
            )
        )

        status = statuses[-1].lower()
        self.assertIn("local 18", status)
        self.assertIn("queued 7", status)
        self.assertIn("downloading 1", status)
        self.assertIn("indexing 2", status)
        self.assertIn("ready 5", status)
        self.assertIn("failed 1", status)
        controller.stop()

    def test_short_title_shows_search_loading_and_best_candidate_count(self) -> None:
        titles: list[str] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda source, entry: [source, entry],
            rows_ready=lambda _rows: None,
            title_callback=titles.append,
            interval_ms=60_000,
        )

        controller.start_session(5)
        self.assertEqual(titles[-1], "Candidate list: searching")

        controller.set_local_rows(10)
        self.assertEqual(titles[-1], "Candidate list: loading 10")

        controller.accept_progress(
            CandidatePreparationProgress(
                queued=90,
                downloading=0,
                indexing=0,
                ready=0,
                failed=0,
            )
        )
        self.assertEqual(titles[-1], "Candidate list: loading 10/100")

        controller.mark_search_complete(5)
        controller.accept_progress(
            CandidatePreparationProgress(
                queued=0,
                downloading=0,
                indexing=0,
                ready=90,
                failed=0,
            )
        )
        self.assertEqual(titles[-1], "Candidate list: best 10")
        controller.stop()

    def test_short_title_keeps_and_clears_search_notice(self) -> None:
        titles: list[str] = []
        controller = CandidateBatchUpdateController(
            row_loader=lambda source, entry: [source, entry],
            rows_ready=lambda _rows: None,
            title_callback=titles.append,
            interval_ms=60_000,
        )

        controller.start_session(11)
        controller.set_local_rows(4)
        controller.set_notice("COD server unavailable; using local data")
        self.assertEqual(
            titles[-1],
            "Candidate list: loading 4 (COD server unavailable; using local data)",
        )

        controller.mark_search_complete(11)
        self.assertEqual(
            titles[-1],
            "Candidate list: best 4 (COD server unavailable; using local data)",
        )

        controller.start_session(12)
        self.assertEqual(titles[-1], "Candidate list: searching")
        controller.stop()


if __name__ == "__main__":
    unittest.main()
