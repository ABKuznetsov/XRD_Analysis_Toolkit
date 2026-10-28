"""Small menu entry points into existing Finder workflows."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QMessageBox, QScrollArea
from pathlib import Path

from xrd_finder.io.candidate_export import write_candidate_csv
from xrd_finder.ui.sample_metadata_dialog import SampleMetadataDialog


class PhaseFinderMenuActionsMixin:
    def _clear_selected_search_peaks_from_menu(self):
        pattern = self._active_pattern()
        if pattern is None:
            QMessageBox.information(self, 'Search peaks', 'Select an XRD pattern first.')
            return
        self._cancel_selected_peak_search()
        if getattr(pattern, 'input_kind', '') == 'peak_list':
            self._manual_search_peaks[pattern.id] = []
        else:
            self._manual_search_peaks.pop(pattern.id, None)
        self._redraw_selected_search_peaks()
        if self._search_mode == 'peaks':
            self._set_candidate_status_state('idle')
            self._set_candidate_batch_detail('Selected peaks 0 | Selection changed')
        else:
            self._set_background_status('Search-peak selection cleared for the active pattern.')

    def _show_project_phases_from_menu(self):
        items = list(self.tree._phase_items.values())
        if not items:
            QMessageBox.information(self, 'Project phases',
                'No CIF structures are embedded in this project. Use Import data to add a CIF, '
                'or add a candidate CIF to the project from Entries.')
            return
        for item in items:
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
        self.tree.scrollToItem(items[0])
        self.tree.setFocus(Qt.FocusReason.MenuBarFocusReason)
        self._set_background_status(f'Project structures: {len(items)}. Use their rows in the project tree.')

    def _inspect_peak_from_menu(self):
        self.peak_information_action.setChecked(True)
        self._toggle_peak_information()

    def _show_manual_from_menu(self):
        from xrd_finder.ui.manual_dialog import ManualDialog
        dialog = getattr(self, '_manual_dialog', None)
        if dialog is None:
            dialog = self._manual_dialog = ManualDialog(self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _open_processing_from_menu(self, key):
        bar = self.finder_action_bar
        self._show_menu_panel(bar)
        if key == 'zero':
            section = bar.zero_shift_section
        else:
            actions = {
                'smooth': self._smooth_active_pattern_plot,
                'background': self._subtract_active_background_plot,
                'xrd_crop': self._crop_xrd_patterns_plot,
            }
            actions[key]()
            section = bar._preprocessing_sections[key]
        section.toggle.setChecked(True)
        section._set_expanded(True)
        bar.processing_scroll.widget().layout().activate()
        bar.processing_scroll.ensureWidgetVisible(section.toggle)
        section.toggle.setFocus(Qt.FocusReason.MenuBarFocusReason)

    def _open_smoothing_from_menu(self):
        self._open_processing_from_menu('smooth')

    def _open_background_from_menu(self):
        self._open_processing_from_menu('background')

    def _open_crop_from_menu(self):
        self._open_processing_from_menu('xrd_crop')

    def _open_zero_shift_from_menu(self):
        self._open_processing_from_menu('zero')

    def _mark_search_peaks_from_menu(self):
        if getattr(self, '_peak_info_armed', False):
            self._cancel_peak_information(close_card=True)
        self._begin_peak_search()

    def _open_materials_project_from_menu(self):
        self._show_database_settings_window()
        field = self.database_panel.materials_project_api_key_input
        scroll = self._database_settings_dialog.findChild(QScrollArea)
        if scroll is not None:
            scroll.ensureWidgetVisible(field)
        field.setFocus(Qt.FocusReason.MenuBarFocusReason)

    def _toggle_menu_grid(self):
        self._set_grid_visible(self.show_grid_action.isChecked())

    def _show_menu_panel(self, widget):
        for index in range(self.right_tabs.count()):
            tab = self.right_tabs.widget(index)
            if tab is widget or tab.isAncestorOf(widget):
                self.right_tabs.setCurrentIndex(index)
                return

    def _search_formula_from_menu(self):
        query, accepted = QInputDialog.getText(
            self, 'Search by formula', 'Formula (enabled local and online databases):',
            text=self.search_input.text(),
        )
        if not accepted or not query.strip():
            return
        self.search_input.setText(query.strip())
        self._show_menu_panel(self.composition_panel)
        self._search_pdf2_text()

    def _search_elements_from_menu(self):
        self._show_menu_panel(self.composition_panel)
        self._cancel_candidate_search_jobs()
        self._set_search_mode('search')
        if self.selected_element_order or self._excluded_elements():
            self._search_from_controls(elements_only=True)
        else:
            self.element_table._buttons['H'].setFocus(Qt.FocusReason.MenuBarFocusReason)
            self._set_candidate_batch_detail('Choose elements, then click Search database.')

    def _show_candidate_entry_card(self):
        candidate = self._candidate_row_values(self.candidate_table.currentRow())
        if not candidate.get('Source') or not candidate.get('Entry'):
            QMessageBox.information(self, 'Entry card', 'Select a candidate in the candidate list first.')
            return
        key = (candidate['Source'], candidate['Entry'])
        # Opening a prepared card must not repeat CIF calculation or discard
        # richer details already populated by the candidate selection pipeline.
        if self.compound_card.candidate_key != key:
            self._enrich_candidate_from_local_cache(candidate)
            self._update_compound_card(candidate)
        self._show_menu_panel(self.compound_card)
        self.compound_card.tabs.setCurrentIndex(1)

    def _focus_candidate_list(self):
        table = self.candidate_table
        table.setFocus(Qt.FocusReason.MenuBarFocusReason)
        if table.currentIndex().isValid():
            table.scrollTo(table.currentIndex())

    def _export_candidate_list(self):
        rows = self.candidate_table.csv_rows()
        if not rows:
            QMessageBox.information(self, 'Export candidate list', 'There are no candidates to export.')
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, 'Export candidate list', str(Path(self._last_directory()) / 'xrd_candidates.csv'),
            'CSV files (*.csv)',
        )
        if not filename:
            return
        target = Path(filename)
        if not target.suffix:
            target = target.with_suffix('.csv')
        try:
            write_candidate_csv(target, self.candidate_table.DISPLAY_HEADERS, rows)
        except OSError as exc:
            QMessageBox.warning(self, 'Export candidate list', f'Could not save the candidate list:\n{exc}')
            return
        self._remember_directory(target)
        self._set_background_status(f'Exported {len(rows)} candidates: {target.name}')

    def _edit_sample_id(self):
        self._edit_active_sample_metadata('sample_id')

    def _edit_sample_datetime(self):
        self._edit_active_sample_metadata('sample_datetime')

    def _edit_sample_notes(self):
        self._edit_active_sample_metadata('notes')

    def _edit_active_sample_metadata(self, focus_field):
        pattern = self._active_pattern()
        if pattern is None:
            QMessageBox.information(self, 'Sample details', 'Select an XRD pattern first.')
            return
        dialog = SampleMetadataDialog(pattern.name, pattern.metadata, self, focus_field=focus_field, notes=pattern.notes)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            updated = dict(pattern.metadata)
            values = dialog.values()
            notes = dialog.notes()
            for key in ('sample_id', 'sample_datetime'):
                value = values[key].strip()
                if value:
                    updated[key] = value
                else:
                    updated.pop(key, None)
            if updated == pattern.metadata and notes == pattern.notes:
                return
            pattern.metadata = updated
            pattern.notes = notes
            pattern.touch()
            self.project.touch()
            self._update_compound_card_sample()
            self._show_menu_panel(self.compound_card)
            self.project_changed.emit()
        finally:
            dialog.deleteLater()
