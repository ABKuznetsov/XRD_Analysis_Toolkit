from __future__ import annotations

import unittest
from unittest.mock import patch

from xrd_finder.services.candidate_preparation_queue import CandidatePreparationProgress
from xrd_finder.ui.candidate_search_actions import PhaseFinderCandidateSearchActionsMixin
from xrd_finder.ui.selected_phases_actions import PhaseFinderSelectedPhasesActionsMixin


class _PreparationQueue:
    def __init__(self, progress: CandidatePreparationProgress):
        self.current = progress

    def progress(self):
        return self.current


class _SearchService:
    def __init__(self, progress: CandidatePreparationProgress):
        self.preparation_queue = _PreparationQueue(progress)

    @staticmethod
    def dedupe_candidate_rows(rows):
        return list(rows)


class _Table:
    def __init__(self):
        self.rows = []

    def upsert_rows(self, rows, _normalizer):
        self.rows.extend(rows)


class _Host(PhaseFinderCandidateSearchActionsMixin):
    def __init__(self, progress: CandidatePreparationProgress):
        self.match_candidates = [{"Entry": "accepted"}]
        self.candidate_search_service = _SearchService(progress)
        self.candidate_table = _Table()
        self._candidate_batch_updates = None
        self.scheduled = 0

    def _apply_candidate_element_filter(self):
        pass

    def _schedule_candidate_gain_ranking(self):
        self.scheduled += 1


class CandidateGainRefreshTests(unittest.TestCase):
    def test_background_rows_wait_for_queue_to_become_idle_before_gain_refresh(self):
        busy = CandidatePreparationProgress(queued=8, downloading=1, indexing=0)
        host = _Host(busy)

        host._merge_prepared_candidate_rows([["COD", "1", "Si O2", "Quartz"]])

        self.assertEqual(host.scheduled, 0)
        self.assertTrue(host._candidate_gain_refresh_after_preparation)

        idle = CandidatePreparationProgress()
        host.candidate_search_service.preparation_queue.current = idle
        callbacks = []
        with patch(
            "xrd_finder.ui.candidate_search_actions.QTimer.singleShot",
            side_effect=lambda _delay, callback: callbacks.append(callback),
        ):
            host._handle_candidate_preparation_progress(idle)

        self.assertEqual(host.scheduled, 0)
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        self.assertEqual(host.scheduled, 1)
        self.assertFalse(host._candidate_gain_refresh_after_preparation)

    def test_repeated_requests_during_gain_coalesce_into_one_follow_up(self):
        class GainHost(PhaseFinderSelectedPhasesActionsMixin):
            def __init__(self):
                self._candidate_gain_ranking_pending = False
                self._candidate_gain_ranking_running = False
                self._candidate_gain_refresh_requested = False
                self.refreshes = 0

            def _refresh_candidate_gain_ranking(self):
                self.refreshes += 1
                if self.refreshes == 1:
                    self._schedule_candidate_gain_ranking()
                    self._schedule_candidate_gain_ranking()

        host = GainHost()
        callbacks = []
        with patch(
            "xrd_finder.ui.selected_phases_actions.QTimer.singleShot",
            side_effect=lambda _delay, callback: callbacks.append(callback),
        ):
            host._schedule_candidate_gain_ranking()
            self.assertEqual(len(callbacks), 1)
            callbacks.pop(0)()
            self.assertEqual(host.refreshes, 1)
            self.assertEqual(len(callbacks), 1)
            callbacks.pop(0)()

        self.assertEqual(host.refreshes, 2)
        self.assertFalse(host._candidate_gain_ranking_running)


if __name__ == "__main__":
    unittest.main()
