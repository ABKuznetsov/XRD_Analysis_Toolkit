from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from xrd_finder.services.auto_search_ranker import (
    AutoSearchRankingResult,
    create_local_reference_peak_loader,
    rank_candidate_rows,
)
from xrd_finder.services.candidate_search_service import (
    CandidateSearchOptions,
    normalize_candidate_row,
)
from xrd_finder.services.cod_online_service import formula_elements
from xrd_finder.services.network import offline_mode_enabled
from xrd_finder.ui.candidate_batch_updates import CandidateBatchUpdateController


class PhaseFinderCandidateSearchActionsMixin:
    LARGE_MANUAL_SEARCH_LIMIT = 100

    @staticmethod
    def _manual_candidate_count(rows: list[list[str]]) -> int:
        return len({
            (str(row[0]).strip().upper(), str(row[1]).strip())
            for row in rows
            if len(row) > 1 and str(row[0]).strip() and str(row[1]).strip()
        })

    @staticmethod
    def _format_estimated_duration(seconds: float) -> str:
        seconds = max(1.0, float(seconds))
        if seconds < 60.0:
            return f"{int(round(seconds))} seconds"
        minutes = seconds / 60.0
        return f"{minutes:.1f} minutes" if minutes < 10.0 else f"{int(round(minutes))} minutes"

    def _candidate_processing_time_range(self, count: int) -> tuple[str, str]:
        measured = float(getattr(self, "_candidate_processing_seconds_per_item", 0.0) or 0.0)
        if measured > 0.0:
            low_rate = max(0.03, measured * 0.75)
            high_rate = max(low_rate, measured * 1.75)
        else:
            low_rate, high_rate = 0.25, 1.5
        return (
            self._format_estimated_duration(count * low_rate),
            self._format_estimated_duration(count * high_rate),
        )

    def _confirm_large_candidate_search(self, count: int) -> bool:
        low, high = self._candidate_processing_time_range(count)
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Broad database search")
        dialog.setText(f"The search found {count} candidate cards.")
        dialog.setInformativeText(
            f"Estimated initial processing time: {low}–{high}. "
            "Online CIF downloads may take longer. You can continue or refine the element filter first."
        )
        process_button = dialog.addButton(
            "Process candidates", QMessageBox.ButtonRole.AcceptRole
        )
        refine_button = dialog.addButton(
            "Refine element filter", QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(refine_button)
        dialog.exec()
        return dialog.clickedButton() is process_button

    def _finish_manual_candidate_rows(
        self,
        rows: list[list[str]],
        search_token: int,
    ) -> bool:
        count = PhaseFinderCandidateSearchActionsMixin._manual_candidate_count(rows)
        if (
            count > PhaseFinderCandidateSearchActionsMixin.LARGE_MANUAL_SEARCH_LIMIT
            and not self._confirm_large_candidate_search(count)
        ):
            preparation_queue = getattr(self.candidate_search_service, "preparation_queue", None)
            if preparation_queue is not None:
                preparation_queue.cancel_session(search_token)
            controller = getattr(self, "_candidate_batch_updates", None)
            if controller is not None:
                controller.stop()
            detail = getattr(self, "candidate_search_detail_label", None)
            if detail is not None:
                detail.setText(
                    f"Found {count} candidates. Refine required or absent elements, then press Find."
                )
            return False

        self.candidate_search_service.queue_candidate_rows(
            rows,
            session_token=search_token,
        )
        started = time.perf_counter()
        self._set_candidate_rows(rows)
        elapsed = time.perf_counter() - started
        if count > 0 and elapsed > 0.0:
            measured = elapsed / count
            previous = float(getattr(self, "_candidate_processing_seconds_per_item", 0.0) or 0.0)
            self._candidate_processing_seconds_per_item = (
                measured if previous <= 0.0 else previous * 0.7 + measured * 0.3
            )
        return True

    def _rerank_loaded_candidates_for_instrument_change(self) -> None:
        table = getattr(self, "candidate_table", None)
        if table is None:
            return
        candidates = [
            candidate
            for candidate in table.all_row_values()
            if candidate.get("Source", "").strip()
            and candidate.get("Entry", "").strip()
        ]
        if not candidates:
            return
        if getattr(self, "match_candidates", None):
            self._schedule_candidate_gain_ranking()
            return

        rows = self._candidate_state_rows(candidates)
        label = getattr(self, "candidate_list_label", None)

        def progress(value: int, maximum: int) -> None:
            if label is not None:
                label.setText(f"Candidate list: Match {value}/{maximum}")
            QApplication.processEvents()

        try:
            self._set_candidate_rows(
                rows,
                force_rank=True,
                rank_progress=progress,
            )
        finally:
            if label is not None:
                label.setText("Candidate list")

    def _initialize_candidate_batch_updates(self) -> None:
        self._candidate_batch_updates = CandidateBatchUpdateController(
            row_loader=self._load_prepared_candidate_row,
            rows_ready=self._merge_prepared_candidate_rows,
            status_callback=self.background_status_changed.emit,
            title_callback=self.candidate_list_label.setText,
            detail_callback=self.candidate_search_detail_label.setText,
            parent=self,
        )
        self.candidate_prepared.connect(self._candidate_batch_updates.accept_notice)
        self.candidate_preparation_progress.connect(
            self._handle_candidate_preparation_progress
        )
        self.cod_server_alert.connect(self._set_candidate_search_notice)

    @staticmethod
    def _preparation_progress_is_busy(progress) -> bool:
        return any(
            int(getattr(progress, name, 0) or 0) > 0
            for name in ("queued", "downloading", "indexing")
        )

    def _candidate_preparation_is_busy(self) -> bool:
        service = getattr(self, "candidate_search_service", None)
        preparation_queue = getattr(service, "preparation_queue", None)
        if preparation_queue is None:
            return False
        try:
            return self._preparation_progress_is_busy(preparation_queue.progress())
        except Exception:
            return False

    def _handle_candidate_preparation_progress(self, progress) -> None:
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is not None:
            controller.accept_progress(progress)
        if (
            getattr(self, "match_candidates", None)
            and getattr(self, "_candidate_gain_refresh_after_preparation", False)
            and not self._preparation_progress_is_busy(progress)
        ):
            self._defer_candidate_gain_after_preparation()

    def _defer_candidate_gain_after_preparation(self) -> None:
        if getattr(self, "_candidate_gain_idle_check_pending", False):
            return
        self._candidate_gain_idle_check_pending = True
        QTimer.singleShot(350, self._finish_candidate_gain_after_preparation)

    def _finish_candidate_gain_after_preparation(self) -> None:
        self._candidate_gain_idle_check_pending = False
        if (
            getattr(self, "match_candidates", None)
            and getattr(self, "_candidate_gain_refresh_after_preparation", False)
            and not self._candidate_preparation_is_busy()
        ):
            self._candidate_gain_refresh_after_preparation = False
            self._schedule_candidate_gain_ranking()

    def _set_candidate_search_notice(self, message: str) -> None:
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is None:
            return
        text = str(message or "")
        if "Primary online database endpoint is unavailable" in text or "Trying COD mirror" in text:
            controller.set_notice("Online database endpoint unavailable; trying mirror")
            return
        if "COD" in text:
            controller.set_notice("Online database unavailable; local data shown")

    def _load_prepared_candidate_row(self, source: str, entry_id: str) -> list[str] | None:
        entry = self.local_phase_cache.get(source, entry_id)
        if entry is None:
            return None
        rows = self.candidate_search_service.cache_rows([entry])
        return rows[0] if rows else None

    def _merge_prepared_candidate_rows(self, prepared_rows: list[list[str]]) -> None:
        rows = self.candidate_search_service.dedupe_candidate_rows(prepared_rows)
        if not rows:
            return
        if self.match_candidates:
            self.candidate_table.upsert_rows(rows, normalize_candidate_row)
            self._apply_candidate_element_filter()
            self._candidate_gain_refresh_after_preparation = True
            if not self._candidate_preparation_is_busy():
                self._candidate_gain_refresh_after_preparation = False
                self._schedule_candidate_gain_ranking()
            return

        if self._rank_by_peak_probability_enabled():
            probability_data = self._probability_observed_data()
            records = probability_data[2] if probability_data is not None else []
            if records:
                for row in rows:
                    probability = self._candidate_row_peak_probability_from_records(
                        row,
                        records,
                        allow_cif_fallback=False,
                    )
                    if probability > 0.0:
                        row[5] = f"{probability:.0f}%"
        self.candidate_table.upsert_rows(rows, normalize_candidate_row)
        self._apply_candidate_element_filter()

    def _stop_candidate_batch_updates(self) -> None:
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is not None:
            controller.stop()

    def _record_initial_candidate_rows(self, rows: list[list[str]]) -> None:
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is None:
            return
        count = sum(
            1
            for row in rows
            if len(row) > 1 and str(row[0]).strip() and str(row[1]).strip()
        )
        controller.set_local_rows(count)

    def _finalize_candidate_search(self, search_token: int) -> None:
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is not None:
            controller.mark_search_complete(search_token)

    def _auto_search_candidates(self) -> None:
        if self._active_pattern() is None:
            QMessageBox.information(self, "Auto search", "Import or select an XRD pattern first.")
            return
        probability_data = self._probability_observed_data() if hasattr(self, "_probability_observed_data") else None
        if probability_data is None:
            QMessageBox.information(self, "Auto search", "No usable peaks were detected in the active pattern.")
            return
        _observed_x, _corrected, observed_records = probability_data
        peak_positions = [self._observed_record_position(record) for record in observed_records[:80]]
        if not peak_positions:
            QMessageBox.information(self, "Auto search", "No usable peaks were detected in the active pattern.")
            return

        # Keep the auto-search pool independent of the element gate. The same
        # ranked local candidates can then be filtered before or after search.
        elements: list[str] = []
        options = self._candidate_search_options()
        options.observed_peak_positions = peak_positions
        options.required_elements = []
        options.optional_elements = []
        options.excluded_elements = []
        options.cod_online_enabled = False
        options.materials_project_enabled = False
        options.aflow_enabled = False
        options.oqmd_enabled = False

        search_token = self._prepare_candidate_database_search()
        auto_search_token = int(getattr(self, "_auto_search_token", 0)) + 1
        self._auto_search_token = auto_search_token
        self._set_auto_search_busy(True)
        label = "observed peak positions in local databases"

        def partial(result) -> None:
            if (
                search_token != getattr(self, "_candidate_search_request_token", 0)
                or auto_search_token != getattr(self, "_auto_search_token", 0)
            ):
                return
            rows = result or []
            if rows:
                self._record_initial_candidate_rows(rows)
                self._set_candidate_rows(rows, skip_rank=True)

        def success(result) -> None:
            if (
                search_token != getattr(self, "_candidate_search_request_token", 0)
                or auto_search_token != getattr(self, "_auto_search_token", 0)
            ):
                return
            self._finalize_candidate_search(search_token)
            rows = result or []
            self._record_initial_candidate_rows(rows)
            if not rows:
                self._set_auto_search_busy(False)
                self._set_candidate_rows([["", "", "", "No candidates found by automatic peak search", "", ""]])
                return
            if self.match_candidates:
                # Gain uses the accepted-phase profile state and remains on its
                # dedicated ranking path. The worker below is the broad initial
                # Match pass used before any phase has been accepted.
                self._set_candidate_rows(rows, skip_rank=True)
                self._set_auto_search_busy(False)
                self._schedule_candidate_gain_ranking()
                return
            # The SQL peak index has already searched the complete local
            # database and returned a bounded shortlist. Rank that entire
            # shortlist; truncating it here made candidates below row 1000
            # invisible to the final Match ordering.
            ranking_total = len(rows)
            cache_root = str(self.local_phase_cache.root)
            pdf2_root = str(getattr(self.match_pdf2, "root", "") or "")
            wavelength = float(self._active_wavelength())
            ranking_rows = [list(row) for row in rows]
            ranking_records = list(observed_records)

            def rank_task(progress):
                peak_loader = create_local_reference_peak_loader(
                    cache_root,
                    pdf2_root or None,
                    wavelength,
                )
                return rank_candidate_rows(
                    ranking_rows,
                    ranking_records,
                    wavelength=wavelength,
                    reference_peak_loader=peak_loader,
                    rank_limit=ranking_total,
                    progress=progress,
                )

            def ranking_success(ranking_result: AutoSearchRankingResult) -> None:
                if (
                    search_token != getattr(self, "_candidate_search_request_token", 0)
                    or auto_search_token != getattr(self, "_auto_search_token", 0)
                ):
                    return
                ranked_rows = ranking_result.rows
                self._set_candidate_rows(ranked_rows, skip_rank=True)
                if not self.match_candidates:
                    self._auto_search_ranked_rows = [list(row) for row in ranked_rows]
                    self._auto_search_scored_keys = set(ranking_result.scored_keys)
                if getattr(self, "scoring_status_label", None) is not None:
                    self.scoring_status_label.setText(
                        f"{self._scoring_source_status_text()} | "
                        f"FP: match {ranking_result.matched_count}/{ranking_total}, gain 0/{ranking_total}"
                    )
                self._apply_candidate_element_filter()
                for row_index in range(self.candidate_table.rowCount()):
                    if not self.candidate_table.isRowHidden(row_index):
                        self.candidate_table.selectRow(row_index)
                        self.candidate_table.scrollToTop()
                        break
                self._set_auto_search_busy(False)

            def ranking_failure(message: str, details: str) -> None:
                if (
                    search_token != getattr(self, "_candidate_search_request_token", 0)
                    or auto_search_token != getattr(self, "_auto_search_token", 0)
                ):
                    return
                self._set_candidate_rows(rows, skip_rank=True)
                self._auto_search_ranked_rows = [list(row) for row in rows]
                self._auto_search_scored_keys = set()
                self._set_auto_search_busy(False)
                QMessageBox.warning(self, "Auto search ranking failed", message or details)

            self._run_background_task(
                "Auto search",
                "Ranking local candidates...",
                rank_task,
                ranking_success,
                ranking_failure,
                with_progress=True,
                operation_name="match.rank.auto",
                show_progress_dialog=False,
            )

        def failure(message: str, details: str) -> None:
            if (
                search_token != getattr(self, "_candidate_search_request_token", 0)
                or auto_search_token != getattr(self, "_auto_search_token", 0)
            ):
                return
            self._finalize_candidate_search(search_token)
            self._set_auto_search_busy(False)
            QMessageBox.warning(self, "Auto search failed", message or details)

        self._run_background_task(
            "Auto search",
            f"Searching candidates from {label}...",
            lambda progress, partial_results: self.candidate_search_service.search_elements(
                elements,
                options,
                progress=progress,
                partial_results=partial_results,
                session_token=search_token,
            ),
            success,
            failure,
            with_progress=True,
            operation_name="match.search.auto",
            on_partial=partial,
            show_progress_dialog=False,
        )

    def _prepare_candidate_database_search(self) -> int:
        self._auto_search_ranked_rows = None
        self._auto_search_scored_keys = set()
        search_token = int(getattr(self, "_candidate_search_request_token", 0)) + 1
        self._candidate_search_request_token = search_token
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is not None:
            controller.start_session(search_token)
        if hasattr(self, "_clear_transient_candidate_preview"):
            self._clear_transient_candidate_preview()
        if hasattr(self, "_clear_probability_caches"):
            self._clear_probability_caches()
        return search_token

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
        search_token = self._prepare_candidate_database_search()

        def partial(result) -> None:
            if search_token != getattr(self, "_candidate_search_request_token", 0):
                return
            rows = result or []
            if rows:
                self._record_initial_candidate_rows(rows)
                self._set_candidate_rows(rows, skip_rank=True)

        def success(result) -> None:
            if search_token != getattr(self, "_candidate_search_request_token", 0):
                return
            self._finalize_candidate_search(search_token)
            rows = result or []
            self._record_initial_candidate_rows(rows)
            if rows:
                self._set_candidate_rows(rows)
            else:
                self._set_candidate_rows([["", "", "", f"No entries found in the selected phase databases for: {query}", "", ""]])

        def failure(message: str, details: str) -> None:
            if search_token != getattr(self, "_candidate_search_request_token", 0):
                return
            self._finalize_candidate_search(search_token)
            QMessageBox.warning(self, "Find candidates", message or details)

        self._run_background_task(
            "Find candidates",
            f"Searching phase databases for {query}...",
            lambda progress, partial_results: self.candidate_search_service.search_text(
                query,
                options,
                progress=progress,
                partial_results=partial_results,
                session_token=search_token,
            ),
            success,
            failure,
            with_progress=True,
            operation_name="match.search.text",
            on_partial=partial,
            show_progress_dialog=True,
        )

    def _search_from_controls(self) -> None:
        ccdc_query = self.ccdc_doi_input.text().strip() if self.ccdc_doi_input is not None else ""
        if ccdc_query:
            if self.search_input is not None:
                self.search_input.setText(ccdc_query)
            self._search_pdf2_text()
            return
        if not self.selected_elements:
            query = self.search_input.text().strip() if self.search_input is not None else ""
            if query:
                self._search_pdf2_text()
                return
            QMessageBox.information(
                self,
                "Find candidates",
                "Select at least one required element before searching databases.",
            )
            return
        elements = list(self.selected_element_order)
        options = self._candidate_search_options()
        options.defer_candidate_preparation = True
        search_label = self.formula_sum_input.text().strip() if self.formula_sum_input is not None else " ".join(elements)
        search_token = self._prepare_candidate_database_search()

        def partial(result) -> None:
            if search_token != getattr(self, "_candidate_search_request_token", 0):
                return
            return

        def success(result) -> None:
            if search_token != getattr(self, "_candidate_search_request_token", 0):
                return
            self._finalize_candidate_search(search_token)
            rows = result or []
            self._record_initial_candidate_rows(rows)
            if self.search_input is not None and self.formula_sum_input is not None:
                self.search_input.setText(self.formula_sum_input.text().strip())
            if not rows:
                self._set_candidate_rows([["", "", "", "No entries found for the selected elements", "", ""]])
                return
            self._finish_manual_candidate_rows(rows, search_token)

        def failure(message: str, details: str) -> None:
            if search_token != getattr(self, "_candidate_search_request_token", 0):
                return
            self._finalize_candidate_search(search_token)
            QMessageBox.warning(self, "Find candidates", message or details)

        self._run_background_task(
            "Find candidates",
            f"Searching phase databases for {search_label}...",
            lambda progress, partial_results: self.candidate_search_service.search_elements(
                elements,
                options,
                progress=progress,
                partial_results=partial_results,
                session_token=search_token,
            ),
            success,
            failure,
            with_progress=True,
            operation_name="match.search.elements",
            on_partial=partial,
            show_progress_dialog=True,
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
            optional_elements=self._optional_elements(),
            required_elements=list(self.selected_element_order),
            observed_peak_positions=self._candidate_search_peak_positions(),
            restrict_to_selected_elements=False,
        )

    def _candidate_search_peak_positions(self) -> list[float]:
        if not hasattr(self, "_rank_by_peak_probability_enabled") or not self._rank_by_peak_probability_enabled():
            return []
        if not hasattr(self, "_probability_observed_data"):
            return []
        probability_data = self._probability_observed_data()
        if probability_data is None:
            return []
        _observed_x, _corrected, observed_records = probability_data
        return [self._observed_record_position(record) for record in observed_records[:80]]

    def _observed_record_position(self, record) -> float:
        value = getattr(record, "two_theta", None)
        if value is not None:
            return float(value)
        return float(record[0])

    def _materials_project_enabled(self) -> bool:
        return (
            self._structural_data_enabled()
            and not offline_mode_enabled()
            and bool(self.settings.value("materials_project/enabled", False, type=bool))
            and bool(getattr(self.materials_project, "api_key", ""))
        )

    def _local_cache_sources(self) -> list[str]:
        sources = []
        if self._source_enabled("sources/user_library", True):
            sources.extend(["USER", "CCDC", "COD"])
        if self._source_enabled("sources/cod_local", True):
            sources.append("COD")
        if self._structural_data_enabled() and bool(self.settings.value("materials_project/enabled", False, type=bool)):
            sources.append("MP")
        if self._structural_data_enabled() and self._source_enabled("sources/aflow", False):
            sources.append("AFLOW")
        if self._structural_data_enabled() and self._source_enabled("sources/oqmd", False):
            sources.append("OQMD")
        return list(dict.fromkeys(sources))

    def _aflow_enabled(self) -> bool:
        return self._structural_data_enabled() and not offline_mode_enabled() and self._source_enabled("sources/aflow", False)

    def _oqmd_enabled(self) -> bool:
        return self._structural_data_enabled() and not offline_mode_enabled() and self._source_enabled("sources/oqmd", False)

    def _cod_online_enabled(self) -> bool:
        return self._structural_data_enabled() and not offline_mode_enabled() and self._source_enabled("sources/cod_online", True)

    def _rruff_enabled(self) -> bool:
        return self._reference_patterns_enabled() and self._source_enabled("sources/rruff", False)

    def _match_pdf2_enabled(self) -> bool:
        return (
            self._source_enabled("sources/match_pdf2", self.match_pdf2.is_configured())
            and self.match_pdf2.is_configured()
        )

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
