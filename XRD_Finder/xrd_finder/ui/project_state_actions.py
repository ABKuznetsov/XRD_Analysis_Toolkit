from __future__ import annotations

from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.ui.element_filter import element_sort_key


class PhaseFinderProjectStateActionsMixin:
    def _sync_finder_state_to_project(self) -> None:
        if not hasattr(self, "candidate_table"):
            return
        current = self.tree.current_object()
        right_tab = self.right_tabs.tabText(self.right_tabs.currentIndex()) if self.right_tabs.count() else "Elements"
        self.project.finder_state = FinderProjectState(
            checked_pattern_ids=self.tree.checked_pattern_ids(),
            checked_phase_ids=self.tree.checked_phase_ids(),
            current_object_type=current[0] if current else "",
            current_object_id=current[1] if current else "",
            show_all_selected_patterns=bool(self.show_all_selected_patterns),
            pattern_stack_offset_percent=int(self.pattern_stack_offset_percent),
            normalize_observed_patterns=bool(self.normalize_observed_patterns),
            auto_refine_cells_on_add=bool(getattr(self, "auto_refine_cells_on_add", False)),
            grid_visible=bool(self.grid_visible),
            show_hkl_labels=bool(self.show_hkl_labels),
            right_tab=right_tab,
            candidate_rows=self.candidate_table.all_row_values(),
            candidate_current_row=int(self.candidate_table.currentRow()),
            match_candidates=[dict(candidate) for candidate in self.match_candidates],
            match_current_row=int(self.match_table.currentRow()),
            match_quantities={str(key): float(value) for key, value in self.match_quantities.items()},
            match_iic={str(key): float(value) for key, value in self.match_iic.items()},
            match_zero_shifts={str(key): float(value) for key, value in self.match_zero_shifts.items()},
            match_cell_scales={str(key): float(value) for key, value in self.match_cell_scales.items()},
            match_alignment_scores={str(key): str(value) for key, value in self.match_alignment_scores.items()},
            selected_elements=sorted(self.selected_elements, key=element_sort_key),
            selected_element_order=list(self.selected_element_order),
            element_states=dict(self.element_states),
            exclude_all_other_elements=bool(self.exclude_all_other_elements),
            search_text=self.search_input.text().strip() if self.search_input is not None else "",
            name_text=self.name_input.text().strip() if self.name_input is not None else "",
            formula_text=self.formula_sum_input.text().strip() if self.formula_sum_input is not None else "",
            ccdc_doi_text=self.ccdc_doi_input.text().strip() if self.ccdc_doi_input is not None else "",
            inorganics_checked=self.inorganics_checkbox.isChecked() if self.inorganics_checkbox is not None else True,
            organics_checked=self.organics_checkbox.isChecked() if self.organics_checkbox is not None else False,
            structural_data_checked=self.structural_data_checkbox.isChecked() if self.structural_data_checkbox is not None else True,
            reference_patterns_checked=self.reference_patterns_checkbox.isChecked() if self.reference_patterns_checkbox is not None else True,
            rank_by_probability_checked=self.rank_by_probability_checkbox.isChecked() if self.rank_by_probability_checkbox is not None else True,
        )

    def _restore_finder_state_from_project(self) -> None:
        state = getattr(self.project, "finder_state", None)
        if state is None:
            return
        self.tree.set_checked_pattern_ids(state.checked_pattern_ids)
        self.tree.set_checked_phase_ids(state.checked_phase_ids)
        if state.current_object_type and state.current_object_id:
            self.tree.select_object(state.current_object_type, state.current_object_id)
        self.show_all_selected_patterns = bool(state.show_all_selected_patterns)
        self.pattern_stack_offset_percent = int(state.pattern_stack_offset_percent)
        self.normalize_observed_patterns = bool(getattr(state, "normalize_observed_patterns", False))
        self.auto_refine_cells_on_add = bool(getattr(state, "auto_refine_cells_on_add", False))
        self.grid_visible = bool(state.grid_visible)
        self.show_hkl_labels = bool(state.show_hkl_labels)
        if self.finder_action_bar is not None:
            mode = "All selected" if self.show_all_selected_patterns else "One"
            self.finder_action_bar.pattern_display_mode.setCurrentText(mode)
            self.finder_action_bar.pattern_offset_slider.setValue(max(0, min(150, self.pattern_stack_offset_percent)))
            self.finder_action_bar.normalize_patterns_checkbox.setChecked(self.normalize_observed_patterns)
            self.finder_action_bar.auto_refine_cells_checkbox.setChecked(self.auto_refine_cells_on_add)
        self._restore_filter_state(state)
        if state.candidate_rows:
            self._set_candidate_rows(self._candidate_state_rows(state.candidate_rows))
            if 0 <= state.candidate_current_row < self.candidate_table.rowCount():
                self.candidate_table.selectRow(state.candidate_current_row)
        self._restore_match_state(state)
        for index in range(self.right_tabs.count()):
            if self.right_tabs.tabText(index) == state.right_tab:
                self.right_tabs.setCurrentIndex(index)
                break
        self._set_grid_visible(self.grid_visible)
        self._refresh_observed_pattern_plot()
        if self.match_candidates and self._match_candidates_have_local_structures():
            self._recalculate_match_profile(auto_zoom=False)
        else:
            self._update_match_table()

    def _restore_filter_state(self, state: FinderProjectState) -> None:
        self.element_states = dict(state.element_states)
        self.selected_elements = set(state.selected_elements)
        self.selected_element_order = list(state.selected_element_order)
        self.exclude_all_other_elements = bool(state.exclude_all_other_elements)
        if self.search_input is not None:
            self.search_input.setText(state.search_text)
        if self.name_input is not None:
            self.name_input.setText(state.name_text)
        if self.formula_sum_input is not None:
            self.formula_sum_input.setText(state.formula_text)
        if self.ccdc_doi_input is not None:
            self.ccdc_doi_input.setText(state.ccdc_doi_text)
        if self.inorganics_checkbox is not None:
            self.inorganics_checkbox.setChecked(state.inorganics_checked)
        if self.organics_checkbox is not None:
            self.organics_checkbox.setChecked(state.organics_checked)
        if self.structural_data_checkbox is not None:
            self.structural_data_checkbox.setChecked(state.structural_data_checked)
        if self.reference_patterns_checkbox is not None:
            self.reference_patterns_checkbox.setChecked(state.reference_patterns_checked)
        if self.rank_by_probability_checkbox is not None:
            self.rank_by_probability_checkbox.setChecked(state.rank_by_probability_checked)
        self._update_element_fields()

    def _restore_match_state(self, state: FinderProjectState) -> None:
        self.match_candidates = [dict(candidate) for candidate in state.match_candidates]
        self.match_structures.clear()
        self.match_quantities = {str(key): float(value) for key, value in state.match_quantities.items()}
        self.match_iic = {str(key): float(value) for key, value in state.match_iic.items()}
        self.match_zero_shifts = {str(key): float(value) for key, value in state.match_zero_shifts.items()}
        self.match_cell_scales = {str(key): float(value) for key, value in state.match_cell_scales.items()}
        self.match_alignment_scores = {str(key): str(value) for key, value in state.match_alignment_scores.items()}
        for candidate in self.match_candidates:
            try:
                local_path = self._candidate_local_cif_path(candidate)
                if local_path is None:
                    continue
                _phase, structure = create_phase_from_cif(local_path)
                phase_name = self._candidate_phase_name(candidate)
                if phase_name:
                    structure.name = phase_name
                self.match_structures[self._candidate_key(candidate)] = structure
            except Exception:
                continue
        self._update_match_table()
        if 0 <= state.match_current_row < self.match_table.rowCount():
            self.match_table.selectRow(state.match_current_row)

    def _match_candidates_have_local_structures(self) -> bool:
        return bool(self.match_candidates) and all(
            self._candidate_key(candidate) in self.match_structures
            for candidate in self.match_candidates
        )

    def _candidate_state_rows(self, candidates: list[dict[str, str]]) -> list[list[str]]:
        rows = []
        for candidate in candidates:
            row = [
                candidate.get("Source", ""),
                candidate.get("Entry", ""),
                candidate.get("Formula", ""),
                candidate.get("Phase", ""),
                candidate.get("Space group", ""),
                candidate.get("Match (%)", ""),
                candidate.get("Gain (%)", ""),
                candidate.get("I/Ic*", ""),
            ]
            rows.append(row)
        return rows
