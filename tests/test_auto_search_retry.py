from __future__ import annotations

import unittest
from types import SimpleNamespace

from xrd_finder.services.candidate_search_service import CandidateSearchService


class PeakSearchRetryTests(unittest.TestCase):
    def test_geometric_fingerprint_shortlist_is_used_before_broad_peak_query(self):
        calls = []
        candidate = object()

        class Cache:
            def search_by_geometric_fingerprint(self, positions, **kwargs):
                calls.append(("fingerprint", len(positions), kwargs["limit"]))
                return [candidate]

            def search_by_peaks(self, positions, **kwargs):
                calls.append(("peaks", len(positions), kwargs["limit"]))
                return []

        service = CandidateSearchService.__new__(CandidateSearchService)
        service.local_phase_cache = Cache()
        service._dedupe_cached_entries = lambda rows: rows
        options = SimpleNamespace(
            observed_peak_positions=[float(value) for value in range(80)],
            excluded_elements=[],
            local_sources=["USER", "COD", "MP"],
        )

        result = service.search_local_cache(options, elements=[])

        self.assertEqual(result, [candidate])
        self.assertEqual(calls, [("fingerprint", 80, service.LOCAL_FINGERPRINT_RESULT_LIMIT)])

    def test_empty_full_peak_query_retries_with_smaller_preselection(self):
        lengths = []
        candidate = object()

        class Cache:
            def search_by_geometric_fingerprint(self, positions, **kwargs):
                return []

            def search_by_peaks(self, positions, **kwargs):
                lengths.append(len(positions))
                return [] if len(positions) > 32 else [candidate]

        service = CandidateSearchService.__new__(CandidateSearchService)
        service.local_phase_cache = Cache()
        service._dedupe_cached_entries = lambda rows: rows
        options = SimpleNamespace(
            observed_peak_positions=[float(value) for value in range(80)],
            excluded_elements=[],
            local_sources=["USER", "COD", "MP"],
        )

        result = service.search_local_cache(options, elements=[])

        self.assertEqual(result, [candidate])
        self.assertEqual(lengths, [80, 32])


if __name__ == "__main__":
    unittest.main()
