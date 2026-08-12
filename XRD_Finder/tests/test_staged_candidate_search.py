from __future__ import annotations

from types import SimpleNamespace
import unittest

from xrd_finder.services.candidate_search_service import (
    CandidateSearchOptions,
    CandidateSearchService,
)


class _Cache:
    root = None

    def __init__(self) -> None:
        self.upserted = []

    def search_is_fresh(self, _source: str, _key: str) -> bool:
        return False

    def upsert_cod_entries(self, entries) -> None:
        self.upserted.extend(entries)


class _CodOnline:
    def search_elements(self, elements, *, excluded_elements, limit):
        del elements, excluded_elements, limit
        return [SimpleNamespace(cod_id="200", formula="Ba O", name="online")]


class StagedCandidateSearchTests(unittest.TestCase):
    def test_local_rows_are_emitted_before_online_rows_are_merged(self) -> None:
        service = object.__new__(CandidateSearchService)
        service.local_phase_cache = _Cache()
        service.cod_online = _CodOnline()
        service._timed_search_local_cache = lambda *_args: [object()]
        service.cache_rows = lambda _entries: [["USER", "100", "Ba O", "local", "", ""]]
        service.filter_cod_entries = lambda entries, _options: entries
        service.cod_rows = lambda _entries: [["COD", "200", "Ba O", "online", "", ""]]
        service.queue_background_cod_downloads = lambda _entries: 0
        service._mark_search_if_complete = lambda *_args: None
        service._emit_background_status = lambda _message: None
        service._queue_background_cod_elements_refresh = lambda *_args: self.fail(
            "staged search must finish the online query instead of detaching it"
        )

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

        rows = service.search_elements(
            ["Ba", "O"],
            options,
            partial_results=partial.append,
        )

        self.assertEqual(partial, [[["USER", "100", "Ba O", "local", "", "", "", ""]]])
        self.assertEqual(
            rows,
            [
                ["USER", "100", "Ba O", "local", "", "", "", ""],
                ["COD", "200", "Ba O", "online", "", "", "", ""],
            ],
        )


if __name__ == "__main__":
    unittest.main()
