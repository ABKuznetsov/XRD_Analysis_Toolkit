from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


class CandidateSearchService:
    STRUCTURAL_RESULT_LIMIT = 500
    ONLINE_RESULT_LIMIT = 300
    COMPUTATIONAL_RESULT_LIMIT = 150

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
        self._download_counter = itertools.count()
        self._download_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._download_shutdown = False
        self._download_thread = threading.Thread(
            target=self._run_download_queue,
            name="xrd-cache-priority",
            daemon=True,
        )
        self._download_thread.start()

    def search_text(self, query: str, options: CandidateSearchOptions) -> list[list[str]]:
        query = query.strip()
        if not query:
            return []

        rows = []
        query_elements = self.element_query_tokens(query)
        doi = extract_doi(query)
        if doi and options.structural_data_enabled:
            try:
                entry = self.download_ccdc_doi_to_cache(doi)
                rows.extend(self.cache_rows([entry]))
            except Exception as exc:
                rows.append(["CCDC", doi, "", "CCDC CIF not available", "", str(exc)])

        ccdc_key = self.search_cache_key("text", query)
        if options.structural_data_enabled and not self.local_phase_cache.search_is_fresh("CCDC", ccdc_key):
            try:
                ccdc_entries = self.ccdc.search_text(
                    query=query,
                    target_dir=self.local_phase_cache.root / "ccdc_cif",
                    limit=self.COMPUTATIONAL_RESULT_LIMIT,
                )
                self.index_ccdc_entries(ccdc_entries)
                self.local_phase_cache.mark_search("CCDC", ccdc_key)
                rows = self.dedupe_candidate_rows(
                    rows
                    + self.cache_rows(
                        self.search_local_cache(
                            options,
                            text="" if query_elements else query,
                            elements=query_elements or None,
                        )
                    )
                )
            except Exception as exc:
                if not rows and self.ccdc.status().installed:
                    rows.append(["CCDC", "", "", "CSD search failed", "", str(exc)])

        if options.local_sources and options.structural_data_enabled:
            rows.extend(
                self.cache_rows(
                    self.search_local_cache(
                        options,
                        text="" if query_elements else query,
                        elements=query_elements or None,
                    )
                )
            )

        if options.rruff_enabled and options.reference_patterns_enabled:
            rows.extend(
                self.rruff_rows(
                    self.rruff.search(
                        text="" if query_elements else query,
                        elements=query_elements or None,
                        excluded_elements=options.excluded_elements,
                        limit=self.STRUCTURAL_RESULT_LIMIT,
                    )
                )
            )

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

        if options.cod_online_enabled and options.structural_data_enabled:
            cod_key = self.search_cache_key("text", query, options.excluded_elements)
            if not self.local_phase_cache.search_is_fresh("COD", cod_key):
                try:
                    if query_elements:
                        cod_entries = self.cod_online.search_elements(
                            query_elements,
                            excluded_elements=options.excluded_elements,
                            limit=self.ONLINE_RESULT_LIMIT,
                        )
                    else:
                        cod_entries = self.cod_online.search_text(query=query, limit=self.ONLINE_RESULT_LIMIT)
                    cod_entries = self.filter_cod_entries(cod_entries, options)
                    self.local_phase_cache.upsert_cod_entries(cod_entries)
                    self.local_phase_cache.mark_search("COD", cod_key)
                    self.queue_background_cod_downloads(cod_entries)
                    rows = self.dedupe_candidate_rows(
                        rows + self.cod_rows(cod_entries)
                    )
                except Exception:
                    pass

        if options.materials_project_enabled and options.structural_data_enabled:
            mp_key = self.search_cache_key("text", query)
            if not self.local_phase_cache.search_is_fresh("MP", mp_key):
                try:
                    mp_entries = self.materials_project.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                    self.local_phase_cache.upsert_materials_project_entries(mp_entries)
                    self.local_phase_cache.mark_search("MP", mp_key)
                    self.queue_background_mp_downloads(mp_entries)
                    rows = self.dedupe_candidate_rows(rows + self.mp_rows(mp_entries))
                except Exception as exc:
                    if not rows:
                        rows.append(["MP", "", "", "Materials Project search failed", "", str(exc)])

        if options.aflow_enabled and options.structural_data_enabled:
            aflow_key = self.search_cache_key("text", query)
            if not self.local_phase_cache.search_is_fresh("AFLOW", aflow_key):
                try:
                    aflow_entries = self.aflow.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                    self.local_phase_cache.upsert_computational_entries(aflow_entries)
                    self.local_phase_cache.mark_search("AFLOW", aflow_key)
                    self.queue_background_aflow_downloads(aflow_entries)
                    rows = self.dedupe_candidate_rows(rows + self.computational_rows(aflow_entries))
                except Exception as exc:
                    if not rows:
                        rows.append(["AFLOW", "", "", "AFLOW search failed", "", str(exc)])

        if options.oqmd_enabled and options.structural_data_enabled:
            oqmd_key = self.search_cache_key("text", query)
            if not self.local_phase_cache.search_is_fresh("OQMD", oqmd_key):
                try:
                    oqmd_entries = self.oqmd.search_text(query=query, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                    self.local_phase_cache.upsert_computational_entries(oqmd_entries)
                    self.local_phase_cache.mark_search("OQMD", oqmd_key)
                    self.queue_background_oqmd_downloads(oqmd_entries)
                    rows = self.dedupe_candidate_rows(rows + self.computational_rows(oqmd_entries))
                except Exception as exc:
                    if not rows:
                        rows.append(["OQMD", "", "", "OQMD search failed", "", str(exc)])

        return self.dedupe_candidate_rows(self.filter_candidate_rows_by_excluded_elements(rows, options))

    def search_elements(self, elements: list[str], options: CandidateSearchOptions) -> list[list[str]]:
        rows = []
        if options.local_sources and options.structural_data_enabled:
            rows.extend(self.cache_rows(self.search_local_cache(options, elements=elements)))
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
        if options.cod_online_enabled and options.structural_data_enabled:
            cod_key = self.search_cache_key("elements", elements, options.excluded_elements)
            if not self.local_phase_cache.search_is_fresh("COD", cod_key):
                try:
                    cod_entries = self.cod_online.search_elements(
                        elements,
                        excluded_elements=options.excluded_elements,
                        limit=self.ONLINE_RESULT_LIMIT,
                    )
                    cod_entries = self.filter_cod_entries(cod_entries, options)
                    self.local_phase_cache.upsert_cod_entries(cod_entries)
                    self.local_phase_cache.mark_search("COD", cod_key)
                    self.queue_background_cod_downloads(cod_entries)
                    rows = self.dedupe_candidate_rows(rows + self.cod_rows(cod_entries))
                except Exception as exc:
                    rows.append(["", "COD", "", "", f"COD search failed: {exc}", "", "", "", "", ""])
        if options.materials_project_enabled and options.structural_data_enabled:
            mp_key = self.search_cache_key("elements", elements)
            if not self.local_phase_cache.search_is_fresh("MP", mp_key):
                try:
                    mp_entries = self.materials_project.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                    self.local_phase_cache.upsert_materials_project_entries(mp_entries)
                    self.local_phase_cache.mark_search("MP", mp_key)
                    self.queue_background_mp_downloads(mp_entries)
                    rows = self.dedupe_candidate_rows(rows + self.mp_rows(mp_entries))
                except Exception as exc:
                    rows.append(["MP", "", "", "Materials Project search failed", "", str(exc)])
        if options.aflow_enabled and options.structural_data_enabled:
            aflow_key = self.search_cache_key("elements", elements)
            if not self.local_phase_cache.search_is_fresh("AFLOW", aflow_key):
                try:
                    aflow_entries = self.aflow.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                    self.local_phase_cache.upsert_computational_entries(aflow_entries)
                    self.local_phase_cache.mark_search("AFLOW", aflow_key)
                    self.queue_background_aflow_downloads(aflow_entries)
                    rows = self.dedupe_candidate_rows(rows + self.computational_rows(aflow_entries))
                except Exception as exc:
                    rows.append(["AFLOW", "", "", "AFLOW search failed", "", str(exc)])
        if options.oqmd_enabled and options.structural_data_enabled:
            oqmd_key = self.search_cache_key("elements", elements)
            if not self.local_phase_cache.search_is_fresh("OQMD", oqmd_key):
                try:
                    oqmd_entries = self.oqmd.search_elements(elements, limit=self.COMPUTATIONAL_RESULT_LIMIT)
                    self.local_phase_cache.upsert_computational_entries(oqmd_entries)
                    self.local_phase_cache.mark_search("OQMD", oqmd_key)
                    self.queue_background_oqmd_downloads(oqmd_entries)
                    rows = self.dedupe_candidate_rows(rows + self.computational_rows(oqmd_entries))
                except Exception as exc:
                    rows.append(["OQMD", "", "", "OQMD search failed", "", str(exc)])
        return self.dedupe_candidate_rows(self.filter_candidate_rows_by_excluded_elements(rows, options))

    def search_local_cache(
        self,
        options: CandidateSearchOptions,
        text: str = "",
        elements: list[str] | None = None,
    ):
        return self.local_phase_cache.search(
            text=text,
            elements=elements,
            excluded_elements=options.excluded_elements,
            sources=options.local_sources,
            limit=self.STRUCTURAL_RESULT_LIMIT,
        )

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

    def queue_background_cod_downloads(self, entries: list[CodEntry]) -> None:
        for entry in entries:
            if not entry.cod_id:
                continue
            self._queue_background_download(
                ("COD", entry.cod_id),
                lambda entry=entry: self.local_phase_cache.download_cod_entry(entry, self.cod_online),
            )

    def queue_background_mp_downloads(self, entries) -> None:
        target_dir = self.local_phase_cache.root / "materials_project_cif"
        for entry in entries:
            if not entry.material_id:
                continue
            self._queue_background_download(
                ("MP", entry.material_id),
                lambda entry=entry: self._download_mp_entry_to_cache(entry, target_dir),
            )

    def _download_mp_entry_to_cache(self, entry, target_dir) -> None:
        cif_path = self.materials_project.download_cif(entry.material_id, target_dir)
        self.local_phase_cache.index_cif(cif_path, source="MP", entry_id=entry.material_id)

    def queue_background_aflow_downloads(self, entries) -> None:
        target_dir = self.local_phase_cache.root / "aflow_cif"
        for entry in entries:
            if not entry.entry_id:
                continue
            self._queue_background_download(
                ("AFLOW", entry.entry_id),
                lambda entry=entry: self._download_aflow_entry_to_cache(entry, target_dir),
            )

    def _download_aflow_entry_to_cache(self, entry, target_dir) -> None:
        cif_path = self.aflow.download_cif(entry.entry_id, target_dir, url_hint=entry.url_hint)
        self.local_phase_cache.index_cif(cif_path, source="AFLOW", entry_id=entry.entry_id)

    def queue_background_oqmd_downloads(self, entries) -> None:
        target_dir = self.local_phase_cache.root / "oqmd_cif"
        for entry in entries:
            if not entry.entry_id:
                continue
            self._queue_background_download(
                ("OQMD", entry.entry_id),
                lambda entry=entry: self._download_oqmd_entry_to_cache(entry, target_dir),
            )

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
    ) -> None:
        if self.local_phase_cache.cif_path(key[0], key[1]) is not None:
            if completion is not None:
                result_box = result_box if result_box is not None else {}
                result_box["result"] = self.local_phase_cache.cif_path(key[0], key[1])
                completion.set()
            return
        with self._download_lock:
            if key in self._queued_downloads and not allow_duplicate:
                return
            self._queued_downloads.add(key)
        self._download_queue.put((priority, next(self._download_counter), key, task, completion, result_box))

    def download_with_priority(self, key: tuple[str, str], task: Callable[[], object]) -> object:
        completion = threading.Event()
        result_box: dict = {}
        self._queue_background_download(
            key,
            task,
            priority=0,
            allow_duplicate=True,
            completion=completion,
            result_box=result_box,
        )
        completion.wait()
        if "error" in result_box:
            raise result_box["error"]
        return result_box.get("result")

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
            row[9],
        ]
    if len(row) >= 7:
        return row[:7]
    if len(row) == 6:
        return [row[0], row[1], row[2], row[3], "", row[4], row[5]]
    if len(row) >= 5:
        return ["", "", "", row[4], "", "", ""]
    padded = list(row) + [""] * 7
    return padded[:7]


