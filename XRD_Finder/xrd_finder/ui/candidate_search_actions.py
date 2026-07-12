from __future__ import annotations

from xrd_finder.services.candidate_search_service import CandidateSearchOptions
from xrd_finder.services.cod_online_service import formula_elements


class PhaseFinderCandidateSearchActionsMixin:
    def _prepare_candidate_database_search(self) -> None:
        if hasattr(self, "_clear_transient_candidate_preview"):
            self._clear_transient_candidate_preview()
        if hasattr(self, "_clear_probability_caches"):
            self._clear_probability_caches()
        if hasattr(self, "candidate_search_service"):
            self.candidate_search_service.cancel_background_downloads()

    def _search_pdf2_text(self) -> None:
        query = self.search_input.text().strip() if self.search_input is not None else ""
        if not query and self.name_input is not None:
            query = self.name_input.text().strip()
        if not query and self.formula_sum_input is not None:
            query = self.formula_sum_input.text().strip()
        if not query:
            self._set_candidate_rows([["", "", "", "Enter a phase name, formula, DOI, or entry ID", "", ""]])
            return
        options = self._candidate_search_options()
        self._prepare_candidate_database_search()

        def success(result) -> None:
            rows = result or []
            if rows:
                self._set_candidate_rows(rows)
            else:
                self._set_candidate_rows([["", "", "", f"No entries found in the selected phase databases for: {query}", "", ""]])

        self._run_background_task(
            "Find candidates",
            f"Searching phase databases for {query}...",
            lambda progress: self.candidate_search_service.search_text(query, options, progress=progress),
            success,
            with_progress=True,
        )

    def _search_from_controls(self) -> None:
        ccdc_query = self.ccdc_doi_input.text().strip() if self.ccdc_doi_input is not None else ""
        if ccdc_query:
            if self.search_input is not None:
                self.search_input.setText(ccdc_query)
            self._search_pdf2_text()
            return
        if not self.selected_elements:
            self._search_pdf2_text()
            return
        elements = list(self.selected_element_order)
        options = self._candidate_search_options()
        search_label = self.formula_sum_input.text().strip() if self.formula_sum_input is not None else " ".join(elements)
        self._prepare_candidate_database_search()

        def success(result) -> None:
            rows = result or []
            if self.search_input is not None and self.formula_sum_input is not None:
                self.search_input.setText(self.formula_sum_input.text().strip())
            if not rows:
                self._set_candidate_rows([["", "", "", "No entries found for the selected elements", "", ""]])
                return
            self._set_candidate_rows(rows)

        self._run_background_task(
            "Find candidates",
            f"Searching phase databases for {search_label}...",
            lambda progress: self.candidate_search_service.search_elements(elements, options, progress=progress),
            success,
            with_progress=True,
        )

    def _candidate_search_options(self) -> CandidateSearchOptions:
        return CandidateSearchOptions(
            local_sources=self._local_cache_sources(),
            excluded_elements=self._excluded_elements(),
            cod_online_enabled=self._cod_online_enabled(),
            rruff_enabled=self._rruff_enabled(),
            match_pdf2_enabled=self._match_pdf2_enabled(),
            materials_project_enabled=self._materials_project_enabled(),
            aflow_enabled=self._aflow_enabled(),
            oqmd_enabled=self._oqmd_enabled(),
            structural_data_enabled=self._structural_data_enabled(),
            reference_patterns_enabled=self._reference_patterns_enabled(),
            material_class_allowed=self._material_class_allowed,
        )

    def _materials_project_enabled(self) -> bool:
        return (
            self._structural_data_enabled()
            and bool(self.settings.value("materials_project/enabled", False, type=bool))
            and bool(getattr(self.materials_project, "api_key", ""))
        )

    def _local_cache_sources(self) -> list[str]:
        sources = []
        if self._source_enabled("sources/user_library", True):
            sources.extend(["USER", "CCDC", "COD"])
        if self._source_enabled("sources/cod_local", True):
            sources.append("COD")
        if self._materials_project_enabled():
            sources.append("MP")
        if self._aflow_enabled():
            sources.append("AFLOW")
        if self._oqmd_enabled():
            sources.append("OQMD")
        return list(dict.fromkeys(sources))

    def _aflow_enabled(self) -> bool:
        return self._structural_data_enabled() and self._source_enabled("sources/aflow", False)

    def _oqmd_enabled(self) -> bool:
        return self._structural_data_enabled() and self._source_enabled("sources/oqmd", False)

    def _cod_online_enabled(self) -> bool:
        return self._structural_data_enabled() and self._source_enabled("sources/cod_online", True)

    def _rruff_enabled(self) -> bool:
        return self._reference_patterns_enabled() and self._source_enabled("sources/rruff", False)

    def _match_pdf2_enabled(self) -> bool:
        return self._source_enabled("sources/match_pdf2", self.match_pdf2.is_configured()) and self.match_pdf2.is_configured()

    def _structural_data_enabled(self) -> bool:
        return self.structural_data_checkbox is None or self.structural_data_checkbox.isChecked()

    def _reference_patterns_enabled(self) -> bool:
        return self.reference_patterns_checkbox is None or self.reference_patterns_checkbox.isChecked()

    def _source_enabled(self, setting_key: str, default: bool) -> bool:
        return bool(self.settings.value(setting_key, default, type=bool))

    def _material_class_allowed(self, formula: str) -> bool:
        if self.inorganics_checkbox is None or self.organics_checkbox is None:
            return True
        allow_inorganic = self.inorganics_checkbox.isChecked()
        allow_organic = self.organics_checkbox.isChecked()
        if allow_inorganic and allow_organic:
            return True
        if not allow_inorganic and not allow_organic:
            return False
        elements = formula_elements(formula)
        is_organic = {"C", "H"}.issubset(elements)
        return (is_organic and allow_organic) or ((not is_organic) and allow_inorganic)
