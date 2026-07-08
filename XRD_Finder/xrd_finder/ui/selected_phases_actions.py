from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QMenu, QMessageBox

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
        menu.addAction("Change color...", self._change_selected_match_color)
        export_action = menu.addAction("Export phase CIF...", self._export_match_table_cif)
        for action in (recalculate_action, export_action):
            action.setEnabled(has_structure)
            if not has_structure:
                action.setToolTip("This selected item is a reference pattern; no CIF structure is available.")
        menu.addAction("Remove selected phase", self._remove_selected_match_candidate)
        menu.addAction("Clear working set", self._clear_match_list)
        menu.exec(global_point)

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
                self._recalculate_match_profile(auto_zoom=self._should_autozoom_match_profile())
            return True
        try:
            cif_path = self._candidate_cif_path(candidate)
            _phase, structure = create_phase_from_cif(cif_path)
            phase_name = self._candidate_phase_name(candidate)
            if phase_name:
                structure.name = phase_name
            if not structure.formula and candidate.get("Formula"):
                structure.formula = candidate["Formula"]
            candidate_copy = candidate.copy()
            iic = self._estimate_structure_corundum_iic(structure)
            if iic > 0:
                candidate_copy["I/Ic*"] = f"{iic:.3g}"
            self.match_candidates.append(candidate_copy)
            self.match_structures[key] = structure
            if recalculate:
                self._recalculate_match_profile(auto_zoom=self._should_autozoom_match_profile())
            return True
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Working set failed", str(exc))
            return False

    def _sync_candidate_rows_to_match_list(self) -> None:
        candidates = self._candidate_rows()
        if not candidates:
            self._clear_match_list()
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        errors = []
        try:
            self.match_candidates.clear()
            self.match_structures.clear()
            for candidate in candidates:
                try:
                    self._add_candidate_to_match_list(candidate, show_errors=False, recalculate=False)
                except Exception as exc:
                    errors.append(str(exc))
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
        key = self._candidate_key(candidate)
        self.match_structures.pop(key, None)
        self.match_scales.pop(key, None)
        self.match_quantities.pop(key, None)
        self.match_iic.pop(key, None)
        self.match_zero_shifts.pop(key, None)
        self.match_cell_scales.pop(key, None)
        self.match_alignment_scores.pop(key, None)
        self._recalculate_match_profile()

    def _change_selected_match_color(self) -> None:
        row = self.match_table.currentRow()
        if row < 0 or row >= len(self.match_candidates):
            return
        candidate = self.match_candidates[row]
        current = QColor(self._phase_color(candidate, row))
        color = QColorDialog.getColor(current, self, "Select phase color")
        if not color.isValid():
            return
        candidate["_Color"] = color.name()
        self._recalculate_match_profile()

    def _clear_match_list(self) -> None:
        self.match_candidates.clear()
        self.match_structures.clear()
        self.match_scales.clear()
        self.match_quantities.clear()
        self.match_iic.clear()
        self.match_zero_shifts.clear()
        self.match_cell_scales.clear()
        self.match_alignment_scores.clear()
        self._clear_calculated_overlay()
        self._update_match_table()

    def _update_match_table(self) -> None:
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

    def _phase_color(self, candidate: dict[str, str], index: int) -> str:
        palette = ["#d93025", "#1a73e8", "#188038", "#f9ab00", "#8e24aa", "#7b1fa2"]
        color = candidate.get("_Color", "")
        if not QColor(color).isValid():
            color = palette[index % len(palette)]
            candidate["_Color"] = color
        return color

