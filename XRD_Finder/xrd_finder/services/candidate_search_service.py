from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import itertools
import queue
import re
import threading

from xrd_finder.services.ccdc_service import CcdcService, extract_doi
from xrd_finder.services.cod_online_service import CodEntry, CodOnlineService, formula_elements
from xrd_finder.services.computational_database_service import AflowService, OqmdService
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION, LocalPhaseCache
from xrd_finder.services.match_pdf2_service import MatchPdf2Service
from xrd_finder.services.materials_project_service import MaterialsProjectService
from xrd_finder.services.rruff_service import RruffService

SearchProgressCallback = Callable[[str, int, int], None]


@dataclass(slots=True)
class CandidateSearchOptions:
    local_sources: list[str]
    excluded_elements: list[str]
    cod_online_enabled: bool
    rruff_enabled: bool
    match_pdf2_enabled: bool
    materials_project_enabled: bool
    aflow_enabled: bool
    oqmd_enabled: bool
    structural_data_enabled: bool
    reference_patterns_enabled: bool
    material_class_allowed: Callable[[str], bool]
    observed_peak_positions: list[float] = field(default_factory=list)


class CandidateSearchService:
    STRUCTURAL_RESULT_LIMIT = 500
    ONLINE_RESULT_LIMIT = 300
    COMPUTATIONAL_RESULT_LIMIT = 150
    BACKGROUND_DOWNLOAD_LIMIT = 20
    CCDC_RESULT_LIMIT = 20

    def __init__(
        self,
        local_phase_cache: LocalPhaseCache,
        cod_online: CodOnlineService,
        ccdc: CcdcService,
        rruff: RruffService,
        match_pdf2: MatchPdf2Service,
        materials_project: MaterialsProjectService,
        aflow: AflowService | None = None,
        oqmd: OqmdService | None = None,
    ) -> None:
        self.local_phase_cache = local_phase_cache
        self.cod_online = cod_online
        self.ccdc = ccdc
        self.rruff = rruff
        self.match_pdf2 = match_pdf2
        self.materials_project = materials_project
        self.aflow = aflow or AflowService()
        self.oqmd = oqmd or OqmdService()
        self._download_lock = threading.Lock()
        self._queued_downloads: set[tuple[str, str]] = set()
        self._refresh_lock = threading.Lock()
        self._queued_refreshes: set[tuple[str, str]] = set()
        self._download_counter = itertools.count()
        self._download_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._download_shutdown = False
        self._download_thread = threading.Thread(
            target=self._run_download_queue,
            name="xrd-cache-priority",
            daemon=True,
        )
        self._download_thread.start()

    def search_text(
        self,
        query: str,
        options: CandidateSearchOptions,
        progress: SearchProgressCallback | None = None,
    ) -> list[list[str]]:
        query = query.strip()
        if not query:
            return []

        rows = []
        query_elements = self.element_query_tokens(query)
        formula_query = self.formula_query_text(query)
        doi = extract_doi(query)
        if doi and options.structural_data_enabled:
            try:
                entry = self.download_ccdc_doi_to_cache(doi)
                rows.extend(self.cache_rows([entry]))
            except Exception as exc:
                rows.append(["CCDC", doi, "", "CCDC CIF not available", "", str(exc)])
        self._emit_search_progress(progress, "Checking local cache...", len(rows), 0, 1)

        ccdc_key = self.search_cache_key("text", query)
        if options.structural_data_enabled and not self.local_phase_cache.search_is_fresh("CCDC", ccdc_key):
            try:
                self._emit_search_progress(progress, "Searching CCDC/CSD...", len(rows), 0, 2)
                ccdc_entries = self.ccdc.search_text(
                    query=query,
                    target_dir=self.local_phase_cache.root / "ccdc_cif",
                    limit=self.CCDC_RESULT_LIMIT,
                )
                self.index_ccdc_entries(ccdc_entries)
                self.local_phase_cache.mark_search("CCDC", ccdc_key)
                rows = self.dedupe_candidate_rows(
                    rows
                    + self.cache_rows(
                        self.search_local_cache(
                            options,
                            text=formula_query or ("" if query_elements else query),
                            elements=query_elements or None,
                        )
                    )
                )
                self._emit_search_progress(progress, f"CCDC/CSD: found {len(ccdc_entries)} entries", len(rows), 0, 3)
            except Exception as exc:
                if not rows and self.ccdc.status().installed:
                    rows.append(["CCDC", "", "", "CSD search failed", "", str(exc)])

        if options.local_sources and options.structural_data_enabled:
            rows.extend(
                self.cache_rows(
                    self.search_local_cache(
                        options,
                        text=formula_query or ("" if query_elements else query),
                        elements=query_elements or None,
                    )
                )
            )
            self._emit_search_progress(progress, f"Local cache: found {len(rows)} candidates", len(rows), 0, 4)

        if options.rruff_enabled and options.reference_patterns_enabled:
            rows.extend(
                self.rruff_rows(
                    self.rruff.search(
                        text=formula_query or ("" if query_elements else query),
                        elements=query_elements or None,
                        excluded_elements=options.excluded_elements,
                        limit=self.STRUCTURAL_RESULT_LIMIT,
                    )
                )
            )
            self._emit_search_progress(progress, f"RRUFF: found {len(rows)} candidates total", len(rows), 0, 5)

        if options.match_pdf2_enabled and options.reference_patterns_enabled:
            rows.extend(
                self.match_pdf2_rows(
                    self.match_pdf2.search(
                        text="" if query_elements else query,
                        elements=query_elements or None,
                        excluded_elements=options.excluded_elements,
                        limit=self.STRUCTURAL_RESULT_LIMIT,
                    )
                )
            )
            self._emit_search_progress(progress, f"PDF-2: found {len(rows)} candidates total", len(rows), 0, 6)

        if options.cod_online_enabled and options.structural_data_enabled:
            cod_key = self.search_cache_key("text", query, options.excluded_elements)
            if not self.local_phase_cache.search_is_fresh("COD", cod_key):
                if rows:
                    self._queue_background_cod_text_refresh(
                        cod_key=cod_key,
                        query=query,
                        formula_query=formula_query,
                        query_elements=query_elements,
                        options=options,
                    )
                    self._emit_search_progress(
                        progress,
                        "Local cache is ready; COD online refresh is running in the background",
                        len(rows),
                        0,
                        8,
                    )
                else:
                    try:
                        self._emit_search_progress(progress, "Searching COD online...", len(rows), 0, 7)
                        cod_entries, cod_result_count = self._search_cod_text_entries(
                            query=query,
                            formula_query=formula_query,
                            query_elements=query_elements,
                            options=options,
                        )
                        self.local_phase_cache.upsert_cod_entries(cod_entries)
                        self._mark_search_if_complete("COD", cod_key, cod_result_count, self.ONLINE_RESULT_LIMIT)
                        queued = self.queue_background_cod_downloads(cod_entries)
                        rows = self.dedupe_candidate_rows(rows + self.cod_rows(cod_entries))
                        self._emit_search_progress(progress, f"COD: found {len(cod_entries)}, queued {queued} CIF downloads", len(rows), queued, 8)
                    except Exception:
                        pass

        if options.materials_project_enabled and options.structural_data_enabled:
            mp_key = self.search_cache_key("text", query)
            if not self.local_phase_cache.search_is_fresh("MP", mp_key):
                if rows:
                    self._queue_background_mp_text_refresh(mp_key, query)
                    self._emit_search_progress(
                        progress,
                        "Local cache is ready; Materials Project refresh is running in the background",
                        len(rows),
                        0,
                        9,
                    )
                else:
                    try:
                        self._emit_search_progress(progress, "Searching Materials Project...", len(rows), 0, 9)
                        mp_entries = self.materials_project.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                        self.local_phase_cache.upsert_materials_project_entries(mp_entries)
                        self._mark_search_if_complete("MP", mp_key, len(mp_entries), self.COMPUTATIONAL_RESULT_LIMIT)
                        queued = self.queue_background_mp_downloads(mp_entries)
                        rows = self.dedupe_candidate_rows(rows + self.mp_rows(mp_entries))
                        self._emit_search_progress(progress, f"Materials Project: found {len(mp_entries)}, queued {queued} CIF downloads", len(rows), queued, 9)
                    except Exception as exc:
                        if not rows:
                            rows.append(["MP", "", "", "Materials Project search failed", "", str(exc)])

        if options.aflow_enabled and options.structural_data_enabled:
            aflow_key = self.search_cache_key("text", query)
            if not self.local_phase_cache.search_is_fresh("AFLOW", aflow_key):
                if rows:
                    self._queue_background_computational_text_refresh("AFLOW", aflow_key, query)
                    self._emit_search_progress(progress, "Local cache is ready; AFLOW refresh is running in the background", len(rows), 0, 10)
                else:
                    try:
                        self._emit_search_progress(progress, "Searching AFLOW...", len(rows), 0, 10)
                        aflow_entries = self.aflow.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                        self.local_phase_cache.upsert_computational_entries(aflow_entries)
                        self._mark_search_if_complete("AFLOW", aflow_key, len(aflow_entries), self.COMPUTATIONAL_RESULT_LIMIT)
                        queued = self.queue_background_aflow_downloads(aflow_entries)
                        rows = self.dedupe_candidate_rows(rows + self.computational_rows(aflow_entries))
                        self._emit_search_progress(progress, f"AFLOW: found {len(aflow_entries)}, queued {queued} CIF downloads", len(rows), queued, 10)
                    except Exception as exc:
                        if not rows:
                            rows.append(["AFLOW", "", "", "AFLOW search failed", "", str(exc)])

        if options.oqmd_enabled and options.structural_data_enabled:
            oqmd_key = self.search_cache_key("text", query)
            if not self.local_phase_cache.search_is_fresh("OQMD", oqmd_key):
                if rows:
                    self._queue_background_computational_text_refresh("OQMD", oqmd_key, query)
                    self._emit_search_progress(progress, "Local cache is ready; OQMD refresh is running in the background", len(rows), 0, 11)
                else:
                    try:
                        self._emit_search_progress(progress, "Searching OQMD...", len(rows), 0, 11)
                        oqmd_entries = self.oqmd.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                        self.local_phase_cache.upsert_computational_entries(oqmd_entries)
                        self._mark_search_if_complete("OQMD", oqmd_key, len(oqmd_entries), self.COMPUTATIONAL_RESULT_LIMIT)
                        queued = self.queue_background_oqmd_downloads(oqmd_entries)
                        rows = self.dedupe_candidate_rows(rows + self.computational_rows(oqmd_entries))
                        self._emit_search_progress(progress, f"OQMD: found {len(oqmd_entries)}, queued {queued} CIF downloads", len(rows), queued, 11)
                    except Exception as exc:
                        if not rows:
                            rows.append(["OQMD", "", "", "OQMD search failed", "", str(exc)])

        rows = self.dedupe_candidate_rows(self.filter_candidate_rows_by_excluded_elements(rows, options))
        self._emit_search_progress(progress, f"Done: found {len(rows)} candidates", len(rows), 0, 12)
        return rows

    def search_elements(
        self,
        elements: list[str],
        options: CandidateSearchOptions,
        progress: SearchProgressCallback | None = None,
    ) -> list[list[str]]:
        rows = []
        self._emit_search_progress(progress, "Checking local cache...", 0, 0, 1)
        if options.local_sources and options.structural_data_enabled:
            rows.extend(self.cache_rows(self.search_local_cache(options, elements=elements)))
            self._emit_search_progress(progress, f"Local cache: found {len(rows)} candidates", len(rows), 0, 2)
        if options.rruff_enabled and options.reference_patterns_enabled:
            rows.extend(
                self.rruff_rows(
                    self.rruff.search(
                        elements=elements,
                        excluded_elements=options.excluded_elements,
                        limit=self.STRUCTURAL_RESULT_LIMIT,
                    )
                )
            )
            self._emit_search_progress(progress, f"RRUFF: found {len(rows)} candidates total", len(rows), 0, 3)
        if options.match_pdf2_enabled and options.reference_patterns_enabled:
            rows.extend(
                self.match_pdf2_rows(
                    self.match_pdf2.search(
                        elements=elements,
                        excluded_elements=options.excluded_elements,
                        limit=self.STRUCTURAL_RESULT_LIMIT,
                    )
                )
            )
            self._emit_search_progress(progress, f"PDF-2: found {len(rows)} candidates total", len(rows), 0, 4)
        if options.cod_online_enabled and options.structural_data_enabled:
            cod_key = self.search_cache_key("elements", elements, options.excluded_elements)
            if not self.local_phase_cache.search_is_fresh("COD", cod_key):
                if rows:
                    self._queue_background_cod_elements_refresh(cod_key, elements, options)
                    self._emit_search_progress(
                        progress,
                        "Local cache is ready; COD online refresh is running in the background",
                        len(rows),
                        0,
                        6,
                    )
                else:
                    try:
                        self._emit_search_progress(progress, "Searching COD online...", len(rows), 0, 5)
                        cod_entries = self.cod_online.search_elements(
                            elements,
                            excluded_elements=options.excluded_elements,
                            limit=self.ONLINE_RESULT_LIMIT,
                        )
                        cod_result_count = len(cod_entries)
                        cod_entries = self.filter_cod_entries(cod_entries, options)
                        self.local_phase_cache.upsert_cod_entries(cod_entries)
                        self._mark_search_if_complete("COD", cod_key, cod_result_count, self.ONLINE_RESULT_LIMIT)
                        queued = self.queue_background_cod_downloads(cod_entries)
                        rows = self.dedupe_candidate_rows(rows + self.cod_rows(cod_entries))
                        self._emit_search_progress(progress, f"COD: found {len(cod_entries)}, queued {queued} CIF downloads", len(rows), queued, 6)
                    except Exception as exc:
                        rows.append(["", "COD", "", "", f"COD search failed: {exc}", "", "", "", "", ""])
        if options.materials_project_enabled and options.structural_data_enabled:
            mp_key = self.search_cache_key("elements", elements)
            if not self.local_phase_cache.search_is_fresh("MP", mp_key):
                if rows:
                    self._queue_background_mp_elements_refresh(mp_key, elements)
                    self._emit_search_progress(
                        progress,
                        "Local cache is ready; Materials Project refresh is running in the background",
                        len(rows),
                        0,
                        8,
                    )
                else:
                    try:
                        self._emit_search_progress(progress, "Searching Materials Project...", len(rows), 0, 7)
                        mp_entries = self.materials_project.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                        self.local_phase_cache.upsert_materials_project_entries(mp_entries)
                        self._mark_search_if_complete("MP", mp_key, len(mp_entries), self.COMPUTATIONAL_RESULT_LIMIT)
                        queued = self.queue_background_mp_downloads(mp_entries)
                        rows = self.dedupe_candidate_rows(rows + self.mp_rows(mp_entries))
                        self._emit_search_progress(progress, f"Materials Project: found {len(mp_entries)}, queued {queued} CIF downloads", len(rows), queued, 8)
                    except Exception as exc:
                        rows.append(["MP", "", "", "Materials Project search failed", "", str(exc)])
        if options.aflow_enabled and options.structural_data_enabled:
            aflow_key = self.search_cache_key("elements", elements)
            if not self.local_phase_cache.search_is_fresh("AFLOW", aflow_key):
                if rows:
                    self._queue_background_computational_elements_refresh("AFLOW", aflow_key, elements)
                    self._emit_search_progress(progress, "Local cache is ready; AFLOW refresh is running in the background", len(rows), 0, 10)
                else:
                    try:
                        self._emit_search_progress(progress, "Searching AFLOW...", len(rows), 0, 9)
                        aflow_entries = self.aflow.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                        self.local_phase_cache.upsert_computational_entries(aflow_entries)
                        self._mark_search_if_complete("AFLOW", aflow_key, len(aflow_entries), self.COMPUTATIONAL_RESULT_LIMIT)
                        queued = self.queue_background_aflow_downloads(aflow_entries)
                        rows = self.dedupe_candidate_rows(rows + self.computational_rows(aflow_entries))
                        self._emit_search_progress(progress, f"AFLOW: found {len(aflow_entries)}, queued {queued} CIF downloads", len(rows), queued, 10)
                    except Exception as exc:
                        rows.append(["AFLOW", "", "", "AFLOW search failed", "", str(exc)])
        if options.oqmd_enabled and options.structural_data_enabled:
            oqmd_key = self.search_cache_key("elements", elements)
            if not self.local_phase_cache.search_is_fresh("OQMD", oqmd_key):
                if rows:
                    self._queue_background_computational_elements_refresh("OQMD", oqmd_key, elements)
                    self._emit_search_progress(progress, "Local cache is ready; OQMD refresh is running in the background", len(rows), 0, 11)
                else:
                    try:
                        self._emit_search_progress(progress, "Searching OQMD...", len(rows), 0, 11)
                        oqmd_entries = self.oqmd.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                        self.local_phase_cache.upsert_computational_entries(oqmd_entries)
                        self._mark_search_if_complete("OQMD", oqmd_key, len(oqmd_entries), self.COMPUTATIONAL_RESULT_LIMIT)
                        queued = self.queue_background_oqmd_downloads(oqmd_entries)
                        rows = self.dedupe_candidate_rows(rows + self.computational_rows(oqmd_entries))
                        self._emit_search_progress(progress, f"OQMD: found {len(oqmd_entries)}, queued {queued} CIF downloads", len(rows), queued, 11)
                    except Exception as exc:
                        rows.append(["OQMD", "", "", "OQMD search failed", "", str(exc)])
        rows = self.dedupe_candidate_rows(self.filter_candidate_rows_by_excluded_elements(rows, options))
        self._emit_search_progress(progress, f"Done: found {len(rows)} candidates", len(rows), 0, 12)
        return rows

    def search_local_cache(
        self,
        options: CandidateSearchOptions,
        text: str = "",
        elements: list[str] | None = None,
    ):
        if options.observed_peak_positions:
            peak_entries = self.local_phase_cache.search_by_peaks(
                options.observed_peak_positions,
                text=text,
                elements=elements,
                excluded_elements=options.excluded_elements,
                sources=options.local_sources,
                limit=self.STRUCTURAL_RESULT_LIMIT,
            )
            if peak_entries:
                return peak_entries
        return self.local_phase_cache.search(
            text=text,
            elements=elements,
            excluded_elements=options.excluded_elements,
            sources=options.local_sources,
            limit=self.STRUCTURAL_RESULT_LIMIT,
        )

    def _search_cod_text_entries(
        self,
        *,
        query: str,
        formula_query: str,
        query_elements: list[str],
        options: CandidateSearchOptions,
    ) -> tuple[list[CodEntry], int]:
        cod_result_count = 0
        if formula_query:
            cod_entries = self.cod_online.search_formula(formula_query, limit=self.ONLINE_RESULT_LIMIT)
            cod_result_count = len(cod_entries)
            if len(cod_entries) < 5 and query_elements:
                element_entries = self.cod_online.search_elements(
                    query_elements,
                    excluded_elements=options.excluded_elements,
                    limit=self.ONLINE_RESULT_LIMIT,
                )
                cod_result_count = max(cod_result_count, len(element_entries))
                cod_entries = self._dedupe_cod_entries(cod_entries + element_entries)
        elif query_elements:
            cod_entries = self.cod_online.search_elements(
                query_elements,
                excluded_elements=options.excluded_elements,
                limit=self.ONLINE_RESULT_LIMIT,
            )
            cod_result_count = len(cod_entries)
        else:
            cod_entries = self.cod_online.search_text(query=query, limit=self.ONLINE_RESULT_LIMIT)
            cod_result_count = len(cod_entries)
        return self.filter_cod_entries(cod_entries, options), cod_result_count

    def _queue_background_cod_text_refresh(
        self,
        *,
        cod_key: str,
        query: str,
        formula_query: str,
        query_elements: list[str],
        options: CandidateSearchOptions,
    ) -> None:
        self._queue_background_refresh(
            ("COD", cod_key),
            lambda: self._refresh_cod_text_cache(cod_key, query, formula_query, query_elements, options),
        )

    def _queue_background_cod_elements_refresh(
        self,
        cod_key: str,
        elements: list[str],
        options: CandidateSearchOptions,
    ) -> None:
        self._queue_background_refresh(
            ("COD", cod_key),
            lambda: self._refresh_cod_elements_cache(cod_key, elements, options),
        )

    def _queue_background_mp_text_refresh(self, mp_key: str, query: str) -> None:
        self._queue_background_refresh(
            ("MP", mp_key),
            lambda: self._refresh_mp_text_cache(mp_key, query),
        )

    def _queue_background_mp_elements_refresh(self, mp_key: str, elements: list[str]) -> None:
        self._queue_background_refresh(
            ("MP", mp_key),
            lambda: self._refresh_mp_elements_cache(mp_key, elements),
        )

    def _queue_background_computational_text_refresh(self, source: str, key: str, query: str) -> None:
        self._queue_background_refresh(
            (source, key),
            lambda: self._refresh_computational_text_cache(source, key, query),
        )

    def _queue_background_computational_elements_refresh(self, source: str, key: str, elements: list[str]) -> None:
        self._queue_background_refresh(
            (source, key),
            lambda: self._refresh_computational_elements_cache(source, key, elements),
        )

    def _queue_background_refresh(self, key: tuple[str, str], task: Callable[[], object]) -> None:
        with self._refresh_lock:
            if key in self._queued_refreshes:
                return
            self._queued_refreshes.add(key)
        thread = threading.Thread(
            target=self._run_background_refresh,
            args=(key, task),
            name=f"xrd-cache-refresh-{key[0]}",
            daemon=True,
        )
        thread.start()

    def _run_background_refresh(self, key: tuple[str, str], task: Callable[[], object]) -> None:
        try:
            task()
        except Exception:
            pass
        finally:
            with self._refresh_lock:
                self._queued_refreshes.discard(key)

    def _refresh_cod_text_cache(
        self,
        cod_key: str,
        query: str,
        formula_query: str,
        query_elements: list[str],
        options: CandidateSearchOptions,
    ) -> None:
        cod_entries, cod_result_count = self._search_cod_text_entries(
            query=query,
            formula_query=formula_query,
            query_elements=query_elements,
            options=options,
        )
        self.local_phase_cache.upsert_cod_entries(cod_entries)
        self._mark_search_if_complete("COD", cod_key, cod_result_count, self.ONLINE_RESULT_LIMIT)
        self.queue_background_cod_downloads(cod_entries)

    def _refresh_cod_elements_cache(
        self,
        cod_key: str,
        elements: list[str],
        options: CandidateSearchOptions,
    ) -> None:
        cod_entries = self.cod_online.search_elements(
            elements,
            excluded_elements=options.excluded_elements,
            limit=self.ONLINE_RESULT_LIMIT,
        )
        cod_result_count = len(cod_entries)
        cod_entries = self.filter_cod_entries(cod_entries, options)
        self.local_phase_cache.upsert_cod_entries(cod_entries)
        self._mark_search_if_complete("COD", cod_key, cod_result_count, self.ONLINE_RESULT_LIMIT)
        self.queue_background_cod_downloads(cod_entries)

    def _refresh_mp_text_cache(self, mp_key: str, query: str) -> None:
        mp_entries = self.materials_project.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
        self.local_phase_cache.upsert_materials_project_entries(mp_entries)
        self._mark_search_if_complete("MP", mp_key, len(mp_entries), self.COMPUTATIONAL_RESULT_LIMIT)
        self.queue_background_mp_downloads(mp_entries)

    def _refresh_mp_elements_cache(self, mp_key: str, elements: list[str]) -> None:
        mp_entries = self.materials_project.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
        self.local_phase_cache.upsert_materials_project_entries(mp_entries)
        self._mark_search_if_complete("MP", mp_key, len(mp_entries), self.COMPUTATIONAL_RESULT_LIMIT)
        self.queue_background_mp_downloads(mp_entries)

    def _refresh_computational_text_cache(self, source: str, key: str, query: str) -> None:
        service = self.aflow if source == "AFLOW" else self.oqmd
        entries = service.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
        self.local_phase_cache.upsert_computational_entries(entries)
        self._mark_search_if_complete(source, key, len(entries), self.COMPUTATIONAL_RESULT_LIMIT)
        if source == "AFLOW":
            self.queue_background_aflow_downloads(entries)
        else:
            self.queue_background_oqmd_downloads(entries)

    def _refresh_computational_elements_cache(self, source: str, key: str, elements: list[str]) -> None:
        service = self.aflow if source == "AFLOW" else self.oqmd
        entries = service.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
        self.local_phase_cache.upsert_computational_entries(entries)
        self._mark_search_if_complete(source, key, len(entries), self.COMPUTATIONAL_RESULT_LIMIT)
        if source == "AFLOW":
            self.queue_background_aflow_downloads(entries)
        else:
            self.queue_background_oqmd_downloads(entries)

    def download_cod_entries_to_cache(self, entries) -> int:
        errors = 0
        for entry in entries:
            try:
                self.local_phase_cache.download_cod_entry(entry, self.cod_online)
            except Exception:
                errors += 1
        return errors

    def download_mp_entries_to_cache(self, entries) -> int:
        errors = 0
        if not entries:
            return errors
        target_dir = self.local_phase_cache.root / "materials_project_cif"
        for entry in entries:
            try:
                cif_path = self.materials_project.download_cif(entry.material_id, target_dir)
                self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=entry.material_id)
            except Exception:
                errors += 1
        return errors

    def queue_background_cod_downloads(self, entries: list[CodEntry]) -> int:
        queued = 0
        for entry in entries[: self.BACKGROUND_DOWNLOAD_LIMIT]:
            if not entry.cod_id:
                continue
            queued += int(self._queue_background_download(
                ("COD", entry.cod_id),
                lambda entry=entry: self.local_phase_cache.download_cod_entry(entry, self.cod_online),
            ))
        return queued

    def queue_background_mp_downloads(self, entries) -> int:
        target_dir = self.local_phase_cache.root / "materials_project_cif"
        queued = 0
        for entry in entries[: self.BACKGROUND_DOWNLOAD_LIMIT]:
            if not entry.material_id:
                continue
            queued += int(self._queue_background_download(
                ("MP", entry.material_id),
                lambda entry=entry: self._download_mp_entry_to_cache(entry, target_dir),
            ))
        return queued

    def _download_mp_entry_to_cache(self, entry, target_dir) -> None:
        cif_path = self.materials_project.download_cif(entry.material_id, target_dir)
        self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=entry.material_id)

    def queue_background_aflow_downloads(self, entries) -> int:
        target_dir = self.local_phase_cache.root / "aflow_cif"
        queued = 0
        for entry in entries[: self.BACKGROUND_DOWNLOAD_LIMIT]:
            if not entry.entry_id:
                continue
            queued += int(self._queue_background_download(
                ("AFLOW", entry.entry_id),
                lambda entry=entry: self._download_aflow_entry_to_cache(entry, target_dir),
            ))
        return queued

    def _download_aflow_entry_to_cache(self, entry, target_dir) -> None:
        cif_path = self.aflow.download_cif(entry.entry_id, target_dir, url_hint=entry.url_hint)
        self.local_phase_cache.index_cif(cif_path, source="AFLOW", entry_id=entry.entry_id)

    def queue_background_oqmd_downloads(self, entries) -> int:
        target_dir = self.local_phase_cache.root / "oqmd_cif"
        queued = 0
        for entry in entries[: self.BACKGROUND_DOWNLOAD_LIMIT]:
            if not entry.entry_id:
                continue
            queued += int(self._queue_background_download(
                ("OQMD", entry.entry_id),
                lambda entry=entry: self._download_oqmd_entry_to_cache(entry, target_dir),
            ))
        return queued

    def _download_oqmd_entry_to_cache(self, entry, target_dir) -> None:
        cif_path = self.oqmd.download_cif(entry.entry_id, target_dir, url_hint=entry.url_hint, formula_hint=entry.formula)
        self.local_phase_cache.index_cif(cif_path, source="OQMD", entry_id=entry.entry_id)

    def _queue_background_download(
        self,
        key: tuple[str, str],
        task: Callable[[], object],
        priority: int = 100,
        allow_duplicate: bool = False,
        completion: threading.Event | None = None,
        result_box: dict | None = None,
    ) -> bool:
        if self.local_phase_cache.cif_path(key[0], key[1]) is not None:
            if completion is not None:
                result_box = result_box if result_box is not None else {}
                result_box["result"] = self.local_phase_cache.cif_path(key[0], key[1])
                completion.set()
            return False
        with self._download_lock:
            if key in self._queued_downloads and not allow_duplicate:
                return False
            self._queued_downloads.add(key)
        self._download_queue.put((priority, next(self._download_counter), key, task, completion, result_box))
        return True

    def download_with_priority(self, key: tuple[str, str], task: Callable[[], object]) -> object:
        cached_path = self.local_phase_cache.cif_path(key[0], key[1])
        if cached_path is not None:
            return cached_path
        with self._download_lock:
            self._queued_downloads.discard(key)
        return task()

    def cancel_background_downloads(self) -> int:
        cancelled = 0
        while True:
            try:
                _priority, _sequence, key, _task, completion, result_box = self._download_queue.get_nowait()
            except queue.Empty:
                break
            with self._download_lock:
                self._queued_downloads.discard(key)
            if completion is not None:
                if result_box is not None:
                    result_box["error"] = TimeoutError("Cancelled because a new database search started.")
                completion.set()
            self._download_queue.task_done()
            cancelled += 1
        return cancelled

    def _run_download_queue(self) -> None:
        while True:
            priority, sequence, key, task, completion, result_box = self._download_queue.get()
            try:
                if self._download_shutdown:
                    return
                cached_path = self.local_phase_cache.cif_path(key[0], key[1])
                if cached_path is not None:
                    result = cached_path
                else:
                    result = task()
                if result_box is not None:
                    result_box["result"] = result
            except Exception as exc:
                if result_box is not None:
                    result_box["error"] = exc
            finally:
                with self._download_lock:
                    self._queued_downloads.discard(key)
                if completion is not None:
                    completion.set()
                self._download_queue.task_done()

    def shutdown_background_downloads(self) -> None:
        self._download_shutdown = True
        self._download_queue.put((999999, next(self._download_counter), ("", ""), lambda: None, None, None))

    def download_ccdc_doi_to_cache(self, doi: str):
        target_dir = self.local_phase_cache.root / "ccdc_cif"
        cif_path = self.ccdc.download_cif_by_doi(doi, target_dir)
        entry_id = cif_path.stem
        self.local_phase_cache.index_cif(cif_path, source="CCDC", entry_id=entry_id)
        entry = self.local_phase_cache.get("CCDC", entry_id)
        if entry is None:
            raise ValueError("CCDC CIF was downloaded but could not be indexed.")
        return entry

    def index_ccdc_entries(self, entries) -> None:
        for entry in entries:
            cif_path = self.local_phase_cache.root / "ccdc_cif" / f"{self.ccdc._safe_id(entry.identifier)}.cif"
            if cif_path.exists():
                self.local_phase_cache.index_cif(cif_path, source="CCDC", entry_id=entry.identifier)

    def cache_rows(self, entries) -> list[list[str]]:
        return [
            [
                entry.source,
                entry.entry_id,
                self.display_formula(entry.formula),
                entry.name or self.display_formula(entry.formula),
                getattr(entry, "spacegroup", ""),
                "",
                self.display_iic(getattr(entry, "iic", None), getattr(entry, "derived_version", 0)),
            ]
            for entry in entries
        ]

    def rruff_rows(self, entries) -> list[list[str]]:
        return [
            [
                "RRUFF",
                self.display_rruff_id(entry.rruff_id),
                self.display_formula(entry.formula),
                entry.name or entry.rruff_id,
                "",
                "",
                "",
            ]
            for entry in entries
        ]

    def cod_rows(self, entries: list[CodEntry]) -> list[list[str]]:
        return [
            [
                "COD",
                entry.cod_id,
                self.display_formula(entry.formula),
                entry.name or entry.mineral or self.display_formula(entry.formula),
                getattr(entry, "spacegroup", "") or getattr(entry, "source", ""),
                "",
                "",
            ]
            for entry in entries
        ]

    def mp_rows(self, entries) -> list[list[str]]:
        return [
            [
                "MP",
                entry.material_id,
                self.display_formula(entry.formula),
                entry.name or self.display_formula(entry.formula),
                getattr(entry, "spacegroup", ""),
                "",
                self.display_iic(getattr(entry, "iic", None), getattr(entry, "derived_version", 0)),
            ]
            for entry in entries
        ]

    def computational_rows(self, entries) -> list[list[str]]:
        return [
            [
                entry.source,
                entry.entry_id,
                self.display_formula(entry.formula),
                entry.name or self.display_formula(entry.formula),
                getattr(entry, "spacegroup", ""),
                "",
                self.display_iic(getattr(entry, "iic", None), getattr(entry, "derived_version", 0)),
            ]
            for entry in entries
        ]

    def match_pdf2_rows(self, entries) -> list[list[str]]:
        return [
            [
                "PDF2",
                entry.entry_id,
                self.display_pdf2_formula(entry.formula),
                self.display_pdf2_phase(entry),
                "",
                "",
                "",
            ]
            for entry in entries
        ]

    def dedupe_candidate_rows(self, rows: list[list[str]]) -> list[list[str]]:
        unique = []
        seen = set()
        for row in rows:
            normalized = normalize_candidate_row(row)
            key = tuple(value.strip().lower() for value in normalized[:4])
            if key in seen:
                continue
            seen.add(key)
            unique.append(normalized)
        return unique

    def filter_candidate_rows_by_excluded_elements(
        self,
        rows: list[list[str]],
        options: CandidateSearchOptions,
    ) -> list[list[str]]:
        excluded = set(options.excluded_elements)
        filtered = []
        for row in rows:
            normalized = normalize_candidate_row(row)
            formula = normalized[2] if len(normalized) > 2 else ""
            if excluded and formula and formula_elements(formula) & excluded:
                continue
            if formula and not options.material_class_allowed(formula):
                continue
            filtered.append(row)
        return filtered

    def filter_cod_entries(self, entries: list[CodEntry], options: CandidateSearchOptions) -> list[CodEntry]:
        return [entry for entry in entries if options.material_class_allowed(entry.formula)]

    def display_formula(self, formula: str) -> str:
        parts = re.findall(r"[A-Z][a-z]?[0-9.]*", formula or "")
        return " ".join(parts) if parts else formula

    def display_iic(self, value, derived_version: int = DERIVED_CACHE_VERSION) -> str:
        if int(derived_version or 0) != DERIVED_CACHE_VERSION:
            return ""
        if value is None or value == "":
            return ""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return ""
        if number <= 0:
            return ""
        return f"{number:.3g}"

    def display_rruff_id(self, rruff_id: str) -> str:
        match = re.search(r"(?:^|[^A-Za-z0-9])(R[0-9]{5,7}(?:-[0-9]+)?)(?=$|[^A-Za-z0-9])", rruff_id or "")
        return match.group(1) if match else rruff_id

    def display_pdf2_formula(self, formula: str) -> str:
        return re.sub(r"\s+", " ", (formula or "").replace("!", "*")).strip()

    def display_pdf2_phase(self, entry) -> str:
        chemical_name = getattr(entry, "chemical_name", "") or ""
        phase_name = getattr(entry, "name", "") or ""
        if chemical_name and phase_name:
            return f"{chemical_name} ({phase_name})"
        return phase_name or chemical_name or getattr(entry, "entry_id", "")

    def element_query_tokens(self, query: str) -> list[str]:
        tokens = re.findall(r"[A-Z][a-z]?", query)
        if not tokens:
            return []
        residue = re.sub(r"[A-Z][a-z]?|[0-9.]+|\s|,|;|/|-|_", "", query)
        return tokens if not residue else []

    def formula_query_text(self, query: str) -> str:
        query = (query or "").strip()
        if not query or not re.search(r"\d", query):
            return ""
        tokens = re.findall(r"[A-Z][a-z]?[0-9.]*", query)
        if not tokens:
            return ""
        residue = re.sub(r"[A-Z][a-z]?[0-9.]*|\s|,|;|/|-|_", "", query)
        return "".join(tokens) if not residue else ""

    def _mark_search_if_complete(self, source: str, query_key: str, result_count: int, limit: int) -> None:
        if int(result_count) < int(limit):
            self.local_phase_cache.mark_search(source, query_key)

    def _emit_search_progress(
        self,
        progress: SearchProgressCallback | None,
        message: str,
        found_count: int,
        queued_count: int,
        step: int,
    ) -> None:
        if progress is None:
            return
        total_steps = 12
        current_step = max(0, min(int(step), total_steps))
        remaining_steps = max(0, total_steps - current_step)
        details = (
            f"{message}\n"
            f"Search progress: step {current_step}/{total_steps}; remaining {remaining_steps}\n"
            f"Found: {int(found_count)} candidates"
        )
        if queued_count:
            details += f"\nCIF downloads queued in background: {int(queued_count)}"
        progress(details, current_step, total_steps)

    def _dedupe_cod_entries(self, entries: list[CodEntry]) -> list[CodEntry]:
        unique = []
        seen = set()
        for entry in entries:
            key = entry.cod_id.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(entry)
        return unique

    def search_cache_key(self, mode: str, query, excluded: list[str] | None = None) -> str:
        if isinstance(query, (list, tuple, set)):
            query_text = " ".join(sorted(str(item).strip() for item in query if str(item).strip()))
        else:
            query_text = re.sub(r"\s+", " ", str(query or "").strip().lower())
        excluded_text = " ".join(sorted(str(item).strip() for item in excluded or [] if str(item).strip()))
        return f"{mode}|{query_text}|exclude:{excluded_text}"


def normalize_candidate_row(row: list[str]) -> list[str]:
    if len(row) >= 10:
        return [
            row[1],
            row[2],
            row[3],
            row[4],
            "",
            row[8],
            "",
            row[9],
        ]
    if len(row) >= 8:
        return row[:8]
    if len(row) == 7:
        return [row[0], row[1], row[2], row[3], row[4], row[5], "", row[6]]
    if len(row) == 6:
        return [row[0], row[1], row[2], row[3], "", row[4], "", row[5]]
    if len(row) >= 5:
        return ["", "", "", row[4], "", "", "", ""]
    padded = list(row) + [""] * 8
    return padded[:8]
