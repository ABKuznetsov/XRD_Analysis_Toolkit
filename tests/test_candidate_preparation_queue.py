from __future__ import annotations

import threading
import unittest

from xrd_finder.services.candidate_preparation_queue import (
    CandidatePreparationJob,
    CandidatePreparationQueue,
    CandidatePreparationStage,
)


class CandidatePreparationQueueCancellationTests(unittest.TestCase):
    def test_clear_drops_queued_work_and_detaches_active_download(self):
        download_started = threading.Event()
        release_download = threading.Event()
        sentinel_finished = threading.Event()
        calls: list[str] = []
        notices = []
        progress_updates = []
        preparation_queue = CandidatePreparationQueue(
            notice_callback=notices.append,
            progress_callback=progress_updates.append,
        )
        self.addCleanup(preparation_queue.shutdown)

        def blocking_fetch():
            calls.append("active-fetch")
            download_started.set()
            self.assertTrue(release_download.wait(2.0))
            return "active-payload"

        preparation_queue.submit(
            CandidatePreparationJob(
                source="COD",
                entry_id="active",
                fetch=blocking_fetch,
                index=lambda payload: calls.append("active-index"),
            ),
            session_token=7,
        )
        preparation_queue.submit(
            CandidatePreparationJob(
                source="COD",
                entry_id="queued",
                fetch=lambda: calls.append("queued-fetch"),
                index=lambda payload: calls.append("queued-index"),
            ),
            session_token=7,
        )
        self.assertTrue(download_started.wait(2.0))

        self.assertEqual(preparation_queue.clear(), 2)
        self.assertEqual(preparation_queue.progress().queued, 0)
        self.assertEqual(preparation_queue.progress().downloading, 0)
        release_download.set()

        preparation_queue.submit(
            CandidatePreparationJob(
                source="USER",
                entry_id="sentinel",
                existing_payload="sentinel-payload",
                index=lambda payload: sentinel_finished.set(),
            ),
            session_token=8,
        )
        self.assertTrue(sentinel_finished.wait(2.0))

        self.assertEqual(calls, ["active-fetch"])
        self.assertFalse(any(notice.entry_id in {"active", "queued"} for notice in notices))
        self.assertEqual(progress_updates[-1].queued, 0)
        self.assertEqual(progress_updates[-1].downloading, 0)

    def test_cancel_session_preserves_shared_job_for_other_session(self):
        download_started = threading.Event()
        release_download = threading.Event()
        notice_received = threading.Event()
        notices = []

        def record_notice(notice):
            notices.append(notice)
            notice_received.set()

        preparation_queue = CandidatePreparationQueue(notice_callback=record_notice)
        self.addCleanup(preparation_queue.shutdown)

        def blocking_fetch():
            download_started.set()
            self.assertTrue(release_download.wait(2.0))
            return "payload"

        job = CandidatePreparationJob(
            source="COD",
            entry_id="shared",
            fetch=blocking_fetch,
            index=lambda payload: payload,
        )
        self.assertTrue(preparation_queue.submit(job, session_token=11))
        self.assertFalse(preparation_queue.submit(job, session_token=12))
        self.assertTrue(download_started.wait(2.0))

        self.assertEqual(preparation_queue.cancel_session(11), 0)
        release_download.set()
        self.assertTrue(notice_received.wait(2.0))

        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].stage, CandidatePreparationStage.READY)
        self.assertEqual(notices[0].session_tokens, (12,))


if __name__ == "__main__":
    unittest.main()
