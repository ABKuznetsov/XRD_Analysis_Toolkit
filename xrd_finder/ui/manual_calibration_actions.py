"""Manual calibration preview and commits, isolated to the active measurement."""
import numpy as np
from PySide6.QtWidgets import QMessageBox

from xrd_finder.services.manual_angle_calibration import (
    apply_manual_angle_calibration, reset_manual_angle_calibration,
)
from xrd_finder.ui.manual_calibration_dialog import ManualCalibrationDialog
from xrd_finder.ui.observed_patterns import observed_pattern_data


_EXPERIMENTAL_LAYERS = {'observed', 'background', 'amorphous', 'coverage_markers',
    'unknown_peaks', 'peak_labels', 'search_peak_selection'}


class ManualCalibrationActionsMixin:
    def _close_manual_calibration(self):
        dialog = getattr(self, '_manual_calibration_dialog', None)
        preview = getattr(self, '_manual_calibration_preview', None)
        self._manual_calibration_dialog = None
        self._manual_calibration_preview = None
        if preview is not None:
            for item, position in preview['items']:
                try:
                    item.setPos(position.x(), position.y())
                except RuntimeError:  # A redraw may already have destroyed a Qt item.
                    pass
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def _open_manual_angle_calibration(self):
        existing = getattr(self, '_manual_calibration_dialog', None)
        if existing is not None:
            existing.raise_(); existing.activateWindow()
            return
        pattern = self._active_pattern()
        if pattern is None or getattr(pattern, 'input_kind', '') == 'peak_list':
            QMessageBox.information(self, 'Manual angle calibration',
                'Select a measured XRD pattern. Edit manual peak positions through Peaks → Add peak.')
            return
        cancel = getattr(self, '_preprocessing_cancel_callback', None)
        self._close_preprocessing_panel()
        if cancel is not None:
            cancel()
        data = observed_pattern_data(pattern)
        context = self.observed_pattern_plot_context.get(pattern.id)
        if data is None or len(data) < 2 or context is None:
            QMessageBox.information(self, 'Manual angle calibration', 'Display an active measured XRD pattern first.')
            return
        self._cancel_candidate_search_jobs()
        self._cancel_peak_information(close_card=True)
        self._candidate_preview_token = int(getattr(self, '_candidate_preview_token', 0))+1
        controller = getattr(self, 'preview_observation_controller', None)
        if controller is not None:
            controller.invalidate()
        correction = float(pattern.angle_calibration_deg)
        items, moving, seen = [], [], set()
        for layer, layer_items in self.plot_layers.items():
            if layer in {'pattern_legends', 'legend_info'}:
                continue
            for item in layer_items:
                if id(item) not in seen and getattr(item, '_xrd_pattern_id', None) == pattern.id:
                    seen.add(id(item))
                    position = item.pos()
                    items.append((item, position))
                    # Preview the working angular axis that Apply will produce,
                    # without stacking an old display-only zero on top of it.
                    raw_x = position.x()+float(getattr(item, '_finder_zero_display_shift', 0.))
                    moving.append((item, raw_x, position.y(), layer in _EXPERIMENTAL_LAYERS))
        preview = self._manual_calibration_preview = dict(project=self.project, pattern=pattern,
            context=context, data=np.array(data, dtype=float, copy=True), correction=correction, items=items)
        dialog = self._manual_calibration_dialog = ManualCalibrationDialog(self, pattern.name, correction,
            any(step.get('kind') == 'calibration' for step in pattern.preprocessing_history))

        def current():
            return (self._manual_calibration_preview is preview and self.project is preview['project']
                and self._active_pattern() is pattern
                and self.observed_pattern_plot_context.get(pattern.id) is context
                and pattern.angle_calibration_deg == correction
                and np.array_equal(observed_pattern_data(pattern), preview['data'], equal_nan=True))

        def update(value):
            if self._manual_calibration_preview is not preview:
                return
            delta = value-correction
            for item, raw_x, y, experimental in moving:
                item.setPos(raw_x-(delta if experimental else 0.), y)

        def commit(reset=False):
            if not current():
                self._close_manual_calibration()
                self._set_background_status('Calibration cancelled: the active measurement changed.')
                return
            value = dialog.correction.value()
            self._close_manual_calibration()
            try:
                modified = (reset_manual_angle_calibration(pattern) if reset else
                    apply_manual_angle_calibration(pattern, preview['data'], value))
            except (TypeError, ValueError) as exc:
                QMessageBox.warning(self, 'Manual angle calibration', str(exc))
                return
            if modified:
                self._after_manual_angle_calibration(pattern)

        dialog.correction.valueChanged.connect(update)
        dialog.apply_button.clicked.connect(lambda: commit())
        dialog.reset_button.clicked.connect(lambda: commit(reset=True))
        dialog.rejected.connect(self._close_manual_calibration)
        update(correction)
        dialog.show()
        dialog.correction.setFocus()

    def _after_manual_angle_calibration(self, pattern):
        self._cancel_candidate_search_jobs()
        self._manual_search_peaks.pop(pattern.id, None)
        # The candidate identities remain useful, but their old Match/Gain
        # numbers describe the previous angular grid and must not survive Apply.
        table = self.candidate_table
        blocked = table.blockSignals(True)
        try:
            for row in range(table.rowCount()):
                for column in (5, 6):
                    item = table.item(row, column)
                    if item is not None:
                        item.setText('')
        finally:
            table.blockSignals(blocked)
        table.set_match_diagnostics({}, ())
        self._auto_search_ranked_rows = None
        self._auto_search_scored_keys = set()
        self._candidate_rank_token += 1
        state = self.profile_states.setdefault(pattern.id, {})
        for key in ('result_snapshot', 'zero_shift_auto_deg', 'zero_shift_observed_width_deg'):
            state.pop(key, None)
        state['zero_shift_visual_deg'] = 0.
        state['correct_zero'] = False
        self.match_zero_shifts.clear()
        self.analysis_preview_paths.pop(pattern.id, None)
        self._sync_zero_shift_controls()
        self._refresh_preprocessing_state(pattern, modified=True)
        self._refresh_candidate_score_labels()
        self._set_candidate_batch_detail('Angles changed | Run Identify phases or Peak search again')
        self._set_background_status(
            f'Manual angle correction {pattern.angle_calibration_deg:+.4f}° applied to {pattern.name}. '
            'Search marks and scores cleared; accepted phases recalculated.')
