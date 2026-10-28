from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from threading import Event
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QMessageBox
from scipy.signal import find_peaks

from xrd_finder.plot_export.metadata import CanvasLayer
from xrd_finder.services.candidate_rows import CandidateRowFormatter, normalize_candidate_row
from xrd_finder.services.candidate_preparation_queue import CandidatePreparationStage
from xrd_finder.services.local_phase_cache import DERIVED_CACHE_VERSION
from xrd_finder.services.selected_peak_search import SelectedPeakQuery, search_selected_peaks
from xrd_finder.services.selected_peak_discovery import search_with_discovery
from xrd_finder.ui.plot_layer_items import tag_xrd_plot_item


class PhaseFinderPeakSelectionActionsMixin:
    def _set_search_mode(self, mode: str) -> None:
        if mode not in {"search", "auto", "peaks"}:
            raise ValueError(f"Unknown search mode: {mode}")
        cancel_find = getattr(self, '_cancel_find_peaks', None)
        if mode != 'peaks' and callable(cancel_find):
            cancel_find()
        self._search_mode = mode
        self.finder_top_toolbar.set_search_mode(mode)
        panel = getattr(self, "composition_panel", None)
        if panel is not None:
            panel.set_search_mode(mode)
        table = getattr(self, "candidate_table", None)
        if table is not None:
            table.set_selected_peak_scoring(mode == "peaks")
        if mode == "peaks":
            self._candidate_gain_auto_enabled = False
        if hasattr(self, "match_plot"):
            self._redraw_selected_search_peaks()

    def _toggle_peak_search(self) -> None:
        if self._search_mode == "peaks":
            self._cancel_candidate_search_jobs()
            self._manual_search_peaks.clear()
            self._set_search_mode("search")
        else:
            self._begin_peak_search()

    def _begin_peak_search(self) -> None:
        if self._active_pattern() is None:
            self.finder_top_toolbar.set_search_mode(self._search_mode)
            QMessageBox.information(self, "Peak search", "Import or select an XRD pattern first.")
            return
        if self._search_mode != "peaks":
            self._cancel_candidate_search_jobs()
        self._set_search_mode("peaks")

    def _search_candidates_in_current_mode(self) -> None:
        if self._search_mode == "peaks":
            self._search_selected_peaks()
        elif self._search_mode == "auto":
            self._auto_search_candidates()
        else:
            self._search_from_controls()

    def _search_selected_peaks(self) -> None:
        pattern = self._active_pattern()
        positions = self._manual_search_peaks.get(pattern.id, []) if pattern else []
        intensities = None
        if getattr(pattern, 'input_kind', '') == 'peak_list':
            points = dict(pattern.peak_points)
            positions = self._manual_search_peaks.setdefault(pattern.id, [a for a, i in pattern.peak_points if i > 0.])
            positions = [a for a in positions if points.get(a, 0.) > 0.]
            intensities = tuple(points[a] for a in positions)
        if not positions:
            message = ('Select at least one manual peak with intensity above zero.'
                if getattr(pattern, 'input_kind', '') == 'peak_list'
                else 'Select peaks on the active XRD pattern first.')
            QMessageBox.information(self, "Peak search", message)
            return
        options = self._candidate_search_options(include_observed_peaks=False)
        online_sources = [source for source, enabled in (
            ('COD', options.cod_online_enabled), ('MP', options.materials_project_enabled),
            ('AFLOW', options.aflow_enabled), ('OQMD', options.oqmd_enabled),
        ) if enabled]
        try:
            query = SelectedPeakQuery(
                tuple(positions), float(self._active_wavelength()),
                self.finder_action_bar.peak_search_tolerance.value(),
                zero_shift_deg=self._pattern_zero_shift_deg(pattern.id),
                sources=tuple(dict.fromkeys(options.local_sources + online_sources)) if options.structural_data_enabled else (),
                required_elements=tuple(self.selected_element_order),
                excluded_elements=tuple(self._excluded_elements()),
                allow_inorganic=self.inorganics_checkbox.isChecked(),
                allow_organic=self.organics_checkbox.isChecked(),
                **({'selected_intensities': intensities} if intensities is not None else {}),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Peak search", str(exc))
            return
        if not query.sources:
            QMessageBox.information(self, "Peak search", "Enable a structural database before searching by selected peaks.")
            return
        self._cancel_candidate_search_jobs()
        self._set_search_mode("peaks")
        token = self._prepare_candidate_database_search()
        cancel = self._selected_peak_search_cancel = Event()
        pattern_id = pattern.id
        index_path = self.local_phase_cache.index_path
        state = {'running': True, 'dirty': False, 'error': ''}
        self._set_auto_search_busy(True)
        self._set_candidate_batch_detail(f"Searching indexed phases | Selected peaks {len(query.selected_two_theta)}")

        def current() -> bool:
            active = self._active_pattern()
            return (not cancel.is_set() and self._search_mode == "peaks"
                    and token == self._candidate_search_request_token
                    and active is not None and active.id == pattern_id)

        def display(result) -> None:
            if not current() or result.cancelled:
                return
            formatter = CandidateRowFormatter(self.local_phase_cache)
            rows = [normalize_candidate_row(row) for row in formatter.cache_rows(result.candidates)]
            for row, candidate in zip(rows, result.candidates):
                row[5] = f"{candidate.match.coverage_percent:.0f}%"
                row[6] = ""
            self._record_initial_candidate_rows(rows)
            self._set_candidate_rows(rows or [["", "", "", "No indexed phases match the selected peaks", "", "", "", ""]], skip_rank=True)
            by_key = {(candidate.source, candidate.entry_id): candidate for candidate in result.candidates}
            for row in range(self.candidate_table.rowCount()):
                values = self.candidate_table.row_values(row)
                candidate = by_key.get((values.get("Source"), values.get("Entry")))
                if candidate is not None:
                    assessment = candidate.match
                    text = (f"Selected peaks: {assessment.matched_count}/{assessment.selected_count}\n"
                            f"Mean position error: {assessment.mean_angle_error_deg:.6g} deg\n"
                            f"Tolerance: +/-{query.tolerance_two_theta_deg:g} deg; zero correction: {query.zero_shift_deg:+g} deg\n"
                            "Coverage of selected peaks only, not identification probability. "
                            "Unselected reference lines and intensities are not scored.")
                    if query.selected_intensities is not None:
                        text = text.replace('Unselected reference lines and intensities are not scored.',
                            'Reference relative intensities and missing reference lines are not compared.')
                        text += '\nCoverage and ranking are weighted by the entered intensities; zero-intensity peaks are ignored.'
                    self.candidate_table.item(row, 5).setToolTip(text)
            busy = state['running'] or self._candidate_preparation_is_busy()
            self._set_auto_search_busy(busy)
            best = result.candidates[0].match.matched_count if result.candidates else 0
            detail = (
                f"Indexed phases {len(result.candidates)} | Selected peaks {best}/{len(query.selected_two_theta)} | "
                f"Tolerance +/-{query.tolerance_two_theta_deg:g} deg")
            if online_sources and not query.required_elements:
                detail = (f'Indexed phases {len(result.candidates)} | Selected peaks '
                          f'{best}/{len(query.selected_two_theta)} | Online: select elements')
            if query.selected_intensities is not None and result.candidates:
                detail += f' | Intensity-weighted coverage {result.candidates[0].match.coverage_percent:.1f}%'
            if state['error']:
                detail += ' | Incomplete'
            elif busy:
                detail += ' | Loading / processing'
            self._set_candidate_batch_detail(detail)
            if state['error']:
                self.candidate_search_detail_label.setToolTip(detail + '\n' + state['error'])
            self._set_candidate_status_state('error' if state['error'] else 'busy' if busy else 'complete')

        def success(result) -> None:
            if not current() or result.cancelled:
                return
            state['running'] = False
            self._finalize_candidate_search(token, error=state['error'])
            display(result)
            if state['dirty']:
                refresh()

        def failure(message: str, details: str) -> None:
            if not current():
                return
            state['running'] = False
            state['error'] = message or details
            self._finalize_candidate_search(token, error=state['error'])
            self._set_auto_search_busy(False)
            self._set_candidate_batch_detail("Selected-peak search failed; results are incomplete")
            self._set_candidate_status_state("error")
            QMessageBox.warning(self, "Peak search", message or details)

        def refresh() -> None:
            if not current():
                return
            if state['running']:
                state['dirty'] = True
                return
            state['dirty'] = False
            state['running'] = True
            self._set_auto_search_busy(True)
            self._set_candidate_status_state('busy')
            self._run_background_task(
                'Peak search', 'Checking newly indexed phase lines...',
                lambda progress: search_selected_peaks(index_path, query, derived_version=DERIVED_CACHE_VERSION,
                                                       progress=progress, cancelled=cancel.is_set),
                success, failure, with_progress=True, operation_name='match.search.selected_peaks.refresh',
                show_progress_dialog=False,
            )

        def prepared(notice) -> None:
            if not current() or token not in notice.session_tokens or notice.source not in query.sources:
                return
            if notice.stage is CandidatePreparationStage.READY:
                refresh()
            elif notice.stage is CandidatePreparationStage.FAILED:
                state['error'] = f'{notice.source} {notice.entry_id}: {notice.error}'
                self._finalize_candidate_search(token, error=state['error'])
                self._set_auto_search_busy(state['running'] or self._candidate_preparation_is_busy())
                self._set_candidate_status_state('error')
                self._set_candidate_batch_detail(f'Selected-peak search incomplete: {notice.source} {notice.entry_id}')
                self.candidate_search_detail_label.setToolTip(state['error'])

        self._selected_peak_notice_handler = prepared

        def preparation_progress(progress) -> None:
            if current():
                busy = state['running'] or self._preparation_progress_is_busy(progress)
                self._set_auto_search_busy(busy)
                if state['error']:
                    self._set_candidate_status_state('error')

        self._selected_peak_progress_handler = preparation_progress

        def worker(progress, partial=None):
            return search_with_discovery(
                index_path, query, options, self.candidate_search_service,
                derived_version=DERIVED_CACHE_VERSION, scan=search_selected_peaks,
                session_token=token, progress=progress, cancelled=cancel.is_set, partial=partial,
            )

        self._run_background_task(
            "Peak search", "Searching selected databases...", worker,
            success, failure, with_progress=True, operation_name="match.search.selected_peaks",
            show_progress_dialog=False, on_partial=display,
        )

    def _on_search_peak_click(self, event) -> None:
        if event.double():
            return
        pick_manual = getattr(self, '_pick_manual_peak', None)
        if callable(pick_manual) and pick_manual(event.scenePos(), event.button()):
            event.accept(); return
        if getattr(self, '_peak_info_armed', False):
            self._pick_peak_information(event.scenePos(), event.button())
            event.accept()
            return
        if self._pick_search_peak(event.scenePos(), event.button()):
            event.accept()

    def _cancel_selected_peak_search(self) -> None:
        cancel_find = getattr(self, '_cancel_find_peaks', None)
        if callable(cancel_find):
            cancel_find()
        cancel = getattr(self, "_selected_peak_search_cancel", None)
        if cancel is not None and not cancel.is_set():
            cancel.set()
            self._candidate_search_request_token += 1
            controller = getattr(self, "_candidate_batch_updates", None)
            if controller is not None:
                controller.stop()
            self._set_auto_search_busy(False)

    def _pick_search_peak(self, scene_position, button) -> bool:
        if self._search_mode != "peaks" or button not in {Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton}:
            return False
        pattern = self._active_pattern()
        if pattern is None:
            return False
        view = self.match_plot.getViewBox()
        if not view.sceneBoundingRect().contains(scene_position):
            return False
        context = self.observed_pattern_plot_context.get(pattern.id, {})
        x = np.asarray(context.get("display_x", []), dtype=float)
        y = np.asarray(context.get("display_y", []), dtype=float)
        if len(x) != len(y) or len(x) < 3:
            return False
        finite = np.isfinite(x) & np.isfinite(y)
        if not np.any(finite):
            return False
        shift = self._pattern_display_zero_shift_deg(pattern.id) if self.profile_states.get(pattern.id, {}).get("correct_zero", False) else 0.
        positions = self._manual_search_peaks.setdefault(pattern.id, [])
        if button == Qt.MouseButton.RightButton:
            indices = [int(np.argmin(np.where(finite, np.abs(x - position), np.inf)))
                       for position in positions if np.any((x == position) & finite)]
        else:
            indices = (np.arange(len(x)).tolist() if getattr(pattern, 'input_kind', '') == 'peak_list'
                       else find_peaks(y)[0].tolist())
        distances = []
        for index in indices:
            if not np.isfinite(x[index]) or not np.isfinite(y[index]):
                continue
            point = view.mapViewToScene(QPointF(float(x[index]) - shift, float(y[index])))
            distances.append(((point.x() - scene_position.x()) ** 2 + (point.y() - scene_position.y()) ** 2, index))
        if not distances:
            return True
        distance, index = min(distances)
        # Hit testing is in screen pixels, independent of angle units and zoom.
        if distance > 18. ** 2:
            return True
        position = float(x[index])
        if button == Qt.MouseButton.LeftButton:
            if position not in positions:
                positions.append(position)
                positions.sort()
            else:
                return True
        else:
            positions.remove(min(positions, key=lambda value: abs(value - position)))
        self._cancel_selected_peak_search()
        self._set_candidate_status_state("idle")
        self._set_candidate_batch_detail(f"Selected peaks {len(positions)} | Selection changed")
        self._redraw_selected_search_peaks()
        return True

    def _redraw_selected_search_peaks(self) -> None:
        for item in self.plot_layers.get("search_peak_selection", []):
            self.match_plot.removeItem(item)
        self.plot_layers["search_peak_selection"] = []
        pattern = self._active_pattern()
        if self._search_mode != "peaks" or pattern is None:
            return
        if getattr(pattern, 'input_kind', '') == 'peak_list':
            self._manual_search_peaks.setdefault(pattern.id, [a for a, i in pattern.peak_points if i > 0.])
        context = self.observed_pattern_plot_context.get(pattern.id, {})
        x = np.asarray(context.get("display_x", []), dtype=float)
        y = np.asarray(context.get("display_y", []), dtype=float)
        if len(x) != len(y) or not len(x):
            return
        finite = np.isfinite(x) & np.isfinite(y)
        selected = [position for position in self._manual_search_peaks.get(pattern.id, [])
                    if np.any((x == position) & finite)]
        if not selected:
            return
        item = pg.ScatterPlotItem(
            selected, [y[int(np.argmin(np.where(finite, np.abs(x - position), np.inf)))] for position in selected],
            symbol="+", size=15, pen=pg.mkPen("#d03a1f", width=2.), brush=None,
        )
        tag_xrd_plot_item(item, layer=CanvasLayer.LABELS, pattern_id=pattern.id,
                          object_id="search-peak-selection", exportable=False)
        self.match_plot.addItem(item)
        self.plot_layers["search_peak_selection"].append(item)
        self._apply_zero_shift_display()
