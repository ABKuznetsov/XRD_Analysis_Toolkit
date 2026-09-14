from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from xrd_finder.services.candidate_search_service import (
    CandidateSearchOptions,
    CandidateSearchService,
)
from xrd_finder.services.local_phase_cache import LocalPhaseCache


class _Cache:
    root = None

    def __init__(self) -> None:
        self.upserted = []

    def search_is_fresh(self, _source: str, _key: str) -> bool:
        return False

    def upsert_cod_entries(self, entries) -> None:
        self.upserted.extend(entries)

    def mark_search(self, source: str, key: str) -> None:
        self.marked = (source, key)


class _CodOnline:
    def __init__(self) -> None:
        self.calls = 0

    def search_elements(self, elements, *, excluded_elements, limit):
        del elements, excluded_elements, limit
        self.calls += 1
        return [SimpleNamespace(cod_id="200", formula="Ba O", name="online")]


class StagedCandidateSearchTests(unittest.TestCase):
    def test_local_rows_return_immediately_and_cod_refresh_runs_in_background(self) -> None:
        service = object.__new__(CandidateSearchService)
        service.local_phase_cache = _Cache()
        service.cod_online = _CodOnline()
        service._timed_search_local_cache = lambda *_args: [object()]
        service.cache_rows = lambda _entries: [["USER", "100", "Ba O", "local", "", ""]]
        service.filter_cod_entries = lambda entries, _options: entries
        service.cod_rows = lambda _entries: [["COD", "200", "Ba O", "online", "", ""]]
        refreshes = []

        def queue_refresh(cod_key, elements, options, *, session_token=None):
            refreshes.append((cod_key, tuple(elements), options, session_token))

        service._emit_background_status = lambda _message: None
        service._queue_background_cod_elements_refresh = queue_refresh

        options = CandidateSearchOptions(
            local_sources=["USER", "COD"],
            excluded_elements=[],
            cod_online_enabled=True,
            rruff_enabled=False,
            match_pdf2_enabled=False,
            materials_project_enabled=False,
            aflow_enabled=False,
            oqmd_enabled=False,
            structural_data_enabled=True,
            reference_patterns_enabled=False,
            material_class_allowed=lambda _formula: True,
        )
        partial = []

        traced_operations = []

        class _Trace:
            def __init__(self, name, **_fields) -> None:
                traced_operations.append(name)

            def __enter__(self):
                return None

            def __exit__(self, *_args):
                return False

        with patch(
            "xrd_finder.services.candidate_search_service.trace_operation",
            side_effect=_Trace,
        ):
            rows = service.search_elements(
                ["Ba", "O"],
                options,
                partial_results=partial.append,
                session_token=17,
            )

        self.assertEqual(partial, [[["USER", "100", "Ba O", "local", "", "", "", ""]]])
        self.assertEqual(rows, [["USER", "100", "Ba O", "local", "", "", "", ""]])
        self.assertEqual(service.cod_online.calls, 0)
        self.assertEqual(len(refreshes), 1)
        self.assertEqual(refreshes[0][1], ("Ba", "O"))
        self.assertIs(refreshes[0][2], options)
        self.assertEqual(refreshes[0][3], 17)
        self.assertNotIn("match.search.cod", traced_operations)

    def test_cod_result_is_marked_fresh_only_after_short_final_batch(self) -> None:
        service = object.__new__(CandidateSearchService)
        cache = _Cache()
        service.local_phase_cache = cache

        service._mark_search_if_complete("COD", "elements:Ba,O", 299, 300)

        self.assertEqual(cache.marked, ("COD", "elements:Ba,O"))

        cache.marked = None
        service._mark_search_if_complete("COD", "elements:Ba,O", 300, 300)
        self.assertIsNone(cache.marked)

    def test_cod_preparation_queues_every_unprepared_result_not_only_first_twenty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = object.__new__(CandidateSearchService)
            service.local_phase_cache = SimpleNamespace(cif_dir=Path(directory))
            queued: list[str] = []
            service._queue_candidate_preparation = lambda **kwargs: queued.append(
                kwargs["entry_id"]
            ) or True
            entries = [
                SimpleNamespace(cod_id=str(index), formula="Ba O", name="")
                for index in range(25)
            ]

            count = service.queue_background_cod_downloads(entries, session_token=9)

        self.assertEqual(count, 25)
        self.assertEqual(queued, [str(index) for index in range(25)])

    def test_incomplete_search_attempt_is_throttled_and_resumes_with_larger_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = LocalPhaseCache(Path(directory))
            cache.record_search_attempt(
                "COD",
                "elements:Ba,O",
                result_limit=300,
                complete=False,
            )

            self.assertTrue(cache.search_is_fresh("COD", "elements:Ba,O"))
            self.assertEqual(
                cache.next_search_limit(
                    "COD",
                    "elements:Ba,O",
                    base_limit=300,
                    maximum_limit=1200,
                ),
                600,
            )

    def test_cod_refresh_expands_full_result_until_server_returns_less_than_limit(self) -> None:
        service = object.__new__(CandidateSearchService)
        calls: list[int] = []
        queued_batches: list[int] = []
        cache = _Cache()
        service.local_phase_cache = cache
        service.ONLINE_RESULT_LIMIT = 300
        service.ONLINE_MAX_RESULT_LIMIT = 1200
        service.cod_online = SimpleNamespace(
            search_elements=lambda _elements, *, excluded_elements, limit: (
                calls.append(limit)
                or [
                    SimpleNamespace(cod_id=str(index), formula="Ba O", name="")
                    for index in range(limit if limit == 300 else 350)
                ]
            )
        )
        service.filter_cod_entries = lambda entries, _options: entries
        service.queue_background_cod_downloads = (
            lambda entries, *, session_token=None: queued_batches.append(len(entries)) or len(entries)
        )
        service._emit_background_status = lambda _message: None

        options = CandidateSearchOptions(
            local_sources=["COD"],
            excluded_elements=[],
            cod_online_enabled=True,
            rruff_enabled=False,
            match_pdf2_enabled=False,
            materials_project_enabled=False,
            aflow_enabled=False,
            oqmd_enabled=False,
            structural_data_enabled=True,
            reference_patterns_enabled=False,
            material_class_allowed=lambda _formula: True,
        )
        service._refresh_cod_elements_cache(
            "elements:Ba,O",
            ["Ba", "O"],
            options,
            session_token=4,
            result_limit=300,
        )

        self.assertEqual(calls, [300, 600])
        self.assertEqual(queued_batches, [300, 350])
        self.assertEqual(cache.marked, ("COD", "elements:Ba,O"))

    def test_empty_local_result_uses_the_expanding_cod_refresh_path(self) -> None:
        service = object.__new__(CandidateSearchService)
        service.local_phase_cache = _Cache()
        service._timed_search_local_cache = lambda *_args: []
        refresh_calls = []
        service._refresh_cod_elements_cache = (
            lambda cod_key, elements, options, *, session_token=None, result_limit=None:
            refresh_calls.append(
                (cod_key, tuple(elements), options, session_token, result_limit)
            )
        )

        options = CandidateSearchOptions(
            local_sources=["COD"],
            excluded_elements=[],
            cod_online_enabled=True,
            rruff_enabled=False,
            match_pdf2_enabled=False,
            materials_project_enabled=False,
            aflow_enabled=False,
            oqmd_enabled=False,
            structural_data_enabled=True,
            reference_patterns_enabled=False,
            material_class_allowed=lambda _formula: True,
        )

        rows = service.search_elements(
            ["Ba", "O"],
            options,
            session_token=23,
        )

        self.assertEqual(rows, [])
        self.assertEqual(len(refresh_calls), 1)
        self.assertEqual(
            refresh_calls[0][0],
            service.search_cache_key("elements", ["Ba", "O"], []),
        )
        self.assertEqual(refresh_calls[0][1], ("Ba", "O"))
        self.assertIs(refresh_calls[0][2], options)
        self.assertEqual(refresh_calls[0][3], 23)
        self.assertEqual(refresh_calls[0][4], service.ONLINE_RESULT_LIMIT)


if __name__ == "__main__":
    unittest.main()
