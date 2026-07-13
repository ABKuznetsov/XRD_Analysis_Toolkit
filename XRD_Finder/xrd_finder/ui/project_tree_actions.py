from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QInputDialog, QMessageBox

from xrd_finder.io.cif_loader import create_phase_from_cif


class PhaseFinderProjectTreeActionsMixin:
    def _after_cif_import(self, path: Path, phase, structure) -> None:
        try:
            entry = self.local_phase_cache.add_user_cif(path)
        except Exception:
            return
        if entry.cif_path:
            phase.source_path = entry.cif_path
            structure.source_path = entry.cif_path

    def _project_phase_user_entry(self, phase) -> str:
        if not phase.source_path:
            return phase.id
        path = Path(phase.source_path)
        entry_id = path.stem
        cached_path = self.local_phase_cache.cif_path("USER", entry_id)
        if cached_path is not None:
            return entry_id
        try:
            entry = self.local_phase_cache.add_user_cif(path)
        except Exception:
            return phase.id
        if entry.cif_path:
            phase.source_path = entry.cif_path
            structure = self._structure_for_phase(phase.id)
            if structure is not None:
                structure.source_path = entry.cif_path
        return entry.entry_id or phase.id

    def _structure_for_phase(self, phase_id: str):
        phase = next((item for item in self.project.phases if item.id == phase_id), None)
        if phase is None:
            return None
        if phase.structure_id:
            structure = next((item for item in self.project.structures if item.id == phase.structure_id), None)
            if structure is not None:
                return structure
        return next((item for item in self.project.structures if item.phase_id == phase_id), None)

    def _current_tree_phase_structure(self):
        current = self.tree.current_object()
        if current is None:
            return None
        object_type, object_id = current
        if object_type != "phase":
            return None
        structure = self._structure_for_phase(object_id)
        if structure is not None:
            return structure
        phase = next((item for item in self.project.phases if item.id == object_id), None)
        if phase is None or not phase.source_path:
            return None
        try:
            _phase, structure = create_phase_from_cif(phase.source_path)
            structure.name = phase.name or structure.name
            structure.formula = phase.formula or structure.formula
            structure.phase_id = phase.id
            structure.id = phase.structure_id or structure.id
            return structure
        except Exception:
            return None


    def _rename_project_object(self, object_type: str, object_id: str) -> None:
        current_name = ""
        if object_type == "project" and object_id == self.project.id:
            current_name = self.project.name
        elif object_type == "pattern":
            current = next((pattern for pattern in self.project.patterns if pattern.id == object_id), None)
            current_name = current.name if current is not None else ""
        elif object_type == "phase":
            current = next((phase for phase in self.project.phases if phase.id == object_id), None)
            current_name = current.name if current is not None else ""
        if not current_name:
            return
        new_name, accepted = QInputDialog.getText(self, "Rename", "Name:", text=current_name)
        if not accepted:
            return
        new_name = new_name.strip()
        if not new_name or new_name == current_name:
            return
        if object_type == "project" and object_id == self.project.id:
            self.project.name = new_name
            self.setWindowTitle(f"{self._base_title} - {self.project.name}")
        elif object_type == "pattern":
            current = next((pattern for pattern in self.project.patterns if pattern.id == object_id), None)
            if current is None:
                return
            current.name = new_name
        elif object_type == "phase":
            current = next((phase for phase in self.project.phases if phase.id == object_id), None)
            if current is None:
                return
            current.name = new_name
            structure = self._structure_for_phase(object_id)
            if structure is not None:
                structure.name = new_name
        self.project.touch()
        self.tree.set_project(self.project)
        self.tree.select_object(object_type, object_id)
        self._refresh_project_phase_candidates()
        self._refresh_observed_pattern_plot()

    def _delete_project_object(self, object_type: str, object_id: str) -> None:
        if object_type not in {"pattern", "phase"}:
            return
        if object_type == "pattern":
            current = next((pattern for pattern in self.project.patterns if pattern.id == object_id), None)
            label = "XRD pattern"
        else:
            current = next((phase for phase in self.project.phases if phase.id == object_id), None)
            label = "CIF phase"
        if current is None:
            return
        answer = QMessageBox.question(
            self,
            f"Delete {label}",
            f"Delete {label} '{current.name}' from this project?\n\nThis removes it from the project tree and cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if object_type == "pattern":
            self.project.patterns = [pattern for pattern in self.project.patterns if pattern.id != object_id]
            if hasattr(self, "profile_states"):
                self.profile_states.pop(object_id, None)
            if hasattr(self, "_invalidate_match_profile_cache"):
                self._invalidate_match_profile_cache(object_id)
        else:
            phase = current
            structure_id = phase.structure_id
            self.project.phases = [item for item in self.project.phases if item.id != object_id]
            self.project.structures = [
                structure
                for structure in self.project.structures
                if structure.phase_id != object_id and (not structure_id or structure.id != structure_id)
            ]
            self.match_candidates = [
                candidate
                for candidate in self.match_candidates
                if not (self._candidate_source(candidate) == "USER" and candidate.get("Entry") in {object_id, phase.id})
            ]
            for state in getattr(self, "profile_states", {}).values():
                candidates = state.get("candidates", [])
                if isinstance(candidates, list):
                    state["candidates"] = [
                        candidate
                        for candidate in candidates
                        if not (self._candidate_source(candidate) == "USER" and candidate.get("Entry") in {object_id, phase.id})
                    ]
            if hasattr(self, "_invalidate_match_profile_cache"):
                self._invalidate_match_profile_cache()
        self.project.touch()
        self.tree.set_project(self.project)
        self._refresh_project_phase_candidates()
        self._refresh_observed_pattern_plot()
        displayed_patterns = self._patterns_to_display() if self.show_all_selected_patterns else [self._active_pattern()]
        has_profile_candidates = any(self._profile_candidates_for_pattern(pattern) for pattern in displayed_patterns if pattern is not None)
        if has_profile_candidates:
            self._recalculate_match_profile()
        else:
            self._update_match_table()

    def _refresh_project_phase_candidates(self) -> None:
        if not hasattr(self, "candidate_table"):
            return
        rows = [
            ["USER", self._project_phase_user_entry(phase), phase.formula, phase.name, "", "loaded structure"]
            for phase in self.project.phases
        ]
        if not rows:
            rows = [["", "", "", "No phases yet", "", ""]]
        self._set_candidate_rows(rows)

    def _on_project_tree_selection_changed(self) -> None:
        if not hasattr(self, "match_plot"):
            return
        if hasattr(self, "_activate_current_profile_state"):
            self._activate_current_profile_state()
        self._clear_probability_caches()
        view_range = self._plot_view_range() if self.show_all_selected_patterns else None
        try:
            self._refresh_observed_pattern_plot()
            if hasattr(self, "_update_compound_card_sample"):
                self._update_compound_card_sample()
            displayed_patterns = self._patterns_to_display() if self.show_all_selected_patterns else [self._active_pattern()]
            has_profile_candidates = any(self._profile_candidates_for_pattern(pattern) for pattern in displayed_patterns if pattern is not None)
            if has_profile_candidates:
                self._recalculate_match_profile()
            elif self.active_overlay_entry_id:
                candidate = self._selected_candidate_row()
                if candidate is not None:
                    self.active_overlay_entry_id = None
                    self._calculate_candidate_overlay(candidate, show_errors=False)
        finally:
            self._restore_plot_view_range(view_range)
            if hasattr(self, "_update_profile_view_context"):
                self._update_profile_view_context()
