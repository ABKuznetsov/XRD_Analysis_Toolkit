from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path

from xrd_finder.core.finder_state import FinderProjectState
from xrd_finder.io.cif_loader import create_phase_from_cif
from xrd_finder.ui.element_filter import element_sort_key
from xrd_finder.ui.plot_view_settings import PlotViewSettings


class PhaseFinderProjectStateActionsMixin:
    def _collect_project_candidate_cif_paths(self) -> dict[str, str]:
        """Resolve one readable local CIF path for every saved candidate key."""
        candidates = list(self.match_candidates)
        for profile_state in self.profile_states.values():
            if isinstance(profile_state, dict):
                candidates.extend(profile_state.get("candidates", []) or [])

        existing_paths = getattr(self.project.finder_state, "candidate_cif_paths", {}) or {}
        candidate_paths: dict[str, str] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            source = str(candidate.get("Source", "") or candidate.get("Qual.", "")).strip().upper()
            entry = str(candidate.get("Entry", "")).strip()
            if source not in {"COD", "USER", "MP", "CCDC", "AFLOW", "OQMD"} or not entry:
                continue
            candidate_key = self._candidate_key(candidate)
            if candidate_key in candidate_paths:
                continue

            local_path = self._candidate_local_cif_path(candidate)
            possible_paths = (local_path, existing_paths.get(candidate_key))
            for possible_path in possible_paths:
                if possible_path is None:
                    continue
                path = Path(possible_path)
                try:
                    with path.open("rb"):
                        pass
                except OSError:
                    continue
                candidate_paths[candidate_key] = str(path)
                break
            else:
                display_name = str(
                    candidate.get("_DisplayName", "")
                    or candidate.get("Phase", "")
                    or candidate.get("Candidate phase", "")
                    or candidate.get("Name", "")
                    or candidate.get("Formula", "")
                    or entry
                )
                raise ValueError(
                    f"Cannot save CIF asset for phase {display_name!r} ({source}:{entry}): "
                    "no readable local CIF is available."
                )
        return candidate_paths

    def _sync_finder_state_to_project(self) -> None:
        if not hasattr(self, "candidate_table"):
            return
        if hasattr(self, "_save_active_profile_state"):
            self._save_active_profile_state()
        current = self.tree.current_object()
        right_tab = self.right_tabs.tabText(self.right_tabs.currentIndex()) if self.right_tabs.count() else "Elements"
        try:
            view_range = [list(axis_range) for axis_range in self._plot_view_range()]
        except Exception:
            view_range = []
        self.project.finder_state = FinderProjectState(
            checked_pattern_ids=self.tree.checked_pattern_ids(),
            checked_phase_ids=self.tree.checked_phase_ids(),
            current_object_type=current[0] if current else "",
            current_object_id=current[1] if current else "",
            tree_expansion_state=self.tree.expansion_state(),
            show_all_selected_patterns=bool(self.show_all_selected_patterns),
            pattern_stack_offset_percent=int(self.pattern_stack_offset_percent),
            normalize_observed_patterns=bool(self.normalize_observed_patterns),
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
            candidate_cif_paths=self._collect_project_candidate_cif_paths(),
            profile_states=deepcopy(self.profile_states),
            phase_colors={str(key): str(value) for key, value in self.phase_colors.items()},
            observed_pattern_colors={str(key): str(value) for key, value in self.observed_pattern_colors.items()},
            plot_view_settings=asdict(self.plot_view_settings),
            plot_view_range=view_range,
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
            reference_patterns_checked=self.reference_patterns_checkbox.isChecked() if self.reference_patterns_checkbox is not None else False,
            rank_by_probability_checked=self.rank_by_probability_checkbox.isChecked() if self.rank_by_probability_checkbox is not None else True,
        )

    def _restore_finder_state_from_project(self) -> None:
        state = getattr(self.project, "finder_state", None)
        if state is None:
            return
        self._project_restore_warnings: list[str] = []
        self._install_embedded_candidate_cifs(state)
        self.profile_states = deepcopy(getattr(state, "profile_states", {}) or {})
        self.phase_colors = dict(getattr(state, "phase_colors", {}) or {})
        self.observed_pattern_colors = dict(getattr(state, "observed_pattern_colors", {}) or {})
        self.show_all_selected_patterns = False
        self._restore_project_plot_view_settings(getattr(state, "plot_view_settings", {}) or {})
        self.tree.restore_expansion_state(getattr(state, "tree_expansion_state", {}) or {})
        self.tree.set_checked_pattern_ids(state.checked_pattern_ids)
        self.tree.set_checked_phase_ids(state.checked_phase_ids)
        if state.current_object_type and state.current_object_id:
            self.tree.select_object(state.current_object_type, state.current_object_id)
        self.show_all_selected_patterns = bool(state.show_all_selected_patterns)
        self.pattern_stack_offset_percent = int(state.pattern_stack_offset_percent)
        self.normalize_observed_patterns = bool(getattr(state, "normalize_observed_patterns", False))
        self.grid_visible = bool(state.grid_visible)
        self.show_hkl_labels = bool(state.show_hkl_labels)
        if self.finder_action_bar is not None:
            mode = "All selected" if self.show_all_selected_patterns else "One"
            self.finder_action_bar.pattern_display_mode.setCurrentText(mode)
            self.finder_action_bar.pattern_offset_slider.setValue(max(0, min(150, self.pattern_stack_offset_percent)))
            self.finder_action_bar.normalize_patterns_checkbox.setChecked(self.normalize_observed_patterns)
        self._restore_filter_state(state)
        if state.candidate_rows:
            self._set_candidate_rows(self._candidate_state_rows(state.candidate_rows))
            if 0 <= state.candidate_current_row < self.candidate_table.rowCount():
                previous_block_state = self.candidate_table.blockSignals(True)
                try:
                    self.candidate_table.selectRow(state.candidate_current_row)
                finally:
                    self.candidate_table.blockSignals(previous_block_state)
        self._restore_match_state(state)
        for index in range(self.right_tabs.count()):
            if self.right_tabs.tabText(index) == state.right_tab:
                self.right_tabs.setCurrentIndex(index)
                break
        self._set_grid_visible(self.grid_visible)
        self._refresh_observed_pattern_plot()
        if self.match_candidates:
            previous_network_suppression = bool(getattr(self, "_suppress_candidate_network", False))
            self._suppress_candidate_network = True
            try:
                self._recalculate_match_profile(auto_zoom=False)
            finally:
                self._suppress_candidate_network = previous_network_suppression
        else:
            self._update_match_table()
        saved_range = getattr(state, "plot_view_range", []) or []
        valid_range = len(saved_range) == 2 and all(
            isinstance(axis_range, (list, tuple)) and len(axis_range) == 2
            for axis_range in saved_range
        )
        if valid_range:
            self._restore_plot_view_range(
                (
                    (float(saved_range[0][0]), float(saved_range[0][1])),
                    (float(saved_range[1][0]), float(saved_range[1][1])),
                )
            )
        if self._project_restore_warnings:
            show_warnings = getattr(self, "_show_project_load_warnings", None)
            if callable(show_warnings):
                show_warnings(list(self._project_restore_warnings))

    def _install_embedded_candidate_cifs(self, state: FinderProjectState) -> None:
        candidate_paths = getattr(state, "candidate_cif_paths", {}) or {}
        for candidate_key, candidate_path in candidate_paths.items():
            source, separator, entry_id = str(candidate_key).partition(":")
            path = Path(candidate_path)
            if not separator or not source or not entry_id or not path.is_file():
                continue
            try:
                if self.local_phase_cache.get(source, entry_id) is None:
                    self.local_phase_cache.install_embedded_cif(path, source, entry_id)
            except Exception as exc:
                self._project_restore_warnings.append(
                    f"Could not install embedded CIF {source}:{entry_id} in the local phase library; "
                    f"the project will keep using its embedded copy: {exc}"
                )

    def _restore_project_plot_view_settings(self, stored: dict) -> None:
        if not isinstance(stored, dict) or not stored:
            return
        defaults = asdict(PlotViewSettings())
        valid_names = {field.name for field in fields(PlotViewSettings)}
        values = {name: stored.get(name, defaults[name]) for name in valid_names}
        settings = PlotViewSettings(**values)
        panel = getattr(self, "plot_settings_panel", None)
        if panel is not None and hasattr(panel, "set_settings"):
            panel.set_settings(settings, emit=False)
        self._apply_plot_view_settings(settings)

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
        stored_structures = self._finder_candidate_structure_overrides(
            self._active_pattern(),
            self.match_candidates,
        )
        for candidate in self.match_candidates:
            candidate_key = self._candidate_key(candidate)
            structure = None
            restore_error: Exception | None = None
            used_saved_structure = False
            try:
                local_path = self._candidate_local_cif_path(candidate)
                if local_path is None:
                    raise FileNotFoundError("no readable CIF is available")
                _phase, structure = create_phase_from_cif(local_path)
                phase_name = self._candidate_phase_name(candidate)
                if phase_name:
                    structure.name = phase_name
            except Exception as exc:
                restore_error = exc
                structure = None
            if structure is None:
                structure = stored_structures.get(candidate_key)
                used_saved_structure = structure is not None
            if restore_error is not None:
                source = str(candidate.get("Source", "") or candidate.get("Qual.", "") or "unknown")
                entry_id = str(candidate.get("Entry", "") or "unknown")
                display_name = str(
                    candidate.get("_DisplayName", "")
                    or candidate.get("Phase", "")
                    or candidate.get("Candidate phase", "")
                    or candidate.get("Name", "")
                    or candidate.get("Formula", "")
                    or entry_id
                )
                details = str(restore_error).strip() or type(restore_error).__name__
                if used_saved_structure:
                    warning = (
                        f"Could not restore CIF for phase {display_name!r} ({source}:{entry_id}); "
                        f"using saved structure only: {details}"
                    )
                else:
                    warning = f"Could not restore phase {display_name!r} ({source}:{entry_id}): {details}"
                self._project_restore_warnings.append(warning)
            if structure is not None:
                self.match_structures[candidate_key] = structure
        self._update_match_table()
        if 0 <= state.match_current_row < self.match_table.rowCount():
            self.match_table.selectRow(state.match_current_row)

    def _match_candidates_have_structures(self) -> bool:
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
