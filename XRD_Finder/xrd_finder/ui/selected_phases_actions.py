from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog, QMenu, QMessageBox, QProgressDialog

from xrd_finder.io.cif_loader import create_phase_from_cif


class PhaseFinderSelectedPhasesActionsMixin:
    def _on_match_row_clicked(self, row: int) -> None:
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates[row]
        self._enrich_candidate_with_structure_info(candidate)
        self._update_compound_card(candidate)
        self._recalculate_match_profile()

    def _show_match_context_menu(self, global_point) -> None:
        row = self.match_table.currentRow()
        candidate = self.match_candidates[row] if 0 <= row < len(self.match_candidates) else None
        has_structure = self._candidate_has_structure(candidate)
        menu = QMenu(self)
        recalculate_action = menu.addAction("Recalculate selected profile", self._recalculate_match_profile)
        rename_action = menu.addAction("Rename phase...", self._edit_selected_match_phase_name)
        menu.addAction("Change color...", self._change_selected_match_color)
        export_action = menu.addAction("Export phase CIF...", self._export_match_table_cif)
        for action in (recalculate_action, export_action):
            action.setEnabled(has_structure)
            if not has_structure:
                action.setToolTip("This selected item is a reference pattern; no CIF structure is available.")
        rename_action.setEnabled(candidate is not None)
        menu.addAction("Remove selected phase", self._remove_selected_match_candidate)
        menu.addAction("Clear working set", self._clear_match_list)
        menu.exec(global_point)

    def _edit_selected_match_phase_name(self) -> None:
        row = self.match_table.currentRow()
        if 0 <= row < len(self.match_candidates):
            self.match_table.edit_phase_name(row)

    def _rename_selected_match_phase(self, row: int, name: str) -> None:
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates[row]
        clean_name = str(name).strip()
        if not clean_name:
            self._update_match_table()
            return
        if clean_name == self._candidate_phase_name(candidate):
            return

        candidate["_DisplayName"] = clean_name
        key = self._candidate_key(candidate)
        # A phase keeps one display name across all observed patterns, just as
        # it keeps one project-wide color. This updates inactive profile states
        # so their local legends change immediately in multi-pattern mode.
        for state in getattr(self, "profile_states", {}).values():
            state_candidates = state.get("candidates", []) if isinstance(state, dict) else []
            if not isinstance(state_candidates, list):
                continue
            for state_candidate in state_candidates:
                if isinstance(state_candidate, dict) and self._candidate_key(state_candidate) == key:
                    state_candidate["_DisplayName"] = clean_name
        structure = self.match_structures.get(key)
        if structure is not None:
            structure.name = clean_name

        try:
            source_path = str(self._candidate_cif_path(candidate))
        except Exception:
            source_path = ""
        project_changed = False
        if source_path:
            for phase in self.project.phases:
                if phase.source_path != source_path:
                    continue
                phase.name = clean_name
                project_structure = next(
                    (item for item in self.project.structures if item.id == phase.structure_id),
                    None,
                )
                if project_structure is not None:
                    project_structure.name = clean_name
                project_changed = True

        if hasattr(self, "_save_active_profile_state"):
            self._save_active_profile_state()
        if project_changed:
            active_pattern_id = self._current_profile_pattern_id() if hasattr(self, "_current_profile_pattern_id") else None
            self.project.touch()
            self.tree.set_project(self.project)
            if active_pattern_id:
                self.tree.select_object("pattern", active_pattern_id)
            self.project_changed.emit()
        self._recalculate_match_profile(auto_zoom=False)

    def _add_selected_candidate_to_match_list(self) -> None:
        candidate = self._selected_candidate_row()
        if candidate is None:
            QMessageBox.information(self, "Working set", "Select a structure source row first.")
            return
        if self._candidate_source(candidate) == "RRUFF":
            self._preview_rruff_reference(candidate, show_errors=True)
            QMessageBox.information(
                self,
                "RRUFF reference",
                "RRUFF entries are measured reference patterns. They can be previewed as overlays, but cannot be used as calculated CIF phases.",
            )
            return
        if self._candidate_source(candidate) == "PDF2":
            self._preview_pdf2_reference(candidate, show_errors=True)
            QMessageBox.information(
                self,
                "PDF-2 reference",
                "PDF-2 entries are reference cards. They can be previewed as peak overlays, but cannot be used as calculated CIF phases.",
            )
            return
        if self._candidate_source(candidate) not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"} or not candidate.get("Entry"):
            QMessageBox.information(self, "Working set", "Only saved COD, CCDC, user, or Materials Project structures can be calculated from CIF for now.")
            return
        self._with_candidate_cif_ready(
            candidate,
            "Working set",
            lambda ready_candidate: self._add_candidate_to_match_list(ready_candidate, show_errors=True, recalculate=True),
        )

    def _add_candidate_to_match_list(
        self,
        candidate: dict[str, str],
        show_errors: bool,
        recalculate: bool = True,
    ) -> bool:
        key = self._candidate_key(candidate)
        if any(self._candidate_key(item) == key for item in self.match_candidates):
            if recalculate:
                self.post_match_pipeline.candidate_added()
            return True
        try:
            self._capture_candidate_gain_indexed_evidence(candidate)
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            phase_name = self._candidate_phase_name(candidate)
            if phase_name:
                structure.name = phase_name
            if not structure.formula and candidate.get("Formula"):
                structure.formula = candidate["Formula"]
            candidate_copy = candidate.copy()
            self.match_candidates.append(candidate_copy)
            self.match_structures[key] = structure
            if hasattr(self, "_save_active_profile_state"):
                self._save_active_profile_state()
            if hasattr(self, "_invalidate_match_profile_cache"):
                self._invalidate_match_profile_cache(getattr(self, "active_profile_pattern_id", None))
            if recalculate:
                self.post_match_pipeline.candidate_added()
            return True
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Working set failed", str(exc))
            return False

    def _sync_candidate_to_sample_phase(self, candidate: dict[str, str], *, show_errors: bool) -> None:
        pattern = self._active_pattern()
        if pattern is None:
            return
        active_pattern_id = pattern.id
        try:
            phase, _structure = self._add_candidate_to_project(candidate)
            self._link_phases_to_checked_patterns([phase.id])
            self.project.touch()
            self.tree.set_project(self.project)
            self.tree.select_object("pattern", active_pattern_id)
            self.project_changed.emit()
            if hasattr(self, "_update_compound_card_sample"):
                self._update_compound_card_sample()
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Sample phase", str(exc))

    def _sync_candidate_rows_to_match_list(self) -> None:
        candidates = self._candidate_rows()
        if not candidates:
            self._clear_match_list()
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        errors = []
        try:
            self.match_candidates.clear()
            self._gain_overlap_locked = False
            self._active_gain_stage = ""
            self.match_structures.clear()
            for candidate in candidates:
                try:
                    self._add_candidate_to_match_list(candidate, show_errors=False, recalculate=False)
                except Exception as exc:
                    errors.append(str(exc))
            if hasattr(self, "_save_active_profile_state"):
                self._save_active_profile_state()
            if hasattr(self, "_invalidate_match_profile_cache"):
                self._invalidate_match_profile_cache(getattr(self, "active_profile_pattern_id", None))
            self._recalculate_match_profile(auto_zoom=self._should_autozoom_match_profile())
        finally:
            self.unsetCursor()
        if errors:
            QMessageBox.warning(self, "Selected phases", "; ".join(errors[:3]))

    def _add_selected_phases_to_xrd(self) -> None:
        if not self.match_candidates:
            QMessageBox.information(self, "Add phases", "Add candidates to selected phases first.")
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        errors = []
        added_phase_ids = []
        try:
            for candidate in self.match_candidates:
                try:
                    phase, _structure = self._add_candidate_to_project(candidate)
                    if phase.id not in added_phase_ids:
                        added_phase_ids.append(phase.id)
                except Exception as exc:
                    errors.append(str(exc))
            self._link_phases_to_checked_patterns(added_phase_ids)
            self.project.touch()
            self.tree.set_project(self.project)
            self.project_changed.emit()
            if hasattr(self, "_update_compound_card_sample"):
                self._update_compound_card_sample()
        finally:
            self.unsetCursor()
        if errors:
            QMessageBox.warning(self, "Add phases", "; ".join(errors[:3]))

    def _link_phases_to_checked_patterns(self, phase_ids: list[str]) -> None:
        if not phase_ids:
            return
        checked_pattern_ids = set(self.tree.checked_pattern_ids())
        if not checked_pattern_ids:
            active = self._active_pattern()
            checked_pattern_ids = {active.id} if active is not None else set()
        for pattern in self.project.patterns:
            if pattern.id not in checked_pattern_ids:
                continue
            for phase_id in phase_ids:
                if phase_id not in pattern.linked_phase_ids:
                    pattern.linked_phase_ids.append(phase_id)

    def _remove_selected_match_candidate(self) -> None:
        row = self.match_table.currentRow()
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates.pop(row)
        self._gain_overlap_locked = False
        self._active_gain_stage = ""
        key = self._candidate_key(candidate)
        self.match_structures.pop(key, None)
        self.match_scales.pop(key, None)
        self.match_quantities.pop(key, None)
        self.match_iic.pop(key, None)
        self.match_zero_shifts.pop(key, None)
        self.match_cell_scales.pop(key, None)
        self.match_alignment_scores.pop(key, None)
        if hasattr(self, "_save_active_profile_state"):
            self._save_active_profile_state()
        if hasattr(self, "_invalidate_match_profile_cache"):
            self._invalidate_match_profile_cache(getattr(self, "active_profile_pattern_id", None))
        self._recalculate_match_profile()
        self._schedule_candidate_gain_ranking()

    def _change_selected_match_color(self) -> None:
        row = self.match_table.currentRow()
        self._change_profile_candidate_color(row)

    def _change_profile_candidate_color(self, row: int) -> None:
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates[row]
        current = QColor(self._phase_color(candidate, row))
        color = QColorDialog.getColor(current, self, "Select phase color")
        if not color.isValid():
            return
        candidate["_Color"] = color.name()
        phase_key = self._candidate_key(candidate)
        self.phase_colors[phase_key] = color.name()
        if hasattr(self, "_save_active_profile_state"):
            self._save_active_profile_state()
        self._recalculate_match_profile()

    def _clear_match_list(self) -> None:
        self.match_candidates.clear()
        self._gain_overlap_locked = False
        self._active_gain_stage = ""
        self.match_structures.clear()
        self.match_scales.clear()
        self.match_quantities.clear()
        self.match_iic.clear()
        self.match_zero_shifts.clear()
        self.match_cell_scales.clear()
        self.match_alignment_scores.clear()
        if hasattr(self, "_save_active_profile_state"):
            self._save_active_profile_state()
        if hasattr(self, "_invalidate_match_profile_cache"):
            self._invalidate_match_profile_cache(getattr(self, "active_profile_pattern_id", None))
        self._clear_calculated_overlay()
        self._update_match_table()

    def _update_match_table(self) -> None:
        if hasattr(self.candidate_table, "set_scoring_stage"):
            self.candidate_table.set_scoring_stage(bool(self.match_candidates))
        rows = []
        for row, candidate in enumerate(self.match_candidates):
            key = self._candidate_key(candidate)
            iic = self.match_iic.get(key, 0.0)
            iic_text = f"{iic:.3g}" if iic > 0 else ""
            rows.append([
                self._phase_color(candidate, row),
                self._phase_legend_label(candidate),
                self.match_alignment_scores.get(key, ""),
                f"{self.match_quantities.get(key, 0.0):.1f}",
                iic_text,
            ])
        self.match_table.set_rows(rows)
        if hasattr(self, "_update_compound_card_sample"):
            self._update_compound_card_sample()
        if hasattr(self, "_update_profile_view_context"):
            self._update_profile_view_context()

    def _schedule_candidate_gain_ranking(self) -> None:
        if getattr(self, "_candidate_gain_ranking_pending", False):
            return
        self._candidate_gain_ranking_pending = True
        QTimer.singleShot(80, self._run_scheduled_candidate_gain_ranking)

    def _run_scheduled_candidate_gain_ranking(self) -> None:
        self._candidate_gain_ranking_pending = False
        self._refresh_candidate_gain_ranking()

    def _refresh_candidate_gain_ranking(self) -> None:
        if not self.match_candidates:
            return
        existing_rows = self._candidate_state_rows(self.candidate_table.all_row_values())
        rows: list[list[str]] = []
        if hasattr(self, "_gain_sql_candidate_rows"):
            gain_context = self._candidate_gain_context()
            if gain_context is not None:
                stage = self._gain_stage_for_context(gain_context)
                rows.extend(self._gain_sql_candidate_rows(stage=stage, context=gain_context))
                if stage == "direct":
                    rows.extend(self._gain_sql_candidate_rows(stage="overlap", context=gain_context))
                elif stage == "overlap":
                    # Once Overlap is locked, uncovered peaks remain useful as
                    # search hints so a phase with both shared and free lines
                    # (for example albite) is not omitted from the candidate
                    # pool. Ranking still uses Overlap evidence only.
                    rows.extend(self._gain_sql_candidate_rows(stage="direct", context=gain_context))
        # The indexed residual lookup is an accelerator, not a hard gate.
        # Keep already loaded candidates available when the narrow SQL query
        # misses a shifted or overlapping phase.
        rows.extend(existing_rows)
        rows = self.candidate_search_service.dedupe_candidate_rows(
            self._candidate_rows_without_gain(rows)
        )
        dialog = QProgressDialog("Updating Gain...", "", 0, max(len(rows), 1), self)
        dialog.setWindowTitle("Gain ranking")
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.show()
        QApplication.processEvents()

        def rank_progress(value: int, maximum: int) -> None:
            maximum = max(int(maximum), 1)
            value = max(0, min(int(value), maximum))
            dialog.setMaximum(maximum)
            dialog.setValue(value)
            dialog.setLabelText(f"Updating Gain... {value}/{maximum}")
            QApplication.processEvents()

        try:
            self._set_candidate_rows(rows, force_rank=True, rank_progress=rank_progress)
            if self.candidate_table.rowCount() > 0:
                self.candidate_table.selectRow(0)
                self.candidate_table.scrollToTop()
        finally:
            dialog.close()

    def _candidate_rows_without_gain(self, rows: list[list[str]]) -> list[list[str]]:
        cleaned = []
        for row in rows:
            values = list(row) + [""] * 8
            values[6] = ""
            cleaned.append(values[:8])
        return cleaned

    def _phase_color(self, candidate: dict[str, str], index: int) -> str:
        palette = ["#d93025", "#1a73e8", "#188038", "#f9ab00", "#8e24aa", "#7b1fa2"]
        phase_key = self._candidate_key(candidate)
        color = self.phase_colors.get(phase_key, "") or candidate.get("_Color", "")
        if not QColor(color).isValid():
            color = palette[len(self.phase_colors) % len(palette)]
        self.phase_colors[phase_key] = color
        candidate["_Color"] = color
        return color
