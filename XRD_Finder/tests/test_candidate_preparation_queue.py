from __future__ import annotations

import threading
import unittest

from xrd_finder.services.candidate_preparation_queue import (
    CandidatePreparationJob,
    CandidatePreparationQueue,
    CandidatePreparationStage,
)


class CandidatePreparationQueueTests(unittest.TestCase):
    def test_job_downloads_then_indexes_and_notifies_all_sessions(self) -> None:
        calls: list[str] = []
        notices = []
        progress = []
        fetch_started = threading.Event()
        release_fetch = threading.Event()
        completed = threading.Event()

        def receive(notice) -> None:
            notices.append(notice)
            completed.set()

        def fetch() -> str:
            calls.append("fetch")
            fetch_started.set()
            release_fetch.wait(2.0)
            return "/tmp/100.cif"

        worker = CandidatePreparationQueue(
            notice_callback=receive,
            progress_callback=progress.append,
        )
        self.addCleanup(worker.shutdown)
        job = CandidatePreparationJob(
            source="cod",
            entry_id="100",
            fetch=fetch,
            index=lambda path: calls.append(f"index:{path}") or "indexed",
        )

        self.assertTrue(worker.submit(job, session_token=3))
        self.assertTrue(fetch_started.wait(2.0))
        self.assertFalse(worker.submit(job, session_token=4))
        release_fetch.set()
        self.assertTrue(completed.wait(2.0))

        self.assertEqual(calls, ["fetch", "index:/tmp/100.cif"])
        self.assertEqual(notices[0].source, "COD")
        self.assertEqual(notices[0].entry_id, "100")
        self.assertEqual(notices[0].session_tokens, (3, 4))
        self.assertEqual(notices[0].stage, CandidatePreparationStage.READY)
        self.assertEqual(notices[0].result, "indexed")
        self.assertTrue(any(item.downloading == 1 for item in progress))
        self.assertTrue(any(item.indexing == 1 for item in progress))

    def test_index_only_job_skips_download(self) -> None:
        indexed = threading.Event()
        notices = []
        worker = CandidatePreparationQueue(
            notice_callback=lambda notice: (notices.append(notice), indexed.set())
        )
        self.addCleanup(worker.shutdown)

        worker.submit(
            CandidatePreparationJob(
                source="MP",
                entry_id="mp-1",
                index=lambda path: path,
                existing_payload="/tmp/mp-1.cif",
            ),
            session_token=7,
        )

        self.assertTrue(indexed.wait(2.0))
        self.assertEqual(notices[0].result, "/tmp/mp-1.cif")
        self.assertEqual(notices[0].stage, CandidatePreparationStage.READY)

    def test_failed_job_updates_progress_without_stopping_worker(self) -> None:
        completed = threading.Event()
        notices = []
        progress = []
        worker = CandidatePreparationQueue(
            notice_callback=lambda notice: (notices.append(notice), completed.set()),
            progress_callback=progress.append,
        )
        self.addCleanup(worker.shutdown)

        worker.submit(
            CandidatePreparationJob(
                source="COD",
                entry_id="offline",
                fetch=lambda: (_ for _ in ()).throw(OSError("offline")),
                index=lambda path: path,
            ),
            session_token=9,
        )

        self.assertTrue(completed.wait(2.0))
        self.assertEqual(notices[0].stage, CandidatePreparationStage.FAILED)
        self.assertIn("offline", notices[0].error)
        self.assertEqual(progress[-1].failed, 1)
        self.assertEqual(progress[-1].queued, 0)


if __name__ == "__main__":
    unittest.main()
