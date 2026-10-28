from __future__ import annotations

import time
from threading import Event
import numpy as np

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
from xrd_finder.services.local_phase_cache import LocalPhaseSearchError
from xrd_finder.services.network import offline_mode_enabled
from xrd_finder.ui.candidate_batch_updates import CandidateBatchUpdateController
from xrd_finder.ui.observed_search_job import ObservedSearchController, apply_observed_search_result
from xrd_finder.ui.theme import is_dark_theme, theme_colors


class PhaseFinderCandidateSearchActionsMixin:
    LARGE_MANUAL_SEARCH_LIMIT = 100

    def _set_candidate_status_state(self, state: str) -> None:
        bar = getattr(self, "candidate_status_bar", None)
        if bar is None:
            return
        palette = theme_colors(is_dark_theme(bar))
        colors = {
            'idle': (palette['panel'], palette['border'], palette['text']),
            'busy': (palette['warning'], '#ba914a', palette['semantic_text']),
            'complete': (palette['gain'], '#23997e', palette['semantic_text']),
            'error': (palette['error'], '#bb6578', palette['semantic_text']),
        }
        if state not in colors:
            raise ValueError(f"Unknown candidate activity state: {state}")
        if bar.property("activityState") == state:
            return
        background, border, foreground = colors[state]
        bar.setProperty("activityState", state)
        bar.setStyleSheet(
            f"QWidget#candidateSearchStatus {{ background: {background};"
            f" border: 1px solid {border}; border-radius: 7px; }}"
            f"QWidget#candidateSearchStatus QLabel {{ color: {foreground};"
            " background: transparent; border: none; font-weight: 600; }"
        )

    def _set_candidate_batch_state(self, state: str) -> None:
        controller = getattr(self, "gain_job_controller", None)
        if controller is not None and controller.running and not getattr(controller, "cancelled", False):
            return
        if getattr(self, "_auto_search_in_progress", False):
            state = "busy"
        self._set_candidate_status_state(state)

    def _set_candidate_batch_detail(self, text: str) -> None:
        controller = getattr(self, "gain_job_controller", None)
        if controller is not None and controller.running and not getattr(controller, "cancelled", False):
            return
        self.candidate_search_detail_label.setText(text)
        self.candidate_search_detail_label.setToolTip(text)

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

        try:
            self.candidate_search_service.queue_candidate_rows(
                rows,
                session_token=search_token,
                wavelength=float(self._instrument_profile_for_pattern(
                    self._active_pattern()).radiation.components[0].wavelength_angstrom),
            )
        except LocalPhaseSearchError as exc:
            controller = getattr(self, "_candidate_batch_updates", None)
            if controller is not None:
                controller.mark_search_complete(search_token, error=str(exc))
            QMessageBox.warning(self, "Candidate preparation incomplete", str(exc))
            return False
        started = time.perf_counter()
        self._set_candidate_rows(rows)
        self.candidate_search_service.queue_iic_updates(rows, session_token=search_token)
        elapsed = time.perf_counter() - started
        if count > 0 and elapsed > 0.0:
            measured = elapsed / count
            previous = float(getattr(self, "_candidate_processing_seconds_per_item", 0.0) or 0.0)
            self._candidate_processing_seconds_per_item = (
                measured if previous <= 0.0 else previous * 0.7 + measured * 0.3
            )
        return True

    def _rerank_loaded_candidates_for_instrument_change(self) -> None:
        if getattr(self, "_search_mode", "search") == "peaks":
            self._cancel_selected_peak_search()
            pattern = self._active_pattern()
            if pattern is not None and self._manual_search_peaks.get(pattern.id):
                self._search_selected_peaks()
            return
        table = getattr(self, "candidate_table", None)
        if table is None:
            return
        candidates = [
            candidate
            for candidate in table.ranking_row_values()
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

    def _prepare_gain_reference_range(self) -> bool:
        """Keep range generation outside the GUI thread and ahead of Gain SQL."""
        options = self._candidate_search_options()
        if not options.local_sources or not options.structural_data_enabled:
            return True
        cache = self.local_phase_cache
        sources, excluded = tuple(options.local_sources), tuple(options.excluded_elements)
        prefix = (float(options.wavelength), sources, excluded)
        key = (*prefix, cache.reference_revision(sources))
        if getattr(self, '_gain_reference_range_ready', None) == key:
            return True
        context_key = self._active_probability_context_key()
        if getattr(self, '_gain_reference_range_pending', None) is not None:
            if (self._gain_reference_range_pending != key or
                    getattr(self, '_gain_reference_range_context', None) != context_key):
                self._gain_reference_range_retry = True
            return False
        if getattr(self, '_gain_reference_range_failed', None) == key:
            return False
        self._gain_reference_range_pending = key
        self._gain_reference_range_context = context_key
        self._gain_reference_range_retry = False
        cache_root, wavelength = cache.root, float(options.wavelength)

        def prepare():
            from xrd_finder.services.local_phase_cache import LocalPhaseCache
            from xrd_finder.services.reference_preparation import prepare_reference_rows
            worker_cache = LocalPhaseCache(cache_root)
            # A first pass may expand records and change the revision itself.
            # Validate a stable pass before caching success; new arrivals must
            # not be stamped ready merely because an older population finished.
            for _attempt in range(3):
                revision = worker_cache.reference_revision(sources)
                entries = worker_cache.search(excluded_elements=list(excluded),
                                              sources=list(sources), limit=2_147_483_647,
                                              strict=True, deduplicate=False, summary_only=True)
                unavailable = prepare_reference_rows(worker_cache,
                    [[entry.source, entry.entry_id] for entry in entries], wavelength=wavelength)
                if worker_cache.reference_revision(sources) == revision:
                    # Unavailable cards stay blank through the guarded loaders;
                    # a malformed CIF must not block all other valid candidates.
                    return revision, tuple(unavailable)
            return None, ()

        def done(result):
            if getattr(self, '_gain_reference_range_pending', None) != key:
                return
            self._gain_reference_range_pending = None
            revision = result[0] if result is not None else None
            if revision is not None:
                self._gain_reference_range_ready = (*prefix, revision)
                self._gain_reference_range_unavailable = result[1]
            retry = bool(getattr(self, '_gain_reference_range_retry', False))
            self._gain_reference_range_retry = False
            if retry or self._active_probability_context_key() == context_key:
                self._schedule_candidate_gain_ranking()

        def failed(_message, _details):
            if getattr(self, '_gain_reference_range_pending', None) == key:
                self._gain_reference_range_failed = (*prefix, cache.reference_revision(sources))
                self._gain_reference_range_pending = None
                retry = bool(getattr(self, '_gain_reference_range_retry', False))
                self._gain_reference_range_retry = False
                if retry:
                    self._schedule_candidate_gain_ranking()

        self._run_background_task('Reference lines', 'Preparing reference d range for Gain...',
                                  prepare, done, failed)
        return False

    def _initialize_candidate_batch_updates(self) -> None:
        self._candidate_batch_updates = CandidateBatchUpdateController(
            row_loader=self._load_prepared_candidate_row,
            rows_ready=self._merge_prepared_candidate_rows,
            status_callback=self.background_status_changed.emit,
            title_callback=self.candidate_list_label.setText,
            detail_callback=self._set_candidate_batch_detail,
            state_callback=self._set_candidate_batch_state,
            parent=self,
        )
        self.candidate_prepared.connect(self._selected_peak_candidate_prepared)
        self.candidate_preparation_progress.connect(
            self._handle_candidate_preparation_progress
        )
        self.cod_server_alert.connect(self._set_candidate_search_notice)
        self.candidate_prepared.connect(self._refresh_calculated_iic)
        QTimer.singleShot(0, self.candidate_search_service.queue_iic_updates)

    def _selected_peak_candidate_prepared(self, notice) -> None:
        if getattr(self, '_search_mode', 'search') != 'peaks':
            self._candidate_batch_updates.accept_notice(notice)
            return
        handler = getattr(self, '_selected_peak_notice_handler', None)
        if handler is not None:
            handler(notice)

    def _refresh_calculated_iic(self, notice) -> None:
        entry = getattr(notice, "result", None)
        if entry is None or not getattr(entry, "iic_method", ""):
            return
        changed = False
        row = self.candidate_table._row_for_candidate_key((entry.source, entry.entry_id))
        if row >= 0:
            candidate = self.candidate_table.row_values(row)
            changed = self._apply_cached_iic(candidate, entry) or changed
            item = self.candidate_table.item(row, self.candidate_table.columnCount() - 1)
            if item is not None:
                item.setText(candidate.get("I/Ic*", ""))
        collections = [self.match_candidates]
        collections.extend(state.get("candidates", []) for state in self.profile_states.values())
        for candidates in collections:
            for candidate in candidates:
                if (self._candidate_source(candidate), candidate.get("Entry", "")) == (entry.source, entry.entry_id):
                    changed = self._apply_cached_iic(candidate, entry) or changed
        if changed:
            self._gain_preparation_revision = int(getattr(self, "_gain_preparation_revision", 0)) + 1
            self._update_match_table()

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
        if getattr(self, '_search_mode', 'search') == 'peaks':
            handler = getattr(self, '_selected_peak_progress_handler', None)
            if handler is not None:
                handler(progress)
            return
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
        if getattr(self, "_search_mode", "search") == "peaks":
            # This result list belongs only to the captured selected-peak query.
            return
        self._gain_preparation_revision = int(getattr(self, "_gain_preparation_revision", 0)) + 1
        rows = self.candidate_search_service.dedupe_candidate_rows(prepared_rows)
        if not rows:
            return
        if self.match_candidates:
            self.candidate_table.upsert_rows(rows, normalize_candidate_row)
            self._apply_candidate_element_filter()
            if not getattr(self, "_candidate_gain_auto_enabled", False):
                return
            self._candidate_gain_refresh_after_preparation = True
            if not self._candidate_preparation_is_busy():
                self._candidate_gain_refresh_after_preparation = False
                self._schedule_candidate_gain_ranking()
            return

        self.candidate_table.upsert_rows(rows, normalize_candidate_row)
        self._apply_candidate_element_filter()
        if self._rank_by_peak_probability_enabled():
            from xrd_finder.ui.candidate_match_job import CandidateMatchQueue
            queue = getattr(self, '_loaded_match_queue', None)
            if queue is None:
                queue = self._loaded_match_queue = CandidateMatchQueue(self)
            all_rows = self.candidate_table.ranking_row_values()
            queue.request(self._candidate_state_rows(all_rows))

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

    def _finalize_candidate_search(self, search_token: int, *, error: str = "") -> None:
        controller = getattr(self, "_candidate_batch_updates", None)
        if controller is not None:
            controller.mark_search_complete(search_token, error=error)

    def _auto_search_candidates(self) -> None:
        if getattr(self._active_pattern(), 'input_kind', '') == 'peak_list':
            self._search_selected_peaks()
            return
        if self._active_pattern() is None:
            self.finder_top_toolbar.set_search_mode(self._search_mode)
            QMessageBox.information(self, "Identify phases", "Import or select an XRD pattern first.")
            return
        self._set_search_mode('auto')
        self._auto_search_token = int(getattr(self, '_auto_search_token', 0)) + 1
        controller = getattr(self, '_observed_search_controller', None)
        if controller is None:
            controller = ObservedSearchController(self)
            self._observed_search_controller = controller
            controller.drained.connect(self._finish_preparation_close)
        controller.request(self._auto_search_prepared)

    def _auto_search_prepared(self, capture, result) -> None:
        self._run_prepared_auto_search((result.x, result.corrected, result.records), capture, result)

    def _run_prepared_auto_search(self, probability_data, capture=None, prepared_result=None) -> None:
        if probability_data is None:
            self.finder_top_toolbar.set_search_mode(self._search_mode)
            QMessageBox.information(self, "Identify phases", "No usable peaks were detected in the active pattern.")
            return
        _observed_x, _corrected, observed_records = probability_data
        peak_positions = [self._observed_record_position(record) for record in observed_records[:80]]
        if not peak_positions:
            self.finder_top_toolbar.set_search_mode(self._search_mode)
            QMessageBox.information(self, "Identify phases", "No usable peaks were detected in the active pattern.")
            return

        self._run_peak_candidate_search(observed_records[:80], mode="auto",
                                        capture=capture, prepared_result=prepared_result)

    def _run_peak_candidate_search(self, observed_records, *, mode: str, capture=None, prepared_result=None) -> None:
        self._cancel_candidate_search_jobs()
        self._set_search_mode(mode)
        if prepared_result is not None:
            scan_x = np.asarray(prepared_result.x, dtype=float)
        else:
            measurement = self._probability_observed_data()
            scan_x = np.asarray(measurement[0] if measurement is not None else [], dtype=float)
        scan_x = scan_x[np.isfinite(scan_x)]
        scan_range = (float(scan_x.min()), float(scan_x.max())) if scan_x.size else None
        peak_positions = [self._observed_record_position(record) for record in observed_records]
        title = "Peak search" if mode == "peaks" else "Identify phases"

        elements = list(self.selected_element_order)
        options = self._candidate_search_options()
        options.observed_peak_positions = peak_positions
        options.cod_online_enabled = False
        options.materials_project_enabled = False
        options.aflow_enabled = False
        options.oqmd_enabled = False

        search_context_key = self._active_probability_context_key()
        selected_keys = tuple((item.get("Source", ""), item.get("Entry", ""))
                              for item in self.match_candidates)
        search_token = self._prepare_candidate_database_search()
        cancel = Event()
        self._candidate_search_cancel = cancel
        self._candidate_gain_auto_enabled = True
        if capture is not None:
            apply_observed_search_result(self, capture, prepared_result)
        auto_search_token = int(getattr(self, "_auto_search_token", 0)) + 1
        self._auto_search_token = auto_search_token
        self._set_auto_search_busy(True)
        label = "selected peak positions in local databases" if mode == "peaks" else "observed peak positions in local databases"

        def request_is_current() -> bool:
            if (
                search_token != getattr(self, "_candidate_search_request_token", 0)
                or auto_search_token != getattr(self, "_auto_search_token", 0)
            ):
                return False
            current_selected = tuple((item.get("Source", ""), item.get("Entry", ""))
                                     for item in self.match_candidates)
            if (search_context_key != self._active_probability_context_key()
                    or selected_keys != current_selected):
                # Invalidate only this request. A superseding search must keep
                # its own busy state and is excluded by the token check above.
                self._auto_search_token = auto_search_token + 1
                self._finalize_candidate_search(search_token)
                self._set_auto_search_busy(False)
                return False
            return True

        def partial(result) -> None:
            if not request_is_current():
                return
            rows = result or []
            if rows:
                self._record_initial_candidate_rows(rows)
                self._set_candidate_rows(rows, skip_rank=True)

        def success(result) -> None:
            if not request_is_current():
                return
            self._finalize_candidate_search(search_token)
            rows = result or []
            self._record_initial_candidate_rows(rows)
            if not rows:
                self._set_auto_search_busy(False)
                self._set_candidate_rows([["", "", "", f"No candidates found: {title.lower()}", "", ""]])
                return
            if self.match_candidates:
                # Gain uses the accepted-phase line state and remains on its
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
            ranking_instrument = self._instrument_profile_for_pattern(self._active_pattern())
            ranking_rows = [list(row) for row in rows]
            ranking_records = list(observed_records)

            def rank_task(progress):
                from xrd_finder.services.reference_preparation import prepare_reference_rows
                from xrd_finder.services.local_phase_cache import LocalPhaseCache
                prepare_reference_rows(LocalPhaseCache(cache_root), ranking_rows,
                    wavelength=ranking_instrument.radiation.components[0].wavelength_angstrom,
                    progress=progress, cancelled=cancel.is_set)
                with create_local_reference_peak_loader(
                    cache_root,
                    pdf2_root or None,
                    wavelength,
                    instrument_profile=ranking_instrument, prepared_only=True, match_only=True,
                    two_theta_range=scan_range,
                ) as peak_loader:
                    return rank_candidate_rows(
                        ranking_rows,
                        ranking_records,
                        wavelength=wavelength,
                        reference_peak_loader=peak_loader,
                        two_theta_range=scan_range,
                        rank_limit=ranking_total,
                        progress=progress,
                        cancelled=cancel.is_set,
                    )

            def ranking_success(ranking_result: AutoSearchRankingResult) -> None:
                if not request_is_current():
                    return
                ranked_rows = ranking_result.rows
                self._set_candidate_rows(ranked_rows, skip_rank=True)
                if hasattr(self.candidate_table, 'set_match_diagnostics'):
                    self.candidate_table.set_match_diagnostics(ranking_result.failures, ranking_result.unavailable_keys)
                if not self.match_candidates:
                    self._auto_search_ranked_rows = [list(row) for row in ranked_rows]
                    self._auto_search_scored_keys = set(ranking_result.scored_keys)
                if getattr(self, "scoring_status_label", None) is not None:
                    self.scoring_status_label.setText(
                        f"{self._scoring_source_status_text()} | "
                        f"FP: match {ranking_result.matched_count}/{ranking_total}, gain 0/{ranking_total}"
                        f" | {len(ranking_result.unavailable_keys)} unavailable, {len(ranking_result.failures)} failed"
                    )
                self._apply_candidate_element_filter()
                self.candidate_table.ensure_visible_selection()
                self._set_auto_search_busy(False)

            def ranking_failure(message: str, details: str) -> None:
                if not request_is_current():
                    return
                self._set_candidate_rows(rows, skip_rank=True)
                self._auto_search_ranked_rows = [list(row) for row in rows]
                self._auto_search_scored_keys = set()
                self._finalize_candidate_search(search_token, error=message or details)
                self._set_auto_search_busy(False)
                QMessageBox.warning(self, f"{title} ranking failed", message or details)

            self._run_background_task(
                title,
                "Ranking local candidates...",
                rank_task,
                ranking_success,
                ranking_failure,
                with_progress=True,
                operation_name="match.rank.auto",
                show_progress_dialog=False,
            )

        def failure(message: str, details: str) -> None:
            if not request_is_current():
                return
            self._finalize_candidate_search(search_token, error=message or details)
            self._set_auto_search_busy(False)
            QMessageBox.warning(self, f"{title} failed", message or details)

        self._run_background_task(
            title,
            f"Searching candidates from {label}...",
            lambda progress, partial_results: self.candidate_search_service.search_elements(
                elements,
                options,
                progress=progress,
                partial_results=partial_results,
                session_token=search_token,
                cancelled=cancel.is_set,
            ),
            success,
            failure,
            with_progress=True,
            operation_name=f"match.search.{mode}",
            on_partial=partial,
            show_progress_dialog=False,
        )

    def _prepare_candidate_database_search(self) -> int:
        self._candidate_gain_auto_enabled = False
        self._candidate_gain_refresh_after_preparation = False
        self._candidate_gain_refresh_requested = False
        preview = getattr(self, 'preview_observation_controller', None)
        if preview is not None:
            preview.invalidate()
        self._candidate_preview_token = int(getattr(self, '_candidate_preview_token', 0)) + 1
        preparation = getattr(self, '_observed_search_controller', None)
        if preparation is not None:
            preparation.invalidate()
            self._set_auto_search_busy(False)
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
        self._cancel_candidate_search_jobs()
        self._set_search_mode("search")
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
        cancel = Event()
        self._candidate_search_cancel = cancel

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
            self._finalize_candidate_search(search_token, error=message or details)
            QMessageBox.warning(self, "Find candidates", message or details)

        self._run_background_task(
            "Find candidates",
            f"Searching phase databases for {query}...",
            lambda progress, partial_results: self.candidate_search_service.search_text(
                query,
                options,
                progress=lambda *args: progress(*args) if not cancel.is_set() and search_token == getattr(self, "_candidate_search_request_token", 0) else None,
                partial_results=partial_results,
                session_token=search_token,
                cancelled=cancel.is_set,
            ),
            success,
            failure,
            with_progress=True,
            operation_name="match.search.text",
            on_partial=partial,
            show_progress_dialog=False,
        )

    def _search_from_controls(self, *, elements_only: bool = False) -> None:
        self._cancel_candidate_search_jobs()
        self._set_search_mode("search")
        ccdc_query = self.ccdc_doi_input.text().strip() if self.ccdc_doi_input is not None and not elements_only else ""
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
        cancel = Event()
        self._candidate_search_cancel = cancel

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
            if self.search_input is not None and self.formula_sum_input is not None:
                self.search_input.setText(self.formula_sum_input.text().strip())
            if not rows:
                self._set_candidate_rows([["", "", "", "No entries found for the selected elements", "", ""]])
                return
            self._finish_manual_candidate_rows(rows, search_token)

        def failure(message: str, details: str) -> None:
            if search_token != getattr(self, "_candidate_search_request_token", 0):
                return
            self._finalize_candidate_search(search_token, error=message or details)
            QMessageBox.warning(self, "Find candidates", message or details)

        self._run_background_task(
            "Find candidates",
            f"Searching phase databases for {search_label}...",
            lambda progress, partial_results: self.candidate_search_service.search_elements(
                elements,
                options,
                progress=lambda *args: progress(*args) if not cancel.is_set() and search_token == getattr(self, "_candidate_search_request_token", 0) else None,
                partial_results=partial_results,
                session_token=search_token,
                cancelled=cancel.is_set,
            ),
            success,
            failure,
            with_progress=True,
            operation_name="match.search.elements",
            on_partial=partial,
            show_progress_dialog=False,
        )

    def _candidate_search_options(self, *, include_observed_peaks: bool = True) -> CandidateSearchOptions:
        allow_inorganic = self.inorganics_checkbox.isChecked()
        allow_organic = self.organics_checkbox.isChecked()

        def material_class_allowed(formula: str) -> bool:
            organic = {'C', 'H'}.issubset(formula_elements(formula))
            return allow_organic if organic else allow_inorganic

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
            material_class_allowed=material_class_allowed,
            optional_elements=self._optional_elements(),
            required_elements=list(self.selected_element_order),
            observed_peak_positions=self._candidate_search_peak_positions() if include_observed_peaks else [],
            wavelength=float(self._instrument_profile_for_pattern(
                self._active_pattern()).radiation.components[0].wavelength_angstrom),
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
